"""Embedding provider adapters with explicit degradation errors."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

QUERY_INSTRUCTION = (
    "Given an interview-preparation query, retrieve relevant passages from resumes, "
    "job descriptions, project documentation, source-code summaries, study notes, "
    "and prior confirmed answers."
)


class EmbeddingUnavailable(RuntimeError):
    """Signal that semantic indexing can degrade without failing the whole request."""


class OllamaEmbeddingClient:
    """Call Ollama's native batch embedding endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int,
        timeout: float,
    ) -> None:
        # Existing OpenAI-compatible configs commonly end in /v1, while the
        # native Ollama endpoint is rooted at /api/embed.
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents without a query instruction."""
        return await self._embed(list(texts))

    async def embed_query(self, query: str) -> list[float]:
        """Prepend a stable retrieval instruction only to the query."""
        vectors = await self._embed([f"Instruct: {QUERY_INSTRUCTION}\nQuery: {query}"])
        return vectors[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            # Local Ollama must bypass system HTTP proxies, which can return a
            # misleading 502 even for 127.0.0.1 on some Windows setups.
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": texts, "truncate": True},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingUnavailable("Ollama embedding service is unavailable") from exc
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingUnavailable("Ollama returned an invalid embedding batch")
        normalized = [[float(value) for value in vector] for vector in vectors]
        if any(len(vector) != self.dimensions for vector in normalized):
            raise EmbeddingUnavailable(
                f"Embedding dimension mismatch; expected {self.dimensions}"
            )
        return normalized
