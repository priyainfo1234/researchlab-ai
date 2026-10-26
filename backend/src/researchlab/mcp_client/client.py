"""MCP search client.

This module knows about MCP and nothing about agents, prompts or graphs. It reports what
actually happened on each attempt through an observer, and the agent layer turns those
callbacks into user-visible events. A tool call is reported as *started* before the
request is sent and *completed* only after a result was received and parsed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Protocol

from mcp import Client

from .parsing import ParseError, SearchHit, parse_call_result


class McpClientError(Exception):
    """Connection / discovery failure."""


class SearchFailedError(Exception):
    """A search failed after all permitted attempts."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class SearchObserver(Protocol):
    async def on_started(self, tool: str, arguments: dict[str, Any], attempt: int) -> None: ...

    async def on_completed(
        self, tool: str, arguments: dict[str, Any], attempt: int, hits: int, duration_ms: int
    ) -> None: ...

    async def on_failed(
        self,
        tool: str,
        arguments: dict[str, Any],
        attempt: int,
        error: str,
        will_retry: bool,
        duration_ms: int,
    ) -> None: ...


@dataclass
class SearchResponse:
    hits: list[SearchHit]
    attempts: int
    duration_ms: int


class SearchProvider(Protocol):
    """What the agent layer depends on. ``McpSearchClient`` is the real implementation."""

    async def search(
        self, query: str, max_results: int, observer: SearchObserver | None = None
    ) -> SearchResponse: ...


def pick_search_tool(tool_names: list[str], preferred: str | None = None) -> str:
    if preferred:
        if preferred not in tool_names:
            raise McpClientError(
                f"configured search tool {preferred!r} not offered by server; has {tool_names}"
            )
        return preferred
    candidates = [n for n in tool_names if "search" in n.lower()]
    if not candidates:
        raise McpClientError(f"no search tool offered by server; has {tool_names}")
    return sorted(candidates, key=lambda n: (len(n), n))[0]


class McpSearchClient:
    """Async context manager wrapping an MCP ``Client`` that exposes a search tool."""

    def __init__(
        self,
        target: Any,
        *,
        tool_name: str | None = None,
        timeout: float = 30,
        max_retries: int = 2,
        concurrency: int = 2,
        backoff_base: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._target = target
        self._preferred_tool = tool_name
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._sem = asyncio.Semaphore(concurrency)
        self._stack = AsyncExitStack()
        self._client: Client | None = None
        self.tool_name: str | None = None

    async def __aenter__(self) -> McpSearchClient:
        try:
            async with asyncio.timeout(self._timeout * 2):
                self._client = await self._stack.enter_async_context(Client(self._target))
                listing = await self._client.list_tools()
        except BaseException as exc:
            await self._stack.aclose()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise McpClientError(f"could not connect to MCP server: {exc!r}") from exc
        self.tool_name = pick_search_tool([t.name for t in listing.tools], self._preferred_tool)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def search(
        self, query: str, max_results: int, observer: SearchObserver | None = None
    ) -> SearchResponse:
        if self._client is None or self.tool_name is None:
            raise McpClientError("client is not connected")
        arguments = {"query": query, "max_results": max_results}
        started = time.monotonic()
        last_error = "unknown error"
        async with self._sem:
            for attempt in range(1, self._max_retries + 2):
                t0 = time.monotonic()
                if observer:
                    await observer.on_started(self.tool_name, arguments, attempt)
                try:
                    async with asyncio.timeout(self._timeout):
                        result = await self._client.call_tool(
                            self.tool_name, arguments, read_timeout_seconds=self._timeout
                        )
                    if result.is_error:
                        texts = [getattr(c, "text", "") for c in result.content]
                        raise RuntimeError(f"tool reported an error: {' '.join(texts)[:300]}")
                    texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
                    hits = parse_call_result(result.structured_content, texts)
                except asyncio.CancelledError:
                    raise
                except ParseError as exc:  # deterministic: retrying will not help
                    last_error = f"ParseError: {exc}"
                    if observer:
                        await observer.on_failed(
                            self.tool_name, arguments, attempt, last_error, False, _ms(t0)
                        )
                    raise SearchFailedError(last_error, attempt) from exc
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"[:400]
                    will_retry = attempt <= self._max_retries
                    if observer:
                        await observer.on_failed(
                            self.tool_name, arguments, attempt, last_error, will_retry, _ms(t0)
                        )
                    if not will_retry:
                        raise SearchFailedError(last_error, attempt) from exc
                    await self._sleep(self._backoff_base * 2 ** (attempt - 1))
                    continue
                if observer:
                    await observer.on_completed(
                        self.tool_name, arguments, attempt, len(hits), _ms(t0)
                    )
                return SearchResponse(hits=hits, attempts=attempt, duration_ms=_ms(started))
        raise SearchFailedError(last_error, self._max_retries + 1)  # pragma: no cover


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
