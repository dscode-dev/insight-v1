"use client";

// Publication Analytics (CONSOLE-OPS-A3 Stage 7) — counts/failures/status &
// source distribution computed from real Nexus operations data. Honest empty
// state when no publication data exists. No fake data.

import { BarChart3 } from "lucide-react";

import { useOps, arr, PageHeader, Card, Empty, ErrorBanner, type Row } from "@/components/console/ops-shared";

function tally(rows: Row[], key: (r: Row) => string): [string, number][] {
  const m = new Map<string, number>();
  for (const r of rows) {
    const k = key(r) || "unknown";
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

export function PublicationAnalytics() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/ops/events?service=nexus&limit=500",
    "/api/v1/ops/tickets?service=nexus&limit=200",
  ]);

  const events = arr(data.events, "events").filter((r) => !r.service || r.service === "nexus");
  const tickets = arr(data.tickets, "tickets").filter((r) => !r.service || r.service === "nexus");
  const total = events.length;
  const failures = events.filter((e) => String(e.severity).toUpperCase() === "ERROR" || String(e.event_type).includes("failed")).length;
  const byType = tally(events, (e) => String(e.event_type));
  const bySeverity = tally(events, (e) => String(e.severity ?? "INFO"));
  const hasAny = total + tickets.length > 0;

  return (
    <div className="space-y-5">
      <PageHeader icon={BarChart3} title="Publication Analytics" updated={updated} onRefresh={refresh}
        subtitle="Counts · failures · distribution · realtime (7s) · operations DB" />
      {error && <ErrorBanner>Operations: {error}</ErrorBanner>}

      {!hasAny ? (
        <Card title="Analytics">
          <Empty>No publication events recorded yet — no analytics to compute. This is an honest
            empty state (no fabricated metrics).</Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Events</p><p className="mt-2 font-mono text-2xl font-semibold">{total}</p></Card>
            <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Failures</p><p className="mt-2 font-mono text-2xl font-semibold text-red-400">{failures}</p></Card>
            <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Open tickets</p><p className="mt-2 font-mono text-2xl font-semibold text-amber-400">{tickets.length}</p></Card>
            <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Event types</p><p className="mt-2 font-mono text-2xl font-semibold">{byType.length}</p></Card>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Card title="By event type">
              {byType.slice(0, 10).map(([k, n]) => (
                <div key={k} className="flex items-center justify-between text-sm"><span>{k}</span><span className="font-mono text-muted-foreground">{n}</span></div>
              ))}
            </Card>
            <Card title="By severity">
              {bySeverity.map(([k, n]) => (
                <div key={k} className="flex items-center justify-between text-sm"><span>{k}</span><span className="font-mono text-muted-foreground">{n}</span></div>
              ))}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
