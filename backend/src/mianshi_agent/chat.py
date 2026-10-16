"""OpenAI-compatible chat adapter with strict JSON extraction."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ChatUnavailable(RuntimeError):
    """Signal a failed or invalid chat-model response."""


class ChatCompletionClient:
    """Call the configured chat model without exposing provider details downstream."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete_json(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Return one JSON object or raise a stable provider error."""
        if not self.base_url or not self.api_key:
            raise ChatUnavailable("chat_model_not_configured")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.model.lower().startswith("deepseek-v4-") or "api.deepseek.com" in (
            self.base_url.lower()
        ):
            # This provider enables high-effort hidden reasoning by default. For
            # short structured output it can consume the whole completion budget
            # before emitting content, so use its supported opt-out request field.
            payload["thinking"] = {"type": "disabled"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(2):
                    try:
                        response = await client.post(
                            f"{self.base_url}/chat/completions",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json=payload,
                        )
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        # No request has reached the model at this stage. Do not
                        # replay ambiguous read/write failures or HTTP errors.
                        if attempt:
                            raise
                        logger.warning("Chat connection failed; retrying connection once")
                        await asyncio.sleep(0.25)
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Chat upstream rejected request: HTTP %s", status)
            if status in (401, 403):
                code = "chat_model_auth_failed"
            elif status == 429:
                code = "chat_model_rate_limited"
            elif status >= 500:
                code = "chat_model_upstream_unavailable"
            else:
                code = "chat_model_request_rejected"
            raise ChatUnavailable(code) from exc
        except httpx.TimeoutException as exc:
            logger.warning("Chat request failed: %s", type(exc).__name__)
            raise ChatUnavailable("chat_model_timeout") from exc
        except httpx.RequestError as exc:
            logger.warning("Chat request failed: %s", type(exc).__name__)
            raise ChatUnavailable("chat_model_connection_failed") from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Chat response failed: %s", type(exc).__name__)
            raise ChatUnavailable("chat_model_request_failed") from exc
        if not isinstance(content, str) or not content.strip():
            raise ChatUnavailable("chat_model_returned_empty_content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = self._extract_json_object(content)
        if not isinstance(parsed, dict):
            raise ChatUnavailable("chat_model_did_not_return_an_object")
        return parsed

    @staticmethod
    def _extract_json_object(content: str) -> dict[str, Any]:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        candidate = (
            fenced.group(1)
            if fenced
            else content[content.find("{") : content.rfind("}") + 1]
        )
        if not candidate:
            raise ChatUnavailable("chat_model_returned_invalid_json")
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ChatUnavailable("chat_model_returned_invalid_json") from exc
        if not isinstance(parsed, dict):
            raise ChatUnavailable("chat_model_did_not_return_an_object")
        return parsed
