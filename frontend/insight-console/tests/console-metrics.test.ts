// Sprint 4.5 Part 17 — Prometheus text rendering + label hygiene.

import { beforeEach, describe, expect, it } from "vitest";

// resetMetrics() wipes the registry, so re-import per test file is
// unnecessary — the module re-registers at import time only.
import { ConsoleMetric, incCounter, renderMetrics, resetMetrics } from "@/lib/console-metrics";

describe("console metrics", () => {
  beforeEach(() => {
    resetMetrics();
  });

  it("renders all six Sprint 4.5 counter families", () => {
    const text = renderMetrics();
    for (const family of [
      "console_ticket_reviews_total",
      "console_publications_total",
      "console_manual_publications_total",
      "console_agent_changes_total",
      "console_provider_incidents_total",
      "console_audit_events_total",
    ]) {
      expect(text).toContain(`# TYPE ${family} counter`);
    }
  });

  it("counts labeled increments independently", () => {
    ConsoleMetric.ticketReview("approved");
    ConsoleMetric.ticketReview("approved");
    ConsoleMetric.ticketReview("rejected");
    const text = renderMetrics();
    expect(text).toContain('console_ticket_reviews_total{action="approved"} 2');
    expect(text).toContain('console_ticket_reviews_total{action="rejected"} 1');
  });

  it("ignores unregistered metric names (no metric invention)", () => {
    incCounter("console_made_up_total", {});
    expect(renderMetrics()).not.toContain("console_made_up_total");
  });

  it("escapes label values", () => {
    ConsoleMetric.manualPublication('agent"with"quotes');
    expect(renderMetrics()).toContain('agent\\"with\\"quotes');
  });

  it("tracks every Sprint 4.5 family through the typed helpers", () => {
    ConsoleMetric.publication();
    ConsoleMetric.manualPublication("ninja");
    ConsoleMetric.agentChange("disable");
    ConsoleMetric.providerIncident("qwen-local");
    ConsoleMetric.auditEvent();
    const text = renderMetrics();
    expect(text).toContain("console_publications_total 1");
    expect(text).toContain('console_manual_publications_total{agent="ninja"} 1');
    expect(text).toContain('console_agent_changes_total{action="disable"} 1');
    expect(text).toContain('console_provider_incidents_total{provider="qwen-local"} 1');
    expect(text).toContain("console_audit_events_total 1");
  });
});
