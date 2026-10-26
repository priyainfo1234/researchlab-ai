"""Per-run evidence registry: the single source of truth for sources and claims.

Sources enter only through ``add_hit`` (i.e. from real tool results). Claims enter only
through ``add_claim`` after the source id and quote have been checked. Reports resolve
citations against this registry, never against model-written URLs.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .mcp_client import SearchHit
from .schemas import Claim, ClaimEvidence, Source, utcnow
from .untrusted import detect_injection, normalize_for_match, quote_in_text, sanitize_text, sanitize_title


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


class SourceRegistry:
    def __init__(self, max_source_chars: int = 4000) -> None:
        self._max_chars = max_source_chars
        self._sources: dict[str, Source] = {}
        self._by_url: dict[str, str] = {}
        self._claims: dict[str, Claim] = {}

    # -- sources ---------------------------------------------------------------------
    def add_hit(self, hit: SearchHit, task_id: str, query: str) -> tuple[Source | None, bool]:
        """Record a hit. Returns (source, is_new); (None, False) if the hit is unusable."""
        key = canonical_url(hit.url)
        if not key.lower().startswith(("http://", "https://")):
            return None, False
        existing_id = self._by_url.get(key)
        if existing_id:
            src = self._sources[existing_id]
            if task_id not in src.found_by_tasks:
                src.found_by_tasks.append(task_id)
            if query not in src.queries:
                src.queries.append(query)
            return src, False
        excerpt = sanitize_text(hit.content, self._max_chars)
        if not excerpt:
            return None, False
        sid = f"s{len(self._sources) + 1}"
        flags = ["possible_prompt_injection"] if detect_injection(hit.content) else []
        src = Source(
            id=sid,
            url=hit.url.strip(),
            title=sanitize_title(hit.title, fallback=hit.url),
            retrieved_at=utcnow(),
            excerpt=excerpt,
            found_by_tasks=[task_id],
            queries=[query],
            flags=flags,
        )
        self._sources[sid] = src
        self._by_url[key] = sid
        return src, True

    def get(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def sources(self) -> list[Source]:
        return list(self._sources.values())

    def sources_for_task(self, task_id: str) -> list[Source]:
        return [s for s in self._sources.values() if task_id in s.found_by_tasks]

    # -- claims ----------------------------------------------------------------------
    def add_claim(self, task_id: str, text: str, source_id: str, quote: str) -> Claim | None:
        """Register a claim if its source exists and was found by this task."""
        src = self._sources.get(source_id)
        if src is None or task_id not in src.found_by_tasks:
            return None
        # The same quote from the same source is one claim, however many tasks surfaced it.
        key = (source_id, normalize_for_match(quote))
        for existing in self._claims.values():
            if (existing.evidence[0].source_id, normalize_for_match(existing.evidence[0].quote)) == key:
                return existing
        verified = quote_in_text(quote, src.excerpt)
        cid = f"c{len(self._claims) + 1}"
        claim = Claim(
            id=cid,
            task_id=task_id,
            text=text.strip(),
            evidence=[ClaimEvidence(source_id=source_id, quote=quote.strip(), quote_verified=verified)],
        )
        self._claims[cid] = claim
        if verified and cid not in src.claim_ids:
            src.claim_ids.append(cid)
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def claims(self) -> list[Claim]:
        return list(self._claims.values())

    def verified_claims(self) -> list[Claim]:
        return [c for c in self._claims.values() if all(e.quote_verified for e in c.evidence)]
