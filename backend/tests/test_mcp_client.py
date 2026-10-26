"""MCP client tests against a real in-process MCP server (genuine protocol, no network)."""

import asyncio

import pytest
from mcp.server import MCPServer

from researchlab.mcp_client import McpClientError, McpSearchClient, SearchFailedError

OK_TEXT = "Detailed Results:\n\nTitle: Hit\nURL: https://ok.test/1\nContent: Body text here."


async def _no_sleep(_: float) -> None:
    return None


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def on_started(self, tool, arguments, attempt):
        self.events.append(("started", attempt))

    async def on_completed(self, tool, arguments, attempt, hits, duration_ms):
        self.events.append(("completed", attempt, hits))

    async def on_failed(self, tool, arguments, attempt, error, will_retry, duration_ms):
        self.events.append(("failed", attempt, will_retry))


def _server(handler, name="web_search") -> MCPServer:
    server = MCPServer("test")
    server.tool(name=name)(handler)
    return server


async def test_successful_search_reports_started_then_completed():
    def web_search(query: str, max_results: int = 5) -> str:
        return OK_TEXT

    rec = Recorder()
    async with McpSearchClient(_server(web_search), timeout=5) as c:
        assert c.tool_name == "web_search"
        res = await c.search("q", 3, rec)
    assert [h.url for h in res.hits] == ["https://ok.test/1"]
    assert rec.events == [("started", 1), ("completed", 1, 1)]


async def test_transient_failures_are_retried_and_each_attempt_reported():
    calls = {"n": 0}

    def web_search(query: str, max_results: int = 5) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporary upstream error")
        return OK_TEXT

    rec = Recorder()
    async with McpSearchClient(
        _server(web_search), timeout=5, max_retries=2, sleep=_no_sleep
    ) as c:
        res = await c.search("q", 3, rec)
    assert res.attempts == 3 and calls["n"] == 3
    assert rec.events == [
        ("started", 1), ("failed", 1, True),
        ("started", 2), ("failed", 2, True),
        ("started", 3), ("completed", 3, 1),
    ]


async def test_retry_limit_is_enforced():
    calls = {"n": 0}

    def web_search(query: str, max_results: int = 5) -> str:
        calls["n"] += 1
        raise RuntimeError("always down")

    rec = Recorder()
    async with McpSearchClient(
        _server(web_search), timeout=5, max_retries=2, sleep=_no_sleep
    ) as c:
        with pytest.raises(SearchFailedError) as exc:
            await c.search("q", 3, rec)
    assert calls["n"] == 3 and exc.value.attempts == 3  # 1 try + 2 retries, never more
    assert ("failed", 3, False) in rec.events
    assert not any(e[0] == "completed" for e in rec.events)  # never claims success


async def test_timeout_is_enforced():
    async def web_search(query: str, max_results: int = 5) -> str:
        await asyncio.sleep(5)
        return OK_TEXT

    rec = Recorder()
    async with McpSearchClient(
        _server(web_search), timeout=0.2, max_retries=0, sleep=_no_sleep
    ) as c:
        with pytest.raises(SearchFailedError):
            await c.search("q", 3, rec)
    assert rec.events[0] == ("started", 1) and rec.events[-1] == ("failed", 1, False)


async def test_unparseable_reply_is_not_retried():
    calls = {"n": 0}

    def web_search(query: str, max_results: int = 5) -> str:
        calls["n"] += 1
        return "some prose that is not a result list"

    async with McpSearchClient(
        _server(web_search), timeout=5, max_retries=3, sleep=_no_sleep
    ) as c:
        with pytest.raises(SearchFailedError, match="ParseError"):
            await c.search("q", 3)
    assert calls["n"] == 1


async def test_server_without_search_tool_is_rejected():
    def echo(text: str) -> str:
        return text

    with pytest.raises(McpClientError, match="no search tool"):
        async with McpSearchClient(_server(echo, name="echo"), timeout=5):
            pass


async def test_configured_tool_name_must_exist():
    def web_search(query: str, max_results: int = 5) -> str:
        return OK_TEXT

    with pytest.raises(McpClientError, match="not offered"):
        async with McpSearchClient(_server(web_search), tool_name="nope", timeout=5):
            pass
