"""Scripted, deterministic stand-in for a language model (DEMO MODE ONLY).

It is extractive and rule-based: it never invents text beyond what the retrieved fixtures
and the fixed plan below contain. It exists so the whole pipeline can be exercised and
tested without API access. It is not evidence of how a real model performs.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ..agents.inputs import PlannerInput, ResearcherInput, SynthesizerInput, VerifierInput
from ..schemas import (
    RawClaim,
    RawVerdict,
    ReportDraft,
    ReportSectionDraft,
    ResearcherOutput,
    ResearchPlan,
    ResearchTask,
    Statement,
    VerifierOutput,
)
from .base import T

_STOP = {"with", "that", "this", "from", "have", "were", "than", "each", "also", "such", "into"}
_MS = re.compile(r"(\d+)\s*ms")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if t not in _STOP}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) >= 20]


DEMO_PLAN = ResearchPlan(
    tasks=[
        ResearchTask(
            id="t1",
            title="Cost and infrastructure",
            objective="Compare upfront and ongoing cost drivers of retrieval versus fine-tuning.",
            search_queries=["retrieval augmented generation cost infrastructure", "fine-tuning cost compute"],
        ),
        ResearchTask(
            id="t2",
            title="Accuracy and grounding",
            objective="Compare how each approach affects answer accuracy and unsupported answers.",
            search_queries=["retrieval grounding hallucination accuracy", "fine-tuning domain accuracy style"],
        ),
        ResearchTask(
            id="t3",
            title="Latency and operations",
            objective="Compare latency overhead and operational burden of each approach.",
            search_queries=["retrieval latency overhead", "hybrid deployment"],
        ),
        ResearchTask(
            id="t4",
            title="Regulatory compliance",
            objective="Find regulatory and compliance obligations that affect the choice.",
            search_queries=["regulatory compliance obligations"],
        ),
    ]
)


class DemoLLM:
    model = "demo-scripted (no model)"

    async def generate(
        self,
        *,
        step: str,
        system: str,
        prompt: str,
        schema: type[T],
        inputs: BaseModel | None = None,
    ) -> T:
        if step == "plan" and isinstance(inputs, PlannerInput):
            return schema.model_validate(DEMO_PLAN.model_dump())
        if step == "research" and isinstance(inputs, ResearcherInput):
            return schema.model_validate(self._research(inputs).model_dump())
        if step == "synthesize" and isinstance(inputs, SynthesizerInput):
            return schema.model_validate(self._synthesize(inputs).model_dump())
        if step == "verify" and isinstance(inputs, VerifierInput):
            return schema.model_validate(self._verify(inputs).model_dump())
        raise ValueError(f"DemoLLM cannot handle step {step!r}")

    # -- researcher -----------------------------------------------------------------
    def _research(self, inp: ResearcherInput) -> ResearcherOutput:
        focus = _tokens(inp.task.title + " " + inp.task.objective)
        claims: list[RawClaim] = []
        for src in inp.sources[:4]:
            sentences = _sentences(src.excerpt)
            if not sentences:
                continue
            best = max(sentences, key=lambda s: (len(_tokens(s) & focus), -sentences.index(s)))
            claims.append(RawClaim(text=best[:400], source_id=src.id, quote=best[:500]))
        gaps = [] if claims else [f"No usable evidence was retrieved for: {inp.task.title}"]
        return ResearcherOutput(claims=claims, gaps=gaps)

    # -- synthesizer ----------------------------------------------------------------
    def _synthesize(self, inp: SynthesizerInput) -> ReportDraft:
        by_task: dict[str, list] = {}
        for c in inp.claims:
            by_task.setdefault(c.task_id, []).append(c)
        sections = []
        summary = []
        for task in inp.plan.tasks:
            claims = by_task.get(task.id)
            if not claims:
                continue
            sections.append(
                ReportSectionDraft(
                    heading=task.title,
                    statements=[Statement(text=c.text, claim_ids=[c.id]) for c in claims],
                )
            )
            summary.append(Statement(text=claims[0].text, claim_ids=[claims[0].id]))
        recs = []
        wanted = [
            c.id
            for c in inp.claims
            if any(k in c.text for k in ("Fine-tuning is effective", "update", "Many deployments"))
        ]
        if wanted:
            recs.append(
                Statement(
                    text="Use retrieval for knowledge that changes, and reserve fine-tuning for tone and format.",
                    claim_ids=wanted[:3],
                )
            )
        recs.append(Statement(text="Run a small pilot on your own documents before committing to either approach."))
        return ReportDraft(
            title="DEMO report: " + inp.question[:120],
            executive_summary=summary[:5] or [Statement(text="No evidence was gathered for this question.")],
            sections=sections
            or [ReportSectionDraft(heading="No findings", statements=[Statement(text="No findings were produced.")])],
            limitations=[
                "This is a scripted demo over synthetic fixture documents, not a real investigation.",
                *inp.gaps,
            ],
            recommendations=recs,
        )

    # -- verifier -------------------------------------------------------------------
    def _verify(self, inp: VerifierInput) -> VerifierOutput:
        claims = {c.id: c for c in inp.claims}
        quotes: dict[str, str] = {}
        ms_values: dict[str, set[str]] = {}
        for st in inp.statements:
            ev = [e for cid in st.claim_ids if cid in claims for e in claims[cid].evidence]
            quotes[st.id] = " ".join(e.quote for e in ev)
            if "latency" in quotes[st.id].lower():
                ms_values[st.id] = set(_MS.findall(quotes[st.id]))

        verdicts: list[RawVerdict] = []
        conflicts: list[str] = []
        for st in inp.statements:
            toks = _tokens(st.text)
            overlap = len(toks & _tokens(quotes[st.id])) / len(toks) if toks else 0.0
            verdict = "supported" if overlap >= 0.6 else "partially_supported" if overlap >= 0.3 else "unsupported"
            explanation = f"Lexical overlap with cited quotes: {overlap:.0%} (demo heuristic)."
            other = [
                o for o in inp.statements
                if o.id != st.id and ms_values.get(st.id) and ms_values.get(o.id)
                and ms_values[o.id] != ms_values[st.id]
            ]
            conflicting: list[str] = []
            if other:
                verdict = "conflicting"
                conflicting = sorted({sid for o in other for sid in o.source_ids})
                explanation = "Latency figures in cited quotes differ between sources."
            verdicts.append(
                RawVerdict(
                    statement_id=st.id,
                    verdict=verdict,
                    explanation=explanation,
                    conflicting_source_ids=conflicting,
                )
            )
        if any(v.verdict == "conflicting" for v in verdicts):
            conflicts.append(
                "Retrieval latency overhead is reported as different values by different sources."
            )
        return VerifierOutput(verdicts=verdicts, conflicts=conflicts, missing_evidence=[])
