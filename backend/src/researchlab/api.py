"""FastAPI application."""

from __future__ import annotations

import asyncio
import html
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from . import __version__
from .config import Settings, get_settings
from .demo import DEMO_QUESTION, load_documents
from .events import EventBus
from .schemas import TERMINAL_EVENTS, RunCreate, RunMode, RunSnapshot
from .service import (
    LiveModeUnavailable,
    LLMFactory,
    RunService,
    SearchFactory,
    default_llms,
    default_search,
)
from .store import Store


def create_app(
    settings: Settings | None = None,
    search_factory: SearchFactory = default_search,
    llm_factory: LLMFactory = default_llms,
) -> FastAPI:
    cfg = settings or get_settings()
    store = Store(cfg.db_path)
    bus = EventBus(store)
    service = RunService(cfg, store, bus, search_factory, llm_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.open()
        try:
            yield
        finally:
            await service.shutdown()
            await store.close()

    app = FastAPI(title="ResearchLab AI", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.service = service
    app.state.store = store

    @app.get("/api/health")
    async def health() -> dict:
        reasons = cfg.live_unavailable_reasons()
        return {
            "status": "ok",
            "version": __version__,
            "modes": {
                "demo": {
                    "available": True,
                    "description": "Deterministic fixtures + scripted model. No web access.",
                    "sample_question": DEMO_QUESTION,
                },
                "live": {
                    "available": not reasons,
                    "reasons": reasons,
                    "model": cfg.gemini_model,
                },
            },
        }

    @app.post("/api/runs", status_code=202)
    async def create_run(req: RunCreate) -> dict:
        try:
            run_id = await service.start(req)
        except LiveModeUnavailable as exc:
            raise HTTPException(409, f"Live mode is unavailable: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"id": run_id}

    @app.get("/api/runs")
    async def list_runs() -> list[dict]:
        return await store.list_runs()

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> RunSnapshot:
        snap = await store.get_snapshot(run_id)
        if snap is None:
            raise HTTPException(404, "run not found")
        return snap

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        after: int = Query(0, ge=0),
        last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> EventSourceResponse:
        if await store.get_snapshot(run_id) is None:
            raise HTTPException(404, "run not found")
        start = max(after, last_event_id or 0)

        async def gen() -> AsyncIterator[dict]:
            q = bus.subscribe(run_id)  # subscribe first so nothing is missed during replay
            last = start
            try:
                for ev in await store.events_after(run_id, last):
                    last = ev.seq
                    yield _sse(ev)
                    if ev.type in TERMINAL_EVENTS:
                        return
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=1.0)
                    except TimeoutError:
                        if not service.is_active(run_id):
                            for tail in await store.events_after(run_id, last):
                                last = tail.seq
                                yield _sse(tail)
                            return
                        continue
                    if ev.seq <= last:
                        continue
                    last = ev.seq
                    yield _sse(ev)
                    if ev.type in TERMINAL_EVENTS:
                        return
            finally:
                bus.unsubscribe(run_id, q)

        return EventSourceResponse(gen(), ping=15)

    @app.get("/demo/sources/{slug}", response_class=HTMLResponse)
    async def demo_source(slug: str) -> str:
        for doc in load_documents():
            if doc["slug"] == slug:
                return (
                    "<!doctype html><meta charset=utf-8>"
                    f"<title>{html.escape(doc['title'])}</title>"
                    "<body style='font-family:system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem'>"
                    "<p><strong>DEMO FIXTURE</strong> &mdash; synthetic text for offline testing; "
                    "not a real source.</p>"
                    f"<h1>{html.escape(doc['title'])}</h1><p>{html.escape(doc['content'])}</p>"
                )
        raise HTTPException(404, "unknown demo document")

    return app


def _sse(ev) -> dict:
    return {"id": str(ev.seq), "event": ev.type.value, "data": ev.model_dump_json()}


def _default_app() -> FastAPI:
    return create_app()


# `uvicorn researchlab.api:app --app-dir src`
app = _default_app()

__all__ = ["app", "create_app", "RunMode"]
