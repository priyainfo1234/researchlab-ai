import type { ResearchTask, RunEvent } from "./types";

export type AgentState = "idle" | "running" | "done" | "warn" | "error";

export interface AgentRow {
  key: string;
  label: string;
  detail: string;
  state: AgentState;
}

/**
 * Derive per-agent status purely from streamed events. Nothing is assumed: an agent is
 * "done" only after an agent_completed event for it was received.
 */
export function deriveAgents(events: RunEvent[]): { rows: AgentRow[]; tasks: ResearchTask[] } {
  const failed = events.some((e) => e.type === "run_failed");
  let tasks: ResearchTask[] = [];
  const planDone = events.find((e) => e.type === "agent_completed" && e.agent === "planner");
  if (planDone && Array.isArray(planDone.data.tasks)) tasks = planDone.data.tasks as ResearchTask[];

  const simple = (agent: string, label: string): AgentRow => {
    const started = events.some((e) => e.type === "agent_started" && e.agent === agent);
    const done = events.some((e) => e.type === "agent_completed" && e.agent === agent);
    const errored = events.some((e) => e.type === "error" && e.agent === agent);
    let state: AgentState = "idle";
    if (done) state = events.some((e) => e.type === "warning" && e.agent === agent) ? "warn" : "done";
    else if (errored) state = "error";
    else if (started) state = failed ? "error" : "running";
    const last = [...events].reverse().find((e) => e.agent === agent);
    return { key: agent, label, detail: last?.message ?? "Waiting", state };
  };

  const rows: AgentRow[] = [simple("planner", "Planner")];
  for (const t of tasks) {
    const mine = events.filter((e) => e.task_id === t.id && e.agent === "researcher");
    const started = mine.some((e) => e.type === "agent_started");
    const completed = mine.find((e) => e.type === "agent_completed");
    const hadError = mine.some((e) => e.type === "error");
    let state: AgentState = "idle";
    if (completed) {
      const status = completed.data.status;
      state = hadError || status === "failed" ? "error" : status === "no_results" ? "warn" : "done";
    } else if (started) state = failed ? "error" : "running";
    rows.push({
      key: `researcher-${t.id}`,
      label: `Researcher · ${t.title}`,
      detail: mine[mine.length - 1]?.message ?? "Waiting",
      state,
    });
  }
  rows.push(simple("synthesizer", "Synthesizer"), simple("verifier", "Verifier"));
  return { rows, tasks };
}

export function elapsedMs(events: RunEvent[], e: RunEvent): number {
  const first = events[0];
  return first ? new Date(e.ts).getTime() - new Date(first.ts).getTime() : 0;
}

/** Insert an event keeping seq order and dropping duplicates (SSE replays after reconnect). */
export function mergeEvent(events: RunEvent[], ev: RunEvent): RunEvent[] {
  if (events.some((e) => e.seq === ev.seq)) return events;
  const next = [...events, ev];
  next.sort((a, b) => a.seq - b.seq);
  return next;
}
