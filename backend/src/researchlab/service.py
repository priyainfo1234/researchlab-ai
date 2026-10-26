"""Run lifecycle: build dependencies for a mode, execute the graph with bounds, persist."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from mcp import StdioServerParameters

from .agents.context import RunAbort, RunContext
from .config import Settings
from .events import EventBus
from .graph import build_graph
from .llm.base import LLM
from .llm.demo import DemoLLM
from .llm.gemini import GeminiLLM
from .mcp_client import McpClientError, McpSearchClient, SearchProvider
from .registry import SourceRegistry
from .schemas import (
    EventType,
    RunCreate,
    RunMode,
    RunSnapshot,
    RunStatus,
    utcnow,
)
from .store import Store

SearchFactory = Callable[[RunMode, Settings], AbstractAsyncContextManager[SearchProvider]]
LLMFactory = Callable[[RunMode, Settings], tuple[LLM, LLM]]

_SRC_DIR = str(Path(__file__).resolve().parents[1])


class LiveModeUnavailable(Exception):
    pass


def default_llms(mode: RunMode, settings: Settings) -> tuple[LLM, LLM]:
    if mode is RunMode.DEMO:
        return DemoLLM(), DemoLLM()
    assert settings.gemini_api_key is not None
    key = settings.gemini_api_key.get_secret_value()
    main = GeminiLLM(key, settings.gemini_model, settings.llm_timeout_seconds)
    verifier = (
        GeminiLLM(key, settings.verifier_model, settings.llm_timeout_seconds)
        if settings.verifier_model
        else main
    )
    return main, verifier


@asynccontextmanager
async def default_search(mode: RunMode, settings: Settings) -> AsyncIterator[SearchProvider]:
    if mode is RunMode.DEMO:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "researchlab.mcp_client.demo_server"],
            env={"PYTHONPATH": _SRC_DIR, "DEMO_BASE_URL": settings.demo_base_url},
        )
    else:
        assert settings.tavily_api_key is not None
        params = StdioServerParameters(
            command=settings.mcp_search_command,
            args=settings.mcp_search_arg_list,
            env={"TAVILY_API_KEY": settings.tavily_api_key.get_secret_value()},
        )
    async with McpSearchClient(
        params,
        tool_name=settings.mcp_search_tool,
        timeout=settings.tool_timeout_seconds,
        max_retries=settings.max_retries,
    ) as client:
        yield client


class RunService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        bus: EventBus,
        search_factory: SearchFactory = default_search,
        llm_factory: LLMFactory = default_llms,
    ) -> None:
        self.settings = settings
        self.store = store
        self.bus = bus
        self._search_factory = search_factory
        self._llm_factory = llm_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # -- public ---------------------------------------------------------------------
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

    def is_active(self, run_id: str) -> bool:
        t = self._tasks.get(run_id)
        return t is not None and not t.done()

    def check_can_start(self, mode: RunMode) -> None:
        if mode is RunMode.LIVE:
            reasons = self.settings.live_unavailable_reasons()
            if reasons:
                raise LiveModeUnavailable("; ".join(reasons))
        if self.active_count() >= self.settings.max_active_runs:
            raise RuntimeError("too many active runs")

    async def start(self, req: RunCreate) -> str:
        self.check_can_start(req.mode)
        llm, _ = self._llm_factory(req.mode, self.settings)
        run_id = uuid.uuid4().hex[:12]
        snap = RunSnapshot(
            run_id=run_id,
            question=req.question,
            mode=req.mode,
            status=RunStatus.QUEUED,
            created_at=utcnow(),
            model=llm.model,
        )
        await self.store.save_snapshot(snap)
        self._tasks[run_id] = asyncio.create_task(self._execute(snap), name=f"run-{run_id}")
        return run_id

    async def wait(self, run_id: str) -> None:
        t = self._tasks.get(run_id)
        if t:
            await t

    async def shutdown(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # -- internals ------------------------------------------------------------------
    async def _execute(self, snap: RunSnapshot) -> None:
        run_id = snap.run_id
        registry = SourceRegistry(self.settings.max_source_chars)
        state: dict = {}
        ctx: RunContext | None = None
        try:
            snap.status = RunStatus.RUNNING
            await self.store.save_snapshot(snap)
            llm, verifier_llm = self._llm_factory(snap.mode, self.settings)
            await self.bus.emit(
                run_id,
                EventType.RUN_STARTED,
                "Run started" + (" (DEMO MODE: fixtures + scripted model)" if snap.mode is RunMode.DEMO else ""),
                agent="system",
                data={"mode": snap.mode, "model": llm.model, "question": snap.question},
            )
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                async with self._search_factory(snap.mode, self.settings) as search:
                    ctx = RunContext(
                        run_id=run_id,
                        question=snap.question,
                        mode=snap.mode,
                        settings=self.settings,
                        llm=llm,
                        verifier_llm=verifier_llm,
                        search=search,
                        registry=registry,
                        bus=self.bus,
                    )
                    state = await build_graph(ctx).ainvoke({"findings": []})
            snap.plan = state.get("plan")
            snap.findings = sorted(state.get("findings", []), key=lambda f: f.task_id)
            snap.report = state.get("report")
            snap.verification = state.get("verification")
            snap.status = RunStatus.COMPLETED
        except TimeoutError:
            snap.status = RunStatus.FAILED
            snap.error = f"Run exceeded the {self.settings.run_timeout_seconds:.0f}s time limit"
        except McpClientError as exc:
            snap.status = RunStatus.FAILED
            snap.error = f"Search tool unavailable: {exc}"
        except RunAbort as exc:
            snap.status = RunStatus.FAILED
            snap.error = str(exc)
        except asyncio.CancelledError:
            snap.status = RunStatus.FAILED
            snap.error = "Run cancelled (server shutting down)"
            raise
        except Exception as exc:  # unexpected: still leave an inspectable record
            snap.status = RunStatus.FAILED
            snap.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            snap.finished_at = utcnow()
            snap.sources = registry.sources()
            snap.claims = registry.claims()
            if ctx:
                snap.stats = ctx.stats
                snap.plan = snap.plan or ctx.plan
                snap.findings = snap.findings or sorted(ctx.findings, key=lambda f: f.task_id)
            try:
                await asyncio.shield(self._finish(snap))
            finally:
                self.bus.forget(run_id)

    async def _finish(self, snap: RunSnapshot) -> None:
        await self.store.save_snapshot(snap)
        if snap.status is RunStatus.COMPLETED:
            await self.bus.emit(
                snap.run_id,
                EventType.RUN_COMPLETED,
                "Run completed",
                agent="system",
                data={"verification": snap.verification.overall if snap.verification else None},
            )
        else:
            await self.bus.emit(
                snap.run_id, EventType.RUN_FAILED, snap.error or "Run failed", agent="system"
            )
