"use client";

import { Radar } from "lucide-react";

import { MetricBars } from "@/components/console/metric-chart";
import { arr, Card, Empty, ErrorBanner, PageHeader, Pill, useOps, type Row } from "@/components/console/ops-shared";
import { withBasePath } from "@/lib/base-path";

const num = (value: unknown) => Number(value ?? 0) || 0;

export function ExplorerOps() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/data-intelligence/data-intelligence/dashboard",
    "/api/v1/data-intelligence/executions",
    "/api/v1/ops/tickets?service=explorer&limit=100",
  ]);
  const dashboard = data.dashboard ?? {};
  const executions = Array.isArray(data.executions) ? data.executions as unknown as Row[] : [];
  const tickets = arr(data.tickets, "tickets").filter((ticket) => !ticket.service || ticket.service === "explorer");
  const sources = Array.isArray(dashboard.sources) ? dashboard.sources as Row[] : [];
  const datasets = Array.isArray(dashboard.datasets) ? dashboard.datasets as Row[] : [];
  const contribution = dashboard.records_per_source as Record<string, number> | undefined;

  return <div className="space-y-5">
    <PageHeader icon={Radar} title="Explorer Operations" subtitle="Pipeline Center runtime · jobs · sources · datasets · Atlas ingestion" updated={updated} onRefresh={refresh} />
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat label="Active jobs" value={num(dashboard.active_jobs)} />
      <Stat label="Throughput / sec" value={num(dashboard.throughput_records_per_second)} />
      <Stat label="Retries" value={num(dashboard.retries)} />
      <Stat label="Failed jobs" value={num(dashboard.failed_jobs)} />
    </div>
    <Card title="Collection runs">
      {executions.length ? executions.slice(0, 30).map((execution) => {
        const ingestion = execution.atlas_ingestion as Row | undefined;
        return <a key={String(execution.execution_id)} href={withBasePath(`/data-intelligence/executions/${execution.execution_id}`)} className="block rounded-lg border-b border-border/50 px-2 py-3 hover:bg-accent/50">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span className="font-mono">{String(execution.execution_id)}</span><Pill value={String(execution.state ?? "unknown")} /></div>
          <div className="mt-1 grid gap-1 text-xs text-muted-foreground sm:grid-cols-4">
            <span>job {String(execution.current ?? "idle")}</span>
            <span>{num(execution.records)} records</span>
            <span>{num(execution.retries)} retries</span>
            <span>Atlas: {String(ingestion?.status ?? "not delivered")}</span>
          </div>
        </a>;
      }) : <Empty>No pipeline executions recorded.</Empty>}
    </Card>
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="Source contribution"><MetricBars points={Object.entries(contribution ?? {}).map(([label, value]) => ({ label, value }))} /></Card>
      <Card title="Source health">
        {sources.map((source) => <a key={String(source.name)} href={withBasePath("/data-intelligence/sources")} className="flex items-center justify-between border-b border-border/50 py-2 text-sm hover:text-primary"><span>{String(source.name)}</span><span className="flex gap-2"><Pill value={String(source.status)} /><Pill value={String(source.health)} /></span></a>)}
      </Card>
      <Card title="Datasets produced">
        {datasets.length ? datasets.map((dataset, index) => <a key={String(dataset.dataset_version ?? index)} href={withBasePath("/data-intelligence/datasets")} className="flex items-center justify-between border-b border-border/50 py-2 text-sm hover:text-primary"><span className="font-mono">{String(dataset.dataset_version ?? dataset.generation_id)}</span><span className="text-xs text-muted-foreground">{num(dataset.rows)} rows</span></a>) : <Empty>No datasets reported.</Empty>}
      </Card>
      <Card title="Source and ingestion alerts">
        {tickets.length ? tickets.map((ticket, index) => <a key={String(ticket.ticket_id ?? index)} href={withBasePath("/data-intelligence/tickets")} className="block border-b border-border/50 py-2 text-sm hover:text-primary"><Pill value={String(ticket.severity ?? "warning")} /> <span className="ml-2">{String(ticket.reason)}</span></a>) : <Empty>No Explorer alerts.</Empty>}
      </Card>
    </div>
  </div>;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-xl border border-border bg-card/60 p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p><p className="mt-1 font-mono text-xl font-semibold">{value}</p></div>;
}
