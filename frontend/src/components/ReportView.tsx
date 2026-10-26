"use client";

import { safeHref } from "@/lib/api";
import type { ReportStatement, RunSnapshot, Source, StatementVerdict } from "@/lib/types";
import { sourceNumber } from "./EvidencePanel";
import { Badge, Panel, VERDICT_META } from "./ui";

function Citations({
  ids,
  sources,
  onJump,
}: {
  ids: string[];
  sources: Map<string, Source>;
  onJump: (id: string) => void;
}) {
  return (
    <span className="ml-1 inline-flex gap-0.5 align-baseline">
      {ids.map((id) => {
        const s = sources.get(id);
        if (!s) return null;
        const href = safeHref(s.url);
        return (
          <a
            key={id}
            href={href ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            title={`${s.title} — ${s.url}`}
            onMouseEnter={() => onJump(id)}
            onFocus={() => onJump(id)}
            className="rounded bg-accent/15 px-1 font-mono text-[11px] leading-5 text-accent no-underline hover:bg-accent/30"
          >
            [{sourceNumber(id)}]
          </a>
        );
      })}
    </span>
  );
}

function Statement({
  st,
  verdict,
  sources,
  onJump,
}: {
  st: ReportStatement;
  verdict?: StatementVerdict;
  sources: Map<string, Source>;
  onJump: (id: string) => void;
}) {
  const meta = verdict ? VERDICT_META[verdict.verdict] : null;
  const flagged = verdict && ["unsupported", "conflicting", "partially_supported"].includes(verdict.verdict);
  return (
    <p
      className={`rounded-lg px-3 py-2 text-[15px] leading-relaxed text-ink/95 ${
        flagged ? "border-l-2 border-warn/60 bg-warn/[0.04]" : ""
      }`}
    >
      {st.text}
      <Citations ids={st.source_ids} sources={sources} onJump={onJump} />
      {meta && verdict && verdict.verdict !== "supported" && (
        <span className="ml-2 inline-block align-middle">
          <Badge tone={meta.tone} title={`${meta.hint} ${verdict.explanation}`}>
            {meta.label}
          </Badge>
        </span>
      )}
    </p>
  );
}

const OVERALL = {
  pass: { tone: "ok", text: "All evidence-checked statements are supported" },
  pass_with_warnings: { tone: "warn", text: "Verified with warnings" },
  fail: { tone: "bad", text: "Verification failed" },
} as const;

export function ReportView({
  snapshot,
  running,
  onJump,
}: {
  snapshot: RunSnapshot | null;
  running: boolean;
  onJump: (id: string) => void;
}) {
  if (!snapshot) {
    return (
      <Panel title="Report">
        <div className="flex min-h-64 flex-col items-center justify-center gap-2 p-8 text-center">
          <p className="text-sm text-mute">{running ? "Research in progress…" : "Your report appears here."}</p>
          <p className="max-w-sm text-xs text-faint">
            Reports cite only sources the tools actually retrieved, and an independent verifier checks every claim.
          </p>
        </div>
      </Panel>
    );
  }

  if (!snapshot.report) {
    return (
      <Panel title="Report">
        <div className="p-6" role="alert">
          <Badge tone={snapshot.status === "failed" ? "bad" : "accent"}>{snapshot.status}</Badge>
          <p className="mt-3 text-sm text-ink">
            {snapshot.status === "failed"
              ? "The run ended without a report."
              : "The report is being written…"}
          </p>
          {snapshot.error && <p className="mt-2 break-words font-mono text-xs text-bad">{snapshot.error}</p>}
          <p className="mt-3 text-xs text-faint">
            The timeline and evidence panels still show everything that happened before the run stopped.
          </p>
        </div>
      </Panel>
    );
  }

  const { report, verification } = snapshot;
  const sources = new Map(snapshot.sources.map((s) => [s.id, s]));
  const verdicts = new Map((verification?.verdicts ?? []).map((v) => [v.statement_id, v]));
  const overall = verification ? OVERALL[verification.overall] : null;
  const row = (st: ReportStatement) => (
    <Statement key={st.id} st={st} verdict={verdicts.get(st.id)} sources={sources} onJump={onJump} />
  );

  return (
    <Panel
      title="Report"
      right={
        <div className="flex items-center gap-1.5">
          {snapshot.mode === "demo" && <Badge tone="warn">DEMO · fixtures</Badge>}
          {overall && <Badge tone={overall.tone}>{overall.text}</Badge>}
        </div>
      }
    >
      <article className="space-y-7 p-5 sm:p-7">
        <header>
          <h1 className="text-balance text-2xl font-semibold leading-tight tracking-tight text-ink sm:text-[28px]">
            {report.title}
          </h1>
          <p className="mt-2 text-xs text-faint">
            {snapshot.stats.sources} sources · {snapshot.stats.claims} extracted claims · {snapshot.stats.tool_calls} tool
            calls · model <span className="font-mono">{snapshot.model}</span>
            {verification && (
              <>
                {" "}
                · verified by <span className="font-mono">{verification.verifier_model}</span>
              </>
            )}
          </p>
        </header>

        <section aria-labelledby="summary">
          <h2 id="summary" className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-accent-2">
            Executive summary
          </h2>
          <div className="space-y-1">{report.executive_summary.map(row)}</div>
        </section>

        {report.sections.map((sec) => (
          <section key={sec.heading}>
            <h2 className="mb-2 text-lg font-semibold text-ink">{sec.heading}</h2>
            <div className="space-y-1">{sec.statements.map(row)}</div>
          </section>
        ))}

        {report.recommendations.length > 0 && (
          <section>
            <h2 className="mb-2 text-lg font-semibold text-ink">Recommendations</h2>
            <div className="space-y-1">{report.recommendations.map(row)}</div>
          </section>
        )}

        {verification && (verification.conflicts.length > 0 || verification.missing_evidence.length > 0) && (
          <section className="rounded-xl border border-bad/25 bg-bad/[0.05] p-4">
            <h2 className="mb-2 text-sm font-semibold text-bad">Verifier findings</h2>
            {verification.conflicts.length > 0 && (
              <>
                <h3 className="text-xs font-medium uppercase tracking-wide text-mute">Conflicts</h3>
                <ul className="mb-2 list-disc pl-5 text-sm text-ink/90">
                  {verification.conflicts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            )}
            {verification.missing_evidence.length > 0 && (
              <>
                <h3 className="text-xs font-medium uppercase tracking-wide text-mute">Missing evidence</h3>
                <ul className="list-disc pl-5 text-sm text-ink/90">
                  {verification.missing_evidence.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        <section className="rounded-xl border border-warn/25 bg-warn/[0.05] p-4">
          <h2 className="mb-2 text-sm font-semibold text-warn">Limitations</h2>
          {report.limitations.length === 0 ? (
            <p className="text-sm text-mute">None reported.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink/90">
              {report.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          )}
        </section>

        <footer className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-4 text-[11px] text-faint">
          <span>
            <Badge tone="ok">Supported</Badge> evidence states it
          </span>
          <span>Unlabelled statements were verified as supported.</span>
          <span>
            <Badge>Judgement</Badge> not evidence-checked
          </span>
        </footer>
      </article>
    </Panel>
  );
}
