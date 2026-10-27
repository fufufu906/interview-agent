"""Lossless transcript boundaries; labels are not evidence of personal facts."""

from __future__ import annotations

import re
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Speaker = Literal["interviewer", "candidate", "assistant", "system", "note", "unknown"]
LABEL = re.compile(
    r"(?m)^[ \t]*(面试官(?:[/／][^：:\n]{1,12})?|候选人(?:[（(][^\n）)]{0,30}[）)])?|"
    r"招聘方|系统|助手|用户|user|assistant|interviewer|candidate)[：:]",
    re.IGNORECASE,
)
HEADING = re.compile(r"(?m)^[ \t]*【[^\n】]+】[ \t]*\r?$")
EDITOR_NOTE = re.compile(
    r"[（(][^）)\n]{0,200}(?:转写|待核实|语音识别|以上仅|该回答中|无法确认)[^）)\n]{0,200}[）)]"
)


class TranscriptTurn(BaseModel):
    turn_id: str = Field(default_factory=lambda: f"extturn_{uuid4().hex}")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    role: Speaker = "unknown"
    session: str = Field(default="第1场", min_length=1, max_length=80)
    topic: str = Field(default="", max_length=200)
    correction: str = Field(default="", max_length=24_000)
    continuation: bool = False


class TranscriptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)


class TranscriptConfirm(BaseModel):
    revision: int = Field(ge=0)
    turns: list[TranscriptTurn] = Field(min_length=1, max_length=2000)
    jd_text: str = Field(default="", max_length=20_000)
    role_title: str = Field(default="", max_length=200)


class TranscriptSplit(BaseModel):
    revision: int
    turn_id: str
    position: int = Field(gt=0)


class TranscriptRevision(BaseModel):
    revision: int


class QuestionReview(BaseModel):
    answer_clean: str = Field(max_length=24_000)
    analysis: str = Field(min_length=1, max_length=12_000)
    quotes: list[str] = Field(default_factory=list, max_length=12)
    suggestion: str = Field(min_length=1, max_length=8000)
    explanation: str = Field(default="", max_length=12_000)
    citations: list[str] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=16)


class ReviewConclusion(BaseModel):
    conclusion: str = Field(min_length=1, max_length=8000)
    priorities: list[str] = Field(min_length=1, max_length=15)
    limitations: list[str] = Field(default_factory=list, max_length=15)


def speaker(label: str) -> Speaker:
    label = label.lower()
    if label in ("assistant", "助手"):
        return "assistant"
    if label in ("user", "用户"):
        return "unknown"  # A user export can contain both sides of the interview.
    if "系统" in label:
        return "system"
    if label.startswith("候选人") or label == "candidate":
        return "candidate"
    return "interviewer"


def parse_transcript(raw: str) -> list[TranscriptTurn]:
    """Partition every character; never trim, remove fillers or rewrite raw input."""
    markers = sorted(
        [(m.start(), m.end(), "label", m.group(1)) for m in LABEL.finditer(raw)]
        + [(m.start(), m.end(), "heading", m.group().strip()) for m in HEADING.finditer(raw)]
    )
    turns: list[TranscriptTurn] = []
    if not markers:
        markers = [(0, 0, "unlabelled", "")]
    if markers[0][0]:
        turns.append(TranscriptTurn(start=0, end=markers[0][0], role="note"))
    topic = ""
    for i, (start, _, kind, label) in enumerate(markers):
        original_start = start
        end = markers[i + 1][0] if i + 1 < len(markers) else len(raw)
        if kind == "heading":
            topic = label[1:-1]
        role = speaker(label) if kind == "label" else "note" if kind == "heading" else "unknown"
        # Keep model-assisted parsing bounded without dropping long passages.
        while end - start > 6000:
            cut = raw.rfind("\n", start + 3000, start + 6000)
            cut = cut + 1 if cut >= 0 else start + 6000
            turns.append(
                TranscriptTurn(
                    start=start,
                    end=cut,
                    role=role,
                    topic=topic,
                    continuation=start != original_start,
                )
            )
            start = cut
        if end > start:
            turns.append(
                TranscriptTurn(
                    start=start,
                    end=end,
                    role=role,
                    topic=topic,
                    continuation=start != original_start,
                )
            )
    # Explicit editorial parentheses stay available but are not spoken answers.
    result = []
    for turn in turns:
        cursor = turn.start
        annotations = (
            list(EDITOR_NOTE.finditer(raw, turn.start, turn.end))
            if turn.role in ("interviewer", "candidate")
            else []
        )
        for annotation in annotations:
            if cursor < annotation.start():
                result.append(
                    turn.model_copy(
                        update={
                            "turn_id": f"extturn_{uuid4().hex}",
                            "start": cursor,
                            "end": annotation.start(),
                            "continuation": turn.continuation or cursor > turn.start,
                        }
                    )
                )
            result.append(
                TranscriptTurn(
                    start=annotation.start(),
                    end=annotation.end(),
                    role="note",
                    topic=turn.topic,
                    session=turn.session,
                )
            )
            cursor = annotation.end()
        if cursor < turn.end:
            result.append(
                turn.model_copy(
                    update={
                        "start": cursor,
                        "continuation": turn.continuation or cursor > turn.start,
                    }
                )
            )
    return result


def validate_partition(raw: str, turns: list[TranscriptTurn]) -> None:
    cursor = 0
    ids = set()
    for turn in turns:
        if turn.start != cursor or turn.end > len(raw) or turn.end <= turn.start:
            raise ValueError("transcript_invalid_boundaries")
        if turn.turn_id in ids:
            raise ValueError("transcript_duplicate_turn")
        ids.add(turn.turn_id)
        cursor = turn.end
    if cursor != len(raw):
        raise ValueError("transcript_incomplete_coverage")


def turn_text(raw: str, turn: dict) -> str:
    text = raw[turn["start"] : turn["end"]]
    return LABEL.sub("", text, count=1).strip()


def question_units(raw: str, turns: list[dict]) -> tuple[list[dict], list[str]]:
    """Each question and follow-up gets an explicit entry; orphans stay visible."""
    units: list[dict] = []
    orphan_ids: list[str] = []
    current = None
    roots: dict[tuple[str, str], str] = {}
    for turn in turns:
        if turn["role"] == "interviewer":
            if turn.get("continuation") and current and current["session"] == turn["session"]:
                current["question"] += "\n" + turn_text(raw, turn)
                current["turn_ids"].append(turn["turn_id"])
                current["end"] = turn["end"]
                continue
            key = (turn["session"], turn["topic"])
            current = {
                "question_id": turn["turn_id"],
                "session": turn["session"],
                "topic": turn["topic"],
                "parent_question_id": roots.get(key) if turn["topic"] else None,
                "question": turn_text(raw, turn),
                "answer": "",
                "notes": [],
                "turn_ids": [turn["turn_id"]],
                "start": turn["start"],
                "end": turn["end"],
            }
            roots.setdefault(key, turn["turn_id"])
            units.append(current)
        elif turn["role"] == "candidate":
            if current and current["session"] == turn["session"]:
                current["answer"] += ("\n\n" if current["answer"] else "") + turn_text(raw, turn)
                current["turn_ids"].append(turn["turn_id"])
                current["end"] = turn["end"]
                if turn.get("correction"):
                    current["notes"].append(turn["correction"])
            else:
                orphan_ids.append(turn["turn_id"])
        elif turn["role"] in ("system", "unknown") or (
            turn["role"] == "note"
            and turn["topic"]
            and current
            and turn["topic"] != current["topic"]
        ):
            current = None
    return units, orphan_ids
