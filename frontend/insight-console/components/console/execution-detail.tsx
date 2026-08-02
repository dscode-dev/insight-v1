"use client";

import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw, Save } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, ts, type Row } from "@/components/console/ops-shared";

export function ExecutionDetail({ executionId, superAdmin }: { executionId: string; superAdmin: boolean }) {
  const [execution, setExecution] = useState<Row | null>(null);
  const [jobs, setJobs] = useState<Row[]>([]);
  const [dataset, setDataset] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const get = useCallback(async (suffix = "") => {
    const r = await fetch(withBasePath(`/api/v1/data-intelligence/executions/${executionId}${suffix}`), { cache: "no-store" });
    const body = await r.json(); if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`); return body;
  }, [executionId]);
  const refresh = useCallback(async () => {
    try { const [e, j, d] = await Promise.all([get(), get("/jobs"), get("/dataset")]); setExecution(e); setJobs(j); setDataset(d); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "unreachable"); }
  }, [get]);
  useEffect(() => { refresh(); const id = setInterval(refresh, 7000); return () => clearInterval(id); }, [refresh]);
  const [persisted, setPersisted] = useState<Row | null>(null);
  const persist = async () => {
    const response = await fetch(withBasePath("/api/v1/atlas-datasets/register-explorer"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        generation_id: execution?.generation,
        name: execution?.pipeline_name,
        completed_at: execution?.ended_at,
        manifest: dataset?.manifest,
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? body.error ?? `HTTP ${response.status}`);
    setPersisted(body);
  };
  if (!execution) return error ? <ErrorBanner>{error}</ErrorBanner> : <Empty>Loading execution.</Empty>;
  const state = String(execution.state);
  const manifest = (dataset?.manifest as Row) ?? {};
  const totals = (manifest.totals as Row) ?? {};
  return <div className="space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="font-mono text-xl font-semibold">{executionId}</h1><p className="text-xs text-muted-foreground">{String(execution.pipeline_name)} · started {ts(execution.started_at)}</p></div><div className="flex items-center gap-2"><Pill value={state} /><Button size="sm" variant="outline" onClick={refresh}><RefreshCw className="h-3.5 w-3.5" /></Button></div></div>
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <Card title="Execution stages"><div className="grid gap-2 md:grid-cols-4"><Stage label="Collected" ready={jobs.length > 0} detail={`${jobs.length} source jobs`} /><Stage label="Validated" ready={jobs.some((job) => Number(job.records_validated ?? 0) > 0)} detail={`${String(execution.records ?? 0)} records`} /><Stage label="Ready for Atlas" ready={Boolean(dataset?.manifest) && Number(execution.failed_source_jobs ?? 0) === 0} detail={String((execution.atlas_ingestion as Row | undefined)?.status ?? "manifest ready")} /><Stage label="Persisted to Atlas" ready={Boolean(persisted)} detail={String(persisted?.dataset_id ?? "awaiting approval")} /></div>{superAdmin ? <Button className="mt-3" size="sm" disabled={!dataset?.manifest || Number(execution.failed_source_jobs ?? 0) > 0 || Boolean(persisted)} onClick={persist}><Save className="h-4 w-4" />Persist to Atlas</Button> : <p className="mt-3 text-xs text-muted-foreground">Persistence approval requires SuperAdmin.</p>}</Card>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-6"><M label="progress" value={`${(Number(execution.progress ?? 0) * 100).toFixed(1)}%`} /><M label="completed" value={execution.jobs_completed} /><M label="remaining" value={execution.jobs_remaining} /><M label="records" value={execution.records ?? totals.fixtures} /><M label="sources" value={execution.source_count} /><M label="ETA seconds" value={execution.eta_seconds} /></div>
    <Card title="Dataset"><div className="grid gap-2 md:grid-cols-4"><M label="generation" value={dataset?.generation} /><M label="checksum" value={dataset?.checksum} /><M label="odds coverage" value={`${String((dataset?.odds_coverage as Row)?.percentage ?? 0)}%`} /><M label="statistics coverage" value={`${String((dataset?.statistics_coverage as Row)?.percentage ?? 0)}%`} /></div><details className="mt-3"><summary className="cursor-pointer text-xs text-primary">Manifest JSON</summary><pre className="mt-2 max-h-72 overflow-auto rounded bg-background p-3 text-[11px]">{JSON.stringify(manifest, null, 2)}</pre></details></Card>
    <Card title={`Jobs (${jobs.length})`}>{jobs.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-muted-foreground"><tr><th>Source</th><th>Competition</th><th>Season</th><th>State</th><th>Duration</th><th>Records</th><th>Odds</th><th>Stats</th><th>Confidence</th><th>Disagreement</th></tr></thead><tbody>{jobs.map((j) => <tr className="border-t border-border" key={String(j.job_id)}><td>{String(j.source)}</td><td>{String(j.competition)}</td><td>{String(j.season)}</td><td><Pill value={String(j.status)} /></td><td>{String(j.duration_ms ?? 0)}ms</td><td>{String(j.records_validated ?? 0)}</td><td>{String(j.odds ?? 0)}</td><td>{String(j.statistics ?? 0)}</td><td>{String(j.confidence ?? "—")}</td><td>{String(j.disagreement ?? 0)}</td></tr>)}</tbody></table></div> : <Empty>No job records yet.</Empty>}</Card>
    <Card title="Source contribution"><div className="grid gap-2 md:grid-cols-3">{Object.entries((execution.source_contribution as Row) ?? {}).map(([k, v]) => <M key={k} label={k} value={v} />)}</div></Card>
    <Card title="Timeline"><div className="space-y-2 text-sm"><Timeline label="Created" value={execution.created_at} /><Timeline label="Started" value={execution.started_at} /><Timeline label="Completed / stopped" value={execution.ended_at} /><Timeline label="Atlas ingestion" value={(execution.atlas_ingestion as Row | undefined)?.status} /><Timeline label="Failures / retries" value={`${String(execution.failed_source_jobs ?? 0)} failures · ${String(execution.retries ?? 0)} retries`} /></div></Card>
  </div>;
}
function M({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border bg-card/60 p-3"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 break-all font-mono text-sm">{String(value ?? "—")}</p></div>; }
function Stage({ label, ready, detail }: { label: string; ready: boolean; detail: string }) { return <div className="rounded border border-border p-3"><Pill value={ready ? "completed" : "pending"} /><p className="mt-2 text-sm font-medium">{label}</p><p className="text-xs text-muted-foreground">{detail}</p></div>; }
function Timeline({ label, value }: { label: string; value: unknown }) { return <div className="flex justify-between gap-4 border-b border-border/50 pb-2"><span>{label}</span><span className="font-mono text-xs text-muted-foreground">{String(value ?? "—")}</span></div>; }
