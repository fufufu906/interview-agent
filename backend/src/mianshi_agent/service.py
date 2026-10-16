"""Application services for profiles, role targets and source ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import aiosqlite

from mianshi_agent.chunking import split_code_document, split_document
from mianshi_agent.config import Settings
from mianshi_agent.db import Database, utcnow_iso
from mianshi_agent.embeddings import EmbeddingUnavailable, OllamaEmbeddingClient
from mianshi_agent.memory_write import MemoryWriteRequest, MemoryWriteService
from mianshi_agent.schemas import (
    ReindexResponse,
    RoleTargetCreate,
    RoleTargetResponse,
    SourceResponse,
    TextSourceCreate,
)

EMBEDDING_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Return public source metadata and whether deduplication was used."""

    response: SourceResponse
    deduplicated: bool


class ProfileService:
    """Coordinate validated writes without embedding secrets in persisted data."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        embeddings: OllamaEmbeddingClient,
        memory_writer: MemoryWriteService | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.embeddings = embeddings
        self.memory_writer = memory_writer or MemoryWriteService(database)

    async def _remember_source(
        self,
        profile_id: str,
        source_id: str,
        request: TextSourceCreate,
    ) -> None:
        await self.memory_writer.record(
            profile_id,
            f"source:{source_id}",
            MemoryWriteRequest(
                content=request.text[:12_000],
                event_type="source_import",
                source_id=source_id,
                source_kind=request.kind,
                source_title=request.title,
                metadata=request.metadata,
            ),
        )

    async def create_role_target(
        self,
        profile_id: str,
        request: RoleTargetCreate,
    ) -> RoleTargetResponse:
        """Store role text and explicit competencies as a small evidence graph."""
        await self.database.require_profile(profile_id)
        role_id = f"role_{uuid4().hex}"
        created_at = utcnow_iso()
        role = await self.database.create_role_target(
            {
                "role_target_id": role_id,
                "profile_id": profile_id,
                "title": request.title,
                "level": request.level,
                "company": request.company,
                "jd_text": request.jd_text,
                "competencies": request.competencies,
                "active": request.activate,
                "created_at": created_at,
            }
        )
        source = await self.ingest_text(
            profile_id,
            TextSourceCreate(
                kind="job_description",
                title=f"岗位 JD：{request.title}",
                text=request.jd_text,
                metadata={"role_target_id": role_id},
            ),
        )
        nodes = [
            {
                "node_id": role_id,
                "profile_id": profile_id,
                "node_type": "role",
                "name": request.title,
                "description": request.jd_text[:1000],
                "source_chunk_id": None,
                "verification_status": "user_supplied",
                "metadata": {"source_id": source.response.source_id},
                "created_at": created_at,
            }
        ]
        edges: list[dict[str, Any]] = []
        source_node_id = f"document_{source.response.source_id}"
        edges.append(
            {
                "edge_id": self._stable_id("edge", role_id, source_node_id, "described_by"),
                "profile_id": profile_id,
                "source_node_id": role_id,
                "target_node_id": source_node_id,
                "edge_type": "described_by",
                "weight": 1.0,
                "verification_status": "user_supplied",
                "created_at": created_at,
            }
        )
        competencies = dict.fromkeys(item.strip() for item in request.competencies if item.strip())
        for competency in competencies:
            digest = hashlib.sha256(f"{profile_id}:{competency}".encode()).hexdigest()
            node_id = f"competency_{digest[:24]}"
            nodes.append(
                {
                    "node_id": node_id,
                    "profile_id": profile_id,
                    "node_type": "competency",
                    "name": competency,
                    "description": "",
                    "source_chunk_id": None,
                    "verification_status": "user_supplied",
                    "metadata": {},
                    "created_at": created_at,
                }
            )
            edges.append(
                {
                    "edge_id": f"edge_{uuid4().hex}",
                    "profile_id": profile_id,
                    "source_node_id": role_id,
                    "target_node_id": node_id,
                    "edge_type": "requires",
                    "weight": 1.0,
                    "verification_status": "user_supplied",
                    "created_at": created_at,
                }
            )
        await self.database.create_graph_nodes_and_edges(nodes, edges)
        return RoleTargetResponse(**role)

    async def ingest_text(
        self,
        profile_id: str,
        request: TextSourceCreate,
    ) -> IngestResult:
        """Chunk, optionally embed, and atomically store one text source."""
        await self.database.require_profile(profile_id)
        normalized_text = request.text.replace("\r\n", "\n").replace("\r", "\n").strip()
        hash_input = normalized_text
        if request.kind == "project_repository":
            hash_input = f"{request.origin_uri}\0{normalized_text}"
        content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        existing = await self.database.find_source_by_hash(profile_id, content_hash)
        if existing:
            await self._remember_source(profile_id, existing["source_id"], request)
            await self._ensure_source_graph(
                profile_id,
                existing["source_id"],
                existing["title"],
                existing["kind"],
            )
            return IngestResult(
                response=SourceResponse(
                    source_id=existing["source_id"],
                    profile_id=profile_id,
                    kind=existing["kind"],
                    title=existing["title"],
                    content_hash=content_hash,
                    chunk_count=existing["chunk_count"],
                    embedding_status="not_requested",
                    created_at=existing["created_at"],
                ),
                deduplicated=True,
            )

        text_chunks = (
            split_code_document(normalized_text)
            if request.metadata.get("content_format") == "code"
            else split_document(normalized_text)
        )
        embeddings: list[list[float] | None] = [None] * len(text_chunks)
        embedding_status = "indexed"
        embedding_error = None
        try:
            vectors = await self._embed_in_batches([item.text for item in text_chunks])
            embeddings = list(vectors)
        except EmbeddingUnavailable as exc:
            embedding_status = "degraded"
            embedding_error = str(exc)

        source_id = f"source_{uuid4().hex}"
        created_at = utcnow_iso()
        chunks = [
            {
                "chunk_id": f"chunk_{uuid4().hex}",
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "locator": chunk.locator,
                "embedding_model": self.settings.memory_embedding_model if vector else None,
                "embedding_dimensions": len(vector) if vector else None,
                "embedding": vector,
            }
            for chunk, vector in zip(text_chunks, embeddings, strict=True)
        ]
        try:
            await self.database.insert_source_with_chunks(
                {
                    "source_id": source_id,
                    "profile_id": profile_id,
                    "kind": request.kind,
                    "title": request.title,
                    "origin_uri": request.origin_uri,
                    "content_hash": content_hash,
                    "raw_text": normalized_text,
                    "metadata": request.metadata,
                    "created_at": created_at,
                },
                chunks,
            )
        except aiosqlite.IntegrityError:
            existing = await self.database.find_source_by_hash(profile_id, content_hash)
            if existing is None:
                raise
            await self._remember_source(profile_id, existing["source_id"], request)
            await self._ensure_source_graph(
                profile_id,
                existing["source_id"],
                existing["title"],
                existing["kind"],
            )
            return IngestResult(
                response=SourceResponse(
                    source_id=existing["source_id"],
                    profile_id=profile_id,
                    kind=existing["kind"],
                    title=existing["title"],
                    content_hash=content_hash,
                    chunk_count=existing["chunk_count"],
                    embedding_status="not_requested",
                    created_at=existing["created_at"],
                ),
                deduplicated=True,
            )
        await self._ensure_source_graph(profile_id, source_id, request.title, request.kind)
        await self._remember_source(profile_id, source_id, request)
        if request.metadata.get("replace_origin") and request.origin_uri:
            await self.database.deactivate_other_source_versions(
                profile_id,
                request.origin_uri,
                source_id,
            )
        return IngestResult(
            response=SourceResponse(
                source_id=source_id,
                profile_id=profile_id,
                kind=request.kind,
                title=request.title,
                content_hash=content_hash,
                chunk_count=len(chunks),
                embedding_status=embedding_status,
                embedding_error=embedding_error,
                created_at=created_at,
            ),
            deduplicated=False,
        )

    async def reindex_missing_embeddings(self, profile_id: str) -> ReindexResponse:
        """Retry semantic indexing without re-importing source documents."""
        await self.database.require_profile(profile_id)
        chunks = await self.database.list_chunks_without_embeddings(profile_id)
        if not chunks:
            return ReindexResponse(
                chunks_found=0,
                chunks_indexed=0,
                embedding_status="not_needed",
            )
        try:
            vectors = await self._embed_in_batches([item["text"] for item in chunks])
        except EmbeddingUnavailable as exc:
            return ReindexResponse(
                chunks_found=len(chunks),
                chunks_indexed=0,
                embedding_status="unavailable",
                embedding_error=str(exc),
            )
        await self.database.update_chunk_embeddings(
            profile_id,
            [
                {
                    "chunk_id": chunk["chunk_id"],
                    "embedding_model": self.settings.memory_embedding_model,
                    "embedding_dimensions": len(vector),
                    "embedding": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )
        return ReindexResponse(
            chunks_found=len(chunks),
            chunks_indexed=len(chunks),
            embedding_status="indexed",
        )

    async def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            vectors.extend(
                await self.embeddings.embed_documents(texts[start : start + EMBEDDING_BATCH_SIZE])
            )
        return vectors

    async def _ensure_source_graph(
        self,
        profile_id: str,
        source_id: str,
        source_title: str,
        source_kind: str,
    ) -> None:
        """Create deterministic document, chunk and adjacency evidence nodes."""
        source_chunks = [
            item
            for item in await self.database.list_chunks(profile_id)
            if item["source_id"] == source_id
        ]
        if not source_chunks:
            return
        created_at = utcnow_iso()
        document_node_id = f"document_{source_id}"
        nodes: list[dict[str, Any]] = [
            {
                "node_id": document_node_id,
                "profile_id": profile_id,
                "node_type": "document",
                "name": source_title,
                "description": source_kind,
                "source_chunk_id": source_chunks[0]["chunk_id"],
                "verification_status": "user_supplied",
                "metadata": {"source_id": source_id, "source_kind": source_kind},
                "created_at": created_at,
            }
        ]
        edges: list[dict[str, Any]] = []
        previous_node_id: str | None = None
        for chunk in source_chunks:
            chunk_node_id = f"evidence_{chunk['chunk_id']}"
            nodes.append(
                {
                    "node_id": chunk_node_id,
                    "profile_id": profile_id,
                    "node_type": "evidence_chunk",
                    "name": f"{source_title} #{chunk['ordinal'] + 1}",
                    "description": chunk["text"][:300],
                    "source_chunk_id": chunk["chunk_id"],
                    "verification_status": "user_supplied",
                    "metadata": {"source_id": source_id, "ordinal": chunk["ordinal"]},
                    "created_at": created_at,
                }
            )
            edges.append(
                {
                    "edge_id": self._stable_id("edge", document_node_id, chunk_node_id, "contains"),
                    "profile_id": profile_id,
                    "source_node_id": document_node_id,
                    "target_node_id": chunk_node_id,
                    "edge_type": "contains",
                    "weight": 1.0,
                    "source_chunk_id": chunk["chunk_id"],
                    "verification_status": "user_supplied",
                    "created_at": created_at,
                }
            )
            if previous_node_id:
                edges.append(
                    {
                        "edge_id": self._stable_id("edge", previous_node_id, chunk_node_id, "next"),
                        "profile_id": profile_id,
                        "source_node_id": previous_node_id,
                        "target_node_id": chunk_node_id,
                        "edge_type": "next",
                        "weight": 0.8,
                        "source_chunk_id": chunk["chunk_id"],
                        "verification_status": "derived",
                        "created_at": created_at,
                    }
                )
            previous_node_id = chunk_node_id
        await self.database.create_graph_nodes_and_edges(nodes, edges)

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]
        return f"{prefix}_{digest}"
