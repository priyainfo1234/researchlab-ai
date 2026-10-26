"""Probe which Gemini models answer right now, using the app's structured-output request shape.

    python scripts/probe_gemini.py [model ...]       (run from backend/, needs backend/.env)

One tiny request per model. Never prints the key.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from researchlab.config import Settings  # noqa: E402
from researchlab.llm.gemini import GeminiLLM  # noqa: E402
from researchlab.schemas import ResearchPlan  # noqa: E402

MODELS = sys.argv[1:] or ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


async def main() -> None:
    s = Settings()
    key = s.gemini_api_key.get_secret_value()
    for m in MODELS:
        t0 = time.monotonic()
        llm = GeminiLLM(key, m, timeout_seconds=40)
        try:
            plan = await llm.generate(
                step="plan",
                system="Decompose the question into 3 research tasks with ids t1,t2,t3. JSON only.",
                prompt="Research question: Is solar power cheaper than coal?",
                schema=ResearchPlan,
            )
            print(f"OK    {m:26} {time.monotonic() - t0:5.1f}s  tasks={[t.id for t in plan.tasks]}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {m:26} {time.monotonic() - t0:5.1f}s  {type(exc).__name__}: {str(exc)[:160]}")


asyncio.run(main())
