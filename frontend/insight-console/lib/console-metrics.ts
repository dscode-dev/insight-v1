// Console operational metrics — Sprint 4.5 Part 17.
//
// In-process labeled counters rendered as Prometheus text exposition
// at GET /api/metrics. No client library: the Console runs as a
// single Next.js server process and only needs counters, so a Map is
// the whole implementation. (Multi-replica deployments would need
// per-pod scraping — noted in CONSOLE_ARCHITECTURE_AUDIT.md.)
//
// `globalThis` anchoring survives Next.js dev-mode module reloads so
// counters don't silently reset between recompiles.

type LabelValues = Record<string, string>;

interface CounterStore {
  /** name → help text */
  help: Map<string, string>;
  /** name → serialized labels → value */
  values: Map<string, Map<string, number>>;
}

const g = globalThis as typeof globalThis & {
  __consoleMetrics?: CounterStore;
};

function store(): CounterStore {
  if (!g.__consoleMetrics) {
    g.__consoleMetrics = { help: new Map(), values: new Map() };
  }
  return g.__consoleMetrics;
}

function register(name: string, help: string): void {
  const s = store();
  if (!s.help.has(name)) {
    s.help.set(name, help);
    s.values.set(name, new Map());
  }
}

function serializeLabels(labels: LabelValues): string {
  const keys = Object.keys(labels).sort();
  if (keys.length === 0) return "";
  const parts = keys.map(
    (k) =>
      `${k}="${(labels[k] ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`,
  );
  return `{${parts.join(",")}}`;
}

export function incCounter(name: string, labels: LabelValues = {}): void {
  const s = store();
  const series = s.values.get(name);
  if (!series) return; // unregistered — refuse to invent metrics
  const key = serializeLabels(labels);
  series.set(key, (series.get(key) ?? 0) + 1);
}

/** Prometheus text exposition format (0.0.4). */
export function renderMetrics(): string {
  const s = store();
  const lines: string[] = [];
  for (const [name, help] of s.help) {
    lines.push(`# HELP ${name} ${help}`);
    lines.push(`# TYPE ${name} counter`);
    const series = s.values.get(name) ?? new Map<string, number>();
    if (series.size === 0) {
      lines.push(`${name} 0`);
      continue;
    }
    for (const [labelKey, value] of series) {
      lines.push(`${name}${labelKey} ${value}`);
    }
  }
  return lines.join("\n") + "\n";
}

/** Test hook — zeroes all series but keeps registrations (they only
 * happen at module import, so wiping them would brick the registry). */
export function resetMetrics(): void {
  const s = store();
  for (const series of s.values.values()) {
    series.clear();
  }
}

// ---- Sprint 4.5 metric set ---------------------------------------------------------

register(
  "console_ticket_reviews_total",
  "Ticket review actions performed through the Console (label: action).",
);
register(
  "console_publications_total",
  "Publications triggered through the Console (ticket publishes).",
);
register(
  "console_manual_publications_total",
  "Manual publications authored through the Console (label: agent).",
);
register(
  "console_agent_changes_total",
  "Agent enable/disable/persona changes (label: action).",
);
register(
  "console_provider_incidents_total",
  "LLM provider offline incidents observed by the Console (label: provider).",
);
register(
  "console_audit_events_total",
  "Console-origin audit events recorded in Nexus.",
);

export const ConsoleMetric = {
  ticketReview: (action: string) =>
    incCounter("console_ticket_reviews_total", { action }),
  publication: () => incCounter("console_publications_total"),
  manualPublication: (agent: string) =>
    incCounter("console_manual_publications_total", { agent }),
  agentChange: (action: string) =>
    incCounter("console_agent_changes_total", { action }),
  providerIncident: (provider: string) =>
    incCounter("console_provider_incidents_total", { provider }),
  auditEvent: () => incCounter("console_audit_events_total"),
} as const;
