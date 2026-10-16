import re
from pathlib import Path

import httpx
import pytest

from mianshi_agent.chat import ChatUnavailable
from mianshi_agent.config import Settings
from mianshi_agent.main import create_app


class WorkspaceChat:
    fail_next = False
    bad_citation = False
    review_gaps = False

    async def complete_json(self, *, max_tokens, messages, **kwargs):
        if self.fail_next:
            self.fail_next = False
            raise ChatUnavailable("chat_model_request_failed")
        if max_tokens == 600:
            return {
                "kind": "question",
                "question": "任务恢复如何避免重复写入？",
                "competency": "稳定性",
            }
        if max_tokens == 500:
            return {"questions": ["任务恢复", "幂等写入"]}
        if max_tokens == 2600:
            found = re.search(r"ID=([^\n]+)", messages[0]["content"])
            cid = "foreign_chunk" if self.bad_citation else found.group(1)
            return {
                "short_answer": "检查点恢复流程，幂等写入避免重复效果。",
                "sections": [
                    {
                        "title": "材料依据",
                        "content": "材料记录了检查点实现。",
                        "basis": "user_material",
                        "citations": [cid],
                    }
                ],
                "evidence_gaps": [{"gap": "测试指标尚缺原始记录", "reason": "需要原始压测报告"}],
                "knowledge_gaps": [
                    {"gap": "没有答题证据，不应保留这一项", "quote": "不存在的回答"}
                ],
                "follow_up_questions": ["部分提交如何处理？"],
            }
        result = {
            "summary": "复盘完成",
            "dimensions": [],
            "strengths": [],
            "improvements": [],
            "knowledge_gaps": [],
            "evidence_gaps": [],
            "next_practice": [],
        }
        if self.review_gaps:
            result["knowledge_gaps"] = ["有效缺口", "未答题推测缺口"]
            result["knowledge_gap_evidence"] = [
                {"gap": "有效缺口", "quote": "用检查点恢复"},
                {"gap": "未答题推测缺口", "quote": "未出现在回答中的话"},
            ]
        return result


@pytest.fixture
async def workspace(tmp_path: Path):
    app = create_app(
        Settings(
            app_database_path=tmp_path / "workspace.sqlite3",
            app_data_dir=tmp_path,
            memory_embedding_base_url="http://127.0.0.1:1",
            embedding_timeout=0.1,
        )
    )
    await app.state.database.initialize()
    chat = WorkspaceChat()
    app.state.interview_service.chat = chat
    app.state.study_service.chat = chat
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        for pid in ("self", "other"):
            await c.post("/api/profiles", json={"profile_id": pid, "display_name": pid})
            await c.post(
                f"/api/profiles/{pid}/roles",
                json={
                    "title": "平台开发",
                    "jd_text": "系统稳定性与幂等设计",
                    "competencies": ["稳定性"],
                },
            )
        imported = await c.post(
            "/api/profiles/self/sources/text",
            json={
                "kind": "resume",
                "title": "个人材料",
                "text": "任务恢复使用检查点，业务写入用幂等键。",
            },
        )
        yield c, app, chat, imported.json()["source_id"]


async def test_workspace_reads_and_role_activation_do_not_cross_profiles(workspace):
    c, _, _, source_id = workspace
    profiles = await c.get("/api/profiles")
    assert len(profiles.json()) == 2
    detail = await c.get(f"/api/profiles/self/sources/{source_id}")
    assert "幂等键" in detail.json()["chunks"][0]["text"]
    assert (await c.get(f"/api/profiles/other/sources/{source_id}")).status_code == 404
    roles = (await c.get("/api/profiles/self/roles")).json()
    rid = roles[0]["role_target_id"]
    assert (await c.post(f"/api/profiles/other/roles/{rid}/activate")).status_code == 404
    assert (await c.get("/api/profiles/other/roles")).json()[0]["active"]
    assert (await c.post(f"/api/profiles/self/roles/{rid}/activate")).status_code == 200


async def test_failed_answer_is_visible_and_retry_does_not_duplicate_it(workspace):
    c, _, chat, _ = workspace
    started = await c.post("/api/profiles/self/interviews", json={"max_prompts": 3})
    sid = started.json()["session"]["session_id"]
    chat.fail_next = True
    result = await c.post(
        f"/api/profiles/self/interviews/{sid}/answers",
        json={
            "request_id": "answer_0001",
            "answer": "用检查点恢复。",
        },
    )
    assert result.status_code == 502
    assert (await c.get("/api/profiles/self/interviews")).json()[0]["status"] == "error"
    assert (await c.get("/api/profiles/other/interviews")).json() == []
    assert (await c.post(f"/api/profiles/other/interviews/{sid}/retry")).status_code == 404
    retry = await c.post(f"/api/profiles/self/interviews/{sid}/retry")
    assert retry.json()["status"] == "awaiting_answer"
    assert sum(t["speaker"] == "candidate" for t in retry.json()["turns"]) == 1
    duplicate = await c.post(
        f"/api/profiles/self/interviews/{sid}/answers",
        json={
            "request_id": "answer_0001",
            "answer": "网络响应不确定后的重试",
        },
    )
    assert len(duplicate.json()["session"]["turns"]) == 3


async def test_manual_review_failure_retries_review_instead_of_another_question(workspace):
    c, _, chat, _ = workspace
    started = await c.post("/api/profiles/self/interviews", json={"max_prompts": 5})
    sid = started.json()["session"]["session_id"]
    await c.post(
        f"/api/profiles/self/interviews/{sid}/answers",
        json={
            "request_id": "answer_0002",
            "answer": "用唯一约束避免重复写入。",
        },
    )
    chat.fail_next = True
    assert (await c.post(f"/api/profiles/self/interviews/{sid}/finish")).status_code == 502
    retried = (await c.post(f"/api/profiles/self/interviews/{sid}/retry")).json()
    assert retried["status"] == "completed"
    assert retried["prompt_count"] == 2
    assert retried["review"]["summary"] == "复盘完成"


async def test_finish_cannot_race_generation_or_assess_without_answers(workspace):
    c, app, chat, _ = workspace
    started = await c.post("/api/profiles/self/interviews", json={})
    sid = started.json()["session"]["session_id"]
    await app.state.database.claim_interview_generation("self", sid)
    assert (await c.post(f"/api/profiles/self/interviews/{sid}/finish")).status_code == 409
    await app.state.database.mark_interview_error("self", sid, "retry")
    await c.post(f"/api/profiles/self/interviews/{sid}/retry")
    chat.fail_next = True  # No model call is allowed without an actual answer.
    review = (await c.post(f"/api/profiles/self/interviews/{sid}/finish")).json()["review"]
    assert review["dimensions"] == []
    assert "尚未收到回答" in review["summary"]
    assert chat.fail_next


async def test_study_validates_citations_persists_and_does_not_invent_learning_gaps(workspace):
    c, _, chat, _ = workspace
    result = await c.post("/api/profiles/self/studies", json={"topic": "任务恢复与幂等"})
    assert result.status_code == 200
    assert result.json()["knowledge_gaps"] == []
    assert result.json()["evidence_gaps"] == ["测试指标尚缺原始记录：需要原始压测报告"]
    assert len((await c.get("/api/profiles/self/studies")).json()) == 1
    assert (await c.get("/api/profiles/other/studies")).json() == []
    chat.bad_citation = True
    failed = await c.post("/api/profiles/self/studies", json={"topic": "幂等"})
    assert failed.status_code == 502
    assert len((await c.get("/api/profiles/self/studies")).json()) == 1


async def test_deep_study_requires_completed_profile_owned_session(workspace):
    c, _, _, _ = workspace
    session = (await c.post("/api/profiles/self/interviews", json={})).json()["session"]
    sid = session["session_id"]
    assert (
        await c.post(
            "/api/profiles/self/studies",
            json={
                "topic": "任务恢复",
                "session_id": sid,
            },
        )
    ).status_code == 409
    assert (
        await c.post(
            "/api/profiles/other/studies",
            json={
                "topic": "任务恢复",
                "session_id": sid,
            },
        )
    ).status_code == 404
    assert (await c.post("/api/profiles/self/interviews", json={"mode": "deep"})).status_code == 422


async def test_learning_gaps_require_a_quote_from_an_actual_answer(workspace):
    c, _, chat, _ = workspace
    chat.review_gaps = True
    session = (await c.post("/api/profiles/self/interviews", json={"max_prompts": 1})).json()[
        "session"
    ]
    result = await c.post(
        f"/api/profiles/self/interviews/{session['session_id']}/answers",
        json={"request_id": "answer_grounded", "answer": "我会用检查点恢复。"},
    )
    assert result.json()["session"]["review"]["knowledge_gaps"] == ["有效缺口"]


async def test_restart_recovery_retains_review_stage_and_role_snapshot(workspace):
    c, app, _, _ = workspace
    started = (await c.post("/api/profiles/self/interviews", json={"max_prompts": 5})).json()
    sid = started["session"]["session_id"]
    original_role = started["session"]["role_target_id"]
    await c.post(
        f"/api/profiles/self/interviews/{sid}/answers",
        json={
            "request_id": "restart_answer_001",
            "answer": "我会用检查点恢复。",
        },
    )
    await app.state.database.claim_interview_generation("self", sid)
    await app.state.database.recover_interrupted_sessions()
    recovered = (await c.post(f"/api/profiles/self/interviews/{sid}/retry")).json()
    assert recovered["status"] == "completed"
    assert recovered["prompt_count"] == 2
    await c.post("/api/profiles/self/roles", json={"title": "运营岗位", "jd_text": "活动策划"})
    study = (
        await c.post(
            "/api/profiles/self/studies",
            json={
                "topic": "任务恢复",
                "session_id": sid,
            },
        )
    ).json()
    assert study["role_target_id"] == original_role
