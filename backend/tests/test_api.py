import json

import httpx
import pytest

from researchlab.api import create_app
from researchlab.schemas import TERMINAL_EVENTS

from .conftest import make_settings

SECRET = "sk-test-SECRET-do-not-leak"
Q = "What are the trade-offs between RAG and fine-tuning?"


@pytest.fixture
async def client():
    app = create_app(make_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, app


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if line.startswith(":") or ":" not in line:
                continue
            k, _, v = line.partition(":")
            fields[k] = v.lstrip()
        if "data" in fields:
            events.append({"id": fields.get("id"), "event": fields.get("event"), **json.loads(fields["data"])})
    return events


async def test_health_reports_modes_and_why_live_is_unavailable(client):
    c, _ = client
    body = (await c.get("/api/health")).json()
    assert body["modes"]["demo"]["available"] is True
    assert body["modes"]["live"]["available"] is False
    assert "GEMINI_API_KEY is not set" in body["modes"]["live"]["reasons"]


async def test_live_run_rejected_with_409_when_keys_missing(client):
    c, _ = client
    r = await c.post("/api/runs", json={"question": Q, "mode": "live"})
    assert r.status_code == 409 and "Live mode is unavailable" in r.json()["detail"]


async def test_validation_errors(client):
    c, _ = client
    assert (await c.post("/api/runs", json={"question": "short", "mode": "demo"})).status_code == 422
    assert (await c.post("/api/runs", json={"question": Q, "mode": "bogus"})).status_code == 422
    assert (await c.get("/api/runs/nope")).status_code == 404
    assert (await c.get("/api/runs/nope/events")).status_code == 404


async def test_demo_run_streams_events_and_can_be_inspected_afterwards(client):
    c, app = client
    r = await c.post("/api/runs", json={"question": Q, "mode": "demo"})
    assert r.status_code == 202
    run_id = r.json()["id"]

    async with c.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = (await resp.aread()).decode()
    streamed = parse_sse(text)
    assert streamed[0]["type"] == "run_started" and streamed[-1]["type"] == "run_completed"
    assert [e["seq"] for e in streamed] == list(range(1, len(streamed) + 1))

    # after completion: snapshot is persisted and complete
    snap = (await c.get(f"/api/runs/{run_id}")).json()
    assert snap["status"] == "completed" and snap["report"] and snap["verification"]
    assert snap["mode"] == "demo" and snap["sources"]

    # replay from the start gives the same events; resume skips what the client has
    async with c.stream("GET", f"/api/runs/{run_id}/events") as resp:
        replay = parse_sse((await resp.aread()).decode())
    assert [e["seq"] for e in replay] == [e["seq"] for e in streamed]
    async with c.stream("GET", f"/api/runs/{run_id}/events?after=10") as resp:
        tail = parse_sse((await resp.aread()).decode())
    assert tail[0]["seq"] == 11 and tail[-1]["type"] in {t.value for t in TERMINAL_EVENTS}

    listing = (await c.get("/api/runs")).json()
    assert listing[0]["id"] == run_id and listing[0]["status"] == "completed"


async def test_demo_source_pages_are_served_and_escaped(client):
    c, _ = client
    r = await c.get("/demo/sources/rag-grounding")
    assert r.status_code == 200 and "DEMO FIXTURE" in r.text
    assert (await c.get("/demo/sources/../etc/passwd")).status_code == 404


async def test_secrets_never_appear_in_api_output():
    app = create_app(make_settings(gemini_api_key=SECRET, tavily_api_key=SECRET))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            health = (await c.get("/api/health")).text
            run_id = (await c.post("/api/runs", json={"question": Q, "mode": "demo"})).json()["id"]
            await app.state.service.wait(run_id)
            snap = (await c.get(f"/api/runs/{run_id}")).text
            async with c.stream("GET", f"/api/runs/{run_id}/events") as resp:
                events = (await resp.aread()).decode()
    assert SECRET not in health + snap + events
    assert '"available":true' in health.replace(" ", "")
