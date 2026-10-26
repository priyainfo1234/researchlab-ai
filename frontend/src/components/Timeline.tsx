"use client";

import { useEffect, useRef, useState } from "react";
import { deriveAgents, elapsedMs } from "@/lib/status";
import type { Connection } from "@/lib/useRun";
import type { EventType, RunEvent } from "@/lib/types";
import { Badge, Panel, StateDot } from "./ui";

const ICON: Partial<Record<EventType, string>> = {
  run_started: "▶",
  agent_started: "●",
  agent_completed: "✓",
  handoff: "→",
  llm_call_started: "◇",
  llm_call_completed: "◆",
  llm_call_failed: "✕",
  tool_call_started: "⚙",
  tool_call_completed: "⚙",
  tool_call_failed: "⚠",
  source_recorded: "❡",
  warning: "!",
  error: "✕",
  run_completed: "■",
  run_failed: "■",
};

const TONE: Partial<Record<EventType, string>> = {
  tool_call_failed: "text-bad",
  llm_call_failed: "text-bad",
  error: "text-bad",
  run_failed: "text-bad",
  warning: "text-warn",
  run_completed: "text-ok",
  agent_completed: "text-ok",
  tool_call_completed: "text-accent-2",
  tool_call_started: "text-accent-2",
  handoff: "text-accent",
  source_recorded: "text-ink",
};

type Filter = "all" | "tools" | "issues";

function matches(f: Filter, e: RunEvent): boolean {
  if (f === "all") return true;
  if (f === "tools") return e.type.startsWith("tool_call") || e.type === "source_recorded";
  return ["warning", "error", "tool_call_failed", "llm_call_failed", "run_failed"].includes(e.type);
}

function detail(e: RunEvent): string | null {
  const d = e.data;
  const bits: string[] = [];
  if (typeof d.attempt === "number" && d.attempt > 1) bits.push(`attempt ${d.attempt}`);
  if (typeof d.duration_ms === "number") bits.push(`${d.duration_ms} ms`);
  if (typeof d.results === "number") bits.push(`${d.results} results`);
  if (typeof d.error === "string") bits.push(d.error);
  if (typeof d.url === "string") bits.push(d.url);
  return bits.length ? bits.join(" · ") : null;
}

export function AgentStatus({ events }: { events: RunEvent[] }) {
  const { rows } = deriveAgents(events);
  return (
    <Panel title="Agents">
      <ul className="divide-y divide-line">
        {rows.map((r) => (
          <li key={r.key} className="flex items-start gap-3 px-4 py-2.5">
            <span className="mt-1.5">
              <StateDot state={r.state} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-ink">{r.label}</span>
              <span className="block truncate text-[11px] text-faint">{r.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function Timeline({ events, connection }: { events: RunEvent[]; connection: Connection }) {
  const [filter, setFilter] = useState<Filter>("all");
  const listRef = useRef<HTMLOListElement>(null);
  const shown = events.filter((e) => matches(filter, e));

  useEffect(() => {
    // Scroll only the list itself; scrollIntoView would also scroll the whole page.
    const el = listRef.current;
    if (el && connection === "streaming") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [events.length, connection]);

  return (
    <Panel
      title="Execution timeline"
      right={
        <div className="flex items-center gap-2">
          <Badge tone={connection === "streaming" ? "accent" : connection === "lost" ? "bad" : "neutral"}>
            {connection === "streaming" ? "live" : connection}
          </Badge>
          <div role="group" aria-label="Filter events" className="flex rounded-lg border border-line p-0.5 text-[11px]">
            {(["all", "tools", "issues"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className={`rounded-md px-2 py-0.5 capitalize ${filter === f ? "bg-raised text-ink" : "text-mute hover:text-ink"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      }
    >
      {events.length === 0 ? (
        <p className="p-4 text-xs text-faint">Events appear here as the workflow runs.</p>
      ) : (
        <ol ref={listRef} className="scroll-thin max-h-[28rem] overflow-y-auto py-1" aria-live="polite">
          {shown.map((e) => {
            const d = detail(e);
            return (
              <li key={e.seq} className="flex gap-3 px-4 py-1.5 hover:bg-white/[0.02]">
                <span className={`mt-0.5 w-4 shrink-0 text-center text-xs ${TONE[e.type] ?? "text-faint"}`} aria-hidden>
                  {ICON[e.type] ?? "·"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-[13px] leading-snug text-ink">{e.message}</span>
                  <span className="flex flex-wrap items-center gap-x-2 text-[11px] text-faint">
                    <span className="font-mono">+{(elapsedMs(events, e) / 1000).toFixed(1)}s</span>
                    {e.agent && <span>{e.agent}</span>}
                    {e.task_id && <span className="font-mono">{e.task_id}</span>}
                    <span className="font-mono opacity-70">{e.type}</span>
                  </span>
                  {d && <span className="mt-0.5 block break-all font-mono text-[11px] text-mute">{d}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
