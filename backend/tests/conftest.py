"""Shared test doubles. Nothing here touches the network or a paid API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from researchlab.agents.context import RunContext
from researchlab.config import Settings
from researchlab.events import EventBus
from researchlab.mcp_client import SearchFailedError, SearchHit, SearchResponse
from researchlab.registry import SourceRegistry
from researchlab.schemas import RunMode
from researchlab.store import Store


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        db_path=":memory:",
        max_retries=1,
        llm_timeout_seconds=5,
        tool_timeout_seconds=5,
        run_timeout_seconds=30,
        gemini_api_key=None,
        tavily_api_key=None,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeSearch:
    """SearchProvider returning canned hits per query. Reports calls like the real client."""

    def __init__(self, results: dict[str, list[SearchHit]] | None = None, fail: set[str] | None = None):
        self.results = results or {}
        self.fail = fail or set()
        self.calls: list[str] = []

    async def search(self, query: str, max_results: int, observer=None) -> SearchResponse:
        self.calls.append(query)
        args = {"query": query, "max_results": max_results}
        if observer:
            await observer.on_started("fake_search", args, 1)
        if query in self.fail:
            if observer:
                await observer.on_failed("fake_search", args, 1, "boom", False, 1)
            raise SearchFailedError("boom", 1)
        hits = self.results.get(query, [])
        if observer:
            await observer.on_completed("fake_search", args, 1, len(hits), 1)
        return SearchResponse(hits=hits, attempts=1, duration_ms=1)


class ScriptedLLM:
    """Returns pre-built objects per step; records every call."""

    def __init__(self, model: str = "scripted", **by_step: Any) -> None:
        self.model = model
        self.by_step = by_step
        self.calls: list[tuple[str, str]] = []

    async def generate(self, *, step, system, prompt, schema, inputs=None):
        self.calls.append((step, prompt))
        value = self.by_step[step]
        if callable(value):
            value = value(inputs)
        if isinstance(value, Exception):
            raise value
        return schema.model_validate(value if isinstance(value, dict) else value.model_dump())


@pytest.fixture
async def store():
    s = Store(":memory:")
    await s.open()
    yield s
    await s.close()


@pytest.fixture
def make_ctx(store) -> Callable[..., RunContext]:
    def _make(search=None, llm=None, verifier_llm=None, **settings_kw: Any) -> RunContext:
        llm = llm or ScriptedLLM()
        return RunContext(
            run_id="run1",
            question="Does X beat Y?",
            mode=RunMode.LIVE,
            settings=make_settings(**settings_kw),
            llm=llm,
            verifier_llm=verifier_llm or llm,
            search=search or FakeSearch(),
            registry=SourceRegistry(),
            bus=EventBus(store),
        )

    return _make


def hit(n: int, content: str | None = None) -> SearchHit:
    return SearchHit(
        url=f"https://example.test/page{n}",
        title=f"Page {n}",
        content=content or f"Fact number {n} is stated here plainly. Another sentence follows.",
    )
