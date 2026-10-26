from __future__ import annotations

from ..schemas import EventType, ResearchPlan
from .context import RunContext, call_llm
from .inputs import PlannerInput

AGENT = "planner"

SYSTEM = (
    "You are the planning agent of a research system. Decompose the user's research question "
    "into 3 to 5 distinct, non-overlapping research tasks that together cover the question. "
    "Each task has a short title, a one-sentence objective, and 1-3 concise web search queries. "
    "Use task ids t1, t2, ... in order. Do not answer the question. Respond only with JSON."
)


async def plan(ctx: RunContext) -> ResearchPlan:
    await ctx.emit(EventType.AGENT_STARTED, "Planner is decomposing the question", agent=AGENT)
    inp = PlannerInput(question=ctx.question)
    result = await call_llm(
        ctx,
        agent=AGENT,
        step="plan",
        system=SYSTEM,
        prompt=f"Research question:\n{ctx.question}",
        schema=ResearchPlan,
        inputs=inp,
    )
    # Bound the work regardless of what the model asked for.
    for task in result.tasks:
        task.search_queries = task.search_queries[: ctx.settings.max_queries_per_task]
    await ctx.emit(
        EventType.AGENT_COMPLETED,
        f"Planner produced {len(result.tasks)} research tasks",
        agent=AGENT,
        tasks=[t.model_dump() for t in result.tasks],
    )
    for task in result.tasks:
        await ctx.emit(
            EventType.HANDOFF,
            f"Planner → researcher: {task.title}",
            agent=AGENT,
            task_id=task.id,
            to="researcher",
        )
    return result
