"""Whole-workflow tests: demo mode through a real stdio MCP subprocess, plus failure paths."""

from contextlib import asynccontextmanager

import pytest

from researchlab.events import EventBus
from researchlab.mcp_client import McpClientError
from researchlab.schemas import EventType, RunCreate, RunMode, RunStatus
from researchlab.service import LiveModeUnavailable, RunService
from researchlab.store import Store

from .conftest import FakeSearch, ScriptedLLM, hit, make_settings

Q = "What are the trade-offs between RAG and fine-tuning?"


@pytest.fixture
async def demo_run(store):
    svc = RunService(make_settings(), store, EventBus(store))
    run_id = await svc.start(RunCreate(question=Q, mode=RunMode.DEMO))
    await svc.wait(run_id)
    yield run_id, await store.get_snapshot(run_id), await store.events_after(run_id)
    await svc.shutdown()


async def test_demo_run_completes_and_is_labelled_demo(demo_run):
    _, snap, events = demo_run
    assert snap.status == RunStatus.COMPLETED and snap.mode == RunMode.DEMO
    assert "DEMO" in events[0].message
    assert "DEMO MODE" in snap.report.limitations[0]
    assert "demo" in snap.model.lower()


async def test_demo_plan_has_3_to_5_tasks_and_one_researcher_each(demo_run):
    _, snap, events = demo_run
    assert 3 <= len(snap.plan.tasks) <= 5
    started = {e.task_id for e in events if e.type == EventType.AGENT_STARTED and e.agent == "researcher"}
    assert started == {t.id for t in snap.plan.tasks}


async def test_every_citation_resolves_to_a_recorded_source(demo_run):
    _, snap, _ = demo_run
    by_id = {s.id: s for s in snap.sources}
    cited = {sid for st in snap.report.all_statements() for sid in st.source_ids}
    assert cited and cited <= set(by_id)
    for s in snap.sources:  # requirement 4: url, title, timestamp, supported claims
        assert s.url.startswith("http") and s.title and s.retrieved_at
    claims = {c.id for c in snap.claims}
    assert any(s.claim_ids for s in snap.sources)
    assert all(set(s.claim_ids) <= claims for s in snap.sources)


async def test_tool_events_correspond_one_to_one_with_attempts(demo_run):
    _, snap, events = demo_run
    started = [e for e in events if e.type == EventType.TOOL_CALL_STARTED]
    ended = [e for e in events if e.type in (EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED)]
    assert len(started) == len(ended) == snap.stats.tool_calls > 0
    assert all(e.data["tool"] == "demo_search" for e in started)


async def test_uncovered_task_and_conflict_are_surfaced_not_hidden(demo_run):
    _, snap, _ = demo_run
    assert any(f.status == "no_results" for f in snap.findings)
    assert any("Regulatory" in lim for lim in snap.report.limitations)
    verdicts = {v.verdict for v in snap.verification.verdicts}
    assert "conflicting" in verdicts and snap.verification.overall == "pass_with_warnings"


async def test_events_are_ordered_and_persisted(demo_run):
    _, _, events = demo_run
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[0].type == EventType.RUN_STARTED and events[-1].type == EventType.RUN_COMPLETED
    types = [e.type for e in events]
    assert types.index(EventType.HANDOFF) < types.index(EventType.TOOL_CALL_STARTED)


# ------------------------------------------------------------------ failure paths


def _service(store, search_cm, llm=None, **kw):
    llm = llm or ScriptedLLM()
    return RunService(
        make_settings(**kw), store, EventBus(store),
        search_factory=search_cm, llm_factory=lambda mode, s: (llm, llm),
    )


async def _run(svc, store):
    run_id = await svc.start(RunCreate(question=Q, mode=RunMode.DEMO))
    await svc.wait(run_id)
    return await store.get_snapshot(run_id), await store.events_after(run_id)


async def test_mcp_unavailable_fails_the_run_honestly(store):
    @asynccontextmanager
    async def broken(mode, settings):
        raise McpClientError("could not connect to MCP server: spawn failed")
        yield  # pragma: no cover

    snap, events = await _run(_service(store, broken), store)
    assert snap.status == RunStatus.FAILED and "Search tool unavailable" in snap.error
    assert events[-1].type == EventType.RUN_FAILED
    assert not any(e.type == EventType.TOOL_CALL_COMPLETED for e in events)
    assert snap.report is None and snap.sources == []


async def test_all_searches_returning_nothing_fails_without_inventing_a_report(store):
    @asynccontextmanager
    async def empty(mode, settings):
        yield FakeSearch({})

    from researchlab.llm.demo import DEMO_PLAN

    snap, events = await _run(_service(store, empty, ScriptedLLM(plan=DEMO_PLAN)), store)
    assert snap.status == RunStatus.FAILED and "No verifiable evidence" in snap.error
    assert snap.report is None
    assert [f.status for f in snap.findings] == ["no_results"] * 4


async def test_run_timeout_is_enforced(store):
    import asyncio

    class SlowLLM(ScriptedLLM):
        async def generate(self, **kw):
            await asyncio.sleep(10)

    @asynccontextmanager
    async def fake(mode, settings):
        yield FakeSearch({"q": [hit(1)]})

    snap, events = await _run(
        _service(store, fake, SlowLLM(), run_timeout_seconds=0.5, llm_timeout_seconds=30), store
    )
    assert snap.status == RunStatus.FAILED and "time limit" in snap.error
    assert events[-1].type == EventType.RUN_FAILED


async def test_live_mode_refuses_to_start_without_keys_and_never_falls_back(store):
    svc = RunService(make_settings(), store, EventBus(store))
    with pytest.raises(LiveModeUnavailable, match="GEMINI_API_KEY.*TAVILY_API_KEY"):
        await svc.start(RunCreate(question=Q, mode=RunMode.LIVE))
    assert await store.list_runs() == []  # nothing was recorded or run


async def test_active_run_limit(store):
    import asyncio

    gate = asyncio.Event()

    class BlockedLLM(ScriptedLLM):
        async def generate(self, **kw):
            await gate.wait()

    @asynccontextmanager
    async def fake(mode, settings):
        yield FakeSearch()

    svc = _service(store, fake, BlockedLLM(), max_active_runs=1)
    first = await svc.start(RunCreate(question=Q, mode=RunMode.DEMO))
    with pytest.raises(RuntimeError, match="too many"):
        await svc.start(RunCreate(question=Q, mode=RunMode.DEMO))
    await svc.shutdown()
    assert first


async def test_interrupted_runs_are_marked_failed_on_restart(tmp_path):
    from researchlab.schemas import RunSnapshot, utcnow

    path = str(tmp_path / "t.db")
    s1 = Store(path)
    await s1.open()
    await s1.save_snapshot(RunSnapshot(run_id="x", question=Q, mode=RunMode.DEMO,
                                       status=RunStatus.RUNNING, created_at=utcnow(), model="m"))
    await s1.close()
    s2 = Store(path)
    await s2.open()
    rows = await s2.list_runs()
    await s2.close()
    assert rows[0]["status"] == "failed" and "restart" in rows[0]["error"]
