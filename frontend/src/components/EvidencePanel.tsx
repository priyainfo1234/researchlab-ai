"use client";

import { safeHref } from "@/lib/api";
import type { Claim, RunEvent, RunSnapshot, Source } from "@/lib/types";
import { Badge, Panel } from "./ui";

/** Sources recorded so far: from the snapshot when finished, else from streamed events. */
function liveSources(events: RunEvent[]): Source[] {
  return events
    .filter((e) => e.type === "source_recorded")
    .map((e) => ({
      id: String(e.data.source_id),
      url: String(e.data.url),
      title: String(e.data.title),
      retrieved_at: String(e.data.retrieved_at),
      excerpt: "",
      found_by_tasks: e.task_id ? [e.task_id] : [],
      queries: [],
      claim_ids: [],
      flags: [],
    }));
}

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function sourceNumber(id: string): string {
  return id.replace(/^s/, "");
}

export function EvidencePanel({
  events,
  snapshot,
  highlight,
}: {
  events: RunEvent[];
  snapshot: RunSnapshot | null;
  highlight: string | null;
}) {
  const sources = snapshot?.sources.length ? snapshot.sources : liveSources(events);
  const claims = new Map<string, Claim>((snapshot?.claims ?? []).map((c) => [c.id, c]));
  const flaggedIds = new Set(
    (snapshot?.verification?.verdicts ?? [])
      .filter((v) => v.verdict === "conflicting")
      .flatMap((v) => [...v.conflicting_source_ids]),
  );

  return (
    <Panel
      title="Evidence"
      right={<span className="text-[11px] text-faint">{sources.length} sources</span>}
      className="min-h-0"
    >
      {sources.length === 0 ? (
        <p className="p-4 text-xs text-faint">
          Every source is listed here with its URL, retrieval time and the claims it supports. Nothing appears until a
          tool call actually returns it.
        </p>
      ) : (
        <ol className="scroll-thin max-h-[70vh] divide-y divide-line overflow-y-auto">
          {sources.map((s) => {
            const href = safeHref(s.url);
            return (
              <li
                key={s.id}
                id={`source-${s.id}`}
                className={`px-4 py-3 ${highlight === s.id ? "flash" : ""}`}
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-md bg-raised px-1 font-mono text-[11px] text-accent">
                    {sourceNumber(s.id)}
                  </span>
                  <div className="min-w-0 flex-1">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-[13px] font-medium leading-snug text-ink underline-offset-2 hover:text-accent-2 hover:underline"
                      >
                        {s.title}
                      </a>
                    ) : (
                      <span className="block text-[13px] font-medium text-ink">{s.title}</span>
                    )}
                    <span className="block truncate font-mono text-[11px] text-faint">{host(s.url)}</span>
                    <span className="block text-[11px] text-faint">
                      Retrieved {new Date(s.retrieved_at).toLocaleTimeString()}
                      {s.found_by_tasks.length > 0 && ` · by ${s.found_by_tasks.join(", ")}`}
                    </span>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {s.flags.includes("possible_prompt_injection") && (
                        <Badge tone="warn" title="This page contained text that looks like an instruction to an AI. It was treated as data.">
                          injection-like text
                        </Badge>
                      )}
                      {flaggedIds.has(s.id) && <Badge tone="bad">in conflict</Badge>}
                    </div>
                    {s.claim_ids.length > 0 && (
                      <ul className="mt-2 space-y-1.5">
                        {s.claim_ids.map((cid) => {
                          const c = claims.get(cid);
                          if (!c) return null;
                          const ev = c.evidence.find((x) => x.source_id === s.id);
                          return (
                            <li key={cid} className="rounded-lg border border-line bg-bg/50 px-2.5 py-1.5">
                              <span className="block text-xs leading-snug text-ink">{c.text}</span>
                              {ev && (
                                <span className="mt-1 block border-l-2 border-accent/40 pl-2 text-[11px] italic leading-snug text-mute">
                                  “{ev.quote}”
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
