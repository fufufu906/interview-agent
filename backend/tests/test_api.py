from pathlib import Path

import httpx

from mianshi_agent.config import Settings
from mianshi_agent.main import create_app


async def test_profile_file_ingestion_and_retrieval_api(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        app_database_path=tmp_path / "api.sqlite3",
        memory_embedding_base_url="http://127.0.0.1:1",
        embedding_timeout=0.1,
    )
    app = create_app(settings)
    await app.state.database.initialize()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        profile = await client.post(
            "/api/profiles",
            json={"profile_id": "candidate", "display_name": "候选人"},
        )
        imported = await client.post(
            "/api/profiles/candidate/sources/file",
            data={"kind": "study_note", "title": "异步笔记"},
            files={"file": ("asyncio.md", "asyncio 取消与超时处理".encode())},
        )
        sources = await client.get("/api/profiles/candidate/sources")
        retrieval = await client.post(
            "/api/profiles/candidate/retrieve",
            json={"query": "asyncio 超时", "limit": 3, "graph_hops": 1},
        )

    assert profile.status_code == 200
    assert imported.status_code == 201
    assert imported.json()["embedding_status"] == "degraded"
    assert sources.status_code == 200
    assert len(sources.json()["items"]) == 1
    assert retrieval.status_code == 200
    assert retrieval.json()["items"][0]["source_title"] == "异步笔记"
