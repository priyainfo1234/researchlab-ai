"""Typed inputs handed to each agent step (also consumed by the scripted demo model)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..schemas import Claim, ReportStatement, ResearchPlan, ResearchTask, Source


class PlannerInput(BaseModel):
    question: str


class ResearcherInput(BaseModel):
    question: str
    task: ResearchTask
    sources: list[Source]


class SynthesizerInput(BaseModel):
    question: str
    plan: ResearchPlan
    claims: list[Claim]
    gaps: list[str] = Field(default_factory=list)


class VerifierInput(BaseModel):
    statements: list[ReportStatement]  # only statements that cite claims
    claims: list[Claim]
    sources: list[Source]
