from __future__ import annotations

from ..schemas import (
    EventType,
    Report,
    ReportDraft,
    ReportSection,
    ReportStatement,
    ResearchPlan,
    RunMode,
    Statement,
    TaskFinding,
)
from ..untrusted import UNTRUSTED_NOTICE, wrap_untrusted
from .context import RunAbort, RunContext, call_llm
from .inputs import SynthesizerInput

AGENT = "synthesizer"

SYSTEM = (
    "You are the report-writing agent. Write a structured research report that answers the "
    "question using ONLY the numbered claims provided. Every factual statement must list the "
    "claim ids (e.g. c3) that support it, and must not say more than those claims say. "
    "Do not add URLs or source names; citations are attached automatically. State limitations "
    "honestly, including topics where no evidence was found. Recommendations should follow from "
    "the evidence; cite claim ids where they do. " + UNTRUSTED_NOTICE + " Respond only with JSON."
)


def _prompt(question: str, plan: ResearchPlan, claims_text: str, gaps: list[str]) -> str:
    tasks = "\n".join(f"- {t.id}: {t.title}" for t in plan.tasks)
    gap_text = "\n".join(f"- {g}" for g in gaps) or "- none reported"
    return (
        f"Question: {question}\n\nResearch tasks:\n{tasks}\n\n"
        f"Known gaps:\n{gap_text}\n\nClaims:\n{claims_text}"
    )


async def synthesize(
    ctx: RunContext, plan: ResearchPlan, findings: list[TaskFinding]
) -> Report:
    await ctx.emit(
        EventType.HANDOFF, "Researchers → synthesizer", agent="researcher", to=AGENT
    )
    await ctx.emit(EventType.AGENT_STARTED, "Synthesizer is writing the report", agent=AGENT)

    claims = ctx.registry.verified_claims()
    if not claims:
        raise RunAbort("No verifiable evidence was retrieved, so no report can be written.")
    allowed = {c.id for c in claims}
    gaps = [g for f in findings for g in f.gaps]

    claims_text = wrap_untrusted(
        "claims", "\n".join(f"[{c.id}] (task {c.task_id}) {c.text}" for c in claims)
    )
    draft = await call_llm(
        ctx,
        agent=AGENT,
        step="synthesize",
        system=SYSTEM,
        prompt=_prompt(ctx.question, plan, claims_text, gaps),
        schema=ReportDraft,
        inputs=SynthesizerInput(question=ctx.question, plan=plan, claims=claims, gaps=gaps),
    )

    counter = 0
    dropped_ids = 0

    async def resolve(st: Statement) -> ReportStatement:
        nonlocal counter, dropped_ids
        counter += 1
        valid = [cid for cid in dict.fromkeys(st.claim_ids) if cid in allowed]
        unknown = [cid for cid in st.claim_ids if cid not in allowed]
        if unknown:
            dropped_ids += len(unknown)
            await ctx.emit(
                EventType.WARNING,
                f"Removed unknown claim ids {unknown} from statement r{counter}",
                agent=AGENT,
            )
        source_ids: list[str] = []
        for cid in valid:
            claim = ctx.registry.get_claim(cid)
            for ev in claim.evidence if claim else []:
                if ev.source_id not in source_ids:
                    source_ids.append(ev.source_id)
        return ReportStatement(
            id=f"r{counter}", text=st.text, claim_ids=valid, source_ids=source_ids
        )

    summary = [await resolve(s) for s in draft.executive_summary]
    sections = [
        ReportSection(heading=sec.heading, statements=[await resolve(s) for s in sec.statements])
        for sec in draft.sections
    ]
    recs = [await resolve(s) for s in draft.recommendations]

    limitations = list(draft.limitations)
    for f in findings:
        if f.status != "ok":
            title = next((t.title for t in plan.tasks if t.id == f.task_id), f.task_id)
            reason = "the search tool failed" if f.status == "failed" else "no usable evidence was found"
            limitations.append(f"Task '{title}': {reason}; this area is not covered by the report.")
    flagged = [s.id for s in ctx.registry.sources() if s.flags]
    if flagged:
        limitations.append(
            f"Source(s) {', '.join(flagged)} contained text resembling instructions to an AI "
            "system; it was treated as data and not followed."
        )
    if dropped_ids:
        limitations.append(f"{dropped_ids} citation(s) referenced unknown claims and were removed.")
    if ctx.mode is RunMode.DEMO:
        limitations.insert(0, "DEMO MODE: fixture documents and a scripted model were used; no live research occurred.")
    limitations = list(dict.fromkeys(limitations))

    report = Report(
        title=draft.title,
        executive_summary=summary,
        sections=sections,
        limitations=limitations,
        recommendations=recs,
    )
    await ctx.emit(
        EventType.AGENT_COMPLETED,
        f"Synthesizer wrote a report with {len(report.all_statements())} statements",
        agent=AGENT,
        statements=len(report.all_statements()),
    )
    return report
