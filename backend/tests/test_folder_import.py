import hashlib
import json
import time

import httpx
import pytest

from mianshi_agent.chat import ChatUnavailable
from mianshi_agent.config import Settings
from mianshi_agent.folder_import import FolderImportCreate, FolderScanCreate, discover, safe_path
from mianshi_agent.main import create_app
from mianshi_agent.schemas import RoleTargetCreate, TextSourceCreate


class Recommender:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.context = None

    async def complete_json(self, **kwargs):
        self.context = json.loads(kwargs["messages"][0]["content"])
        if self.mode == "offline":
            raise ChatUnavailable("offline")
        if self.mode == "invent":
            return {"files": [{"file_id": "../outside.md", "reason": "invented"}]}
        return {
            "files": [
                {"file_id": item["file_id"], "reason": "后端架构相关"}
                for item in self.context["candidates"]
                if item["path"].endswith((".md", ".py"))
            ]
        }


@pytest.fixture
async def setup(tmp_path):
    app = create_app(
        Settings(
            app_database_path=tmp_path / "test.sqlite3",
            app_data_dir=tmp_path / "storage",
            memory_embedding_base_url="http://127.0.0.1:1",
            embedding_timeout=0.05,
        )
    )
    await app.state.database.initialize()
    await app.state.database.create_profile("candidate", "候选人")
    await app.state.database.create_profile("other", "另一人")
    root = tmp_path / "项目资料"
    root.mkdir()
    (root / "architecture.md").write_text("Checkpoint 恢复与幂等键设计", encoding="utf-8")
    (root / "worker.py").write_text("def resume():\n    return 'checkpoint'", encoding="utf-8")
    (root / "other.txt").write_text("周末做饭计划", encoding="utf-8")
    app.state.folder_service.chat = Recommender()
    return app, root


async def test_folder_api_import_preserves_original_provenance_and_deduplicates(setup):
    app, root = setup
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        base = "/api/profiles/candidate/sources/folder"
        scan = await client.post(f"{base}/scan", json={"path": str(root)})
        assert scan.status_code == 200
        plan = scan.json()
        assert plan["model_status"] == "recommended"
        ids = [f["file_id"] for f in plan["files"] if f["recommended"]]
        assert len(ids) == 2
        assert await app.state.database.list_sources("candidate") == []
        payload = {"scan_id": plan["scan_id"], "file_ids": ids, "kind": "study_note"}
        cross_profile = await client.post("/api/profiles/other/sources/folder/import", json=payload)
        assert cross_profile.status_code == 409
        imported = await client.post(f"{base}/import", json=payload)
        assert imported.status_code == 200
        assert imported.json()["imported"] == 2
        again = await client.post(f"{base}/import", json=payload)
        assert all(f["deduplicated"] for f in again.json()["files"])
        assert len(await app.state.database.list_sources("candidate")) == 2
        listed = (await client.get("/api/profiles/candidate/sources")).json()["items"]
        assert {item["relative_path"] for item in listed} == {"architecture.md", "worker.py"}
        assert all(item["folder_root"] == str(root) for item in listed)
        assert "metadata" not in listed[0]
        code = next(f for f in imported.json()["files"] if f["path"] == "worker.py")
        detail = await app.state.database.source_detail("candidate", code["source"]["source_id"])
        assert detail["origin_uri"] == (root / "worker.py").as_uri()
        assert detail["metadata"]["provenance"] == "code_observed_not_contribution_proof"
        assert "def resume" in detail["chunks"][0]["text"]
        retrieval = await client.post(
            "/api/profiles/candidate/retrieve", json={"query": "Checkpoint 幂等"}
        )
        assert retrieval.json()["items"]
        assert await app.state.database.list_sources("other") == []
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}


async def test_changed_file_is_rejected_but_other_files_import(setup):
    app, root = setup
    service = app.state.folder_service
    scan = await service.scan("candidate", FolderScanCreate(path=str(root)))
    (root / "architecture.md").write_text("changed", encoding="utf-8")
    result = await service.import_selected(
        "candidate",
        FolderImportCreate(scan_id=scan["scan_id"], file_ids=[f["file_id"] for f in scan["files"]]),
    )
    assert result["failed"] == 1 and result["imported"] == 2
    assert "文件已变化" in result["files"][0]["error"]
    with pytest.raises(ValueError, match="folder_file_not_in_scan"):
        await service.import_selected(
            "candidate", FolderImportCreate(scan_id=scan["scan_id"], file_ids=["../other.md"])
        )
    service.plans[scan["scan_id"]].expires = time.monotonic() - 1
    with pytest.raises(ValueError, match="folder_scan_expired"):
        await service.import_selected(
            "candidate", FolderImportCreate(scan_id=scan["scan_id"], file_ids=["file_1"])
        )


@pytest.mark.parametrize(
    ("local_path", "relative_path", "expected_root"),
    [
        (r"E:\java-ai-xiaozhiyiliao\src\App.java", "src/App.java", r"E:\java-ai-xiaozhiyiliao"),
        (
            r"E:\autodeepsearch agent\backend\agent.py",
            "backend/agent.py",
            r"E:\autodeepsearch agent",
        ),
        ("/projects/demo/src/app.py", "src/app.py", "/projects/demo"),
        (r"E:\demo\other\App.java", "src/App.java", None),
        (r"E:\demo\App.java", "../App.java", None),
    ],
)
async def test_legacy_repository_paths_are_grouped_without_reimport(
    setup, local_path, relative_path, expected_root
):
    app, _ = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/profiles/candidate/sources/text",
            json={
                "kind": "project_repository",
                "title": "旧项目 · " + relative_path,
                "text": "已有项目正文，不重新导入。",
                "metadata": {"local_path": local_path, "relative_path": relative_path},
            },
        )
        assert created.status_code == 201
        source_id = created.json()["source_id"]
        listed = (await client.get("/api/profiles/candidate/sources")).json()["items"]
        assert listed[0]["folder_root"] == expected_root
        assert listed[0]["source_id"] == source_id
        detail = (await client.get(f"/api/profiles/candidate/sources/{source_id}")).json()
        assert "folder_root" not in detail["metadata"]
        assert detail["metadata"]["local_path"] == local_path


@pytest.mark.parametrize("mode", ["offline", "invent"])
async def test_model_failure_keeps_manual_candidates_without_importing(setup, mode):
    app, root = setup
    app.state.folder_service.chat = Recommender(mode)
    scan = await app.state.folder_service.scan("candidate", FolderScanCreate(path=str(root)))
    assert scan["model_status"] == "unavailable"
    assert len(scan["files"]) == 3 and all(not f["recommended"] for f in scan["files"])
    assert scan["warnings"]
    assert await app.state.database.list_sources("candidate") == []


async def test_model_context_uses_only_current_profile_resume_and_jd(setup):
    app, root = setup
    await app.state.profile_service.ingest_text(
        "candidate", TextSourceCreate(kind="resume", title="简历", text="使用 Python 开发后端")
    )
    await app.state.profile_service.ingest_text(
        "other", TextSourceCreate(kind="resume", title="他人简历", text="other-private-resume")
    )
    await app.state.profile_service.create_role_target(
        "candidate", RoleTargetCreate(title="后端工程师", jd_text="实现并发稳定性")
    )
    await app.state.folder_service.scan(
        "candidate", FolderScanCreate(path=str(root), focus="恢复机制")
    )
    context = app.state.folder_service.chat.context
    assert context["role"]["title"] == "后端工程师" and context["focus"] == "恢复机制"
    assert "Python" in str(context["resume"])
    assert "other-private" not in str(context)


def test_discovery_excludes_dependencies_hidden_credentials_and_unreadable_pdf(tmp_path):
    for name in ("node_modules", ".git", "dist"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "ignored.md").write_text("ignored")
    for name in (".env", "credentials.json", "secrets.yaml", "package-lock.json"):
        (tmp_path / name).write_text("secret")
    (tmp_path / "readme.md").write_text("readable")
    (tmp_path / "broken.pdf").write_bytes(b"not pdf")
    (tmp_path / "large.txt").write_text("a" * 100)
    files, warnings, stats = discover(tmp_path, 80)
    assert [f["path"] for f in files.values()] == ["readme.md"]
    assert stats["unreadable"] == 1 and stats["limited"]
    assert warnings
    with pytest.raises(ValueError, match="file_path_changed"):
        safe_path(tmp_path, "../outside.md")


async def test_invalid_folder_paths_have_actionable_errors(setup):
    app, root = setup
    for path, error in (
        ("relative", "folder_absolute_path_required"),
        (str(root / "missing"), "folder_not_found"),
        (root.anchor, "folder_select_subdirectory"),
    ):
        with pytest.raises(ValueError, match=error):
            await app.state.folder_service.scan("candidate", FolderScanCreate(path=path))
