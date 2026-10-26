"""Typed schemas shared by the agents, the API and the persisted run snapshot.

LLM-facing models (``*Output``) are deliberately small: the model never supplies URLs,
titles or timestamps. Those come from the source registry, which is populated only from
real tool results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunMode(StrEnum):
    LIVE = "live"
    DEMO = "demo"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- API input


class RunCreate(BaseModel):
    question: str = Field(min_length=8, max_length=600)
    mode: RunMode = RunMode.LIVE

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


# --------------------------------------------------------------------------- planner


class ResearchTask(BaseModel):
    id: str = Field(pattern=r"^t[1-9]$")
    title: str = Field(min_length=3, max_length=120)
    objective: str = Field(min_length=10, max_length=400)
    search_queries: list[str] = Field(min_length=1, max_length=3)


class ResearchPlan(BaseModel):
    tasks: list[ResearchTask] = Field(min_length=3, max_length=5)

    @field_validator("tasks")
    @classmethod
    def _unique_ids(cls, tasks: list[ResearchTask]) -> list[ResearchTask]:
        ids = [t.id for t in tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        return tasks


# --------------------------------------------------------------------------- evidence


class Source(BaseModel):
    """A retrieved web page. Created only from an actual tool result."""

    id: str
    url: str
    title: str
    retrieved_at: datetime
    excerpt: str  # sanitised, truncated content as retrieved
    found_by_tasks: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)  # claims this source supports
    flags: list[str] = Field(default_factory=list)  # e.g. possible_prompt_injection

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("only http(s) URLs are allowed")
        return v


class ClaimEvidence(BaseModel):
    source_id: str
    quote: str
    quote_verified: bool = False  # quote found verbatim (normalised) in the source text


class Claim(BaseModel):
    id: str
    task_id: str
    text: str
    evidence: list[ClaimEvidence]


class RawClaim(BaseModel):
    """What the researcher LLM returns. Validated against the registry before use."""

    text: str = Field(min_length=5, max_length=400)
    source_id: str
    quote: str = Field(min_length=5, max_length=500)


class ResearcherOutput(BaseModel):
    claims: list[RawClaim] = Field(max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=5)


class TaskFinding(BaseModel):
    task_id: str
    status: Literal["ok", "no_results", "failed"]
    claim_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    error: str | None = None


# --------------------------------------------------------------------------- report


class Statement(BaseModel):
    text: str = Field(min_length=5, max_length=700)
    claim_ids: list[str] = Field(default_factory=list)


class ReportSectionDraft(BaseModel):
    heading: str = Field(min_length=3, max_length=120)
    statements: list[Statement] = Field(min_length=1, max_length=8)


class ReportDraft(BaseModel):
    """Synthesizer output."""

    title: str = Field(min_length=5, max_length=160)
    executive_summary: list[Statement] = Field(min_length=1, max_length=5)
    sections: list[ReportSectionDraft] = Field(min_length=1, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[Statement] = Field(default_factory=list, max_length=6)


class ReportStatement(Statement):
    id: str
    source_ids: list[str] = Field(default_factory=list)  # resolved from claim_ids


class ReportSection(BaseModel):
    heading: str
    statements: list[ReportStatement]


class Report(BaseModel):
    title: str
    executive_summary: list[ReportStatement]
    sections: list[ReportSection]
    limitations: list[str]
    recommendations: list[ReportStatement]

    def all_statements(self) -> list[ReportStatement]:
        out = list(self.executive_summary)
        for s in self.sections:
            out.extend(s.statements)
        out.extend(self.recommendations)
        return out


# --------------------------------------------------------------------------- verifier

Verdict = Literal["supported", "partially_supported", "unsupported", "conflicting", "inference"]


class RawVerdict(BaseModel):
    statement_id: str
    verdict: Literal["supported", "partially_supported", "unsupported", "conflicting"]
    explanation: str = Field(max_length=400)
    conflicting_source_ids: list[str] = Field(default_factory=list)


class VerifierOutput(BaseModel):
    verdicts: list[RawVerdict]
    conflicts: list[str] = Field(default_factory=list, max_length=8)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)


class StatementVerdict(BaseModel):
    statement_id: str
    verdict: Verdict
    explanation: str
    conflicting_source_ids: list[str] = Field(default_factory=list)
    checked_by: Literal["code", "llm"] = "llm"


class Verification(BaseModel):
    verdicts: list[StatementVerdict]
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    overall: Literal["pass", "pass_with_warnings", "fail"]
    verifier_model: str


# --------------------------------------------------------------------------- run snapshot


class RunStats(BaseModel):
    tool_calls: int = 0
    tool_failures: int = 0
    llm_calls: int = 0
    sources: int = 0
    claims: int = 0


class RunSnapshot(BaseModel):
    """Everything needed to inspect a run after the fact."""

    run_id: str
    question: str
    mode: RunMode
    status: RunStatus
    created_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    model: str
    plan: ResearchPlan | None = None
    findings: list[TaskFinding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    report: Report | None = None
    verification: Verification | None = None
    stats: RunStats = Field(default_factory=RunStats)


# --------------------------------------------------------------------------- events


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    HANDOFF = "handoff"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    LLM_CALL_FAILED = "llm_call_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    SOURCE_RECORDED = "source_recorded"
    WARNING = "warning"
    ERROR = "error"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


TERMINAL_EVENTS = {EventType.RUN_COMPLETED, EventType.RUN_FAILED}


class RunEvent(BaseModel):
    run_id: str
    seq: int
    ts: datetime
    type: EventType
    agent: str | None = None
    task_id: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
