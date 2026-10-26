"""Shared run context and the single bounded LLM-call helper used by every agent."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..config import Settings
from ..events import EventBus
from ..llm.base import LLM, T
from ..mcp_client import SearchProvider
from ..registry import SourceRegistry
from ..schemas import EventType, ResearchPlan, RunMode, RunStats, TaskFinding


class RunAbort(Exception):
    """The run cannot produce a trustworthy result; fail it with this message."""


@dataclass
class RunContext:
    run_id: str
    question: str
    mode: RunMode
    settings: Settings
    llm: LLM
    verifier_llm: LLM
    search: SearchProvider
    registry: SourceRegistry
    bus: EventBus
    stats: RunStats = field(default_factory=RunStats)
    # Progress mirror so a run that aborts part-way is still inspectable.
    plan: ResearchPlan | None = None
    findings: list[TaskFinding] = field(default_factory=list)

    async def emit(
        self,
        type: EventType,
        message: str,
        *,
        agent: str | None = None,
        task_id: str | None = None,
        **data: object,
    ) -> None:
        await self.bus.emit(self.run_id, type, message, agent=agent, task_id=task_id, data=data)


async def call_llm(
    ctx: RunContext,
    *,
    agent: str,
    step: str,
    system: str,
    prompt: str,
    schema: type[T],
    inputs: BaseModel,
    llm: LLM | None = None,
    task_id: str | None = None,
) -> T:
    """Call a model with a timeout and bounded retries; every attempt is reported."""
    model = llm or ctx.llm
    attempts = ctx.settings.max_retries + 1
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        await ctx.emit(
            EventType.LLM_CALL_STARTED,
            f"{agent}: calling model for {step}",
            agent=agent,
            task_id=task_id,
            step=step,
            model=model.model,
            attempt=attempt,
        )
        ctx.stats.llm_calls += 1
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(ctx.settings.llm_timeout_seconds):
                result = await model.generate(
                    step=step, system=system, prompt=prompt, schema=schema, inputs=inputs
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last = exc
            err = f"{type(exc).__name__}: {str(exc)[:300]}"
            await ctx.emit(
                EventType.LLM_CALL_FAILED,
                f"{agent}: model call failed ({step})",
                agent=agent,
                task_id=task_id,
                step=step,
                attempt=attempt,
                error=err,
                will_retry=attempt < attempts,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            if attempt < attempts:
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
            continue
        await ctx.emit(
            EventType.LLM_CALL_COMPLETED,
            f"{agent}: model call completed ({step})",
            agent=agent,
            task_id=task_id,
            step=step,
            attempt=attempt,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return result
    raise RunAbort(f"{agent} could not get a valid model response for {step}: {last}")
