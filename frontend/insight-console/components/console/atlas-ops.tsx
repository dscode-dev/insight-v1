"use client";

import { Brain } from "lucide-react";

import { MetricBars } from "@/components/console/metric-chart";
import { arr, Card, Empty, ErrorBanner, PageHeader, Pill, useOps } from "@/components/console/ops-shared";

type Row = Record<string, unknown>;
const num = (value: unknown) => Number(value ?? 0) || 0;

export function AtlasOps() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/data-intelligence/atlas/ingestion",
    "/api/v1/ops/events?service=atlas&limit=500",
    "/api/v1/ops/tickets?service=atlas&limit=100",
  ]);
  const ingestion = data.ingestion ?? {};
  const events = arr(data.events, "events").filter((event) => !event.service || event.service === "atlas");
  const tickets = arr(data.tickets, "tickets").filter((ticket) => !ticket.service || ticket.service === "atlas");
  const reasoning = events.filter((event) => String(event.event_type).includes("reason"));
  const conflicts = events.filter((event) => String(event.event_type).includes("conflict"));
  const metadata = events.map((event) => event.metadata as Row | undefined).filter(Boolean) as Row[];
  const uncertainty = distribution(metadata, "uncertainty", "mean_uncertainty");
  const confidence = distribution(metadata, "confidence", "mean_confidence");
  const behaviorCounts = countBy(events, (event) => String((event.metadata as Row | undefined)?.behavior ?? "").trim());

  return <div className="space-y-5">
    <PageHeader icon={Brain} title="Atlas Operations" subtitle="Memory · vectors · reasoning · behavior · confidence · no candidate-centric telemetry" updated={updated} onRefresh={refresh} />
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat label="Memory snapshots" value={num(ingestion.memories)} />
      <Stat label="Vector growth" value={num(ingestion.vectors)} />
      <Stat label="Behaviors" value={num(ingestion.behaviors)} />
      <Stat label="Signals" value={num(ingestion.signals)} />
    </div>
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="Runtime executions">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Reasoning executions" value={reasoning.length} compact />
          <Stat label="Conflicts" value={conflicts.length} compact />
          <Stat label="Ingestion batches" value={num(ingestion.batches)} compact />
          <Stat label="Last ingestion" value={String(ingestion.last_ingested_at ?? "—")} compact />
        </div>
      </Card>
      <Card title="Behavior counts">
        <MetricBars points={Object.entries(behaviorCounts).map(([label, value]) => ({ label, value })).slice(0, 12)} empty="Behavior-level events are not emitted separately; aggregate ingestion count remains available." />
      </Card>
      <Card title="Uncertainty distribution">
        <Buckets values={uncertainty} empty="The operations stream does not emit uncertainty samples yet. Atlas ingestion counts are shown without inventing a distribution." />
      </Card>
      <Card title="Confidence distribution">
        <Buckets values={confidence} empty="The operations stream does not emit confidence samples yet. No synthetic buckets are displayed." />
      </Card>
    </div>
    <Card title="Vector neighbors and reasoning evidence">
      {events.length ? events.slice(0, 20).map((event, index) => <details key={String(event.event_id ?? index)} className="border-b border-border/50 py-2 text-sm last:border-0"><summary className="cursor-pointer"><Pill value={String(event.severity ?? event.status ?? "info")} /> <span className="ml-2">{String(event.message ?? event.event_type)}</span></summary><pre className="mt-2 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify(event, null, 2)}</pre></details>) : <Empty>No Atlas runtime events are currently emitted to Operations.</Empty>}
    </Card>
    <Card title="Atlas alerts">
      {tickets.length ? tickets.map((ticket, index) => <div key={String(ticket.ticket_id ?? index)} className="py-1 text-sm"><Pill value={String(ticket.severity ?? "warning")} /> <span className="ml-2">{String(ticket.reason)}</span></div>) : <Empty>No Atlas alerts.</Empty>}
    </Card>
  </div>;
}

function Stat({ label, value, compact = false }: { label: string; value: string | number; compact?: boolean }) {
  return <div className={compact ? "" : "rounded-xl border border-border bg-card/60 p-3"}><p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p><p className={`mt-1 font-mono font-semibold ${compact ? "text-sm" : "text-xl"}`}>{value}</p></div>;
}
function distribution(rows: Row[], ...keys: string[]) {
  return rows.flatMap((row) => keys.map((key) => row[key])).filter((value): value is number => typeof value === "number");
}
function countBy(rows: Row[], key: (row: Row) => string) {
  const result: Record<string, number> = {};
  for (const row of rows) { const label = key(row); if (label) result[label] = (result[label] ?? 0) + 1; }
  return result;
}
function Buckets({ values, empty }: { values: number[]; empty: string }) {
  if (!values.length) return <Empty>{empty}</Empty>;
  const buckets = [0, 0, 0, 0];
  values.forEach((value) => {
    const index = Math.min(3, Math.floor(Math.max(0, value) * 4));
    buckets[index] = (buckets[index] ?? 0) + 1;
  });
  return <MetricBars points={buckets.map((value, index) => ({ label: `${index * 25}–${(index + 1) * 25}%`, value }))} />;
}
