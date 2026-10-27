"""Lossless import, confirmation gates, durable generation and Word export."""

import json
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from docx import Document

from mianshi_agent.config import Settings
from mianshi_agent.main import create_app
from mianshi_agent.transcripts import (
    TranscriptConfirm,
    parse_transcript,
    question_units,
    validate_partition,
)

RAW = (
    "测试面试\r\n\r\n【恢复机制】\r\n面试官：如何恢复？\r\n候选人：呃，我保存检查点。\r\n"
    "面试官：如何防止重复？\r\n候选人：通过幂等键。\r\n"
)


class FakeChat:
    def __init__(self):
        self.calls = []
        self.bad_quote = False
        self.bad_citation = False
        self.fail_summary = False

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        data = json.loads(kwargs["messages"][0]["content"])
        if "原文" in data:
            return {"parts": [{"text": data["原文"], "role": "note"}]}
        if "逐题记录" in data:
            if self.fail_summary:
                raise ValueError("summary_test_failure")
            return {
                "conclusion": "回答涉及检查点和幂等，缺少验证案例。",
                "priorities": ["准备一个恢复失败案例"],
                "limitations": ["没有JD，匹配未评估"],
            }
        answer = data["回答片段"]
        return {
            "answer_clean": answer.replace("呃，", ""),
            "analysis": "说明了机制，需补充验证步骤。",
            "quotes": ["虚构原话" if self.bad_quote else answer[:20]],
            "suggestion": "我会说明检查点与幂等的设计，并补充实际测试依据。",
            "explanation": "代码存在不证明个人贡献。",
            "citations": ["foreign"] if self.bad_citation else [],
            "gaps": ["个人职责待确认"],
        }


class EmptyRetrieval:
    async def retrieve(self, pid, query, **kwargs):
        assert kwargs["memory_only"] is True
        return SimpleNamespace(
            items=[],
            diagnostics=SimpleNamespace(model_dump=lambda: {"embedding_status": "not_needed"}),
        )


@pytest.fixture
async def setup(tmp_path):
    app = create_app(
        Settings(
            app_database_path=tmp_path / "db.sqlite3",
            app_data_dir=tmp_path,
            llm_base_url="",
            llm_api_key="",
        )
    )
    db = app.state.database
    await db.initialize()
    await db.create_profile("self", "测试候选人")
    await db.create_profile("other", "另一档案")
    service = app.state.external_review_service
    await service.store.initialize()
    chat = FakeChat()
    service.chat = chat
    service.retrieval = EmptyRetrieval()
    return app, service, chat


def confirm_body(record):
    return {
        "revision": record["revision"],
        "turns": record["turns"],
        "role_title": "",
        "jd_text": "",
    }


async def drain(service):
    for _ in range(30):
        if not await service.process_next():
            return
    raise AssertionError("queue did not terminate")


def test_rules_preserve_every_character_and_all_followups():
    turns = parse_transcript(RAW)
    validate_partition(RAW, turns)
    assert "".join(RAW[t.start : t.end] for t in turns) == RAW
    units, orphans = question_units(RAW, [t.model_dump() for t in turns])
    assert len(units) == 2
    assert not orphans
    assert units[1]["parent_question_id"] == units[0]["question_id"]
    assert "呃" in units[0]["answer"]


def test_mixed_user_export_never_assumes_user_is_candidate():
    raw = "user: 面试官提问和本人回答混在一起\nassistant: 我来给你建议\nuser: 好的\n"
    turns = parse_transcript(raw)
    assert [t.role for t in turns] == ["unknown", "assistant", "unknown"]
    assert question_units(raw, [t.model_dump() for t in turns])[0] == []


def test_long_transcript_is_lossless_and_partition_validation_rejects_gaps():
    raw = "候选人：" + "很长的回答。" * 3000
    turns = parse_transcript(raw)
    validate_partition(raw, turns)
    assert max(t.end - t.start for t in turns) <= 6000
    turns[0].end -= 1
    with pytest.raises(ValueError, match="boundaries"):
        validate_partition(raw, turns)


async def test_full_api_flow_requires_confirmation_and_exports_same_content(setup):
    app, service, chat = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        prefix = "/api/profiles/self/external-reviews"
        r = await c.post(prefix, json={"title": "测试记录", "text": RAW})
        assert r.status_code == 201
        draft = r.json()
        rid = draft["review_id"]
        assert draft["status"] == "draft" and chat.calls == []
        assert (await c.get(f"{prefix}/{rid}/raw")).content == RAW.encode()
        assert (await c.get(f"{prefix}/{rid}/docx")).status_code == 409
        assert (
            await c.post(f"{prefix}/{rid}/confirm", json=confirm_body(draft))
        ).status_code == 202
        await drain(service)
        ready = (await c.get(f"{prefix}/{rid}")).json()
        assert ready["status"] == "completed"
        assert ready["coverage"]["reviewed_questions"] == 2
        assert ready["raw_text"] == RAW
        exported = await c.get(f"{prefix}/{rid}/docx")
        assert exported.status_code == 200
        doc = Document(BytesIO(exported.content))
        text = "\n".join(p.text for p in doc.paragraphs)
        for q in ready["questions"]:
            assert q["question"] in text
            for field in ("answer_clean", "analysis", "suggestion", "explanation"):
                assert q["result"]["content"][field] in text
        assert ready["summary"]["conclusion"] in text
        assert round(doc.sections[0].page_width.cm) == 21
        assert (await service.database.list_sources("self")) == []


async def test_profile_isolation_on_read_edit_export_and_retry(setup):
    app, service, _ = setup
    draft = await service.create("self", "隔离测试", RAW)
    rid = draft["review_id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        prefix = f"/api/profiles/other/external-reviews/{rid}"
        for suffix in ("", "/raw", "/docx"):
            assert (await c.get(prefix + suffix)).status_code == 404
        for suffix in ("/confirm", "/draft"):
            assert (await c.post(prefix + suffix, json=confirm_body(draft))).status_code == 404
        assert (await c.post(prefix + "/retry")).status_code == 404
        assert (await c.get("/api/profiles/other/external-reviews")).json() == []


async def test_invalid_confirmation_does_not_mutate_revision(setup):
    _, service, _ = setup
    draft = await service.create("self", "混合对话", "user: 你好\nassistant: 建议\n")
    request = TranscriptConfirm(**confirm_body(draft))
    with pytest.raises(ValueError, match="resolve_unknown"):
        await service.confirm("self", draft["review_id"], request)
    unchanged = await service.get("self", draft["review_id"])
    assert unchanged["revision"] == draft["revision"]
    assert unchanged["jobs"] == []


async def test_stale_edits_and_split_preserve_raw(setup):
    _, service, _ = setup
    draft = await service.create("self", "拆分", "没有标记的提问和回答")
    turn = draft["turns"][0]
    request = SimpleNamespace(turn_id=turn["turn_id"], position=5, revision=draft["revision"])
    split = await service.split("self", draft["review_id"], request)
    assert split["raw_text"] == draft["raw_text"]
    assert split["coverage"]["covered_characters"] == len(draft["raw_text"])
    with pytest.raises(RuntimeError, match="revision_conflict"):
        await service.save_draft(
            "self", draft["review_id"], TranscriptConfirm(**confirm_body(draft))
        )


async def test_model_parser_cannot_rewrite_original(setup):
    _, service, chat = setup
    draft = await service.create("self", "原文", "user: 不确定\n")

    async def bad(**kwargs):
        return {"parts": [{"text": "确定", "role": "candidate"}]}

    chat.complete_json = bad
    await service.parse_unknown("self", draft["review_id"], draft["revision"])
    await drain(service)
    record = await service.get("self", draft["review_id"])
    assert record["status"] == "draft"
    assert record["raw_text"] == draft["raw_text"]
    assert record["coverage"]["unknown_turns"] == 1
    assert record["jobs"][0]["error"] == "transcript_parse_changed_text"


@pytest.mark.parametrize("invalid", ["bad_quote", "bad_citation"])
async def test_reject_fake_evidence_and_retry_preserves_ready_questions(setup, invalid):
    _, service, chat = setup
    draft = await service.create("self", "重试", RAW)
    await service.confirm("self", draft["review_id"], TranscriptConfirm(**confirm_body(draft)))
    await service.process_next()
    first = (await service.get("self", draft["review_id"]))["questions"][0]["result"]
    setattr(chat, invalid, True)
    await drain(service)
    failed = await service.get("self", draft["review_id"])
    assert failed["status"] == "error"
    assert failed["coverage"]["reviewed_questions"] == 1
    setattr(chat, invalid, False)
    await service.retry("self", draft["review_id"])
    await drain(service)
    ready = await service.get("self", draft["review_id"])
    assert ready["status"] == "completed"
    assert ready["questions"][0]["result"] == first


async def test_upload_preserves_bytes_and_missing_answers_stay_unassessed(setup):
    app, service, chat = setup
    raw = "面试官：如何恢复？\r\n".encode("gb18030")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        prefix = "/api/profiles/self/external-reviews"
        r = await c.post(prefix + "/upload", files={"file": ("input.txt", raw, "text/plain")})
        draft = r.json()
        assert r.status_code == 201
        assert (await c.get(f"{prefix}/{draft['review_id']}/raw")).content == raw
        await c.post(f"{prefix}/{draft['review_id']}/confirm", json=confirm_body(draft))
        await drain(service)
        ready = await service.get("self", draft["review_id"])
        assert "尚未测评" in ready["questions"][0]["result"]["content"]["analysis"]
        assert not any("回答片段" in call["messages"][0]["content"] for call in chat.calls)


async def test_restart_recovers_claimed_job_and_keeps_role_snapshot(setup):
    _, service, _ = setup
    draft = await service.create("self", "恢复", RAW)
    request = TranscriptConfirm(
        **{**confirm_body(draft), "jd_text": "冻结岗位", "role_title": "岗位A"}
    )
    await service.confirm("self", draft["review_id"], request)
    claimed = await service.store.claim()
    assert claimed is not None
    await service.store.initialize()
    await drain(service)
    ready = await service.get("self", draft["review_id"])
    assert ready["status"] == "completed"
    assert ready["role"] == {"title": "岗位A", "jd_text": "冻结岗位"}


def test_supplement_is_not_candidate_original():
    turns = parse_transcript(RAW)
    answer = next(t for t in turns if t.role == "candidate")
    answer.correction = "后来补充的内容，不是当场说的"
    units, _ = question_units(RAW, [t.model_dump() for t in turns])
    assert answer.correction not in units[0]["answer"]
    assert units[0]["notes"] == [answer.correction]
