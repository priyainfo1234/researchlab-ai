"""Does the live verifier catch bad statements? Tampers with a saved live run and re-verifies it.

    python scripts/probe_verifier.py [verifier_model]     (run from backend/ after smoke_live.py)

Appends known-bad statements (each citing a REAL claim that does not support it) to the report and
checks whether the verifier flags them. Spends one model call. Diagnostic only.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from researchlab.agents import verifier  # noqa: E402
from researchlab.agents.context import RunContext  # noqa: E402
from researchlab.config import Settings  # noqa: E402
from researchlab.events import EventBus  # noqa: E402
from researchlab.llm.gemini import GeminiLLM  # noqa: E402
from researchlab.registry import SourceRegistry  # noqa: E402
from researchlab.schemas import ReportSection, ReportStatement, RunSnapshot  # noqa: E402
from researchlab.store import Store  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "last_live_run.json"


async def main() -> None:
    snap = RunSnapshot.model_validate_json(DATA.read_text(encoding="utf-8"))
    settings = Settings(db_path=":memory:")
    model = sys.argv[1] if len(sys.argv) > 1 else settings.verifier_model or settings.gemini_model
    llm = GeminiLLM(settings.gemini_api_key.get_secret_value(), model, 60)

    reg = SourceRegistry()
    reg._sources = {s.id: s for s in snap.sources}  # noqa: SLF001 - diagnostic rebuild
    reg._claims = {c.id: c for c in snap.claims}  # noqa: SLF001
    store = Store(":memory:")
    await store.open()
    ctx = RunContext(run_id="probe", question=snap.question, mode=snap.mode, settings=settings, llm=llm,
                     verifier_llm=llm, search=None, registry=reg, bus=EventBus(store))  # type: ignore[arg-type]

    real = snap.claims[0]
    src = real.evidence[0].source_id
    bad = [
        ("BAD-1 unrelated fabrication", "Fine-tuning always reduces hallucinations to exactly zero in every enterprise deployment."),
        ("BAD-2 contradiction", "RAG is always far more expensive than fine-tuning because of its upfront training costs."),
        ("BAD-3 overreach", "A 2025 study of 400 companies found 93% of them abandoned RAG within a year."),
    ]
    report = snap.report.model_copy(deep=True)
    extra = [ReportStatement(id=f"x{i}", text=t, claim_ids=[real.id], source_ids=[src]) for i, (_, t) in enumerate(bad)]
    report.sections.append(ReportSection(heading="Injected probes", statements=extra))

    result = await verifier.verify(ctx, report)
    by_id = {v.statement_id: v for v in result.verdicts}
    print("verifier model:", model, "| overall:", result.overall)
    caught = 0
    for i, (label, _) in enumerate(bad):
        v = by_id[f"x{i}"]
        ok = v.verdict in ("unsupported", "conflicting", "partially_supported")
        caught += ok
        print(f"  {'CAUGHT' if ok else 'MISSED'}  {label}: {v.verdict} | {v.explanation[:110]}")
    real_ids = [s.id for s in snap.report.executive_summary]
    print("original statements still supported:", sum(by_id[i].verdict == "supported" for i in real_ids), "/", len(real_ids))
    print(f"caught {caught}/{len(bad)}")
    await store.close()


asyncio.run(main())
