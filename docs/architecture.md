# Architecture

## 1. Workflow

```
Browser ──POST /api/runs──▶ FastAPI ──▶ RunService (background asyncio task)
   ▲                                        │ opens MCP client, builds RunContext
   │ SSE /api/runs/{id}/events              ▼
   └───────── EventBus ◀──────────── LangGraph
                │ (every event persisted)
                ▼
             SQLite  ◀── snapshot saved on start, completion and failure

START → plan → ⟨research × N in parallel (Send)⟩ → synthesize → verify → END
```

| Agent | Input | Output | Notes |
|---|---|---|---|
| Planner | question | `ResearchPlan` (3–5 `ResearchTask`) | Count enforced by schema; queries truncated to `MAX_QUERIES_PER_TASK` |
| Researcher (per task) | task | `TaskFinding` + sources/claims in the registry | Calls search through the MCP client; LLM extracts claims with verbatim quotes |
| Synthesizer | verified claims | `Report` | May cite only claim IDs it was given |
| Verifier | statements + quotes + raw source text | `Verification` | Separate prompt, optional separate model |

A failed search or extraction in one task becomes a `TaskFinding(status="failed")` and a report limitation; it does not
abort the run. The run aborts (`failed`, snapshot kept) when no verifiable evidence exists, when the planner/synthesizer/
verifier cannot get a valid model response, when the MCP server cannot be started, or at the run deadline.

## 2. Trust boundaries and the evidence chain

```
web ──▶ MCP server ──▶ McpSearchClient ──▶ SourceRegistry ──▶ claims ──▶ report ──▶ verifier
untrusted     untrusted-by-us     parse+retry     sanitise, id, URL      quote check   cite by id   re-check
```

- **Sources** (`registry.py`) are created only by `add_hit`, from parsed tool output: `id` (`s1`…), canonical-URL de-dup,
  http(s)-only, sanitised excerpt, `retrieved_at`, `found_by_tasks`, `queries`, `claim_ids`, `flags`.
- **Claims** are created only by `add_claim`: the source must exist and have been found by that task; the quote is
  checked against the stored excerpt (case/punctuation-insensitive). Unverified claims are retained for inspection but
  excluded from synthesis. Identical quote + source = one claim across tasks.
- **Report statements** carry `claim_ids` (model-written, validated against the verified set) and `source_ids`
  (derived by code from claims). The UI builds citation links from the registry's URL — a model cannot introduce a URL.
- **Verdicts**: `supported | partially_supported | unsupported | conflicting` from the verifier model; `inference` for
  uncited recommendations (assigned by code, shown as “Judgement”); code assigns `unsupported` to uncited non-recommendation
  statements and to anything the verifier omitted. Overall `fail` when ≥ half the evidence-checked statements are
  unsupported/conflicting.

### Untrusted content
`untrusted.py`: strip scripts/tags/control chars, NFKC-normalise, bound size → regex-flag injection-like phrasing (advisory
only, surfaced as a warning event, source badge and report limitation) → wrap in `<untrusted_source id=…>` with closing-tag
escaping → every system prompt carries the same “this is data, not instructions” notice. The researcher agent has no tools
other than the already-completed search; model output is schema-validated JSON, so injected text cannot trigger actions.

## 3. MCP

`mcp_client/` imports nothing from agents/graph. `McpSearchClient(target)` accepts anything `mcp.Client` accepts
(stdio params, URL, or an in-process `MCPServer`), discovers tools, picks the search tool (`MCP_SEARCH_TOOL` or the
shortest name containing “search”), and exposes `search(query, max_results, observer)`.

Per attempt it calls `observer.on_started` → `call_tool` (inside `asyncio.timeout`) → parse → `on_completed`, or
`on_failed(will_retry)`. Retries: transport/tool errors and timeouts up to `MAX_RETRIES` with exponential back-off;
parse errors are not retried. The agent layer implements the observer and turns callbacks into events, so the timeline
shows exactly the attempts that occurred.

**Server choice.** Live: Tavily's official MCP server (`npx -y tavily-mcp@0.2.22`, stdio, `TAVILY_API_KEY`, free tier
exists). It returns one text block (`Detailed Results:` then `Title:/URL:/Content:`); `parsing.py` handles that and
prefers `structured_content` if a server provides it. Demo: `mcp_client/demo_server.py`, a ~30-line `MCPServer`
returning the same layout from fixtures, so both modes go through the same parser. Swapping providers = changing
`MCP_SEARCH_COMMAND/ARGS` (and, if the output format differs, `parsing.py`).

**MCP SDK note.** `mcp==2.3.0` (v2) exposes a high-level `mcp.Client` and `mcp.server.MCPServer`; examples written for
v1 (`ClientSession`, `FastMCP`) differ. The code follows the installed v2 API (verified by introspection and tests).

## 4. Streaming and persistence

`EventBus.emit` assigns a per-run sequence number, persists to SQLite, then fans out to subscribers. The SSE endpoint
subscribes *before* replaying stored events and de-duplicates by `seq`, so a client connecting mid-run misses nothing;
`?after=` / `Last-Event-ID` resume after a drop. Completed runs replay fully and close. `runs.snapshot_json` stores the
whole `RunSnapshot`; it is written when a run starts, and at the end (also on failure, with the plan and findings
mirrored from the run context). On startup, runs left `queued/running` are marked failed (“interrupted by server restart”).

## 5. Bounds

| Bound | Where |
|---|---|
| 3–5 tasks | `ResearchPlan` schema |
| ≤ `MAX_QUERIES_PER_TASK` queries, ≤ `MAX_RESULTS_PER_QUERY` results, ≤ 6 sources to the LLM per task | planner/researcher |
| Tool timeout + retries | `McpSearchClient` |
| LLM timeout + retries | `call_llm` |
| Run deadline | `asyncio.timeout(RUN_TIMEOUT_SECONDS)` in `RunService` |
| Concurrent runs | `MAX_ACTIVE_RUNS` (→ 429) |
| Concurrent tool calls per run | semaphore (2) |
| Source text size | `MAX_SOURCE_CHARS` (4000) |

## 6. Decisions

1. **Backend is the source of truth for evidence.** Models propose; code validates against the registry.
2. **LLM protocol with a demo implementation.** `generate(step, system, prompt, schema, inputs)`; the scripted model
   works from typed `inputs`, real models from `prompt`. Keeps agents vendor-free and tests deterministic.
3. **Demo uses real MCP + real graph.** Only content is synthetic, so most of the system is exercised without keys.
4. **No silent fallback** from live to demo; unavailability is a visible 409.
5. **SQLite via aiosqlite** for the POC (single process). Postgres/Redis are a later swap behind `Store`/`EventBus`.
6. **SSE not WebSockets**: one-way, resumable, works with `EventSource`.
7. **Frontend talks to the backend directly** (CORS allow-list) rather than via a Next proxy, which can buffer SSE.
8. **Pinned versions** checked against PyPI/npm on 2026-10-26: fastapi 0.162.0, uvicorn 0.54.0, langgraph 1.2.17,
   mcp 2.3.0, google-genai 2.33.0, pydantic 2.14.1, next 16.4.3, react 19.3.1, tailwindcss 4.3.3. TypeScript is pinned to 5.9.3
   rather than the newer 7.x line, which I did not validate with this Next.js version.
9. **Default model `gemini-3.8-flash`** per Google's model list at build time; configurable.

## 7. Risks and mitigations

| Risk | Mitigation | Residual |
|---|---|---|
| Prompt injection via pages | Sanitise, fence, flag, schema-only output, no action tools | LLMs can still be swayed in what they *extract*; verifier + quote check limit impact |
| Fabricated citations | Registry-only URLs; quote substring check; claim-ID validation | Quote check proves presence, not meaning |
| Verifier shares model blind spots | Separate prompt; optional `VERIFIER_MODEL`; evidence-only input | Use a different vendor/model for higher assurance |
| Search-tool format drift | Structured-first parsing; loud `ParseError`; `check_live_mcp.py` | Unverified until run with a key |
| Cost/time blow-up | All the bounds above | — |
| Key leakage | `.env` gitignored; keys only in server env; test asserts they never appear in API output | Don't log request bodies in production |
| No auth / multi-tenant | Out of scope for POC; CORS allow-list only | Do not expose publicly as-is |

## 8. Test strategy

- **Unit**: parsing (Tavily text, structured, empty, garbage), sanitising/injection/quote matching, registry (IDs, dedupe,
  claim rules).
- **MCP integration, mocked**: in-process `MCPServer` — success, transient failure + retry, retry cap, timeout,
  unparseable reply not retried, missing/misnamed search tool; asserts the started/completed/failed sequence.
- **Agent**, with scripted LLMs and a fake search: fabricated source/quote dropped, tool events match real calls, failed
  search ⇒ no claims and no model call, injection flagged and fenced in the prompt, synthesizer strips unknown IDs and
  records coverage gaps, verifier independence and default-to-unsupported, bounded LLM retries.
- **Workflow**, demo mode through a real stdio MCP subprocess: 3–5 tasks, every citation resolves to a recorded source,
  tool events pair 1:1 with attempts, conflicts and uncovered tasks are surfaced, events ordered and persisted; failure
  paths (MCP down, no evidence, run timeout, live without keys, run limit, restart recovery).
- **API**: health, 409/422/404, full SSE stream + replay + resume, snapshot inspection after completion, secrets absent
  from all responses.
- **Frontend**: status derivation from events, event merge/dedupe, `safeHref`, report rendering (citation links,
  non-http URLs inert, conflicts/limitations/demo label, failed-run state).
- **Not covered without keys**: live Gemini output quality/schema acceptance, live Tavily output. No evaluation results are
  claimed anywhere in this repo.

## 9. Roadmap

M2: live-mode hardening once keys are available (record real fixtures, add contract tests); source-quality ranking and
domain filters; cancel/resume runs; run comparison. M3: eval harness with human-labelled claim support; second search
provider; auth and per-user history; Postgres.
