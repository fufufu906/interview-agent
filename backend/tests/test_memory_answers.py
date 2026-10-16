"""Memory boundaries, durable jobs and automatic/manual generation contracts."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from mianshi_agent.config import Settings
from mianshi_agent.db import utcnow_iso
from mianshi_agent.main import create_app
from mianshi_agent.memory_answers import short_term_context
from mianshi_agent.memory_write import (
    MemoryWriteRequest,
    MemoryWriteRouter,
    MemoryWriteService,
)
from mianshi_agent.schemas import RoleTargetCreate, TextSourceCreate


class Classifier:
    def __init__(self, payload=None, fail=False):
        self.calls = 0
        self.payload = payload
        self.fail = fail

    async def complete_json(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline")
        return self.payload


@pytest.mark.parametrize(
    "event",
    [
        "interview_question",
        "interview_answer",
        "interview_review",
        "interview_skip",
        "generated_answer",
    ],
)
async def test_interview_events_always_use_short_term_rules(event):
    chat = Classifier(fail=True)
    result = await MemoryWriteRouter(chat).classify(
        MemoryWriteRequest(
            content="我是候选人，这是本轮材料",
            event_type=event,
        )
    )
    assert result.write_target == "short_term_memory"
    assert result.classifier == "rule"
    assert chat.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"category": "semantic", "write_target": "short_term_memory", "reason": "bad pairing"},
        {"category": "semantic", "write_target": "long_term_memory", "reason": "no source"},
        {"category": "unknown", "write_target": "general", "reason": "bad enum"},
    ],
)
async def test_unknown_write_cannot_fail_open(payload):
    chat = Classifier(payload)
    result = await MemoryWriteRouter(chat).classify(MemoryWriteRequest(content="ambiguous"))
    assert result.classifier == "fallback"
    assert result.write_target == "general"
    assert chat.calls == 1


async def test_unknown_write_llm_and_failure_fallback():
    chat = Classifier({"category": "general", "write_target": "general", "reason": "uncertain"})
    result = await MemoryWriteRouter(chat).classify(MemoryWriteRequest(content="ambiguous"))
    assert result.classifier == "llm"
    assert chat.calls == 1
    failed = await MemoryWriteRouter(Classifier(fail=True)).classify(
        MemoryWriteRequest(content="ambiguous"),
    )
    assert failed.write_target == "general"
    assert failed.confidence == 0


class ReferenceChat:
    def __init__(self):
        self.calls = []
        self.bad_citation = False

    async def complete_json(self, **kwargs):
        data = json.loads(kwargs["messages"][0]["content"])
        self.calls.append(data)
        material = data["长期资料"]
        return {
            "answer": "我会先明确任务状态和写入边界，再结合材料说明检查点与幂等约束。",
            "basis": "user_material" if material else "general_knowledge",
            "citations": ["foreign_chunk"]
            if self.bad_citation
            else ([material[0]["chunk_id"]] if material else []),
            "evidence_gaps": ["个人职责和上线效果仍需补充原始依据"],
        }


class InterviewChat:
    async def complete_json(self, *, max_tokens, **kwargs):
        if max_tokens == 600:
            return {"kind": "question", "question": "你怎样实现任务恢复？", "competency": "稳定性"}
        return {
            "summary": "只评价本轮实际回答",
            "dimensions": [],
            "strengths": [],
            "improvements": [],
            "knowledge_gaps": [],
            "evidence_gaps": [],
            "next_practice": [],
        }


@pytest.fixture
async def setup(tmp_path: Path):
    app = create_app(
        Settings(
            app_database_path=tmp_path / "memory.sqlite3",
            app_data_dir=tmp_path,
            memory_embedding_base_url="http://127.0.0.1:1",
            embedding_timeout=0.1,
            llm_base_url="",
            llm_api_key="",
        )
    )
    db = app.state.database
    await db.initialize()
    await db.create_profile("self", "候选人")
    await db.create_profile("other", "另一个档案")
    profiles = app.state.profile_service
    role = await profiles.create_role_target(
        "self",
        RoleTargetCreate(
            title="平台开发",
            jd_text="OLD_ROLE_SNAPSHOT 负责稳定性与任务恢复",
            competencies=["稳定性"],
        ),
    )
    await profiles.ingest_text(
        "self",
        TextSourceCreate(
            kind="project_document",
            title="任务恢复项目文档",
            text="SOURCE_DOCUMENT 使用检查点保存任务状态，通过幂等约束避免重复写入。",
        ),
    )
    await profiles.ingest_text(
        "self",
        TextSourceCreate(
            kind="study_note",
            title="历史面试复盘",
            text="HISTORICAL_MARKER 曾声称每秒处理一千万次请求，但未经验证。",
        ),
    )
    await profiles.ingest_text(
        "other",
        TextSourceCreate(
            kind="resume",
            title="其他档案简历",
            text="OTHER_PROFILE_SECRET 不应出现在候选人记忆里。",
        ),
    )
    app.state.interview_service.chat = InterviewChat()
    chat = ReferenceChat()
    app.state.memory_answer_service.chat = chat
    return app, db, role, chat


async def legacy_session(db, role, *, session_id="legacy", questions=2):
    now = utcnow_iso()
    await db.create_interview_session(
        {
            "session_id": session_id,
            "profile_id": "self",
            "role_target_id": role.role_target_id,
            "mode": "quick",
            "focus": "任务恢复",
            "max_prompts": 3,
            "created_at": now,
        }
    )
    for index in range(questions):
        await db.append_interviewer_turn(
            "self",
            session_id,
            {
                "turn_id": f"{session_id}_q{index}",
                "kind": "question",
                "content": f"第{index}题：任务恢复如何避免重复写入？",
                "competency": "稳定性",
                "evidence": [],
                "created_at": now,
            },
        )
        if index + 1 < questions:
            await db.accept_interview_answer(
                "self",
                session_id,
                {
                    "turn_id": f"{session_id}_a{index}",
                    "content": "CURRENT_SHORT_MARKER 本轮用检查点恢复。",
                    "request_id": f"request_{session_id}_{index}",
                    "created_at": now,
                },
            )
    review = {
        "summary": "原始复盘保留",
        "dimensions": [],
        "strengths": [],
        "improvements": [],
        "knowledge_gaps": [],
        "evidence_gaps": [],
        "next_practice": [],
    }
    await db.complete_interview_session("self", session_id, review)
    return await db.get_interview_session("self", session_id)


async def test_new_completion_auto_queues_and_preserves_real_answers(setup):
    app, db, _, chat = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        started = (await c.post("/api/profiles/self/interviews", json={"max_prompts": 1})).json()
        sid = started["session"]["session_id"]
        completed = await c.post(
            f"/api/profiles/self/interviews/{sid}/answers",
            json={
                "request_id": "new_answer_1",
                "answer": "CURRENT_SHORT_MARKER 我使用检查点恢复。",
            },
        )
        assert completed.status_code == 200
        session = completed.json()["session"]
        assert session["status"] == "completed"
        assert [r["status"] for r in session["memory_answers"]] == ["queued"]
        assert chat.calls == []  # API only enqueues; the worker performs generation.
        original_turns = session["turns"]
        assert await app.state.memory_answer_service.process_next()
        stored = (await c.get(f"/api/profiles/self/interviews/{sid}")).json()
    assert stored["turns"] == original_turns
    assert stored["review"]["summary"] == "只评价本轮实际回答"
    assert stored["memory_answers"][0]["status"] == "ready"
    assert "CURRENT_SHORT_MARKER" in chat.calls[0]["本轮短期记忆"]
    materials = json.dumps(chat.calls[0]["长期资料"], ensure_ascii=False)
    assert "SOURCE_DOCUMENT" in materials
    assert "CURRENT_SHORT_MARKER" not in materials
    assert "HISTORICAL_MARKER" not in materials
    assert "OTHER_PROFILE_SECRET" not in materials
    async with db.connect() as conn:
        rows = await (
            await conn.execute(
                "SELECT write_target FROM memory_write_log WHERE session_id = ?",
                (sid,),
            )
        ).fetchall()
    assert rows and all(row["write_target"] == "short_term_memory" for row in rows)


async def test_history_is_manual_profile_scoped_and_idempotent(setup):
    app, db, role, chat = setup
    original = await legacy_session(db, role)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        path = "/api/profiles/self/interviews/legacy"
        baseline = (await c.get(path)).json()
        assert baseline["memory_answers"] == []
        denied = await c.post("/api/profiles/other/interviews/legacy/memory-answers")
        assert denied.status_code == 404
        assert (await c.post(path + "/memory-answers")).status_code == 202
        assert (await c.post(path + "/memory-answers")).status_code == 202
        assert len((await c.get(path)).json()["memory_answers"]) == 2
        service = app.state.memory_answer_service
        assert await service.process_next()
        assert await service.process_next()
        assert not await service.process_next()
        assert len(chat.calls) == 2
        await c.post(path + "/memory-answers")
        assert not await service.process_next()
        result = (await c.get(path)).json()
    assert result["turns"] == original["turns"]
    assert result["review"] == baseline["review"]
    assert all(a["status"] == "ready" for a in result["memory_answers"])
    assert len(chat.calls) == 2


async def test_failure_retry_and_restart_do_not_discard_other_results(setup):
    app, db, role, chat = setup
    await legacy_session(db, role)
    service = app.state.memory_answer_service
    await service.enqueue("self", "legacy")
    chat.bad_citation = True
    assert await service.process_next()
    chat.bad_citation = False
    assert await service.process_next()
    answers = await db.list_memory_answers("self", "legacy")
    assert [a["status"] for a in answers] == ["error", "ready"]
    assert answers[0]["error"] == "memory_answer_invalid_citation"
    kept = answers[1]
    await service.enqueue("self", "legacy")
    claimed = await db.claim_memory_answer()
    assert claimed["question_turn_id"] == "legacy_q0"
    await db.recover_memory_answers()  # Simulate restarting mid-generation.
    assert await service.process_next()
    answers = await db.list_memory_answers("self", "legacy")
    assert [a["status"] for a in answers] == ["ready", "ready"]
    assert answers[1] == kept
    assert not await service.process_next()


async def test_bound_role_and_older_question_survive_context_window(setup):
    app, db, role, chat = setup
    session = await legacy_session(db, role, questions=1)
    await app.state.profile_service.create_role_target(
        "self",
        RoleTargetCreate(
            title="另一个岗位",
            jd_text="NEW_ROLE_MUST_NOT_REPLACE_OLD",
            competencies=[],
        ),
    )
    await app.state.memory_answer_service.enqueue("self", "legacy")
    await app.state.memory_answer_service.process_next()
    assert "OLD_ROLE_SNAPSHOT" in chat.calls[0]["岗位快照"]["jd"]
    assert "NEW_ROLE_MUST_NOT_REPLACE_OLD" not in json.dumps(chat.calls[0])
    question = session["turns"][0]
    session["turns"].extend(
        [
            {
                "turn_id": f"later_{i}",
                "speaker": "candidate",
                "kind": "answer",
                "content": "很长的后续回答" * 5000,
            }
            for i in range(20)
        ]
    )
    context = short_term_context(session, question, [])
    assert question["content"] in context
    assert len(context) <= 12_000


async def test_write_scope_and_non_scalar_metadata(setup):
    _, db, role, _ = setup
    await legacy_session(db, role, questions=1)
    writer = MemoryWriteService(db)
    with pytest.raises(KeyError):
        await writer.record(
            "other",
            "bad_event",
            MemoryWriteRequest(
                content="data",
                event_type="interview_answer",
                session_id="legacy",
            ),
        )
    result = await writer.router.classify(
        MemoryWriteRequest(
            content="资料正文",
            source_kind="project_document",
            metadata={"memory_scope": [], "content_type": {}},
        )
    )
    assert result.write_target == "long_term_memory"


async def test_lifespan_worker_drains_durable_queue(setup):
    app, db, role, chat = setup
    await legacy_session(db, role, questions=1)
    async with app.router.lifespan_context(app):
        await app.state.memory_answer_service.enqueue("self", "legacy")
        for _ in range(100):
            rows = await db.list_memory_answers("self", "legacy")
            if rows[0]["status"] == "ready":
                break
            await asyncio.sleep(0.05)
        assert rows[0]["status"] == "ready"
    assert len(chat.calls) == 1
