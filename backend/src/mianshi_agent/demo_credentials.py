"""One immutable visitor credential identity, with a renewable in-memory lease."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time

from mianshi_agent.chat import ChatCompletionClient, ChatUnavailable

DEEPSEEK_MODELS = ("deepseek-flash", "deepseek-v4-pro")


class VisitorChat(ChatCompletionClient):
    """Dedicated to one visitor's service graph, including its background workers.

    Only a salted digest and model ID are persisted. Renewal must use the same
    key/model; choosing different credentials requires an explicit new workspace.
    An already sent request can finish after disconnect; subsequent calls fail.
    """

    def __init__(self, salt: str, binding: dict | None, slots: asyncio.Semaphore, ttl=1800):
        super().__init__(base_url="https://api.deepseek.com", api_key="", model="", timeout=90)
        self._salt = salt
        self.binding = binding
        self._slots = slots
        self._ttl = ttl
        self.expires_at = 0.0
        self.inflight = 0
        self._calls = 0

    def connect(self, key: str, model: str) -> dict:
        if (
            model not in DEEPSEEK_MODELS
            or not 10 <= len(key) <= 256
            or not key.isascii()
            or any(c.isspace() or ord(c) < 33 for c in key)
        ):
            raise ValueError("demo_invalid_credentials")
        binding = {
            "digest": hashlib.sha256((self._salt + key).encode()).hexdigest(),
            "model": model,
        }
        if self.binding and (
            not hmac.compare_digest(self.binding["digest"], binding["digest"])
            or self.binding["model"] != model
        ):
            raise ValueError("demo_new_workspace_required")
        self.binding = binding
        self.api_key = key
        self.model = model
        self.expires_at = time.time() + self._ttl
        return binding

    def disconnect(self):
        self.api_key = ""
        self.expires_at = 0

    def status(self):
        connected = bool(self.api_key) and self.expires_at > time.time()
        if not connected:
            self.disconnect()
        return {
            "connected": connected,
            "model": self.binding["model"] if self.binding else DEEPSEEK_MODELS[0],
            "bound": self.binding is not None,
            "expires_at": self.expires_at if connected else None,
            "inflight": self.inflight,
        }

    async def complete_json(self, **kwargs):
        async with self._slots:
            if not self.status()["connected"]:
                raise ChatUnavailable("demo_key_required")
            if self._calls >= 120:
                raise ChatUnavailable("demo_generation_limit")
            # Snapshot the credential: disconnect cannot mutate an in-flight call.
            client = ChatCompletionClient(
                base_url=self.base_url, api_key=self.api_key, model=self.model, timeout=self.timeout
            )
            self.inflight += 1
            self._calls += 1
            try:
                return await client.complete_json(**kwargs)
            finally:
                self.inflight -= 1
