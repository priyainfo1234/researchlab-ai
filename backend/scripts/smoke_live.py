"""Run ONE live-mode workflow in-process (spends a small amount of Gemini + Tavily quota).

    python scripts/smoke_live.py "your question"        (run from backend/, needs backend/.env)

Prints events and a result summary. Never prints key values.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from researchlab.config import Settings  # noqa: E402
from researchlab.events import EventBus  # noqa: E402
from researchlab.schemas import RunCreate, RunMode  # noqa: E402
from researchlab.service import RunService  # noqa: E402
from researchlab.store import Store  # noqa: E402

QUESTION = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "What are the main trade-offs between retrieval-augmented generation and fine-tuning for enterprise assistants?"
)


async def main() -> None:
    t0 = time.monotonic()
    settings = Settings(db_path=":memory:")
    print("live unavailable reasons:", settings.live_unavailable_reasons() or "none", "| model:", settings.gemini_model)
    store = Store(":memory:")
    await store.open()
    svc = RunService(settings, store, EventBus(store))
    rid = await svc.start(RunCreate(question=QUESTION, mode=RunMode.LIVE))
    await svc.wait(rid)
    snap = await store.get_snapshot(rid)
    print("status:", snap.status, "| secs:", round(time.monotonic() - t0, 1), "| stats:", snap.stats)
    print("error:", snap.error)
    for e in await store.events_after(rid):
        extra = ""
        if e.type.value in ("llm_call_failed", "tool_call_failed", "error"):
            extra = " | " + str(e.data.get("error", ""))[:300]
        print(e.seq, e.type.value, e.agent, e.task_id, e.message[:90] + extra)
    if snap.report:
        print("TITLE:", snap.report.title)
        print("sources:", [(s.id, s.url[:60]) for s in snap.sources][:8])
        print("verification:", snap.verification.overall if snap.verification else None)
    out = Path(__file__).resolve().parents[1] / "data" / "last_live_run.json"  # data/ is gitignored
    out.parent.mkdir(exist_ok=True)
    out.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    print("snapshot written to", out)
    await svc.shutdown()
    await store.close()


asyncio.run(main())
print("DONE")
