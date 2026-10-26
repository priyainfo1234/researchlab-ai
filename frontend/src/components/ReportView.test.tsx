import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportView } from "./ReportView";
import type { RunSnapshot } from "@/lib/types";

const base: RunSnapshot = {
  run_id: "r1",
  question: "q",
  mode: "live",
  status: "completed",
  created_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:01:00Z",
  error: null,
  model: "m",
  plan: null,
  findings: [],
  sources: [
    {
      id: "s1", url: "https://example.test/a", title: "Example A", retrieved_at: "2026-01-01T00:00:30Z",
      excerpt: "x", found_by_tasks: ["t1"], queries: ["q"], claim_ids: ["c1"], flags: [],
    },
    {
      id: "s2", url: "javascript:alert(1)", title: "Bad", retrieved_at: "2026-01-01T00:00:30Z",
      excerpt: "x", found_by_tasks: ["t1"], queries: ["q"], claim_ids: [], flags: [],
    },
  ],
  claims: [],
  report: {
    title: "A Report",
    executive_summary: [{ id: "r1", text: "Summary text.", claim_ids: ["c1"], source_ids: ["s1"] }],
    sections: [{ heading: "Findings", statements: [{ id: "r2", text: "Disputed text.", claim_ids: ["c1"], source_ids: ["s1", "s2"] }] }],
    limitations: ["Nothing about Z was found."],
    recommendations: [],
  },
  verification: {
    verdicts: [
      { statement_id: "r1", verdict: "supported", explanation: "ok", conflicting_source_ids: [], checked_by: "llm" },
      { statement_id: "r2", verdict: "conflicting", explanation: "sources disagree", conflicting_source_ids: ["s2"], checked_by: "llm" },
    ],
    conflicts: ["A disagrees with B"],
    missing_evidence: [],
    overall: "pass_with_warnings",
    verifier_model: "checker",
  },
  stats: { tool_calls: 2, tool_failures: 0, llm_calls: 4, sources: 2, claims: 1 },
};

describe("ReportView", () => {
  it("renders citations as external links to the recorded source URLs", () => {
    render(<ReportView snapshot={base} running={false} onJump={() => {}} />);
    const link = screen.getAllByRole("link", { name: "[1]" })[0]!;
    expect(link).toHaveAttribute("href", "https://example.test/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("never turns a non-http source URL into a working link", () => {
    render(<ReportView snapshot={base} running={false} onJump={() => {}} />);
    const bad = screen.getByRole("link", { name: "[2]" });
    expect(bad.getAttribute("href")).toBe("#");
  });

  it("surfaces verifier conflicts, flagged statements and limitations", () => {
    render(<ReportView snapshot={base} running={false} onJump={() => {}} />);
    expect(screen.getByText("A disagrees with B")).toBeInTheDocument();
    expect(screen.getByText("Conflict")).toBeInTheDocument();
    expect(screen.getByText("Nothing about Z was found.")).toBeInTheDocument();
    expect(screen.getByText("Verified with warnings")).toBeInTheDocument();
  });

  it("labels demo reports", () => {
    render(<ReportView snapshot={{ ...base, mode: "demo" }} running={false} onJump={() => {}} />);
    expect(screen.getByText(/DEMO/)).toBeInTheDocument();
  });

  it("shows the error and no report for a failed run", () => {
    const failed = { ...base, report: null, verification: null, status: "failed" as const, error: "No verifiable evidence" };
    render(<ReportView snapshot={failed} running={false} onJump={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No verifiable evidence");
  });
});
