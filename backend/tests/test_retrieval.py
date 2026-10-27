from pathlib import Path

import pytest

from mianshi_agent.config import Settings
from mianshi_agent.db import Database
from mianshi_agent.embeddings import EmbeddingUnavailable
from mianshi_agent.retrieval import RetrievalService
from mianshi_agent.schemas import TextSourceCreate
from mianshi_agent.service import ProfileService


class OfflineEmbeddings:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailable("offline for test")

    async def embed_query(self, query: str) -> list[float]:
        raise EmbeddingUnavailable("offline for test")


@pytest.fixture
async def services(tmp_path: Path):
    settings = Settings(
        app_data_dir=tmp_path,
        app_database_path=tmp_path / "test.sqlite3",
    )
    database = Database(settings.app_database_path)
    await database.initialize()
    embeddings = OfflineEmbeddings()
    return (
        database,
        ProfileService(database, settings, embeddings),
        RetrievalService(database, settings, embeddings),
    )


async def test_lexical_retrieval_degrades_cleanly_without_embeddings(services) -> None:
    database, profiles, retrieval = services
    await database.create_profile("self", "演示候选人")
    result = await profiles.ingest_text(
        "self",
        TextSourceCreate(
            kind="project_document",
            title="任务恢复设计",
            text="LangGraph Checkpointer 保存执行状态。幂等写入避免恢复后产生重复业务记录。",
        ),
    )
    assert result.response.embedding_status == "degraded"

    response = await retrieval.retrieve(
        "self", "恢复任务时如何避免重复写入", limit=3, graph_hops=1
    )
    assert response.items
    assert response.items[0].source_title == "任务恢复设计"
    assert response.items[0].lexical_score > 0
    assert response.diagnostics.embedding_status == "not_needed"


async def test_profile_queries_never_return_another_profiles_chunks(services) -> None:
    database, profiles, retrieval = services
    await database.create_profile("alice", "Alice")
    await database.create_profile("bob", "Bob")
    await profiles.ingest_text(
        "alice",
        TextSourceCreate(kind="resume", title="Alice resume", text="Alice 熟悉 Python asyncio。"),
    )
    await profiles.ingest_text(
        "bob",
        TextSourceCreate(kind="resume", title="Bob resume", text="Bob 熟悉 Java Spring Boot。"),
    )

    response = await retrieval.retrieve("alice", "Java Spring Boot", limit=5, graph_hops=0)
    assert all(item.source_title != "Bob resume" for item in response.items)


async def test_same_source_deduplicates_inside_profile_only(services) -> None:
    database, profiles, _ = services
    await database.create_profile("alice", "Alice")
    await database.create_profile("bob", "Bob")
    payload = TextSourceCreate(kind="study_note", title="RAG", text="向量检索与词法检索互补。")

    first = await profiles.ingest_text("alice", payload)
    second = await profiles.ingest_text("alice", payload)
    other_profile = await profiles.ingest_text("bob", payload)

    assert first.deduplicated is False
    assert second.deduplicated is True
    assert second.response.source_id == first.response.source_id
    assert other_profile.deduplicated is False
    assert other_profile.response.source_id != first.response.source_id


async def test_ingestion_builds_adjacent_chunk_graph(services) -> None:
    database, profiles, _ = services
    await database.create_profile("self", "演示候选人")
    await profiles.ingest_text(
        "self",
        TextSourceCreate(
            kind="study_note",
            title="长文档",
            text=f"第一部分\n\n{'架' * 500}\n\n第二部分\n\n{'构' * 500}",
        ),
    )
    chunks = await database.list_chunks("self")
    assert len(chunks) >= 2

    distances, visited = await database.expand_chunks(
        "self",
        [chunks[0]["chunk_id"]],
        max_hops=1,
        max_nodes=20,
    )
    assert chunks[1]["chunk_id"] in distances
    assert distances[chunks[1]["chunk_id"]] == 1
    assert visited >= 2


async def test_reindex_reports_unavailable_provider(services) -> None:
    database, profiles, _ = services
    await database.create_profile("self", "演示候选人")
    await profiles.ingest_text(
        "self",
        TextSourceCreate(kind="study_note", title="RAG", text="混合检索"),
    )

    result = await profiles.reindex_missing_embeddings("self")
    assert result.chunks_found == 1
    assert result.chunks_indexed == 0
    assert result.embedding_status == "unavailable"


async def test_changed_repository_file_deactivates_previous_version(services) -> None:
    database, profiles, retrieval = services
    await database.create_profile("self", "演示候选人")
    common = {
        "kind": "project_repository",
        "title": "项目文件",
        "origin_uri": "project://demo/service.py",
        "metadata": {"content_format": "code", "replace_origin": True},
    }
    await profiles.ingest_text(
        "self",
        TextSourceCreate(text="def old_implementation():\n    return 'old'", **common),
    )
    await profiles.ingest_text(
        "self",
        TextSourceCreate(text="def current_implementation():\n    return 'current'", **common),
    )

    sources = await database.list_sources("self")
    response = await retrieval.retrieve(
        "self", "old_implementation", limit=5, graph_hops=0
    )
    assert len(sources) == 1
    assert all("old_implementation" not in item.text for item in response.items)
