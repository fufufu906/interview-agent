"""Public API request and response contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal[
    "resume",
    "job_description",
    "project_repository",
    "project_document",
    "study_note",
    "confirmed_answer",
    "external_reference",
]
InterviewMode = Literal["quick", "deep"]
SessionStatus = Literal["generating", "awaiting_answer", "completed", "error"]


class ProfileCreate(BaseModel):
    """Create one isolated interview profile."""

    profile_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=120)


class ProfileResponse(ProfileCreate):
    """Expose a stored profile."""

    created_at: str


class RoleTargetCreate(BaseModel):
    """Store one role target and its explicit competency map."""

    title: str = Field(min_length=1, max_length=200)
    level: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=200)
    jd_text: str = Field(min_length=1, max_length=100_000)
    competencies: list[str] = Field(default_factory=list, max_length=50)
    activate: bool = True


class RoleTargetResponse(BaseModel):
    """Expose a stored role target."""

    role_target_id: str
    profile_id: str
    title: str
    level: str
    company: str
    jd_text: str
    competencies: list[str]
    active: bool
    created_at: str


class TextSourceCreate(BaseModel):
    """Import user-provided or verified text into one profile."""

    kind: SourceKind
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=2_000_000)
    origin_uri: str = Field(default="", max_length=2_048)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceResponse(BaseModel):
    """Expose import and indexing status without returning full private text."""

    source_id: str
    profile_id: str
    kind: SourceKind
    title: str
    content_hash: str
    chunk_count: int
    embedding_status: Literal["indexed", "degraded", "not_requested"]
    embedding_error: str | None = None
    created_at: str
    folder_root: str | None = None
    relative_path: str | None = None


class SourceListResponse(BaseModel):
    """List the private sources available to one profile."""

    items: list[SourceResponse]


class ReindexResponse(BaseModel):
    """Report the result of embedding chunks that were previously degraded."""

    chunks_found: int
    chunks_indexed: int
    embedding_status: Literal["indexed", "not_needed", "unavailable"]
    embedding_error: str | None = None


class RetrievalRequest(BaseModel):
    """Retrieve evidence only inside one profile."""

    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=8, ge=1, le=50)
    graph_hops: int = Field(default=1, ge=0, le=2)


class RetrievalItem(BaseModel):
    """Return one evidence chunk and transparent channel scores."""

    chunk_id: str
    source_id: str
    source_title: str
    source_kind: str
    text: str
    locator: dict[str, Any]
    fused_score: float
    lexical_score: float
    vector_score: float
    graph_distance: int | None = None


class RetrievalDiagnostics(BaseModel):
    """Report which channels ran and why a channel degraded."""

    lexical_candidates: int
    vector_candidates: int
    graph_nodes_visited: int
    embedding_status: Literal["ok", "unavailable", "not_needed"]
    embedding_error: str | None = None


class RetrievalResponse(BaseModel):
    """Return ranked evidence with retrieval diagnostics."""

    items: list[RetrievalItem]
    diagnostics: RetrievalDiagnostics


class InterviewSessionCreate(BaseModel):
    """Start a role-specific interview without exposing an answer first."""

    mode: InterviewMode = "quick"
    focus: str = Field(default="", max_length=1_000)
    max_prompts: int = Field(default=8, ge=1, le=20)


class InterviewAnswerCreate(BaseModel):
    """Submit one idempotent candidate answer."""

    request_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{7,127}$")
    answer: str = Field(default="", max_length=20_000)
    action: Literal["answer", "skip"] = "answer"

    @model_validator(mode="after")
    def require_actual_answer(self) -> InterviewAnswerCreate:
        if self.action == "answer" and not self.answer.strip():
            raise ValueError("answer must not be blank")
        return self


class InterviewTurnResponse(BaseModel):
    """Expose one ordered interview utterance and its evidence references."""

    turn_id: str
    ordinal: int
    speaker: Literal["interviewer", "candidate"]
    kind: Literal["question", "follow_up", "clarification", "answer", "skip"]
    content: str
    competency: str
    evidence: list[dict[str, Any]]
    created_at: str


class ReviewDimension(BaseModel):
    """Give one qualitative, evidence-backed review dimension."""

    dimension: str
    rating: Literal["strong", "mixed", "needs_work", "not_enough_evidence"]
    evidence: str
    advice: str


class AnswerGapEvidence(BaseModel):
    gap: str
    quote: str


class GroundedGapContent(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def normalize_structured_gaps(cls, value: Any) -> Any:
        """Accept equivalent gap objects without bypassing provenance checks."""
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if isinstance(payload.get("evidence_gaps"), list):
            gaps = []
            for item in payload["evidence_gaps"]:
                if isinstance(item, dict) and isinstance(item.get("gap"), str):
                    # Keep the model's explanation; do not turn arbitrary objects
                    # or invalid reasons into strings that appear well formed.
                    reason = item.get("reason", "")
                    if isinstance(reason, str):
                        gaps.append(item["gap"] + (f"：{reason}" if reason else ""))
                    else:
                        gaps.append(item)
                else:
                    gaps.append(item)
            payload["evidence_gaps"] = gaps
        if not isinstance(payload.get("knowledge_gaps"), list):
            return payload
        evidence = payload.get("knowledge_gap_evidence", [])
        if not isinstance(evidence, list):
            return payload
        evidence = list(evidence)
        gaps = []
        for item in payload["knowledge_gaps"]:
            if isinstance(item, dict) and isinstance(item.get("gap"), str):
                gaps.append(item["gap"])
                if isinstance(item.get("quote"), str):
                    evidence.append({"gap": item["gap"], "quote": item["quote"]})
            else:
                gaps.append(item)
        payload["knowledge_gaps"] = gaps
        payload["knowledge_gap_evidence"] = evidence
        return payload


class InterviewReview(GroundedGapContent):
    """Review the completed session without inventing precise scores."""

    summary: str
    dimensions: list[ReviewDimension]
    strengths: list[str]
    improvements: list[str]
    knowledge_gaps: list[str]
    knowledge_gap_evidence: list[AnswerGapEvidence] = Field(default_factory=list)
    evidence_gaps: list[str]
    next_practice: list[str]


class MemoryAnswerContent(BaseModel):
    """Generated reference content, never a candidate's submitted answer."""

    answer: str = Field(min_length=1, max_length=8000)
    basis: Literal["user_material", "general_knowledge", "insufficient_evidence"]
    citations: list[str] = Field(default_factory=list, max_length=12)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=12)


class MemoryAnswerResponse(BaseModel):
    question_turn_id: str
    status: Literal["queued", "generating", "ready", "error"]
    content: MemoryAnswerContent | None = None
    evidence: list[RetrievalItem] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics | None = None
    error: str | None = None
    updated_at: str


class InterviewSessionResponse(BaseModel):
    """Expose the complete current state of one interview session."""

    session_id: str
    profile_id: str
    role_target_id: str
    mode: InterviewMode
    focus: str
    status: SessionStatus
    max_prompts: int
    prompt_count: int
    turns: list[InterviewTurnResponse]
    review: InterviewReview | None = None
    memory_answers: list[MemoryAnswerResponse] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


class InterviewStepResponse(BaseModel):
    """Return the updated session plus the newly created turn when applicable."""

    session: InterviewSessionResponse
    new_turn: InterviewTurnResponse | None = None


class SourceChunkResponse(BaseModel):
    chunk_id: str
    text: str
    locator: dict[str, Any]


class SourceDetailResponse(BaseModel):
    source_id: str
    title: str
    kind: SourceKind
    origin_uri: str
    content_hash: str
    metadata: dict[str, Any]
    chunks: list[SourceChunkResponse]


class InterviewSummary(BaseModel):
    session_id: str
    role_title: str
    focus: str
    status: SessionStatus
    prompt_count: int
    max_prompts: int
    created_at: str
    updated_at: str


class DeepStudyCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class StudySection(BaseModel):
    title: str
    content: str
    basis: Literal["general_knowledge", "user_material"]
    citations: list[str] = Field(default_factory=list, max_length=12)


class DeepStudyContent(GroundedGapContent):
    short_answer: str
    sections: list[StudySection] = Field(min_length=1, max_length=12)
    evidence_gaps: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    knowledge_gap_evidence: list[AnswerGapEvidence] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


class DeepStudyResponse(DeepStudyContent):
    study_id: str
    profile_id: str
    role_target_id: str = ""
    topic: str
    plan: list[str]
    evidence: list[RetrievalItem]
    diagnostics: RetrievalDiagnostics
    created_at: str
