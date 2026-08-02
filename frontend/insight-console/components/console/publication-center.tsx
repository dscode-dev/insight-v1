"use client";

// Publication Center (CONSOLE-OPS-A3 Stage 7) — real publication operations data
// from the operations DB (service=nexus): events, tickets, runs. Honest
// disabled-by-design / no-data states. No placeholder boxes, no fake data.

import { Newspaper } from "lucide-react";

import { useOps, arr, ts, PageHeader, Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

export function PublicationCenter() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/ops/events?service=nexus&limit=200",
    "/api/v1/ops/tickets?service=nexus&limit=50",
    "/api/v1/ops/runs?service=nexus&limit=50",
  ]);

  const events = arr(data.events, "events").filter((r) => !r.service || r.service === "nexus");
  const tickets = arr(data.tickets, "tickets").filter((r) => !r.service || r.service === "nexus");
  const runs = arr(data.runs, "runs").filter((r) => !r.service || r.service === "nexus");
  const hasAny = events.length + tickets.length + runs.length > 0;

  return (
    <div className="space-y-5">
      <PageHeader icon={Newspaper} title="Publication Center" updated={updated} onRefresh={refresh}
        subtitle="Nexus publication operations · realtime (7s) · operations DB" />
      {error && <ErrorBanner>Operations: {error}</ErrorBanner>}

      {!hasAny && (
        <Card title="Publication state">
          <Empty>
            No Nexus publication events, runs or tickets recorded yet. Publication is operational
            but idle (no trends published in this window), or the Nexus publication run has not
            started. This is an honest empty state — no data is fabricated. Rich trend/output/
            consumer detail will appear here once Nexus emits publication operations events.
          </Empty>
        </Card>
      )}

      {runs.length > 0 && (
        <Card title="Publication runs">
          {runs.slice(0, 8).map((r, i) => (
            <div key={i} className="flex items-center justify-between gap-2 text-sm">
              <span className="font-mono">{String(r.run_label ?? r.run_id)}</span>
              <span className="flex items-center gap-2 text-xs text-muted-foreground"><Pill value={String(r.status)} /> {ts(r.started_at)}</span>
            </div>
          ))}
        </Card>
      )}

      {tickets.length > 0 && (
        <Card title="Publication tickets">
          {tickets.slice(0, 10).map((t, i) => (
            <div key={i} className="text-sm"><Pill value={String(t.severity ?? "warning")} /> <span className="ml-1">{String(t.reason)}</span> <span className="text-xs text-muted-foreground">×{String(t.count ?? 1)} — {String(t.impact ?? "")}</span></div>
          ))}
        </Card>
      )}

      {events.length > 0 && (
        <Card title="Publication events / history">
          <div className="space-y-1.5">
            {events.slice(0, 30).map((e, i) => (
              <div key={i} className="flex items-start justify-between gap-3 text-sm">
                <span><span className="text-xs font-semibold text-sky-400">{String(e.event_type)}</span> <span>{String(e.message ?? "")}</span></span>
                <span className="shrink-0 text-xs text-muted-foreground">{ts(e.timestamp)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
