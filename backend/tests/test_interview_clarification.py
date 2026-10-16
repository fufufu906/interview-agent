"""Regressions for clarification quotas, explicit skips and durable retries."""

import pytest
from test_interview import interview_service as base_interview_fixture

from mianshi_agent.chat import ChatUnavailable
from mianshi_agent.schemas import InterviewAnswerCreate, InterviewSessionCreate

interview_service = base_interview_fixture


async def submit(interviews, sid, key, text="", action="answer"):
    return await interviews.answer(
        "self", sid, InterviewAnswerCreate(request_id=key, answer=text, action=action)
    )


async def test_question_echo_stays_on_same_prompt_until_supplemented(interview_service):
    _, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=2))
    sid = started.session.session_id
    echoed = await submit(interviews, sid, "echo_0001", "**请介绍你的任务恢复设计。**")
    assert echoed.new_turn.kind == "clarification"
    assert echoed.session.prompt_count == 1
    assert echoed.session.review is None
    duplicate = await submit(interviews, sid, "echo_0001", "不同内容")
    assert len(duplicate.session.turns) == 3
    assert duplicate.session.prompt_count == 1
    fixed = await submit(interviews, sid, "fixed_001", "我使用检查点保存状态。")
    assert fixed.new_turn.kind == "follow_up"
    assert fixed.session.prompt_count == 2


async def test_last_prompt_echo_does_not_auto_finish_and_skip_is_idempotent(interview_service):
    _, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=1))
    sid = started.session.session_id
    echoed = await submit(interviews, sid, "echo_0002", started.new_turn.content)
    assert echoed.session.status == "awaiting_answer"
    assert echoed.session.prompt_count == 1
    assert echoed.session.review is None
    # Only the final review is needed after explicit skip; no new question call.
    interviews.chat.responses = [interviews.chat.responses[-1]]
    skipped = await submit(interviews, sid, "skip_0001", action="skip")
    assert skipped.session.status == "completed"
    assert skipped.session.prompt_count == 1
    assert skipped.session.turns[-1].kind == "skip"
    duplicate = await submit(interviews, sid, "skip_0001", action="skip")
    assert len(duplicate.session.turns) == len(skipped.session.turns)


async def test_model_clarification_and_corrected_answer_share_quota(interview_service):
    _, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=2))
    sid = started.session.session_id
    interviews.chat.responses.insert(
        0,
        {
            "kind": "clarification",
            "question": "请澄清检查点是否代表业务事务已经提交。",
            "competency": "稳定性",
        },
    )
    bad = await submit(interviews, sid, "wrong_001", "只要有检查点就一定没有重复写入。")
    assert bad.new_turn.kind == "clarification"
    assert bad.session.prompt_count == 1
    corrected = await submit(interviews, sid, "fixed_002", "业务写入还需要唯一约束和事务边界。")
    assert corrected.session.prompt_count == 2
    assert corrected.new_turn.kind == "follow_up"


async def test_skip_without_actual_answer_does_not_assess_ability(interview_service):
    _, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=1))
    sid = started.session.session_id
    interviews.chat.responses = []  # No model call allowed for a skip-only review.
    result = await submit(interviews, sid, "skip_0002", action="skip")
    assert result.session.status == "completed"
    assert result.session.review.dimensions == []
    assert result.session.review.knowledge_gaps == []


async def test_skip_moves_to_next_prompt_once_without_becoming_an_answer(interview_service):
    _, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=2))
    sid = started.session.session_id
    result = await submit(interviews, sid, "skip_0003", action="skip")
    assert result.session.status == "awaiting_answer"
    assert result.session.prompt_count == 2
    assert result.new_turn.kind == "question"
    assert result.session.turns[-2].kind == "skip"
    assert not any(t.kind == "answer" for t in result.session.turns)
    duplicate = await submit(interviews, sid, "skip_0003", action="skip")
    assert duplicate.session.prompt_count == 2
    assert len(duplicate.session.turns) == 3


class FailThenClarify:
    def __init__(self):
        self.calls = 0

    async def complete_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise ChatUnavailable("offline")
        assert kwargs["max_tokens"] == 600
        return {"kind": "clarification", "question": "请补充具体实现条件。", "competency": "稳定性"}


async def test_last_answer_retry_rechecks_instead_of_premature_review(interview_service):
    database, interviews = interview_service
    started = await interviews.start("self", InterviewSessionCreate(max_prompts=1))
    sid = started.session.session_id
    interviews.chat = FailThenClarify()
    with pytest.raises(ChatUnavailable):
        await submit(interviews, sid, "failed_01", "这里我想先描述一下大概的实现。")
    failed = await database.get_interview_session("self", sid)
    assert failed["generation_stage"] == "question"
    retried = await interviews.retry("self", sid)
    assert retried.status == "awaiting_answer"
    assert retried.prompt_count == 1
    assert retried.turns[-1].kind == "clarification"
    assert sum(t.kind == "answer" for t in retried.turns) == 1
