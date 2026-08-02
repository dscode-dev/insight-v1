"use client";

import { useOps, arr, Card, Empty, ErrorBanner, PageHeader, Pill } from "@/components/console/ops-shared";
import { ShieldAlert } from "lucide-react";

export function OperationalIncidents() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/ops/tickets?limit=100",
    "/api/v1/ops/events?limit=200",
  ]);
  const tickets = arr(data.tickets, "tickets").filter((ticket) => String(ticket.status ?? "open") !== "resolved");
  const failures = arr(data.events, "events").filter((event) =>
    /error|critical|failed|degraded/i.test(`${event.severity ?? ""} ${event.status ?? ""} ${event.event_type ?? ""}`),
  );
  return <div className="space-y-5">
    <PageHeader icon={ShieldAlert} title="Operational Overview" subtitle="Incidents, failures, degraded services and active alerts" updated={updated} onRefresh={refresh} />
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <div className="grid gap-3 sm:grid-cols-3">
      <Card title="Open incidents"><strong className="font-mono text-2xl">{tickets.length}</strong></Card>
      <Card title="Recent failures"><strong className="font-mono text-2xl">{failures.length}</strong></Card>
      <Card title="Critical"><strong className="font-mono text-2xl">{[...tickets, ...failures].filter((row) => /critical/i.test(String(row.severity))).length}</strong></Card>
    </div>
    <Card title="Needs attention">
      {![...tickets, ...failures].length ? <Empty>No active incidents reported.</Empty> : [...tickets, ...failures].slice(0, 50).map((row, index) =>
        <details key={String(row.ticket_id ?? row.event_id ?? index)} className="border-b border-border/50 py-2 last:border-0">
          <summary className="cursor-pointer text-sm"><Pill value={String(row.severity ?? row.status ?? "warning")} /> <span className="ml-2">{String(row.reason ?? row.message ?? row.event_type)}</span></summary>
          <pre className="mt-2 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify(row, null, 2)}</pre>
        </details>)}
    </Card>
  </div>;
}
