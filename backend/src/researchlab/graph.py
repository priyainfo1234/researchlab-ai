"""LangGraph workflow: plan -> research (parallel fan-out) -> synthesize -> verify."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .agents import planner, researcher, synthesizer, verifier
from .agents.context import RunContext
from .schemas import Report, ResearchPlan, ResearchTask, TaskFinding, Verification


class WorkflowState(TypedDict, total=False):
    plan: ResearchPlan
    findings: Annotated[list[TaskFinding], operator.add]
    report: Report
    verification: Verification


class ResearchInput(TypedDict):
    task: ResearchTask


def build_graph(ctx: RunContext):
    async def plan_node(state: WorkflowState) -> WorkflowState:
        ctx.plan = await planner.plan(ctx)
        return {"plan": ctx.plan}

    def fan_out(state: WorkflowState) -> list[Send]:
        return [Send("research", {"task": t}) for t in state["plan"].tasks]

    async def research_node(state: ResearchInput) -> WorkflowState:
        finding = await researcher.research(ctx, state["task"])
        ctx.findings.append(finding)
        return {"findings": [finding]}

    async def synthesize_node(state: WorkflowState) -> WorkflowState:
        findings = sorted(state.get("findings", []), key=lambda f: f.task_id)
        return {"report": await synthesizer.synthesize(ctx, state["plan"], findings)}

    async def verify_node(state: WorkflowState) -> WorkflowState:
        return {"verification": await verifier.verify(ctx, state["report"])}

    g = StateGraph(WorkflowState)
    g.add_node("plan", plan_node)
    g.add_node("research", research_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("verify", verify_node)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["research"])
    g.add_edge("research", "synthesize")  # waits for all parallel branches
    g.add_edge("synthesize", "verify")
    g.add_edge("verify", END)
    return g.compile()
