"""Deterministic demo mode: fixture corpus, local demo MCP server, scripted stand-in model."""

from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE_PATH = Path(__file__).with_name("fixtures.json")

DEMO_QUESTION = (
    "What are the trade-offs between retrieval-augmented generation and fine-tuning "
    "for enterprise knowledge assistants?"
)


def load_documents() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["documents"]


def document_url(base_url: str, slug: str) -> str:
    return f"{base_url.rstrip('/')}/demo/sources/{slug}"


def search_documents(query: str, max_results: int) -> list[dict]:
    """Keyword match against curated per-document keywords (not full text)."""
    tokens = {t for t in re.findall(r"[a-z][a-z-]{2,}", query.lower())}
    scored = []
    for doc in load_documents():
        score = len(tokens & set(doc["keywords"]))
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda p: (-p[0], p[1]["slug"]))
    return [d for _, d in scored[:max_results]]
