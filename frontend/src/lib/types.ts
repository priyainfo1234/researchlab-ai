// Mirrors backend/src/researchlab/schemas.py. The backend is the source of truth.

export type RunMode = "live" | "demo";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export type EventType =
  | "run_started"
  | "agent_started"
  | "agent_completed"
  | "handoff"
  | "llm_call_started"
  | "llm_call_completed"
  | "llm_call_failed"
  | "tool_call_started"
  | "tool_call_completed"
  | "tool_call_failed"
  | "source_recorded"
  | "warning"
  | "error"
  | "run_completed"
  | "run_failed";

export const EVENT_TYPES: EventType[] = [
  "run_started", "agent_started", "agent_completed", "handoff",
  "llm_call_started", "llm_call_completed", "llm_call_failed",
  "tool_call_started", "tool_call_completed", "tool_call_failed",
  "source_recorded", "warning", "error", "run_completed", "run_failed",
];

export const TERMINAL: EventType[] = ["run_completed", "run_failed"];

export interface RunEvent {
  run_id: string;
  seq: number;
  ts: string;
  type: EventType;
  agent: string | null;
  task_id: string | null;
  message: string;
  data: Record<string, unknown>;
}

export interface ResearchTask {
  id: string;
  title: string;
  objective: string;
  search_queries: string[];
}

export interface Source {
  id: string;
  url: string;
  title: string;
  retrieved_at: string;
  excerpt: string;
  found_by_tasks: string[];
  queries: string[];
  claim_ids: string[];
  flags: string[];
}

export interface Claim {
  id: string;
  task_id: string;
  text: string;
  evidence: { source_id: string; quote: string; quote_verified: boolean }[];
}

export interface TaskFinding {
  task_id: string;
  status: "ok" | "no_results" | "failed";
  claim_ids: string[];
  gaps: string[];
  error: string | null;
}

export interface ReportStatement {
  id: string;
  text: string;
  claim_ids: string[];
  source_ids: string[];
}

export interface Report {
  title: string;
  executive_summary: ReportStatement[];
  sections: { heading: string; statements: ReportStatement[] }[];
  limitations: string[];
  recommendations: ReportStatement[];
}

export type Verdict = "supported" | "partially_supported" | "unsupported" | "conflicting" | "inference";

export interface StatementVerdict {
  statement_id: string;
  verdict: Verdict;
  explanation: string;
  conflicting_source_ids: string[];
  checked_by: "code" | "llm";
}

export interface Verification {
  verdicts: StatementVerdict[];
  conflicts: string[];
  missing_evidence: string[];
  overall: "pass" | "pass_with_warnings" | "fail";
  verifier_model: string;
}

export interface RunSnapshot {
  run_id: string;
  question: string;
  mode: RunMode;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  model: string;
  plan: { tasks: ResearchTask[] } | null;
  findings: TaskFinding[];
  sources: Source[];
  claims: Claim[];
  report: Report | null;
  verification: Verification | null;
  stats: { tool_calls: number; tool_failures: number; llm_calls: number; sources: number; claims: number };
}

export interface RunSummary {
  id: string;
  question: string;
  mode: RunMode;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface Health {
  status: string;
  version: string;
  modes: {
    demo: { available: boolean; description: string; sample_question: string };
    live: { available: boolean; reasons: string[]; model: string };
  };
}
