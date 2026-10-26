# ResearchLab AI

A multi-agent research proof of concept. You ask a question; a **planner** splits it into 3–5 tasks, parallel
**researchers** investigate them through a real **MCP** search tool, a **synthesizer** writes a cited report, and an
independent **verifier** checks the report against the retrieved evidence. Every step streams to a dark web UI and is
persisted so a run can be inspected afterwards.

Stack: Python 3.11+ · FastAPI · LangGraph · official MCP Python SDK · Gemini API (`google-genai`) · Next.js + TypeScript.

> **Status: milestone 1 (vertical slice).** Demo mode and live mode (Gemini + Tavily MCP) have both been run end to
> end; see [Verification status](#verification-status) for exactly what was and was not checked.

## Two modes — never mixed

| | **Demo** | **Live** |
|---|---|---|
| Model | Scripted, rule-based stand-in (`llm/demo.py`) | Gemini via `google-genai` |
| Search | Local MCP server over bundled **synthetic** fixtures | Tavily's MCP server over the web |
| Needs keys | No | `GEMINI_API_KEY`, `TAVILY_API_KEY` |
| Labelled in UI/report | `DEMO MODE` badge, report limitation | — |

The demo still runs the real LangGraph workflow, a real MCP client talking to a real MCP server over stdio, real event
streaming and persistence. Only the *content* is synthetic. Live mode **never falls back** to demo: without keys the API
returns `409` and says which key is missing.

## Quick start (Windows PowerShell shown; macOS/Linux are analogous)

Prerequisites: Python ≥ 3.11, Node ≥ 20 (the live MCP server runs through `npx`), npm.

```powershell
# 1. Backend
cd backend
py -3 -m venv .venv                     # see "Windows long paths" below if your path is long
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy ..\.env.example .env               # optional: only needed for live mode
.venv\Scripts\python -m uvicorn researchlab.api:app --app-dir src --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                             # http://localhost:3000
```

Open http://localhost:3000, leave **Demo** selected, and press **Run demo**.

For live mode put real keys in `backend/.env` (gitignored; never in `NEXT_PUBLIC_*` variables), restart the backend, and
choose **Live research**. Check the MCP server can launch first (this downloads the pinned `tavily-mcp` package via npx
and makes **no** search request):

```powershell
.venv\Scripts\python scripts\check_live_mcp.py
```

### Windows long paths
Windows limits paths to 260 characters by default. If the project lives in a deeply nested folder, `pip`/`uv` can fail
with “system cannot find the path specified”. Create the venv in a short location (e.g. `%LOCALAPPDATA%\rl-venv`) or enable
long paths. The code itself is path-independent.

## Tests

```powershell
cd backend ; .venv\Scripts\python -m pytest -q      # 60 tests, no network, no paid API
cd frontend; npm run typecheck ; npm test ; npm run build
```

Backend tests use: an in-process MCP server (real protocol), scripted LLMs, a fake search provider, and the full demo
workflow through a real stdio subprocess. See [docs/architecture.md](docs/architecture.md#test-strategy).

## Configuration

All settings are environment variables (see [.env.example](.env.example)). Bounds: `RUN_TIMEOUT_SECONDS`,
`LLM_TIMEOUT_SECONDS`, `TOOL_TIMEOUT_SECONDS`, `MAX_RETRIES`, `MAX_QUERIES_PER_TASK`, `MAX_RESULTS_PER_QUERY`,
`MAX_ACTIVE_RUNS`. Models: `GEMINI_MODEL` (default `gemini-3.8-flash`), optional `VERIFIER_MODEL`.

## API

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Version and which modes are available (and why live is not) |
| `POST /api/runs` `{question, mode}` | Start a run → `202 {id}`; `409` live without keys; `429` too many runs |
| `GET /api/runs` / `GET /api/runs/{id}` | List runs / full persisted snapshot (plan, findings, sources, claims, report, verification) |
| `GET /api/runs/{id}/events` | SSE stream. Replays stored events, then follows live. Resumable via `?after=<seq>` or `Last-Event-ID` |
| `GET /demo/sources/{slug}` | Fixture pages that demo citations link to |

## What is and is not guaranteed

Guaranteed by code (and covered by tests):
- Sources enter only from real MCP tool results; each records URL, title, retrieval timestamp and the claims it supports.
- Tool events are emitted by the MCP client at the call site — “completed” only after a result was received and parsed.
- Report citations resolve against the source registry. Model-written URLs/titles are never used. Unknown claim IDs are
  stripped; claims whose quote is not found in the source text are excluded and reported.
- Retrieved text is sanitised, size-bounded, fenced as untrusted data, and injection-looking text is flagged.
- Timeouts and retry limits apply to every tool call, model call and the whole run.

Not guaranteed:
- That a *live* verifier's judgements are correct — it is an LLM. It is independent (own prompt, optional separate model,
  sees raw evidence not the writer's reasoning) but not infallible.
- That the search results are true; the report says what sources *said*.
- Prompt-injection defence is layered mitigation, not a proof.

## Verification status

| Item | Status |
|---|---|
| Backend unit/mocked/workflow/API tests (61) | ✅ pass |
| Frontend typecheck, 11 unit tests, production build | ✅ pass |
| Demo mode in a real browser (desktop + 375 px mobile) | ✅ checked manually |
| Run persisted, replayed after a backend restart | ✅ checked manually |
| Tavily MCP launch (`tavily-mcp@0.2.22`), tool discovery (`tavily_search` auto-selected) | ✅ run on 2026-10-26 (`scripts/check_live_mcp.py`) |
| Live end-to-end run: Gemini structured output + Tavily results parsed + report + verification, via CLI and via the HTTP API/SSE | ✅ completed 3 times on `gemini-3.5-flash-lite` (~30 s, 19–24 claims, 26–35 sources); a spot-check found sampled quotes match their statements |
| Live verifier catches bad statements | ✅ 3 of 3 injected false statements flagged (`scripts/probe_verifier.py`). **Tiny sample, not an evaluation.** |
| `gemini-3.8-flash` (the default) and `gemini-3.6-flash` | ⚠️ returned `503 high demand` on the test day (Google-side capacity); the app retried within bounds, reported each failure, and failed the run cleanly. Set `GEMINI_MODEL=gemini-3.5-flash-lite` (or `gemini-3.1-flash-lite`) if you hit this. |
| Live mode in the browser UI | ⚠️ not clicked through; same backend path as the verified API run |

## Layout

```
backend/src/researchlab/   config · schemas · registry · untrusted · events · store · service · graph · api
  mcp_client/              MCP client + parsing (no agent imports)
  llm/                     LLM protocol · Gemini adapter · scripted demo model
  agents/                  planner · researcher · synthesizer · verifier
  demo/                    fixtures.json (synthetic) + helpers
frontend/src/              app/ · components/ · lib/ (api, SSE hook, status derivation)
docs/architecture.md       design, decisions, risks, roadmap
```

Nothing in this repository has been pushed or deployed.
