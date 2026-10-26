"use client";

import { useEffect, useState } from "react";
import type { Health, RunMode, RunSummary } from "@/lib/types";
import { Badge, Panel } from "./ui";

export function QuestionPanel({
  health,
  healthError,
  submitting,
  error,
  history,
  activeRunId,
  onSubmit,
  onOpen,
}: {
  health: Health | null;
  healthError: string | null;
  submitting: boolean;
  error: string | null;
  history: RunSummary[];
  activeRunId: string | null;
  onSubmit: (question: string, mode: RunMode) => void;
  onOpen: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<RunMode>("demo");
  const sample = health?.modes.demo.sample_question;
  useEffect(() => {
    // Demo is the default mode, so offer its sample question once the backend answers.
    if (sample) setQuestion((q) => q || sample);
  }, [sample]);
  const live = health?.modes.live;
  const liveBlocked = !live?.available;

  const choose = (m: RunMode) => {
    setMode(m);
    if (m === "demo" && health && !question.trim()) setQuestion(health.modes.demo.sample_question);
  };

  const canSubmit = question.trim().length >= 8 && !submitting && (mode === "demo" || !liveBlocked);

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Research question">
        <form
          className="flex flex-col gap-3 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) onSubmit(question.trim(), mode);
          }}
        >
          <div role="radiogroup" aria-label="Mode" className="grid grid-cols-2 gap-1 rounded-xl border border-line bg-bg/60 p-1">
            {(["demo", "live"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => choose(m)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  mode === m ? "bg-raised text-ink shadow-inner" : "text-mute hover:text-ink"
                }`}
              >
                {m === "demo" ? "Demo" : "Live research"}
              </button>
            ))}
          </div>

          {mode === "demo" ? (
            <p className="rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-xs leading-relaxed text-warn">
              <strong>Demo mode.</strong> Uses synthetic fixture documents and a scripted stand-in for the model.
              It exercises the real workflow and MCP plumbing but performs no web research.
            </p>
          ) : liveBlocked ? (
            <p className="rounded-lg border border-bad/25 bg-bad/[0.06] px-3 py-2 text-xs leading-relaxed text-bad">
              {healthError ?? `Live mode unavailable: ${live?.reasons.join("; ") || "checking…"}. Add keys to backend/.env.`}
            </p>
          ) : (
            <p className="text-xs text-mute">
              Live: web search via MCP, reasoning by <span className="font-mono">{live?.model}</span>.
            </p>
          )}

          <label className="sr-only" htmlFor="q">Research question</label>
          <textarea
            id="q"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={600}
            rows={4}
            placeholder="Ask a question that needs several angles of research…"
            className="w-full resize-y rounded-xl border border-line bg-bg/60 px-3 py-2.5 text-sm text-ink placeholder:text-faint focus:border-accent/60 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-xl bg-gradient-to-r from-accent to-accent-2 px-4 py-2.5 text-sm font-semibold text-bg shadow-lg shadow-accent/20 transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Starting…" : mode === "demo" ? "Run demo" : "Start research"}
          </button>
          {error && (
            <p role="alert" className="text-xs text-bad">
              {error}
            </p>
          )}
        </form>
      </Panel>

      <Panel title="Recent runs" right={<span className="text-[11px] text-faint">{history.length}</span>}>
        {history.length === 0 ? (
          <p className="p-4 text-xs text-faint">No runs yet.</p>
        ) : (
          <ul className="scroll-thin max-h-64 divide-y divide-line overflow-y-auto">
            {history.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => onOpen(r.id)}
                  aria-current={r.id === activeRunId}
                  className={`flex w-full flex-col gap-1 px-4 py-2.5 text-left transition hover:bg-white/[0.03] ${
                    r.id === activeRunId ? "bg-white/[0.04]" : ""
                  }`}
                >
                  <span className="line-clamp-2 text-[13px] text-ink">{r.question}</span>
                  <span className="flex items-center gap-1.5">
                    <Badge tone={r.status === "completed" ? "ok" : r.status === "failed" ? "bad" : "accent"}>
                      {r.status}
                    </Badge>
                    <Badge>{r.mode}</Badge>
                    <span className="text-[11px] text-faint">{new Date(r.created_at).toLocaleString()}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
