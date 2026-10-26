"use client";

import { useCallback, useEffect, useState } from "react";
import { EvidencePanel } from "@/components/EvidencePanel";
import { QuestionPanel } from "@/components/QuestionPanel";
import { ReportView } from "@/components/ReportView";
import { AgentStatus, Timeline } from "@/components/Timeline";
import { Badge } from "@/components/ui";
import { getHealth, listRuns } from "@/lib/api";
import type { Health, RunSummary } from "@/lib/types";
import { useRun } from "@/lib/useRun";

type Tab = "workspace" | "report" | "evidence";

export default function Page() {
  const run = useRun();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [tab, setTab] = useState<Tab>("workspace");
  const [highlight, setHighlight] = useState<string | null>(null);

  const refreshHistory = useCallback(() => {
    listRuns().then(setHistory).catch(() => undefined);
  }, []);

  useEffect(() => {
    getHealth().then(setHealth).catch((e: Error) => setHealthError(e.message));
    refreshHistory();
  }, [refreshHistory]);

  const finished = run.snapshot?.status === "completed" || run.snapshot?.status === "failed";
  useEffect(() => {
    if (finished) refreshHistory();
  }, [finished, refreshHistory]);

  const running = !!run.runId && !finished && run.connection !== "lost";

  const jump = useCallback((id: string) => {
    setHighlight(id);
    document.getElementById(`source-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    window.setTimeout(() => setHighlight((h) => (h === id ? null : h)), 1700);
  }, []);

  const submit = async (q: string, mode: "live" | "demo") => {
    const id = await run.start(q, mode);
    if (id) {
      setTab("workspace");
      refreshHistory();
    }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "workspace", label: "Workspace" },
    { id: "report", label: "Report" },
    { id: "evidence", label: `Evidence${run.snapshot ? ` (${run.snapshot.sources.length})` : ""}` },
  ];
  // Three columns need room; below 1280px the sections become tabs.
  const show = (t: Tab) => (tab === t ? "block" : "hidden") + " xl:block";

  return (
    <div className="mx-auto flex min-h-dvh max-w-[1700px] flex-col px-4 pb-24 sm:px-6 xl:pb-8">
      <header className="flex items-center justify-between gap-4 py-5">
        <div className="flex items-center gap-3">
          <div
            aria-hidden
            className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-2 text-sm font-black text-bg"
          >
            R
          </div>
          <div>
            <h1 className="text-[15px] font-semibold leading-tight tracking-tight">ResearchLab AI</h1>
            <p className="text-[11px] text-faint">Planner · Researchers · Verifier</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {run.snapshot?.mode === "demo" && <Badge tone="warn">DEMO MODE</Badge>}
          {health ? (
            <Badge tone="ok">backend v{health.version}</Badge>
          ) : (
            <Badge tone={healthError ? "bad" : "neutral"}>{healthError ? "backend offline" : "connecting…"}</Badge>
          )}
        </div>
      </header>

      {healthError && (
        <p role="alert" className="mb-4 rounded-xl border border-bad/30 bg-bad/[0.07] px-4 py-3 text-sm text-bad">
          {healthError}
        </p>
      )}

      <main className="grid flex-1 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(290px,340px)_minmax(0,1fr)_minmax(290px,360px)]">
        <div className={`${show("workspace")} space-y-4`}>
          <QuestionPanel
            health={health}
            healthError={healthError}
            submitting={run.submitting}
            error={run.error}
            history={history}
            activeRunId={run.runId}
            onSubmit={submit}
            onOpen={(id) => {
              run.open(id);
              setTab("report");
            }}
          />
          <AgentStatus events={run.events} />
          <Timeline events={run.events} connection={run.connection} />
        </div>

        <div className={show("report")}>
          <ReportView snapshot={run.snapshot} running={running} onJump={jump} />
        </div>

        <div className={`${show("evidence")} xl:sticky xl:top-4`}>
          <EvidencePanel events={run.events} snapshot={run.snapshot} highlight={highlight} />
        </div>
      </main>

      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-3 border-t border-line bg-bg/90 backdrop-blur xl:hidden"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id}
            className={`py-3.5 text-sm font-medium ${tab === t.id ? "text-accent-2" : "text-mute"}`}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
