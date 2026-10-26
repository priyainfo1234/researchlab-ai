"""Run one DEMO-mode workflow in-process and print the events. Dev helper, no API keys needed.

    python scripts/smoke_demo.py
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


async def main() -> None:
    t0 = time.monotonic()
    settings = Settings(db_path=":memory:", _env_file=None)
    store = Store(":memory:")
    await store.open()
    svc = RunService(settings, store, EventBus(store))
    rid = await svc.start(
        RunCreate(question="What are the trade-offs of RAG vs fine-tuning?", mode=RunMode.DEMO)
    )
    await svc.wait(rid)
    snap = await store.get_snapshot(rid)
    print("status:", snap.status, "| error:", snap.error, "| secs:", round(time.monotonic() - t0, 1))
    print("stats:", snap.stats)
    for e in await store.events_after(rid):
        print(e.seq, e.type.value, e.agent, e.task_id, e.message[:100])
    if snap.verification:
        print("OVERALL", snap.verification.overall, snap.verification.conflicts)
        for v in snap.verification.verdicts:
            print(" ", v.statement_id, v.verdict, "|", v.explanation[:70])
    await svc.shutdown()
    await store.close()


asyncio.run(main())
print("DONE")
