"""Profile-scoped TF-IDF, vector fusion and bounded graph expansion."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from mianshi_agent.config import Settings
from mianshi_agent.db import Database
from mianshi_agent.embeddings import EmbeddingUnavailable, OllamaEmbeddingClient
from mianshi_agent.schemas import (
    RetrievalDiagnostics,
    RetrievalItem,
    RetrievalResponse,
)


def lexical_tokens(text: str) -> list[str]:
    """Tokenize identifiers and Chinese unigrams/bigrams for a deterministic baseline."""
    lowered = text.casefold()
    tokens = re.findall(r"[a-z0-9_][a-z0-9_.+#/-]*", lowered)
    for segment in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.extend(segment)
        tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
    return tokens


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    total = max(1, sum(counts.values()))
    return {token: count / total * idf.get(token, 1.0) for token, count in counts.items()}


def _sparse_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    numerator = sum(value * right.get(token, 0.0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, numerator / (left_norm * right_norm)))


def tfidf_scores(query: str, chunks: list[dict[str, Any]]) -> dict[str, float]:
    """Score the complete active profile corpus so IDF is stable within one query."""
    query_tokens = lexical_tokens(query)
    document_tokens = [lexical_tokens(item["text"]) for item in chunks]
    if not query_tokens or not document_tokens:
        return {item["chunk_id"]: 0.0 for item in chunks}
    document_frequency = Counter(token for tokens in document_tokens for token in set(tokens))
    size = len(document_tokens)
    idf = {
        token: math.log((1 + size) / (1 + count)) + 1.0
        for token, count in document_frequency.items()
    }
    query_vector = _tfidf_vector(query_tokens, idf)
    return {
        chunk["chunk_id"]: _sparse_cosine(query_vector, _tfidf_vector(tokens, idf))
        for chunk, tokens in zip(chunks, document_tokens, strict=True)
    }


def dense_cosine(left: list[float], right: list[float]) -> float:
    """Compute bounded cosine similarity for equal-length dense vectors."""
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


class RetrievalService:
    """Fuse independent retrieval channels and disclose degradation."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        embeddings: OllamaEmbeddingClient,
    ) -> None:
        self.database = database
        self.settings = settings
        self.embeddings = embeddings

    async def retrieve(
        self,
        profile_id: str,
        query: str,
        *,
        limit: int,
        graph_hops: int,
        memory_only: bool = False,
    ) -> RetrievalResponse:
        """Retrieve evidence while never falling through to another profile."""
        await self.database.require_profile(profile_id)
        chunks = await self.database.list_chunks(profile_id, for_memory=memory_only)
        lexical = tfidf_scores(query, chunks)
        lexical_ranked = sorted(lexical, key=lexical.get, reverse=True)[
            : self.settings.retrieval_lexical_limit
        ]

        vector: dict[str, float] = {}
        embedding_status = "not_needed"
        embedding_error = None
        embedded_chunks = [
            item
            for item in chunks
            if item["embedding"]
            and item["embedding_model"] == self.settings.memory_embedding_model
            and item["embedding_dimensions"] == self.settings.memory_embedding_dimensions
        ]
        if embedded_chunks:
            try:
                query_vector = await self.embeddings.embed_query(query)
                vector = {
                    item["chunk_id"]: dense_cosine(query_vector, item["embedding"])
                    for item in embedded_chunks
                }
                embedding_status = "ok"
            except EmbeddingUnavailable as exc:
                embedding_status = "unavailable"
                embedding_error = str(exc)
        vector_ranked = sorted(vector, key=vector.get, reverse=True)[
            : self.settings.retrieval_vector_limit
        ]

        fused: dict[str, float] = {}
        for ranking in (lexical_ranked, vector_ranked):
            for rank, chunk_id in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (
                    self.settings.retrieval_rrf_k + rank
                )

        seed_ids = sorted(fused, key=fused.get, reverse=True)[:limit]
        graph_distances, graph_nodes_visited = await self.database.expand_chunks(
            profile_id,
            seed_ids,
            max_hops=min(graph_hops, self.settings.retrieval_max_graph_hops),
            max_nodes=self.settings.retrieval_max_graph_nodes,
        )
        for chunk_id, distance in graph_distances.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (
                self.settings.retrieval_rrf_k + len(seed_ids) + distance
            )

        by_id = {item["chunk_id"]: item for item in chunks}
        ranked_ids = [
            chunk_id for chunk_id in sorted(fused, key=fused.get, reverse=True) if chunk_id in by_id
        ][:limit]
        items = [
            RetrievalItem(
                chunk_id=chunk_id,
                source_id=by_id[chunk_id]["source_id"],
                source_title=by_id[chunk_id]["source_title"],
                source_kind=by_id[chunk_id]["source_kind"],
                text=by_id[chunk_id]["text"],
                locator=by_id[chunk_id]["locator"],
                fused_score=fused[chunk_id],
                lexical_score=lexical.get(chunk_id, 0.0),
                vector_score=vector.get(chunk_id, 0.0),
                graph_distance=graph_distances.get(chunk_id),
            )
            for chunk_id in ranked_ids
        ]
        return RetrievalResponse(
            items=items,
            diagnostics=RetrievalDiagnostics(
                lexical_candidates=len(lexical_ranked),
                vector_candidates=len(vector_ranked),
                graph_nodes_visited=graph_nodes_visited,
                embedding_status=embedding_status,
                embedding_error=embedding_error,
            ),
        )
