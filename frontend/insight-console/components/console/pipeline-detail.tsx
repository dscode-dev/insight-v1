"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Copy, Pencil, Play, RotateCcw, Square, Trash2 } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, ts, type Row } from "@/components/console/ops-shared";
import { EditPipelineForm, type Catalog } from "@/components/console/data-intelligence-center";

export function PipelineDetail({ pipelineId }: { pipelineId: string }) {
  const router = useRouter();
  const [pipeline, setPipeline] = useState<Row | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [executions, setExecutions] = useState<Row[]>([]);
  const [signalSources, setSignalSources] = useState<Row[]>([]);
  const [realtimeStatus, setRealtimeStatus] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const call = async (path: string, method = "GET", body?: unknown) => {
    const r = await fetch(withBasePath(`/api/v1/data-intelligence/${path}`), {
      method, cache: "no-store",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const b = await r.json(); if (!r.ok) throw new Error(b.detail ?? `HTTP ${r.status}`); return b;
  };
  const refresh = useCallback(async () => {
    try {
      const [p, c, e, ss] = await Promise.all([
        call(`pipelines/${pipelineId}`), call("pipelines/catalog"), call("executions"), call("realtime/sources"),
      ]);
      setPipeline(p); setCatalog(c); setExecutions((e as Row[]).filter((r) => r.pipeline_id === pipelineId));
      setSignalSources(ss); setError(null);
      if (p.type === "realtime") setRealtimeStatus(await call(`pipelines/${pipelineId}/status`).catch(() => null));
    } catch (e) { setError(e instanceof Error ? e.message : "unreachable"); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineId]);
  useEffect(() => { refresh(); }, [refresh]);
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!pipeline || !catalog) return <Empty>Loading pipeline.</Empty>;
  const isRealtime = pipeline.type === "realtime";
  const estimate = (pipeline.estimate as Row) ?? {};
  const action = async (name: string) => { await call(`pipelines/${pipelineId}/${name}`, "POST"); refresh(); };
  const remove = async () => { await call(`pipelines/${pipelineId}`, "DELETE"); router.push("/data-intelligence/pipelines"); };

  if (editing) {
    return <EditPipelineForm row={pipeline} catalog={catalog} signalSources={signalSources} onCancel={() => setEditing(false)}
      onDone={() => { setEditing(false); refresh(); }} />;
  }

  const deleteControls = confirmingDelete ? <>
    <Button size="sm" variant="destructive" onClick={remove}>Confirm delete</Button>
    <Button size="sm" variant="outline" onClick={() => setConfirmingDelete(false)}>Cancel</Button>
  </> : <Button size="sm" variant="outline" onClick={() => setConfirmingDelete(true)}><Trash2 className="h-4 w-4" />Delete</Button>;

  return <div className="space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-xl font-semibold">{String(pipeline.name)}</h1><p className="text-xs text-muted-foreground">{String(pipeline.description)} · owner {String(pipeline.owner)} · version {String(pipeline.version ?? 1)}{isRealtime ? " · real-time" : ""}</p></div><Pill value={isRealtime ? String(realtimeStatus?.state ?? "stopped") : (pipeline.enabled ? "enabled" : "disabled")} /></div>
    <div className="flex flex-wrap gap-2">
      {isRealtime ? <>
        {String(realtimeStatus?.state ?? "stopped") === "running"
          ? <Button size="sm" variant="outline" onClick={() => action("stop")}><Square className="h-4 w-4" />Stop</Button>
          : <Button size="sm" onClick={() => action("start")}><Play className="h-4 w-4" />Start</Button>}
        <Button size="sm" variant="outline" onClick={() => action("restart")}><RotateCcw className="h-4 w-4" />Restart</Button>
      </> : <>
        <Button size="sm" disabled={!pipeline.enabled} onClick={() => action("execute")}><Play className="h-4 w-4" />Start execution</Button>
        <Button size="sm" variant="outline" onClick={() => action("duplicate")}><Copy className="h-4 w-4" />Duplicate</Button>
      </>}
      <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />Edit</Button>
      {deleteControls}
    </div>
    {isRealtime ? <Card title="Real-time status"><div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <Block label="signals captured" value={realtimeStatus?.signals_captured ?? 0} />
      <Block label="errors" value={realtimeStatus?.errors ?? 0} />
      <Block label="last signal" value={ts(realtimeStatus?.last_signal_at)} />
      <Block label="running since" value={ts(realtimeStatus?.started_at)} />
    </div></Card> : null}
    <Card title="Configuration"><div className="grid gap-3 md:grid-cols-2">
      {isRealtime
        ? <Block label="Signal sources" value={((pipeline.signal_source_ids as string[]) ?? [])
            .map((id) => signalSources.find((s) => s.source_id === id)?.name ?? id)} />
        : <><Block label="Sources" value={pipeline.sources} /><Block label="Competitions" value={pipeline.competitions} /><Block label="Themes" value={pipeline.themes} /><Block label="Duration / schedule" value={{ duration: pipeline.duration, schedule: pipeline.schedule }} /></>}
    </div></Card>
    {!isRealtime ? <Card title="Execution estimate"><div className="grid grid-cols-2 gap-2 md:grid-cols-5">{Object.entries(estimate).filter(([, v]) => !Array.isArray(v)).map(([k, v]) => <Block key={k} label={k} value={v} />)}</div></Card> : null}
    {!isRealtime ? <Card title={`Timeline and executions (${executions.length})`}>{executions.length ? executions.map((e) => <Link href={`/data-intelligence/executions/${e.execution_id}`} className="grid gap-2 border-b border-border py-3 text-sm hover:text-primary md:grid-cols-[1fr_repeat(5,auto)]" key={String(e.execution_id)}><span className="font-mono">{String(e.execution_id)}</span><span>{(Number(e.progress ?? 0) * 100).toFixed(1)}%</span><span>{String(e.jobs_completed ?? 0)}/{String(e.jobs_total ?? 0)} jobs</span><span>{String(e.throughput_records_per_second ?? 0)}/s</span><span>ETA {String(e.eta_seconds ?? "—")}s</span><Pill value={String(e.state)} /></Link>) : <Empty>No execution for this pipeline.</Empty>}</Card> : null}
  </div>;
}
function Block({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border bg-background/30 p-3"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><pre className="mt-1 whitespace-pre-wrap text-xs">{typeof value === "string" || typeof value === "number" ? String(value) : JSON.stringify(value, null, 2)}</pre></div>; }
