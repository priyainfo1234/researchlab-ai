"""Independent verifier.

Independence is structural: a separate system prompt, an optionally different model, and no
access to the synthesizer's reasoning or prompt. It sees only the finished statements, the
claims' verbatim quotes, and the raw retrieved source text. Cheap deterministic checks run
first; the model judges semantic support.
"""

from __future__ import annotations

from ..schemas import (
    EventType,
    Report,
    ReportStatement,
    StatementVerdict,
    Verification,
    VerifierOutput,
)
from ..untrusted import UNTRUSTED_NOTICE, wrap_untrusted
from .context import RunContext, call_llm
from .inputs import VerifierInput

AGENT = "verifier"

SYSTEM = (
    "You are an independent fact-checking agent. For each report statement, decide whether the "
    "cited evidence supports it. Judge ONLY from the evidence text provided. Verdicts: "
    "'supported' (evidence states it), 'partially_supported' (evidence covers only part, or is "
    "weaker than the statement), 'unsupported' (evidence does not say it), 'conflicting' (other "
    "provided evidence contradicts it; list the conflicting source ids). Also list conflicts "
    "between sources and important evidence that is missing. Be strict; do not be generous. "
    + UNTRUSTED_NOTICE
    + " Respond only with JSON."
)


def _overall(verdicts: list[StatementVerdict]) -> str:
    checked = [v for v in verdicts if v.verdict != "inference"]
    if not checked:
        return "fail"
    bad = [v for v in checked if v.verdict in ("unsupported", "conflicting")]
    partial = [v for v in checked if v.verdict == "partially_supported"]
    if len(bad) * 2 >= len(checked):
        return "fail"
    if bad or partial or len(checked) < len(verdicts):
        return "pass_with_warnings"
    return "pass"


def _prompt(statements: list[ReportStatement], inp: VerifierInput) -> str:
    claims = {c.id: c for c in inp.claims}
    lines = []
    for st in statements:
        lines.append(f"Statement {st.id}: {st.text}")
        for cid in st.claim_ids:
            for ev in claims[cid].evidence:
                lines.append(f"  cites {cid} -> source {ev.source_id}, quote: \"{ev.quote}\"")
    evidence = "\n\n".join(
        wrap_untrusted(s.id, f"Title: {s.title}\n{s.excerpt}") for s in inp.sources
    )
    return (
        "Statements to check:\n" + "\n".join(lines) + "\n\nFull source text:\n" + evidence +
        "\n\nReturn one verdict per statement id."
    )


async def verify(ctx: RunContext, report: Report) -> Verification:
    await ctx.emit(EventType.HANDOFF, "Synthesizer → verifier", agent="synthesizer", to=AGENT)
    await ctx.emit(EventType.AGENT_STARTED, "Verifier is checking claims against evidence", agent=AGENT)

    verdicts: dict[str, StatementVerdict] = {}
    to_check: list[ReportStatement] = []
    for st in report.all_statements():
        if st.claim_ids:
            to_check.append(st)
        elif any(st.id == r.id for r in report.recommendations):
            verdicts[st.id] = StatementVerdict(
                statement_id=st.id,
                verdict="inference",
                explanation="Recommendation cites no evidence; it is the system's judgement, not a verified finding.",
                checked_by="code",
            )
        else:
            verdicts[st.id] = StatementVerdict(
                statement_id=st.id,
                verdict="unsupported",
                explanation="Statement cites no retrieved evidence.",
                checked_by="code",
            )

    conflicts: list[str] = []
    missing: list[str] = []
    if to_check:
        cited_claims = {cid for st in to_check for cid in st.claim_ids}
        claims = [c for c in ctx.registry.claims() if c.id in cited_claims]
        source_ids = {e.source_id for c in claims for e in c.evidence}
        sources = [s for s in ctx.registry.sources() if s.id in source_ids]
        inp = VerifierInput(statements=to_check, claims=claims, sources=sources)
        out = await call_llm(
            ctx,
            agent=AGENT,
            step="verify",
            system=SYSTEM,
            prompt=_prompt(to_check, inp),
            schema=VerifierOutput,
            inputs=inp,
            llm=ctx.verifier_llm,
        )
        known_sources = {s.id for s in ctx.registry.sources()}
        wanted = {st.id for st in to_check}
        for rv in out.verdicts:
            if rv.statement_id in wanted and rv.statement_id not in verdicts:
                verdicts[rv.statement_id] = StatementVerdict(
                    statement_id=rv.statement_id,
                    verdict=rv.verdict,
                    explanation=rv.explanation,
                    conflicting_source_ids=[s for s in rv.conflicting_source_ids if s in known_sources],
                )
        for st in to_check:
            if st.id not in verdicts:
                verdicts[st.id] = StatementVerdict(
                    statement_id=st.id,
                    verdict="unsupported",
                    explanation="Verifier returned no verdict for this statement; treated as unsupported.",
                    checked_by="code",
                )
        conflicts, missing = out.conflicts, out.missing_evidence

    ordered = [verdicts[s.id] for s in report.all_statements()]
    result = Verification(
        verdicts=ordered,
        conflicts=conflicts,
        missing_evidence=missing,
        overall=_overall(ordered),
        verifier_model=ctx.verifier_llm.model,
    )
    flagged = [v for v in ordered if v.verdict in ("unsupported", "conflicting", "partially_supported")]
    for v in flagged:
        await ctx.emit(
            EventType.WARNING,
            f"Verifier flagged {v.statement_id}: {v.verdict}",
            agent=AGENT,
            statement_id=v.statement_id,
            verdict=v.verdict,
        )
    await ctx.emit(
        EventType.AGENT_COMPLETED,
        f"Verifier finished: {result.overall} ({len(flagged)} flagged)",
        agent=AGENT,
        overall=result.overall,
        flagged=len(flagged),
    )
    return result
