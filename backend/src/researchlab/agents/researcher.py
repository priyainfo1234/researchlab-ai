from __future__ import annotations

from typing import Any

from ..mcp_client import SearchFailedError
from ..schemas import EventType, ResearcherOutput, ResearchTask, TaskFinding
from ..untrusted import UNTRUSTED_NOTICE, wrap_untrusted
from .context import RunAbort, RunContext, call_llm
from .inputs import ResearcherInput

AGENT = "researcher"
MAX_SOURCES_PER_TASK = 6

SYSTEM = (
    "You are a research worker. You receive one research task and web sources retrieved for it. "
    "Extract up to 6 factual claims that help the task. Each claim MUST be supported by exactly "
    "one source: give the source id and a quote copied VERBATIM from that source's text. "
    "Do not use outside knowledge. If the sources do not cover something, list it under 'gaps'. "
    + UNTRUSTED_NOTICE
    + " Respond only with JSON."
)


class _ToolEvents:
    """Turns real MCP client callbacks into events. Nothing is reported unless it happened."""

    def __init__(self, ctx: RunContext, task_id: str) -> None:
        self._ctx = ctx
        self._task_id = task_id

    async def on_started(self, tool: str, arguments: dict[str, Any], attempt: int) -> None:
        await self._ctx.emit(
            EventType.TOOL_CALL_STARTED,
            f"MCP tool {tool}: {arguments['query']}",
            agent=AGENT,
            task_id=self._task_id,
            tool=tool,
            arguments=arguments,
            attempt=attempt,
        )
        self._ctx.stats.tool_calls += 1

    async def on_completed(
        self, tool: str, arguments: dict[str, Any], attempt: int, hits: int, duration_ms: int
    ) -> None:
        await self._ctx.emit(
            EventType.TOOL_CALL_COMPLETED,
            f"MCP tool {tool} returned {hits} result(s)",
            agent=AGENT,
            task_id=self._task_id,
            tool=tool,
            arguments=arguments,
            attempt=attempt,
            results=hits,
            duration_ms=duration_ms,
        )

    async def on_failed(
        self,
        tool: str,
        arguments: dict[str, Any],
        attempt: int,
        error: str,
        will_retry: bool,
        duration_ms: int,
    ) -> None:
        self._ctx.stats.tool_failures += 1
        await self._ctx.emit(
            EventType.TOOL_CALL_FAILED,
            f"MCP tool {tool} failed" + (" – will retry" if will_retry else ""),
            agent=AGENT,
            task_id=self._task_id,
            tool=tool,
            arguments=arguments,
            attempt=attempt,
            error=error,
            will_retry=will_retry,
            duration_ms=duration_ms,
        )


def _prompt(task: ResearchTask, sources_text: str) -> str:
    return (
        f"Task {task.id}: {task.title}\nObjective: {task.objective}\n\n"
        f"Sources:\n{sources_text}\n\n"
        "Return claims with source_id (e.g. s1) and a verbatim quote."
    )


async def research(ctx: RunContext, task: ResearchTask) -> TaskFinding:
    """Investigate one task. Failures are contained: they become a finding, not a crash."""
    await ctx.emit(
        EventType.AGENT_STARTED,
        f"Researcher started: {task.title}",
        agent=AGENT,
        task_id=task.id,
    )
    observer = _ToolEvents(ctx, task.id)
    search_errors: list[str] = []
    for query in task.search_queries[: ctx.settings.max_queries_per_task]:
        try:
            response = await ctx.search.search(query, ctx.settings.max_results_per_query, observer)
        except SearchFailedError as exc:
            search_errors.append(str(exc))
            await ctx.emit(
                EventType.ERROR,
                f"Search failed for '{query}' after {exc.attempts} attempt(s)",
                agent=AGENT,
                task_id=task.id,
                error=str(exc),
            )
            continue
        for hit in response.hits:
            source, is_new = ctx.registry.add_hit(hit, task.id, query)
            if source is None:
                continue
            if is_new:
                ctx.stats.sources += 1
                await ctx.emit(
                    EventType.SOURCE_RECORDED,
                    f"Recorded source {source.id}: {source.title}",
                    agent=AGENT,
                    task_id=task.id,
                    source_id=source.id,
                    url=source.url,
                    title=source.title,
                    retrieved_at=source.retrieved_at.isoformat(),
                )
                if source.flags:
                    await ctx.emit(
                        EventType.WARNING,
                        f"Source {source.id} contains text that looks like an instruction to an "
                        "AI system; it is treated strictly as data",
                        agent=AGENT,
                        task_id=task.id,
                        source_id=source.id,
                        flags=source.flags,
                    )

    sources = ctx.registry.sources_for_task(task.id)[:MAX_SOURCES_PER_TASK]
    if not sources:
        status = "failed" if search_errors else "no_results"
        msg = (
            "Search tool failed; no evidence gathered"
            if search_errors
            else "Search returned no usable results"
        )
        await ctx.emit(
            EventType.AGENT_COMPLETED,
            f"Researcher finished {task.id}: {msg}",
            agent=AGENT,
            task_id=task.id,
            status=status,
        )
        return TaskFinding(
            task_id=task.id,
            status=status,
            gaps=[f"No evidence retrieved for '{task.title}'."],
            error="; ".join(search_errors) or None,
        )

    sources_text = "\n\n".join(
        wrap_untrusted(s.id, f"Title: {s.title}\n{s.excerpt}") for s in sources
    )
    inp = ResearcherInput(question=ctx.question, task=task, sources=sources)
    try:
        out = await call_llm(
            ctx,
            agent=AGENT,
            step="research",
            system=SYSTEM,
            prompt=_prompt(task, sources_text),
            schema=ResearcherOutput,
            inputs=inp,
            task_id=task.id,
        )
    except RunAbort as exc:
        await ctx.emit(
            EventType.ERROR, f"Extraction failed for {task.id}", agent=AGENT, task_id=task.id,
            error=str(exc),
        )
        return TaskFinding(task_id=task.id, status="failed", error=str(exc),
                           gaps=[f"Claim extraction failed for '{task.title}'."])

    claim_ids: list[str] = []
    dropped = 0
    for raw in out.claims:
        claim = ctx.registry.add_claim(task.id, raw.text, raw.source_id, raw.quote)
        if claim is None:
            dropped += 1
            await ctx.emit(
                EventType.WARNING,
                f"Dropped a claim citing unknown source '{raw.source_id}'",
                agent=AGENT,
                task_id=task.id,
            )
            continue
        ctx.stats.claims = len(ctx.registry.claims())
        if not claim.evidence[0].quote_verified:
            dropped += 1
            await ctx.emit(
                EventType.WARNING,
                f"Claim {claim.id} excluded: quote not found in {raw.source_id}",
                agent=AGENT,
                task_id=task.id,
                claim_id=claim.id,
            )
            continue
        claim_ids.append(claim.id)

    gaps = list(out.gaps)
    if dropped:
        gaps.append(
            f"{dropped} extracted claim(s) were excluded because they could not be verified "
            "against the source text."
        )
    await ctx.emit(
        EventType.AGENT_COMPLETED,
        f"Researcher finished {task.id}: {len(claim_ids)} verified claim(s) from {len(sources)} source(s)",
        agent=AGENT,
        task_id=task.id,
        status="ok" if claim_ids else "no_results",
        claims=len(claim_ids),
    )
    return TaskFinding(
        task_id=task.id,
        status="ok" if claim_ids else "no_results",
        claim_ids=claim_ids,
        gaps=gaps,
    )
