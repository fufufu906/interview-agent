"""Public visitor boundaries, BYOK background routing, expiry and cost controls."""

import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import pytest

from mianshi_agent.chat import ChatCompletionClient, ChatUnavailable
from mianshi_agent.demo_credentials import VisitorChat
from mianshi_agent.public_demo import COOKIE, DemoSettings, create_demo_app

KEY_A = "sk-demo-visitor-a-not-a-real-key"
KEY_B = "sk-demo-visitor-b-not-a-real-key"
HEADERS = {"X-Interview-Demo": "1", "Origin": "https://demo.example"}


@asynccontextmanager
async def client_for(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://demo.example", headers=HEADERS
    ) as c:
        yield c


@pytest.fixture
async def demo(tmp_path, monkeypatch):
    # Public mode must never fall back to the owner's configured model.
    monkeypatch.setenv("LLM_API_KEY", "owner-key-must-not-be-used")
    settings = DemoSettings(
        data_dir=tmp_path,
        public_origin="https://demo.example",
        embedding_base_url="http://127.0.0.1:1",
    )
    app = create_demo_app(settings)
    async with app.router.lifespan_context(app):
        yield app, tmp_path


async def visit(c, key=None):
    assert (await c.post("/api/demo/visit")).status_code == 200
    assert (await c.get("/api/profiles")).status_code == 200
    if key:
        result = await c.post(
            "/api/demo/credentials", json={"api_key": key, "model": "deepseek-flash"}
        )
        assert result.status_code == 200, result.text


async def test_public_example_requires_no_key_but_private_api_does(demo):
    app, _ = demo
    async with client_for(app) as c:
        example = await c.get("/api/demo/example")
        assert "非本次实时生成" in example.json()["label"]
        assert (await c.get("/api/profiles")).status_code == 401
        cookie = await c.post("/api/demo/visit")
        assert "HttpOnly" in cookie.headers["set-cookie"]
        assert "Secure" in cookie.headers["set-cookie"]
        assert "SameSite=strict" in cookie.headers["set-cookie"]
        await c.get("/api/profiles")
        assert (await c.post("/api/profiles/visitor/interviews", json={"max_prompts": 1})).json()[
            "detail"
        ] == "demo_key_required"


async def test_visitor_sources_and_ids_cannot_cross_databases(demo):
    app, _ = demo
    async with client_for(app) as a, client_for(app) as b:
        await visit(a, KEY_A)
        await visit(b, KEY_B)
        result = await a.post(
            "/api/profiles/visitor/sources/text",
            json={
                "kind": "study_note",
                "title": "A-private",
                "text": "belongs-only-to-A",
            },
        )
        assert result.status_code == 201
        sid = result.json()["source_id"]
        assert (await a.get(f"/api/profiles/visitor/sources/{sid}")).status_code == 200
        assert (await b.get(f"/api/profiles/visitor/sources/{sid}")).status_code == 404
        assert "A-private" not in (await b.get("/api/profiles/visitor/sources")).text
        assert (await b.get("/api/profiles/self/sources")).status_code == 404
        assert (await a.post("/api/profiles", json={"profile_id": "other"})).status_code == 403


async def test_csrf_host_file_and_arbitrary_provider_are_rejected(demo):
    app, _ = demo
    async with client_for(app) as c:
        assert (
            await c.post("/api/demo/visit", headers={"Origin": "https://evil.example"})
        ).status_code == 403
        await visit(c, KEY_A)
        result = await c.post("/api/profiles/visitor/sources/folder/scan", json={"path": "/app"})
        assert result.status_code == 403
        assert (await c.get("/api/profiles/visitor/external-review-samples")).json() == []
        result = await c.post(
            "/api/demo/credentials",
            json={
                "api_key": KEY_A,
                "model": "deepseek-flash",
                "base_url": "http://127.0.0.1/admin",
            },
        )
        assert result.status_code == 422
        assert KEY_A not in result.text


async def test_secret_never_returned_or_persisted_and_cannot_silently_change(demo, caplog):
    app, root = demo
    async with client_for(app) as c:
        await visit(c, KEY_A)
        assert KEY_A not in (await c.get("/api/demo/credentials")).text
        result = await c.post(
            "/api/demo/credentials", json={"api_key": KEY_B, "model": "deepseek-flash"}
        )
        assert result.status_code == 422 and KEY_B not in result.text
        await c.delete("/api/demo/credentials")
        assert not (await c.get("/api/demo/credentials")).json()["connected"]
        await visit(c, KEY_A)  # Explicit renewal of the same identity is allowed.
    for path in root.iterdir():
        data = path.read_bytes()
        assert KEY_A.encode() not in data and KEY_B.encode() not in data
        assert b"owner-key-must-not-be-used" not in data
    assert KEY_A not in caplog.text


async def test_expired_key_fails_closed_even_for_background_client(demo, monkeypatch):
    app, _ = demo
    calls = []

    async def fake(self, **kwargs):
        calls.append(self.api_key)
        return {"ok": True}

    monkeypatch.setattr(ChatCompletionClient, "complete_json", fake)
    async with client_for(app) as a, client_for(app) as b:
        await visit(a, KEY_A)
        await visit(b, KEY_B)
        guests = list(app.state.visitors.guests.values())
        await asyncio.gather(*(g.chat.complete_json() for g in guests))
        assert set(calls) == {KEY_A, KEY_B}
        guests[0].chat.expires_at = time.time() - 1
        with pytest.raises(ChatUnavailable, match="demo_key_required"):
            await guests[0].chat.complete_json()
        assert guests[0].chat.api_key == ""
        assert len(calls) == 2


async def test_restart_keeps_records_but_requires_same_key(demo):
    app, root = demo
    async with client_for(app) as c:
        await visit(c, KEY_A)
        cookie = c.cookies.get(COOKIE)
    for digest in list(app.state.visitors.guests):
        await app.state.visitors.close(digest)
    async with client_for(app) as c:
        c.cookies.set(COOKIE, cookie)
        assert len((await c.get("/api/profiles/visitor/sources")).json()["items"]) == 3
        assert not (await c.get("/api/demo/credentials")).json()["connected"]
        assert (
            await c.post(
                "/api/demo/credentials", json={"api_key": KEY_B, "model": "deepseek-flash"}
            )
        ).status_code == 422
        await visit(c, KEY_A)
        assert (await c.get("/api/demo/credentials")).json()["connected"]


async def test_size_limits_and_reset_revoke_old_cookie(demo):
    app, _ = demo
    async with client_for(app) as c:
        await visit(c, KEY_A)
        cookie = c.cookies.get(COOKIE)
        response = await c.post("/api/profiles/visitor/sources/text", content=b"x" * 2_000_001)
        assert response.status_code == 413
        assert (
            await c.post("/api/profiles/visitor/interviews", json={"max_prompts": 20})
        ).status_code == 422
        assert (await c.post("/api/demo/reset")).status_code == 200
        c.cookies.set(COOKIE, cookie)
        assert (await c.get("/api/profiles")).status_code == 401


async def test_background_suggestions_keep_each_visitors_key(demo, monkeypatch):
    app, _ = demo
    calls = []

    async def fake(self, *, max_tokens, **kwargs):
        calls.append((self.api_key, max_tokens))
        if max_tokens == 600:
            return {"kind": "question", "question": "如何处理资料缺口？", "competency": "证据边界"}
        if "面试记忆回答助手" in kwargs.get("system_prompt", ""):
            return {
                "answer": "明确列出资料缺口，不编造个人经历。",
                "basis": "general_knowledge",
                "citations": [],
                "evidence_gaps": [],
            }
        return {
            "summary": "演示复盘",
            "dimensions": [],
            "strengths": [],
            "improvements": [],
            "knowledge_gaps": [],
            "evidence_gaps": [],
            "next_practice": [],
        }

    monkeypatch.setattr(ChatCompletionClient, "complete_json", fake)
    async with client_for(app) as a, client_for(app) as b:
        for c, key in ((a, KEY_A), (b, KEY_B)):
            await visit(c, key)
            start = await c.post("/api/profiles/visitor/interviews", json={"max_prompts": 1})
            assert start.status_code == 201, start.text
            sid = start.json()["session"]["session_id"]
            result = await c.post(
                f"/api/profiles/visitor/interviews/{sid}/answers",
                json={"answer": "我会说明缺口。", "request_id": "answer-001"},
            )
            assert result.status_code == 200, result.text
        for _ in range(100):
            if {key for key, tokens in calls if tokens == 1800} == {KEY_A, KEY_B}:
                break
            await asyncio.sleep(0.05)
        assert {key for key, tokens in calls if tokens == 1800} == {KEY_A, KEY_B}
        assert all(key in (KEY_A, KEY_B) for key, _ in calls)


def test_public_origin_requires_https_unless_explicit_local_preview():
    with pytest.raises(ValueError):
        DemoSettings(public_origin="http://public.example")
    with pytest.raises(ValueError):
        DemoSettings(public_origin="https://demo.example/some/path")
    assert DemoSettings(public_origin="http://127.0.0.1:5180", allow_http_local=True)


async def test_lease_rechecks_expiry_after_waiting_for_capacity(monkeypatch):
    slot = asyncio.Semaphore(0)
    chat = VisitorChat("salt", None, slot)
    chat.connect(KEY_A, "deepseek-flash")
    task = asyncio.create_task(chat.complete_json())
    await asyncio.sleep(0)
    chat.disconnect()
    slot.release()
    with pytest.raises(ChatUnavailable, match="demo_key_required"):
        await task
