import { describe, expect, it } from "vitest";
import { safeHref } from "./api";
import { deriveAgents, mergeEvent } from "./status";
import type { EventType, RunEvent } from "./types";

let seq = 0;
const ev = (
  type: EventType,
  agent: string | null,
  task_id: string | null = null,
  data: Record<string, unknown> = {},
  message = type,
): RunEvent => ({
  run_id: "r",
  seq: ++seq,
  ts: new Date(1_700_000_000_000 + seq * 1000).toISOString(),
  type,
  agent,
  task_id,
  message,
  data,
});

const tasks = [
  { id: "t1", title: "Cost", objective: "o", search_queries: ["q"] },
  { id: "t2", title: "Risk", objective: "o", search_queries: ["q"] },
];

describe("deriveAgents", () => {
  it("is all idle before anything happens", () => {
    const { rows } = deriveAgents([]);
    expect(rows.map((r) => r.state)).toEqual(["idle", "idle", "idle"]);
  });

  it("marks an agent done only after agent_completed arrives", () => {
    const events = [ev("agent_started", "planner")];
    expect(deriveAgents(events).rows[0]?.state).toBe("running");
    events.push(ev("agent_completed", "planner", null, { tasks }));
    expect(deriveAgents(events).rows[0]?.state).toBe("done");
  });

  it("creates one researcher row per planned task and reflects each outcome", () => {
    const events = [
      ev("agent_completed", "planner", null, { tasks }),
      ev("agent_started", "researcher", "t1"),
      ev("agent_completed", "researcher", "t1", { status: "ok" }),
      ev("agent_started", "researcher", "t2"),
      ev("agent_completed", "researcher", "t2", { status: "no_results" }),
    ];
    const rows = deriveAgents(events).rows.filter((r) => r.key.startsWith("researcher-"));
    expect(rows.map((r) => [r.label, r.state])).toEqual([
      ["Researcher · Cost", "done"],
      ["Researcher · Risk", "warn"],
    ]);
  });

  it("shows running work as errored once the run has failed", () => {
    const events = [ev("agent_started", "synthesizer"), ev("run_failed", "system")];
    const row = deriveAgents(events).rows.find((r) => r.key === "synthesizer");
    expect(row?.state).toBe("error");
  });
});

describe("mergeEvent", () => {
  it("ignores duplicates and keeps seq order", () => {
    const a = ev("run_started", "system");
    const b = ev("agent_started", "planner");
    let list = mergeEvent([], b);
    list = mergeEvent(list, a);
    list = mergeEvent(list, a);
    expect(list.map((e) => e.seq)).toEqual([a.seq, b.seq]);
  });
});

describe("safeHref", () => {
  it("allows only http(s)", () => {
    expect(safeHref("https://example.com/a")).toBe("https://example.com/a");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>")).toBeNull();
    expect(safeHref("not a url")).toBeNull();
  });
});
