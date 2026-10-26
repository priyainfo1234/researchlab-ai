import type { ReactNode } from "react";
import type { AgentState } from "@/lib/status";
import type { Verdict } from "@/lib/types";

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-line bg-surface/80 backdrop-blur ${className}`}>
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mute">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}

const TONES = {
  neutral: "border-line text-mute bg-white/[0.03]",
  ok: "border-ok/30 text-ok bg-ok/10",
  warn: "border-warn/30 text-warn bg-warn/10",
  bad: "border-bad/30 text-bad bg-bad/10",
  accent: "border-accent/30 text-accent bg-accent/10",
} as const;

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: keyof typeof TONES;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-5 ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

const DOT: Record<AgentState, string> = {
  idle: "bg-faint/60",
  running: "bg-accent pulse-ring",
  done: "bg-ok",
  warn: "bg-warn",
  error: "bg-bad",
};

export function StateDot({ state }: { state: AgentState }) {
  return <span aria-label={state} className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[state]}`} />;
}

export const VERDICT_META: Record<Verdict, { label: string; tone: keyof typeof TONES; hint: string }> = {
  supported: { label: "Supported", tone: "ok", hint: "Evidence states this." },
  partially_supported: { label: "Partial", tone: "warn", hint: "Evidence covers only part of this." },
  unsupported: { label: "Unsupported", tone: "bad", hint: "Evidence does not say this." },
  conflicting: { label: "Conflict", tone: "bad", hint: "Other evidence contradicts this." },
  inference: { label: "Judgement", tone: "neutral", hint: "Not evidence-checked; the system's own inference." },
};
