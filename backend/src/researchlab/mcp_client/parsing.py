"""Normalise MCP search tool results into ``SearchHit`` objects.

Tavily's MCP server returns a single text block (``Detailed Results:`` followed by
``Title:/URL:/Content:`` lines). We prefer ``structured_content`` when a server provides
it, and fall back to parsing that text format. If neither yields results from a
non-empty reply we raise ``ParseError`` rather than guessing.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

_LABEL = re.compile(r"^(Title|ID|URL|Content|Raw Content|Favicon):\s?(.*)$")


class ParseError(Exception):
    """The tool replied, but not in a format we can interpret."""


class SearchHit(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    score: float | None = Field(default=None)


def _from_structured(data: Any) -> list[SearchHit] | None:
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list):
        return None
    hits = []
    for item in results:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        try:
            hits.append(
                SearchHit(
                    url=str(item["url"]),
                    title=str(item.get("title") or ""),
                    content=str(item.get("content") or item.get("snippet") or ""),
                    score=item.get("score") if isinstance(item.get("score"), int | float) else None,
                )
            )
        except ValidationError:
            continue
    return hits


def parse_text_results(text: str) -> list[SearchHit]:
    """Parse the ``Title: / URL: / Content:`` text layout."""
    marker = text.find("Detailed Results:")
    body = text[marker + len("Detailed Results:") :] if marker != -1 else text
    images = body.find("\nImages:")
    if images != -1:
        body = body[:images]

    hits: list[SearchHit] = []
    current: dict[str, list[str]] = {}
    field: str | None = None

    def flush() -> None:
        nonlocal current, field
        url = " ".join(current.get("URL", [])).strip()
        if url:
            hits.append(
                SearchHit(
                    url=url,
                    title=" ".join(current.get("Title", [])).strip(),
                    content="\n".join(current.get("Content", [])).strip(),
                )
            )
        current, field = {}, None

    for line in body.splitlines():
        m = _LABEL.match(line)
        if m:
            label, value = m.groups()
            # A repeated Title, or a URL after a URL, starts a new result.
            starts_new = (label == "Title" and "Title" in current) or (
                label == "URL" and "URL" in current
            )
            if starts_new or (label == "Title" and "URL" in current):
                flush()
            current.setdefault(label, []).append(value)
            field = label
        elif field == "Content" and line.strip():
            current["Content"].append(line)
    flush()
    return hits


def parse_call_result(structured: Any, text_blocks: list[str]) -> list[SearchHit]:
    structured_hits = _from_structured(structured)
    if structured_hits:
        return structured_hits

    text = "\n".join(t for t in text_blocks if t).strip()
    if not text:
        return []
    hits = parse_text_results(text)
    if hits:
        return hits
    if "Detailed Results:" in text or "No results" in text:
        return []  # a well-formed empty reply
    raise ParseError("search tool reply was not in a recognised format")
