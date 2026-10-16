from pathlib import Path

import pytest

from mianshi_agent.config import Settings
from mianshi_agent.db import Database
from mianshi_agent.embeddings import EmbeddingUnavailable
from mianshi_agent.interview import InterviewService
from mianshi_agent.retrieval import RetrievalService
from mianshi_agent.schemas import (
    InterviewAnswerCreate,
    InterviewSessionCreate,
    RoleTargetCreate,
    TextSourceCreate,
)
from mianshi_agent.service import ProfileService


class OfflineEmbeddings:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailable("offline for test")

    async def embed_query(self, query: str) -> list[float]:
        raise EmbeddingUnavailable("offline for test")


class ScriptedChat:
    def __init__(self) -> None:
        self.responses = [
            {"kind": "question", "question": "请介绍你的任务恢复设计。", "competency": "系统架构"},
            {
                "kind": "follow_up",
                "question": "恢复后如何避免重复写入？",
                "competency": "稳定性",
            },
            {"kind": "question", "question": "本题回答已收到。", "competency": "稳定性"},
            {
                "summary": "回答覆盖了实现主线，但指标证据仍需补充。",
                "dimensions": [
                    {
                        "dimension": "技术正确性",
                        "rating": "mixed",
                        "evidence": "提到了检查点与幂等约束。",
                        "advice": "补充事务边界和失败场景。",
                    }
                ],
                "strengths": ["能够说明核心机制"],
                "improvements": ["补充异常边界"],
                "knowledge_gaps": ["取消传播"],
                "evidence_gaps": ["缺少生产环境指标"],
                "next_practice": ["重新回答任务恢复题"],
            },
        ]

    async def complete_json(self, **_: object) -> dict:
        return self.responses.pop(0)


@pytest.fixture
async def interview_service(tmp_path: Path) -> tuple[Database, InterviewService]:
    settings = Settings(
        app_data_dir=tmp_path,
        app_database_path=tmp_path / "interview.sqlite3",
    )
    database = Database(settings.app_database_path)
    await database.initialize()
    embeddings = OfflineEmbeddings()
    profiles = ProfileService(database, settings, embeddings)
    retrieval = RetrievalService(database, settings, embeddings)
    await database.create_profile("self", "测试候选人")
    await profiles.ingest_text(
        "self",
        TextSourceCreate(
            kind="resume",
            title="简历",
            text="使用 LangGraph Checkpointer 实现任务恢复，并通过幂等写入避免重复记录。",
        ),
    )
    await profiles.create_role_target(
        "self",
        RoleTargetCreate(
            title="AI 应用平台开发",
            jd_text="负责系统架构、稳定性和 AI 应用工程。",
            competencies=["系统架构", "稳定性"],
        ),
    )
    return database, InterviewService(database, retrieval, ScriptedChat())


async def test_strict_interview_reviews_only_after_last_answer(interview_service) -> None:
    database, interviews = interview_service
    started = await interviews.start(
        "self", InterviewSessionCreate(max_prompts=2, focus="任务恢复")
    )
    assert started.session.status == "awaiting_answer"
    assert started.session.review is None
    assert started.new_turn is not None

    first = await interviews.answer(
        "self",
        started.session.session_id,
        InterviewAnswerCreate(request_id="answer_0001", answer="我使用检查点保存状态。"),
    )
    assert first.session.status == "awaiting_answer"
    assert first.session.review is None
    assert first.new_turn is not None
    assert first.new_turn.kind == "follow_up"

    duplicate = await interviews.answer(
        "self",
        started.session.session_id,
        InterviewAnswerCreate(request_id="answer_0001", answer="不会被重复写入"),
    )
    assert duplicate.new_turn is None
    assert len(duplicate.session.turns) == 3

    completed = await interviews.answer(
        "self",
        started.session.session_id,
        InterviewAnswerCreate(
            request_id="answer_0002",
            answer="写入使用唯一约束，并让重试复用业务幂等键。",
        ),
    )
    assert completed.session.status == "completed"
    assert completed.session.review is not None
    assert completed.session.review.dimensions[0].rating == "mixed"
    assert len(completed.session.turns) == 4

    stored = await database.get_interview_session("self", started.session.session_id)
    assert stored["prompt_count"] == 2


async def test_session_lookup_is_profile_scoped(interview_service) -> None:
    database, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=1))
    await database.create_profile("other", "Other")

    with pytest.raises(KeyError, match="interview_session_not_found"):
        await interviews.get("other", started.session.session_id)
