"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, Copy, Database, Gauge, Layers3, Pause, Play, Plus,
  RefreshCw, RotateCcw, Server, ShieldAlert, Square, Ticket,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, ts, type Row } from "@/components/console/ops-shared";

type Mode = "pipelines" | "executions" | "datasets" | "sources" | "tickets" | "dashboard";
type Catalog = {
  sources: Row[];
  competitions: Array<{ key: string; name: string; seasons: string[] }>;
  themes: string[];
  durations: string[];
};

const API = "/api/v1/data-intelligence";

async function request(path: string, method = "GET", body?: unknown) {
  const r = await fetch(withBasePath(`${API}/${path}`), {
    method, cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await r.json();
  if (!r.ok) throw new Error(String(payload.detail ?? payload.error ?? `HTTP ${r.status}`));
  return payload;
}

export function DataIntelligenceCenter({ mode }: { mode: Mode }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [dashboard, setDashboard] = useState<Row | null>(null);
  const [executions, setExecutions] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      if (mode === "pipelines") {
        const [p, c, e] = await Promise.all([request("pipelines"), request("pipelines/catalog"), request("executions")]);
        setRows(p); setCatalog(c); setExecutions(e);
      } else if (mode === "executions" || mode === "datasets") {
        setRows(await request("executions"));
      } else if (mode === "sources") {
        const c = await request("pipelines/catalog");
        setCatalog(c); setRows(c.sources);
      } else if (mode === "tickets") {
        setRows(await request("tickets?status="));
      } else {
        setDashboard(await request("data-intelligence/dashboard"));
      }
      setUpdated(new Date()); setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unreachable");
    }
  }, [mode]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 7000);
    return () => clearInterval(id);
  }, [refresh]);

  const titles: Record<Mode, [string, string]> = {
    pipelines: ["Mission Center", "Create, duplicate, estimate and inspect Explorer missions"],
    executions: ["Mission Executions", "Merged into Mission Center for live and historical collection generations"],
    datasets: ["Dataset Center", "Generation manifests, hashes and coverage"],
    sources: ["Sources", "Health, priority, collection weight and contribution"],
    tickets: ["Tickets", "Operational issues connected to missions, providers, datasets and Atlas evidence"],
    dashboard: ["Operations Center", "Explorer dashboard content is merged into Operations"],
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold"><Layers3 className="h-5 w-5 text-primary" />{titles[mode][0]}</h1>
          <p className="text-xs text-muted-foreground">{titles[mode][1]}{updated ? ` · updated ${updated.toLocaleTimeString()}` : ""}</p>
        </div>
        <Button size="sm" variant="outline" onClick={refresh}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>
      </div>
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      {mode === "pipelines" && catalog ? <Pipelines rows={rows} executions={executions} catalog={catalog} refresh={refresh} /> : null}
      {mode === "executions" ? <Executions rows={rows} refresh={refresh} /> : null}
      {mode === "datasets" ? <Datasets rows={rows} /> : null}
      {mode === "sources" ? <Sources rows={rows} refresh={refresh} /> : null}
      {mode === "tickets" ? <Tickets rows={rows} refresh={refresh} /> : null}
      {mode === "dashboard" ? <Dashboard body={dashboard} /> : null}
    </div>
  );
}

function Pipelines({ rows, executions, catalog, refresh }: { rows: Row[]; executions: Row[]; catalog: Catalog; refresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sources, setSources] = useState<string[]>(["espn", "football_data"]);
  const [sourceConfig, setSourceConfig] = useState<Record<string, { weight: number; priority: number }>>({
    espn: { weight: 1, priority: 1 },
    football_data: { weight: 1, priority: 2 },
  });
  const [competitions, setCompetitions] = useState<string[]>(["brasileirao_serie_a"]);
  const [themes, setThemes] = useState<string[]>(["fixtures", "odds"]);
  const [duration, setDuration] = useState("one-shot");
  const [schedule, setSchedule] = useState("");
  const [customHours, setCustomHours] = useState(24);
  const [estimate, setEstimate] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = useMemo(() => ({
    name: name || "Draft", description,
    sources: sources.map((source, i) => ({
      name: source, enabled: true,
      weight: sourceConfig[source]?.weight ?? 1,
      priority: sourceConfig[source]?.priority ?? i + 1,
    })),
    competitions, themes,
    duration: duration === "custom" ? { mode: duration, hours: customHours } : { mode: duration },
    schedule: schedule || null,
  }), [name, description, sources, sourceConfig, competitions, themes, duration, customHours, schedule]);

  useEffect(() => {
    if (!sources.length || !competitions.length || !themes.length) return;
    const id = setTimeout(() => request("pipelines/estimate", "POST", draft).then(setEstimate).catch(() => setEstimate(null)), 250);
    return () => clearTimeout(id);
  }, [draft, sources.length, competitions.length, themes.length]);

  const toggle = (value: string, values: string[], set: (v: string[]) => void) =>
    set(values.includes(value) ? values.filter((v) => v !== value) : [...values, value]);

  const create = async () => {
    setBusy(true);
    try { await request("pipelines", "POST", draft); setOpen(false); setName(""); refresh(); }
    finally { setBusy(false); }
  };

  return <>
    <div className="flex justify-end"><Button size="sm" onClick={() => setOpen(!open)}><Plus className="h-4 w-4" />New mission</Button></div>
    {open ? <Card title="Create acquisition mission">
      <div className="grid gap-4 lg:grid-cols-2">
        <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Historical market enrichment" /></Field>
        <Field label="Description"><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div>
          <Choices label="Sources" values={catalog.sources.map((s) => String(s.name))} selected={sources} onToggle={(v) => {
            toggle(v, sources, setSources);
            if (!sourceConfig[v]) setSourceConfig({ ...sourceConfig, [v]: { weight: 1, priority: sources.length + 1 } });
          }} />
          <div className="mt-2 space-y-1">
            {sources.map((source) => <div key={source} className="grid grid-cols-[1fr_80px_80px] items-center gap-2 text-xs">
              <span>{source}</span>
              <input aria-label={`${source} weight`} title="weight" className="input" type="number" min={0.1} max={10} step={0.1} value={sourceConfig[source]?.weight ?? 1} onChange={(e) => setSourceConfig({ ...sourceConfig, [source]: { weight: Number(e.target.value), priority: sourceConfig[source]?.priority ?? 1 } })} />
              <input aria-label={`${source} priority`} title="priority" className="input" type="number" min={1} max={99} value={sourceConfig[source]?.priority ?? 1} onChange={(e) => setSourceConfig({ ...sourceConfig, [source]: { weight: sourceConfig[source]?.weight ?? 1, priority: Number(e.target.value) } })} />
            </div>)}
          </div>
        </div>
        <Choices label="Themes" values={catalog.themes} selected={themes} onToggle={(v) => toggle(v, themes, setThemes)} />
        <Choices label="Competitions" values={catalog.competitions.map((c) => c.key)} selected={competitions} onToggle={(v) => toggle(v, competitions, setCompetitions)} />
        <div className="space-y-3">
          <Field label="Duration"><select className="input" value={duration} onChange={(e) => setDuration(e.target.value)}>{catalog.durations.map((d) => <option key={d}>{d}</option>)}</select></Field>
          {duration === "custom" ? <Field label="Custom hours"><input className="input" type="number" min={1} max={168} value={customHours} onChange={(e) => setCustomHours(Number(e.target.value))} /></Field> : null}
          <Field label="Schedule (optional)"><input className="input" value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder="manual or cron expression" /></Field>
          <Estimate body={estimate} />
        </div>
      </div>
      <div className="mt-4 flex justify-end"><Button disabled={busy || !name || !sources.length || !competitions.length} onClick={create}>Create mission</Button></div>
    </Card> : null}
    <div className="grid gap-3 lg:grid-cols-2">{rows.map((p) => <PipelineCard key={String(p.pipeline_id)} row={p} executions={executions.filter((e) => e.pipeline_id === p.pipeline_id)} refresh={refresh} />)}</div>
  </>;
}

function PipelineCard({ row, executions, refresh }: { row: Row; executions: Row[]; refresh: () => void }) {
  const estimate = (row.estimate as Row) ?? {};
  const action = async (kind: "execute" | "duplicate") => {
    await request(`pipelines/${row.pipeline_id}/${kind}`, "POST"); refresh();
  };
  return <Card>
    <div className="space-y-3">
      <div className="flex justify-between gap-2"><div><Link className="font-medium hover:text-primary" href={`/data-intelligence/pipelines/${row.pipeline_id}`}>{String(row.name)}</Link><p className="text-xs text-muted-foreground">{String(row.description ?? "")}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">mission v{String(row.version ?? 1)}{row.revision_of ? ` · revision of ${row.revision_of}` : ""}</p></div><Pill value={row.enabled ? "enabled" : "disabled"} /></div>
      <div className="grid grid-cols-3 gap-2 text-xs"><Metric label="parent jobs" value={estimate.parent_jobs} /><Metric label="requests" value={estimate.estimated_requests} /><Metric label="runtime" value={`${estimate.estimated_runtime_hours ?? 0}h`} /></div>
      <p className="text-xs text-muted-foreground">{(row.competitions as string[]).join(", ")} · {(row.themes as string[]).join(", ")}</p>
      {executions.slice(0, 3).map((execution) => <Link key={String(execution.execution_id)} href={`/data-intelligence/executions/${execution.execution_id}`} className="grid grid-cols-4 gap-2 rounded border border-border p-2 text-xs hover:text-primary"><span className="truncate font-mono">{String(execution.execution_id)}</span><span>{(Number(execution.progress ?? 0) * 100).toFixed(1)}%</span><span>{String(execution.throughput_records_per_second ?? 0)}/s</span><Pill value={String(execution.state)} /></Link>)}
      <div className="flex gap-2"><Button size="sm" disabled={!row.enabled} onClick={() => action("execute")}><Play className="h-3.5 w-3.5" />Start mission</Button><Button size="sm" variant="outline" onClick={() => action("duplicate")}><Copy className="h-3.5 w-3.5" />Duplicate</Button></div>
    </div>
  </Card>;
}

function Executions({ rows, refresh }: { rows: Row[]; refresh: () => void }) {
  const control = async (id: unknown, action: string) => { await request(`executions/${id}/${action}`, "POST"); refresh(); };
  if (!rows.length) return <Empty>No mission executions.</Empty>;
  return <div className="space-y-2">{rows.map((e) => {
    const state = String(e.state);
    const progress = Number(e.progress ?? 0) * 100;
    return <Card key={String(e.execution_id)}>
      <div className="space-y-3">
        <div className="flex flex-wrap justify-between gap-2"><div><Link className="font-mono text-sm hover:text-primary" href={`/data-intelligence/executions/${e.execution_id}`}>{String(e.execution_id)}</Link><p className="text-xs text-muted-foreground">{String(e.pipeline_name)} · {ts(e.started_at)}</p></div><Pill value={state} /></div>
        <div className="h-2 overflow-hidden rounded bg-muted"><div className="h-full bg-primary" style={{ width: `${Math.min(100, progress)}%` }} /></div>
        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-5"><Metric label="progress" value={`${progress.toFixed(1)}%`} /><Metric label="jobs" value={`${e.jobs_completed ?? 0}/${e.jobs_total ?? 0}`} /><Metric label="records" value={e.records ?? 0} /><Metric label="duration" value={formatDuration(Number(e.duration_seconds ?? 0))} /><Metric label="ETA" value={e.eta_seconds ? formatDuration(Number(e.eta_seconds)) : "—"} /></div>
        {["running", "paused", "pending"].includes(state) ? <div className="flex gap-2">
          {state === "paused" ? <Button size="sm" onClick={() => control(e.execution_id, "resume")}><RotateCcw className="h-3.5 w-3.5" />Resume</Button> : <Button size="sm" variant="outline" onClick={() => control(e.execution_id, "pause")}><Pause className="h-3.5 w-3.5" />Pause</Button>}
          <Button size="sm" variant="destructive" onClick={() => control(e.execution_id, "stop")}><Square className="h-3.5 w-3.5" />Stop</Button>
        </div> : null}
      </div>
    </Card>;
  })}</div>;
}

function Datasets({ rows }: { rows: Row[] }) {
  const available = rows.filter((r) => r.generation_root || (r.datasets as unknown[])?.length);
  return <div className="grid gap-3 lg:grid-cols-2">{available.map((e) => <Card key={String(e.execution_id)}>
    <div className="flex justify-between gap-3"><div><Link className="font-mono text-sm hover:text-primary" href={`/data-intelligence/executions/${e.execution_id}`}>{String(e.generation)}</Link><p className="text-xs text-muted-foreground">{String(e.pipeline_name)}</p></div><Database className="h-4 w-4 text-primary" /></div>
    <div className="mt-3 grid grid-cols-3 gap-2 text-xs"><Metric label="records" value={e.records ?? "—"} /><Metric label="sources" value={e.source_count ?? "—"} /><Metric label="state" value={e.state} /></div>
  </Card>)}</div>;
}

function Sources({ rows, refresh }: { rows: Row[]; refresh: () => void }) {
  const toggle = async (source: Row) => {
    await request(`sources/${source.enabled ? "disable" : "enable"}`, "POST", { source: source.name });
    refresh();
  };
  const priority = async (source: Row, value: number) => {
    await request("sources/priority", "POST", { source: source.name, priority: value });
    refresh();
  };
  return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{rows.map((s) => <Card key={String(s.name)}>
    <div className="flex justify-between"><div><p className="font-medium">{String(s.name)}</p><p className="text-xs text-muted-foreground">{(s.themes as string[]).join(", ")}</p></div><div className="flex gap-1"><Pill value={s.enabled ? "enabled" : "disabled"} /><Pill value={String(s.health)} /></div></div>
    <div className="mt-3 grid grid-cols-3 gap-2 text-xs"><Metric label="classification" value={s.status} /><Metric label="contribution" value={s.contribution ?? 0} /><Metric label="records" value={s.records_validated ?? 0} /><Metric label="failures" value={s.failures ?? 0} /><Metric label="success rate" value={s.success_rate ?? "—"} /><Metric label="latency" value={s.average_latency_ms == null ? "—" : `${s.average_latency_ms}ms`} /><Metric label="coverage" value={Array.isArray(s.themes) ? `${(s.themes as string[]).length} categories` : "—"} /><Field label="Priority"><input className="input" type="number" min={1} max={999} defaultValue={Number(s.priority ?? 100)} onBlur={(event) => priority(s, Number(event.target.value))} /></Field></div>
    <Button className="mt-3" size="sm" variant="outline" onClick={() => toggle(s)}>{s.enabled ? "Disable" : "Enable"}</Button>
  </Card>)}</div>;
}

function Tickets({ rows, refresh }: { rows: Row[]; refresh: () => void }) {
  const annotate = async (ticket: Row, form: HTMLFormElement) => {
    const values = new FormData(form);
    await request("tickets/annotate", "POST", { ticket_id: ticket.ticket_id, assignment: values.get("assignment"), status: values.get("status"), comment: values.get("comment"), execution_id: values.get("execution_id"), pipeline_id: values.get("pipeline_id") });
    form.reset(); refresh();
  };
  return <div className="space-y-2">{rows.map((t) => <Card key={String(t.ticket_id)}>
    <div className="flex gap-3"><Ticket className="mt-0.5 h-4 w-4 text-amber-400" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Pill value={String(t.severity)} /><span className="font-medium">{String(t.error_type ?? t.reason)}</span><span className="text-xs text-muted-foreground">{String(t.status)}</span></div><p className="mt-1 text-sm">{String(t.suggested_action ?? t.impact ?? "Inspect source evidence.")}</p><p className="text-xs text-muted-foreground">Provider: {String(t.provider ?? t.source ?? "explorer")} · mission: {String(t.execution_id ?? t.job_id ?? "—")} · dataset: {String(t.dataset_id ?? t.generation ?? "—")} · Atlas report: {String(t.atlas_report_id ?? "—")} · assigned: {String(t.assignment ?? "unassigned")}</p>{Array.isArray(t.comments) ? (t.comments as Row[]).map((comment, index) => <p key={index} className="mt-1 rounded bg-background/50 p-2 text-xs">{String(comment.comment)} — {String(comment.actor)} · {ts(comment.timestamp)}</p>) : null}<form className="mt-3 grid gap-2 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); annotate(t, event.currentTarget); }}><input name="assignment" className="input" placeholder="assignee" defaultValue={String(t.assignment ?? "")} /><select name="status" className="input" defaultValue={String(t.status ?? "open")}><option>open</option><option>investigating</option><option>resolved</option><option>dismissed</option></select><input name="execution_id" className="input" placeholder="related mission / execution" defaultValue={String(t.execution_id ?? t.job_id ?? "")} /><input name="pipeline_id" className="input" placeholder="related mission template" defaultValue={String(t.pipeline_id ?? "")} /><input className="input" readOnly value={`provider: ${String(t.provider ?? t.source ?? "—")}`} /><input className="input" readOnly value={`dataset: ${String(t.dataset_id ?? t.generation ?? "—")}`} /><input className="input" readOnly value={`event: ${String(t.event_id ?? "—")}`} /><input className="input" readOnly value={`atlas: ${String(t.atlas_report_id ?? "—")}`} /><input name="comment" className="input md:col-span-2" placeholder="comment" /><Button size="sm">Save</Button></form></div></div>
  </Card>)}</div>;
}

function Dashboard({ body }: { body: Row | null }) {
  if (!body) return <Empty>Loading dashboard.</Empty>;
  const sources = (body.sources as Row[]) ?? [];
  const datasets = (body.datasets as Row[]) ?? [];
  return <>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5"><MetricCard icon={Play} label="active missions" value={body.active_pipelines} /><MetricCard icon={Layers3} label="mission templates" value={body.pipelines} /><MetricCard icon={Activity} label="mission runs" value={body.executions} /><MetricCard icon={Server} label="sources" value={sources.length} /><MetricCard icon={ShieldAlert} label="tickets" value={body.tickets} /></div>
    <div className="grid gap-3 lg:grid-cols-2"><Card title="Source health">{sources.map((s) => <div key={String(s.name)} className="flex justify-between py-1 text-sm"><span>{String(s.name)}</span><span className="flex gap-3"><span className="font-mono text-muted-foreground">{String(s.contribution ?? 0)}</span><Pill value={String(s.health)} /></span></div>)}</Card><Card title="Dataset growth">{datasets.length ? datasets.map((d) => <div key={String(d.generation)} className="flex justify-between py-1 text-sm"><span className="font-mono">{String(d.generation)}</span><span>{String(((d.manifest as Row)?.totals as Row)?.fixtures ?? 0)} fixtures</span></div>) : <Empty>No generation manifests.</Empty>}</Card></div>
  </>;
}

function Choices({ label, values, selected, onToggle }: { label: string; values: string[]; selected: string[]; onToggle: (v: string) => void }) {
  return <div><p className="mb-2 text-xs font-medium">{label}</p><div className="flex max-h-44 flex-wrap gap-1.5 overflow-auto">{values.map((v) => <button type="button" key={v} onClick={() => onToggle(v)} className={`rounded border px-2 py-1 text-xs ${selected.includes(v) ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"}`}>{v}</button>)}</div></div>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-medium">{label}</span>{children}</label>; }
function Estimate({ body }: { body: Row | null }) { return <div className="grid grid-cols-3 gap-2"><Metric label="jobs" value={body?.source_jobs ?? "—"} /><Metric label="requests" value={body?.estimated_requests ?? "—"} /><Metric label="runtime" value={body ? `${body.estimated_runtime_hours}h` : "—"} /></div>; }
function Metric({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border bg-background/30 p-2"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 font-mono text-sm">{String(value ?? "—")}</p></div>; }
function MetricCard({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: unknown }) { return <Card><Icon className="h-4 w-4 text-primary" /><p className="mt-2 text-[10px] uppercase text-muted-foreground">{label}</p><p className="font-mono text-xl font-semibold">{String(value ?? 0)}</p></Card>; }
function formatDuration(seconds: number) { const h = Math.floor(seconds / 3600); const m = Math.floor(seconds % 3600 / 60); return `${h}h ${m}m`; }
