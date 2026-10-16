"""Regression for structured evidence gaps returned by the configured model."""

import pytest
from pydantic import ValidationError

from mianshi_agent.schemas import DeepStudyContent, InterviewReview


@pytest.mark.parametrize("model", [DeepStudyContent, InterviewReview])
def test_evidence_gap_objects_preserve_gap_and_reason(model):
    fields = (
        {
            "short_answer": "原理",
            "sections": [{"title": "原理", "content": "解释", "basis": "general_knowledge"}],
        }
        if model is DeepStudyContent
        else {
            "summary": "复盘",
            "dimensions": [],
            "strengths": [],
            "improvements": [],
            "next_practice": [],
        }
    )
    result = model.model_validate(
        {
            **fields,
            "knowledge_gaps": [],
            "evidence_gaps": ["缺少职责说明", {"gap": "缺少并发指标", "reason": "需原始压测记录"}],
        }
    )
    assert result.evidence_gaps == ["缺少职责说明", "缺少并发指标：需原始压测记录"]


@pytest.mark.parametrize(
    "gap", [{"reason": "缺失 gap"}, {"gap": "缺少指标", "reason": ["无效格式"]}]
)
def test_malformed_evidence_gap_still_rejected(gap):
    with pytest.raises(ValidationError):
        DeepStudyContent.model_validate(
            {
                "short_answer": "原理",
                "sections": [{"title": "原理", "content": "解释", "basis": "general_knowledge"}],
                "evidence_gaps": [gap],
            }
        )
