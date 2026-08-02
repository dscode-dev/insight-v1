"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Copy, Play } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

export function PipelineDetail({ pipelineId }: { pipelineId: string }) {
  const [pipeline, setPipeline] = useState<Row | null>(null);
  const [executions, setExecutions] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const call = async (path: string, method = "GET") => {
    const r = await fetch(withBasePath(`/api/v1/data-intelligence/${path}`), { method, cache: "no-store" });
    const b = await r.json(); if (!r.ok) throw new Error(b.detail ?? `HTTP ${r.status}`); return b;
  };
  const refresh = useCallback(async () => {
    try {
      const [p, e] = await Promise.all([call(`pipelines/${pipelineId}`), call("executions")]);
      setPipeline(p); setExecutions((e as Row[]).filter((r) => r.pipeline_id === pipelineId)); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "unreachable"); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineId]);
  useEffect(() => { refresh(); }, [refresh]);
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!pipeline) return <Empty>Loading pipeline.</Empty>;
  const estimate = (pipeline.estimate as Row) ?? {};
  const action = async (name: string) => { await call(`pipelines/${pipelineId}/${name}`, "POST"); refresh(); };
  return <div className="space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-xl font-semibold">{String(pipeline.name)}</h1><p className="text-xs text-muted-foreground">{String(pipeline.description)} · owner {String(pipeline.owner)} · version {String(pipeline.version ?? 1)}</p></div><Pill value={pipeline.enabled ? "enabled" : "disabled"} /></div>
    <div className="flex gap-2"><Button size="sm" disabled={!pipeline.enabled} onClick={() => action("execute")}><Play className="h-4 w-4" />Start execution</Button><Button size="sm" variant="outline" onClick={() => action("duplicate")}><Copy className="h-4 w-4" />Duplicate</Button></div>
    <Card title="Configuration"><div className="grid gap-3 md:grid-cols-2"><Block label="Sources" value={pipeline.sources} /><Block label="Competitions" value={pipeline.competitions} /><Block label="Themes" value={pipeline.themes} /><Block label="Duration / schedule" value={{ duration: pipeline.duration, schedule: pipeline.schedule }} /></div></Card>
    <Card title="Execution estimate"><div className="grid grid-cols-2 gap-2 md:grid-cols-5">{Object.entries(estimate).filter(([, v]) => !Array.isArray(v)).map(([k, v]) => <Block key={k} label={k} value={v} />)}</div></Card>
    <Card title={`Timeline and executions (${executions.length})`}>{executions.length ? executions.map((e) => <Link href={`/data-intelligence/executions/${e.execution_id}`} className="grid gap-2 border-b border-border py-3 text-sm hover:text-primary md:grid-cols-[1fr_repeat(5,auto)]" key={String(e.execution_id)}><span className="font-mono">{String(e.execution_id)}</span><span>{(Number(e.progress ?? 0) * 100).toFixed(1)}%</span><span>{String(e.jobs_completed ?? 0)}/{String(e.jobs_total ?? 0)} jobs</span><span>{String(e.throughput_records_per_second ?? 0)}/s</span><span>ETA {String(e.eta_seconds ?? "—")}s</span><Pill value={String(e.state)} /></Link>) : <Empty>No execution for this pipeline.</Empty>}</Card>
  </div>;
}
function Block({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border bg-background/30 p-3"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><pre className="mt-1 whitespace-pre-wrap text-xs">{typeof value === "string" || typeof value === "number" ? String(value) : JSON.stringify(value, null, 2)}</pre></div>; }
