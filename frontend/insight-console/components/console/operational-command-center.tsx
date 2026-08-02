"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, Brain, CheckCircle2, Cloud, Database, Radar, RefreshCw,
  ServerCog, ShieldAlert,
} from "lucide-react";

import { MetricBars } from "@/components/console/metric-chart";
import { Pill } from "@/components/console/ops-shared";
import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type Row = Record<string, unknown>;
type Tab = "overview" | "infrastructure" | "missions" | "explorer" | "atlas" | "providers" | "timeline" | "coverage" | "intelligence" | "operations";
type InsightItem = { title: string; detail: string; tone: "good" | "watch" | "risk" | "neutral" };
type ReadinessItem = { label: string; score: number; blocker?: string };

const TABS: Array<{ id: Tab; label: string; icon: typeof Activity }> = [
  { id: "overview", label: "Overview", icon: CheckCircle2 },
  { id: "infrastructure", label: "Infra", icon: Cloud },
  { id: "missions", label: "Missions", icon: Activity },
  { id: "explorer", label: "Explorer", icon: Radar },
  { id: "atlas", label: "Atlas", icon: Brain },
  { id: "providers", label: "Providers", icon: Database },
  { id: "timeline", label: "Timeline", icon: Activity },
  { id: "coverage", label: "Coverage", icon: Database },
  { id: "intelligence", label: "Intelligence", icon: Activity },
  { id: "operations", label: "Incidents", icon: ShieldAlert },
];

async function json(path: string): Promise<Row> {
  const response = await fetch(withBasePath(path), { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

const rows = (body: Row | undefined, key: string): Row[] =>
  Array.isArray(body?.[key]) ? body?.[key] as Row[] : [];
const num = (value: unknown) => Number(value ?? 0) || 0;
const text = (value: unknown, fallback = "—") =>
  value === undefined || value === null || value === "" ? fallback : String(value);
const pct = (value: number) => `${Math.max(0, Math.min(100, Math.round(value)))}%`;

export function OperationalCommandCenter() {
  const t = useT("operations");
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<Record<string, Row>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const requests = {
      infrastructure: "/api/operations/status",
      explorer: "/api/v1/data-intelligence/data-intelligence/dashboard",
      executions: "/api/v1/data-intelligence/executions",
      atlas: "/api/v1/data-intelligence/atlas/ingestion",
      events: "/api/v1/ops/events?limit=200",
      tickets: "/api/v1/ops/tickets?limit=100",
      history: "/api/v1/ops/history?limit=200",
      dlq: "/api/v1/dlq?unreplayed=1&limit=100",
    };
    const settled = await Promise.allSettled(
      Object.entries(requests).map(async ([key, path]) => [key, await json(path)] as const),
    );
    const next: Record<string, Row> = {};
    const nextErrors: string[] = [];
    for (const result of settled) {
      if (result.status === "fulfilled") next[result.value[0]] = result.value[1];
      else nextErrors.push(result.reason instanceof Error ? result.reason.message : "unknown source error");
    }
    setData(next);
    setErrors(nextErrors);
    setUpdated(new Date());
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const explorer = useMemo(() => data.explorer ?? {}, [data.explorer]);
  const atlas = useMemo(() => data.atlas ?? {}, [data.atlas]);
  const events = useMemo(() => rows(data.events, "events"), [data.events]);
  const history = useMemo(() => rows(data.history, "timeline"), [data.history]);
  const tickets = useMemo(() => rows(data.tickets, "tickets"), [data.tickets]);
  const dlq = useMemo(() => rows(data.dlq, "items"), [data.dlq]);
  const executions = useMemo(() => Array.isArray(data.executions) ? data.executions as Row[] : [], [data.executions]);
  const sources = useMemo(() => Array.isArray(explorer.sources) ? explorer.sources as Row[] : [], [explorer.sources]);
  const activeExecutions = executions.filter((item) =>
    ["pending", "running", "paused"].includes(String(item.state)),
  );
  const intelligence = useMemo(() => intelligenceStats(events, atlas), [events, atlas]);
  const operational = useMemo(
    () => operationalIntelligence({ infrastructure: data.infrastructure, explorer, atlas, executions, tickets, events, dlq, stats: intelligence }),
    [data.infrastructure, explorer, atlas, executions, tickets, events, dlq, intelligence],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <ServerCog className="h-5 w-5 text-primary" /> {t("title")}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("subtitle")}
            {updated ? ` · ${updated.toLocaleTimeString()}` : ""}
          </p>
        </div>
        <button onClick={refresh} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs hover:bg-accent">
          <RefreshCw className="h-3.5 w-3.5" /> {t("refresh")}
        </button>
      </div>

      {errors.length ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3 text-xs text-amber-300">
          {t("degraded", { count: errors.length })}
          <details className="mt-1"><summary>{t("details")}</summary>{errors.map((error) => <div key={error} className="font-mono">{error}</div>)}</details>
        </div>
      ) : null}

      <div className="sticky top-0 z-[1] -mx-1 flex flex-wrap gap-1.5 border-y border-border bg-background/95 px-1 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        {TABS.map(({ id, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)} className={cn(
            "ix-transition inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs",
            tab === id ? "border-primary/40 bg-primary/10 text-primary shadow-sm shadow-primary/5" : "border-border bg-card/70 hover:bg-accent",
          )}>
            <Icon className="h-3.5 w-3.5" /> {t(`tab.${id}`)}
          </button>
        ))}
      </div>

      <MotionTabPanel key={tab} tab={tab}>
        {tab === "overview" ? (
          <OverviewTab operational={operational} />
        ) : null}
        {tab === "infrastructure" ? <InfrastructureTab body={data.infrastructure} events={history.length ? history : events} /> : null}
        {tab === "missions" ? <MissionCenterTab active={activeExecutions} executions={executions} events={history.length ? history : events} /> : null}
        {tab === "explorer" ? <ExplorerTab body={explorer} active={activeExecutions} executions={executions} /> : null}
        {tab === "atlas" ? <AtlasTab body={atlas} stats={intelligence} /> : null}
        {tab === "providers" ? <ProviderMatrixTab sources={sources} /> : null}
        {tab === "timeline" ? <OperationalTimelineTab events={history.length ? history : events} tickets={tickets} executions={executions} /> : null}
        {tab === "coverage" ? <CoverageCenterTab explorer={explorer} atlas={atlas} executions={executions} sources={sources} /> : null}
        {tab === "intelligence" ? <IntelligenceTab stats={intelligence} /> : null}
        {tab === "operations" ? <OperationsTab tickets={tickets} events={history.length ? history : events} dlq={dlq} /> : null}
      </MotionTabPanel>
    </div>
  );
}

function MotionTabPanel({ tab, children }: { tab: Tab; children: React.ReactNode }) {
  return (
    <section className="animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
      {children}
    </section>
  );
}

function OverviewTab({ operational }: { operational: ReturnType<typeof operationalIntelligence> }) {
  return (
    <div className="space-y-3">
      <ExecutiveSummary items={operational.summary} risk={operational.risk} />
      <div className="grid gap-3 xl:grid-cols-[1.2fr_0.8fr]">
        <OperationalInsights items={operational.insights} />
        <RecommendedActions items={operational.actions} />
      </div>
      <ReadinessDashboard items={operational.readiness} />
    </div>
  );
}

function InfrastructureTab({ body, events }: { body?: Row; events: Row[] }) {
  const domains = body?.domains as Record<string, Row[]> | undefined;
  const services = withEventStates([...(domains?.robozao ?? []), ...(domains?.google_cloud ?? [])], events);
  const degraded = services.filter((service) => !["healthy", "up"].includes(String(service.status)));
  return (
    <div className="space-y-3">
      <MetricGrid items={[
        ["Services", services.length], ["Healthy", services.length - degraded.length],
        ["Need attention", degraded.length], ["Domains", Object.keys(domains ?? {}).length],
      ]} />
      <ServiceRegistryPanel services={services} />
      <div className="grid gap-3 xl:grid-cols-2">
        <LiveStatesPanel services={services} />
        <CurrentActivityPanel services={services} />
        <OperationalMetricsPanel services={services} />
        <CommunicationGraphPanel services={services} />
        <HealthTimelinePanel services={services} />
        <IocAlertsPanel services={services} />
      </div>
    </div>
  );
}

function ExplorerTab({ body, active, executions }: { body: Row; active: Row[]; executions: Row[] }) {
  const sources = Array.isArray(body.sources) ? body.sources as Row[] : [];
  const records = body.records_per_source as Record<string, number> | undefined;
  return (
    <div className="space-y-3">
      <MetricGrid items={[
        ["Active jobs", num(body.active_jobs)], ["Throughput / sec", num(body.throughput_records_per_second)],
        ["Retries", num(body.retries)], ["Failed jobs", num(body.failed_jobs)],
      ]} />
      <div className="grid gap-3 lg:grid-cols-2">
        <MissionIntelligencePanel active={active} executions={executions} />
        <Panel title="Active collections">
          {active.length ? active.map((run) => <ExecutionRow key={String(run.execution_id)} run={run} />) :
            <EmptyState>No active collection. Latest runs remain available below.</EmptyState>}
          {executions.filter((run) => !active.includes(run)).slice(0, 5).map((run) => <ExecutionRow key={String(run.execution_id)} run={run} />)}
        </Panel>
        <Panel title="Source contribution">
          <MetricBars points={Object.entries(records ?? {}).map(([label, value]) => ({ label, value }))} />
        </Panel>
        <ProviderIntelligencePanel sources={sources} />
        <Panel title="Pipeline totals">
          <MetricGrid compact items={[
            ["Pipelines", num(body.pipelines)], ["Executions", num(body.executions)],
            ["Completed", num(body.completed_jobs)], ["Tickets", num(body.tickets)],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

function AtlasTab({ body, stats }: { body: Row; stats: ReturnType<typeof intelligenceStats> }) {
  const total = num(body.memories) + num(body.vectors) + num(body.behaviors) + num(body.signals);
  return (
    <div className="space-y-3">
      <MetricGrid items={[
        ["Memory snapshots", num(body.memories)], ["Vectors ingested", num(body.vectors)],
        ["Behaviors", num(body.behaviors)], ["Signals", num(body.signals)],
      ]} />
      <div className="grid gap-3 lg:grid-cols-2">
        <EnterpriseWidget title="Intelligence runtime" summary="Reasoning, conflicts, confidence and uncertainty">
          <MetricGrid compact items={[
            ["Reasoning executions", stats.reasoning], ["Conflicts", stats.conflicts],
            ["Avg uncertainty", stats.uncertainty == null ? "not emitted" : `${(stats.uncertainty * 100).toFixed(1)}%`],
            ["Avg confidence", stats.confidence == null ? "not emitted" : `${(stats.confidence * 100).toFixed(1)}%`],
          ]} />
        </EnterpriseWidget>
        <EnterpriseWidget title="Ingestion" summary="Atlas operational ingestion counters">
          <MetricGrid compact items={[
            ["Batches", num(body.batches)], ["Latest", text(body.last_ingested_at)],
            ["Memory/vector ratio", num(body.vectors) ? (num(body.memories) / num(body.vectors)).toFixed(2) : "—"],
            ["Total intelligence", num(body.memories) + num(body.vectors) + num(body.behaviors) + num(body.signals)],
          ]} />
        </EnterpriseWidget>
        <EnterpriseWidget title="Growth and coverage" summary="Expandable Atlas growth evidence">
          <MetricGrid compact items={[
            ["Total intelligence", total],
            ["Latest ingestion", text(body.last_ingested_at)],
            ["Coverage evolution", "not emitted"],
            ["Current reports", "runtime endpoint"],
          ]} />
          <p className="mt-3 text-xs text-muted-foreground">
            Growth since previous execution is shown only when the operations stream emits comparable snapshots; no values are inferred.
          </p>
        </EnterpriseWidget>
      </div>
    </div>
  );
}

function IntelligenceTab({ stats }: { stats: ReturnType<typeof intelligenceStats> }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Generation volume">
        <MetricBars points={[
          { label: "signals", value: stats.signals },
          { label: "behaviors", value: stats.behaviors },
          { label: "conflicts", value: stats.conflicts },
          { label: "reasoning", value: stats.reasoning },
        ]} />
      </Panel>
      <Panel title="Confidence and uncertainty">
        {stats.confidence == null && stats.uncertainty == null
          ? <EmptyState>The operations stream does not yet emit distribution values. Counts remain real; no values are inferred.</EmptyState>
          : <MetricBars points={[
              { label: "confidence ×100", value: Math.round((stats.confidence ?? 0) * 100) },
              { label: "uncertainty ×100", value: Math.round((stats.uncertainty ?? 0) * 100) },
            ]} />}
      </Panel>
    </div>
  );
}

function OperationsTab({ tickets, events, dlq }: { tickets: Row[]; events: Row[]; dlq: Row[] }) {
  const failures = events.filter((event) =>
    ["error", "critical", "failed"].some((value) =>
      `${event.severity ?? ""} ${event.status ?? ""} ${event.event_type ?? ""}`.toLowerCase().includes(value),
    ),
  );
  return (
    <div className="space-y-4">
      <MetricGrid items={[
        ["Open tickets", tickets.length], ["Recent failures", failures.length],
        ["DLQ messages", dlq.length], ["Alerts", tickets.filter((ticket) => String(ticket.status) !== "resolved").length],
      ]} />
      <Panel title="Needs attention">
        {[...tickets, ...failures].slice(0, 20).map((item, index) => (
          <details key={String(item.ticket_id ?? item.event_id ?? index)} className="border-b border-border/50 py-2 text-sm last:border-0">
            <summary className="cursor-pointer">
              <span className="mr-2 text-amber-400">{text(item.severity, text(item.status, "attention"))}</span>
              {text(item.reason, text(item.message, text(item.event_type)))}
            </summary>
            <pre className="mt-2 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify(item, null, 2)}</pre>
          </details>
        ))}
        {!tickets.length && !failures.length ? <EmptyState>No incidents or degraded events reported.</EmptyState> : null}
      </Panel>
    </div>
  );
}

type MissionEvent = { row: Row; op: Row; at: string; index: number };
type MissionStageView = { name: string; status: string; started?: string; finished?: string; durationMs: number; retries: number; warnings: number; errors: number; events: MissionEvent[] };
type MissionJobView = { jobId: string; provider: string; competition: string; season: string; worker: string; status: string; progress: string; durationMs: number; records: number; signals: number; errors: number; retries: number; fallbacks: number; events: MissionEvent[] };
type MissionView = {
  missionId: string;
  missionType: string;
  owner: string;
  priority: string;
  status: string;
  currentStage: string;
  progress: string;
  startedAt: string;
  eta: string;
  elapsed: string;
  expectedFinish: string;
  currentProvider: string;
  currentCompetition: string;
  currentSeason: string;
  currentWorker: string;
  health: string;
  risk: string;
  summary: string;
  events: MissionEvent[];
  stages: MissionStageView[];
  jobs: MissionJobView[];
  providers: Array<{ provider: string; events: MissionEvent[]; status: string; durationMs: number; failures: number; retries: number }>;
  atlas: MissionEvent[];
  diagnostics: InsightItem[];
  reports: string[];
  batches: string[];
};

function MissionCenterTab({ active, executions, events }: { active: Row[]; executions: Row[]; events: Row[] }) {
  const missions = useMemo(() => buildMissionViews(events, executions), [events, executions]);
  const activeIds = new Set(active.map((item) => String(item.execution_id ?? item.mission_id ?? item.run_id ?? "")));
  const preferred = missions.find((mission) => activeIds.has(mission.missionId)) ?? missions[0];
  const [selectedMissionId, setSelectedMissionId] = useState<string>("");
  const selected = missions.find((mission) => mission.missionId === (selectedMissionId || preferred?.missionId)) ?? preferred;
  const [replayIndex, setReplayIndex] = useState(0);
  const replayEvent = selected?.events[Math.min(replayIndex, Math.max(0, selected.events.length - 1))];

  useEffect(() => {
    setReplayIndex(0);
  }, [selected?.missionId]);

  return (
    <div className="space-y-3">
      <EnterpriseWidget title="Mission Operations Center" summary="Mission-first reconstruction from canonical operational events" filterPlaceholder="Filter mission">
        <div className="grid gap-3 xl:grid-cols-[0.72fr_1.28fr]">
          <div className="space-y-2">
            {missions.slice(0, 20).map((mission) => (
              <button
                key={mission.missionId}
                onClick={() => setSelectedMissionId(mission.missionId)}
                className={cn(
                  "w-full rounded-lg border p-3 text-left text-sm transition hover:bg-accent",
                  selected?.missionId === mission.missionId ? "border-primary/40 bg-primary/10" : "border-border bg-background/30",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs">{mission.missionId}</span>
                  <Pill value={mission.status} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{mission.summary}</p>
                <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                  <span>{mission.jobs.length} job(s)</span>
                  <span>{mission.events.length} event(s)</span>
                  <span>{mission.progress}</span>
                </div>
              </button>
            ))}
            {!missions.length ? <EmptyState>No mission events are available in the current operational window.</EmptyState> : null}
          </div>
          {selected ? <MissionOverviewPanel mission={selected} /> : <EmptyState>Select a mission to inspect.</EmptyState>}
        </div>
      </EnterpriseWidget>

      {selected ? (
        <>
          <div className="grid gap-3 2xl:grid-cols-[1.1fr_0.9fr]">
            <MissionExecutionFlow mission={selected} />
            <MissionDiagnosticsPanel mission={selected} />
          </div>
          <div className="grid gap-3 2xl:grid-cols-[1fr_1fr]">
            <MissionJobsPanel mission={selected} />
            <MissionProviderJourney mission={selected} />
          </div>
          <div className="grid gap-3 2xl:grid-cols-[1fr_1fr]">
            <MissionAtlasJourney mission={selected} />
            <MissionReplayPanel mission={selected} replayIndex={replayIndex} setReplayIndex={setReplayIndex} replayEvent={replayEvent} />
          </div>
          <MissionActionsPanel mission={selected} />
        </>
      ) : null}
    </div>
  );
}

function MissionRow({ execution, selected }: { execution: Row; selected: boolean }) {
  const estimate = execution.estimate as Row | undefined;
  const tasks = Array.isArray(execution.completed_tasks) ? execution.completed_tasks as unknown[] : [];
  return (
    <details open={selected} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
      <summary className="cursor-pointer">
        <span className="font-mono">{text(execution.execution_id)}</span>
        <span className="ml-2"><Pill value={text(execution.state, "unknown")} /></span>
      </summary>
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-3">
        <Datum label="Planner" value={text(execution.pipeline_name)} />
        <Datum label="Jobs" value={`${num(execution.jobs_completed)}/${num(execution.jobs_total) || num(estimate?.source_jobs) || "—"}`} />
        <Datum label="ETA" value={execution.eta_seconds ? `${Math.round(num(execution.eta_seconds) / 60)}m` : text(estimate?.estimated_runtime)} />
        <Datum label="Providers" value={Array.isArray((estimate?.source_estimates as Row[] | undefined)) ? (estimate?.source_estimates as Row[]).map((s) => text(s.source)).join(", ") : "not emitted"} />
        <Datum label="Signals generated" value={text(execution.signals_generated, "not emitted")} />
        <Datum label="Persistence" value={text(execution.persistence_status, execution.generation_root ? "dataset persisted" : "not reported")} />
      </div>
      <pre className="mt-3 max-h-44 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify({ current: execution.current, estimate, completed_tasks: tasks.slice(0, 10), datasets: execution.datasets }, null, 2)}</pre>
    </details>
  );
}

function MissionOverviewPanel({ mission }: { mission: MissionView }) {
  return (
    <div className="rounded-xl border border-border bg-background/30 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-mono text-sm font-semibold">{mission.missionId}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{mission.summary}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Pill value={mission.status} />
          <Pill value={mission.health} />
          <Pill value={mission.risk} />
        </div>
      </div>
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-3 xl:grid-cols-4">
        <Datum label="Mission type" value={mission.missionType} />
        <Datum label="Owner" value={mission.owner} />
        <Datum label="Priority" value={mission.priority} />
        <Datum label="Current stage" value={mission.currentStage} />
        <Datum label="Current progress" value={mission.progress} />
        <Datum label="Started at" value={mission.startedAt} />
        <Datum label="ETA" value={mission.eta} />
        <Datum label="Elapsed" value={mission.elapsed} />
        <Datum label="Expected finish" value={mission.expectedFinish} />
        <Datum label="Current provider" value={mission.currentProvider} />
        <Datum label="Current competition" value={mission.currentCompetition} />
        <Datum label="Current season" value={mission.currentSeason} />
        <Datum label="Current worker" value={mission.currentWorker} />
        <Datum label="Jobs" value={mission.jobs.length} />
        <Datum label="Reports" value={mission.reports.length ? mission.reports.join(", ") : "not linked"} />
        <Datum label="Batches" value={mission.batches.length ? mission.batches.join(", ") : "not linked"} />
      </div>
    </div>
  );
}

function MissionExecutionFlow({ mission }: { mission: MissionView }) {
  return (
    <EnterpriseWidget title="Mission execution flow" summary="Planning → expansion → collection → parsing → enrichment → signals → Atlas → reasoning → persistence → completed">
      <div className="space-y-2">
        {mission.stages.map((stage) => (
          <details key={stage.name} open={stage.events.length > 0} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
            <summary className="cursor-pointer">
              <span className="font-medium capitalize">{stage.name.replaceAll("_", " ")}</span>
              <span className="ml-2"><Pill value={stage.status} /></span>
              <span className="ml-2 text-xs text-muted-foreground">{stage.events.length} event(s) · {stage.durationMs ? `${stage.durationMs} ms` : "duration not emitted"}</span>
            </summary>
            <div className="mt-3 grid gap-2 text-xs md:grid-cols-4">
              <Datum label="Started" value={text(stage.started)} />
              <Datum label="Finished" value={text(stage.finished)} />
              <Datum label="Duration" value={stage.durationMs ? `${stage.durationMs} ms` : "not emitted"} />
              <Datum label="Retries" value={stage.retries} />
              <Datum label="Warnings" value={stage.warnings} />
              <Datum label="Errors" value={stage.errors} />
              <Datum label="Events" value={stage.events.length} />
            </div>
          </details>
        ))}
      </div>
    </EnterpriseWidget>
  );
}

function MissionJobsPanel({ mission }: { mission: MissionView }) {
  return (
    <EnterpriseWidget title="Job Explorer" summary="Jobs grouped by canonical job_id">
      <div className="space-y-2">
        {mission.jobs.map((job) => (
          <details key={job.jobId} open={mission.jobs.length === 1} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
            <summary className="cursor-pointer">
              <span className="font-mono text-xs">{job.jobId}</span>
              <span className="ml-2"><Pill value={job.status} /></span>
              <span className="ml-2 text-xs text-muted-foreground">{job.provider} · {job.competition} · {job.season}</span>
            </summary>
            <div className="mt-3 grid gap-2 text-xs md:grid-cols-4">
              <Datum label="Provider" value={job.provider} />
              <Datum label="Competition" value={job.competition} />
              <Datum label="Season" value={job.season} />
              <Datum label="Worker" value={job.worker} />
              <Datum label="Progress" value={job.progress} />
              <Datum label="Duration" value={job.durationMs ? `${job.durationMs} ms` : "not emitted"} />
              <Datum label="Records" value={job.records} />
              <Datum label="Signals" value={job.signals || "not emitted"} />
              <Datum label="Errors" value={job.errors} />
              <Datum label="Retries" value={job.retries} />
              <Datum label="Fallbacks" value={job.fallbacks} />
              <Datum label="Events" value={job.events.length} />
            </div>
          </details>
        ))}
        {!mission.jobs.length ? <EmptyState>No job_id-linked events for this mission.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function MissionProviderJourney({ mission }: { mission: MissionView }) {
  const order = ["provider_selected", "provider_request_started", "provider_response_received", "provider_parsing_started", "raw_records_accepted", "raw_records_ignored", "raw_records_rejected", "provider_fallback", "provider_retry", "job_completed"];
  return (
    <EnterpriseWidget title="Provider journey" summary="Provider selected → request → response → parsing → accepted/ignored/rejected → fallback/retry → completed">
      <div className="space-y-2">
        {mission.providers.map((provider) => (
          <details key={provider.provider} open className="rounded-lg border border-border bg-background/30 p-3 text-sm">
            <summary className="cursor-pointer">
              <span className="font-medium">{provider.provider}</span>
              <span className="ml-2"><Pill value={provider.status} /></span>
              <span className="ml-2 text-xs text-muted-foreground">{provider.events.length} event(s), {provider.failures} failure(s), {provider.retries} retry event(s)</span>
            </summary>
            <div className="mt-3 grid gap-2">
              {order.map((type) => {
                const items = provider.events.filter((event) => text(event.op.event_type) === type || text(event.op.event_type).includes(type.replace("provider_", "")));
                return (
                  <div key={type} className="grid grid-cols-[180px_1fr] gap-2 rounded border border-border/60 bg-card/40 p-2 text-xs">
                    <span className="font-mono">{type}</span>
                    <span>{items.length ? `${items.length} event(s) · latest ${items[items.length - 1]?.at}` : "not emitted"}</span>
                  </div>
                );
              })}
            </div>
          </details>
        ))}
        {!mission.providers.length ? <EmptyState>No provider-linked events for this mission.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function MissionAtlasJourney({ mission }: { mission: MissionView }) {
  const stages = ["batch_queue_received", "atlas_batch_received", "signal_loading", "signal_state", "behavior", "memory_lookup", "similarity", "vector_search", "reasoning", "report", "persistence"];
  return (
    <EnterpriseWidget title="Atlas journey" summary="Atlas events linked by batch_id, signal_batch_id or report_id when emitted">
      <div className="space-y-2">
        {stages.map((stage) => {
          const items = mission.atlas.filter((event) =>
            text(event.op.stage).includes(stage) || text(event.op.event_type).includes(stage) || text(event.op.event_type).includes(stage.replace("_", "")),
          );
          const warnings = items.filter((event) => ["WARN", "WARNING"].includes(text(event.op.severity).toUpperCase())).length;
          const errors = items.filter((event) => ["ERROR", "CRITICAL"].includes(text(event.op.severity).toUpperCase())).length;
          const duration = items.reduce((sum, event) => sum + num(event.op.duration_ms), 0);
          return (
            <details key={stage} open={items.length > 0} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
              <summary className="cursor-pointer">
                <span className="font-medium capitalize">{stage.replaceAll("_", " ")}</span>
                <span className="ml-2"><Pill value={items.length ? errors ? "error" : warnings ? "warning" : "observed" : "not linked"} /></span>
              </summary>
              <div className="mt-3 grid gap-2 text-xs md:grid-cols-4">
                <Datum label="Events" value={items.length} />
                <Datum label="Duration" value={duration ? `${duration} ms` : "not emitted"} />
                <Datum label="Warnings" value={warnings} />
                <Datum label="Errors" value={errors} />
                <Datum label="Confidence" value={atlasConfidence(items)} />
              </div>
            </details>
          );
        })}
        {!mission.atlas.length ? <EmptyState>No Atlas batch/report events are linked to this mission in the current event window.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function MissionDiagnosticsPanel({ mission }: { mission: MissionView }) {
  return (
    <EnterpriseWidget title="Mission diagnostics" summary="Deterministic diagnostics from event type, severity, duration, coverage and emitted counters">
      <div className="space-y-2">
        {mission.diagnostics.map((item) => <InsightLine key={`${item.title}-${item.detail}`} item={item} />)}
        {!mission.diagnostics.length ? <EmptyState>No deterministic mission diagnostics in the current event window.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function MissionReplayPanel({ mission, replayIndex, setReplayIndex, replayEvent }: { mission: MissionView; replayIndex: number; setReplayIndex: (value: number) => void; replayEvent?: MissionEvent }) {
  const jumpTo = (predicate: (event: MissionEvent) => boolean) => {
    const next = mission.events.findIndex(predicate);
    if (next >= 0) setReplayIndex(next);
  };
  return (
    <EnterpriseWidget title="Mission replay" summary="Visualization-only replay using operational events; no backend replay">
      <div className="mb-3 flex flex-wrap gap-2">
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50" disabled={replayIndex <= 0} onClick={() => setReplayIndex(Math.max(0, replayIndex - 1))}>Previous event</button>
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50" disabled={replayIndex >= mission.events.length - 1} onClick={() => setReplayIndex(Math.min(mission.events.length - 1, replayIndex + 1))}>Next event</button>
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => jumpTo((event) => Boolean(event.op.stage))}>Jump to stage</button>
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => jumpTo((event) => text(event.op.severity).toUpperCase() === "ERROR" || text(event.op.event_type).includes("failed"))}>Jump to error</button>
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => jumpTo((event) => Boolean(event.op.provider))}>Jump to provider</button>
        <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => jumpTo((event) => Boolean(event.op.report_id))}>Jump to report</button>
      </div>
      {replayEvent ? (
        <div className="rounded-lg border border-border bg-background/30 p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs">{replayIndex + 1}/{mission.events.length}</span>
            <Pill value={text(replayEvent.op.severity, "INFO")} />
            <span className="font-medium">{text(replayEvent.op.event_type)}</span>
            <span className="text-xs text-muted-foreground">{replayEvent.at}</span>
          </div>
          <div className="mt-3 grid gap-2 text-xs md:grid-cols-4">
            <Datum label="Stage" value={text(replayEvent.op.stage)} />
            <Datum label="Provider" value={text(replayEvent.op.provider)} />
            <Datum label="Competition" value={text(replayEvent.op.competition)} />
            <Datum label="Season" value={text(replayEvent.op.season)} />
            <Datum label="Job" value={text(replayEvent.op.job_id)} />
            <Datum label="Report" value={text(replayEvent.op.report_id)} />
            <Datum label="Previous" value={text(replayEvent.op.previous_state)} />
            <Datum label="Current" value={text(replayEvent.op.current_state)} />
          </div>
          <pre className="mt-3 max-h-52 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify(replayEvent.row, null, 2)}</pre>
        </div>
      ) : <EmptyState>No replay event selected.</EmptyState>}
    </EnterpriseWidget>
  );
}

function MissionActionsPanel({ mission }: { mission: MissionView }) {
  const actions = ["Restart", "Cancel", "Persist", "Reprocess", "Regenerate Signals", "Recalculate Atlas", "Export Timeline", "Create Ticket"];
  return (
    <EnterpriseWidget title="Mission actions" summary="Read-only action catalog. Controls remain disabled until IOC-CONTROL.">
      <div className="grid gap-2 md:grid-cols-4">
        {actions.map((action) => (
          <button key={action} disabled className="rounded-lg border border-border bg-background/30 p-3 text-left text-xs opacity-60">
            <span className="font-medium">{action}</span>
            <p className="mt-1 text-muted-foreground">Disabled · IOC-CONTROL required · mission {mission.missionId.slice(0, 18)}…</p>
          </button>
        ))}
      </div>
    </EnterpriseWidget>
  );
}

function ProviderMatrixTab({ sources }: { sources: Row[] }) {
  const [sort, setSort] = useState("health_score");
  const scored = useMemo(() => sources.map((source) => {
    const jobs = num(source.jobs);
    const failures = num(source.failures);
    const contribution = num(source.contribution ?? source.records_validated);
    const success = source.success_rate == null ? (jobs ? (jobs - failures) / jobs : 0) : num(source.success_rate);
    const healthPenalty = ["deprecated", "blocked"].includes(String(source.status).toLowerCase()) ? 30 : 0;
    const score = Math.max(0, Math.min(100, Math.round(success * 100 - healthPenalty - (contribution ? 0 : 20))));
    return { source, score, contribution, failures, latency: num(source.average_latency_ms), success };
  }).sort((a, b) => {
    if (sort === "latency") return a.latency - b.latency;
    if (sort === "contribution") return b.contribution - a.contribution;
    if (sort === "failures") return b.failures - a.failures;
    return b.score - a.score;
  }), [sources, sort]);
  return (
    <EnterpriseWidget title="Provider matrix" summary="Sortable provider availability, coverage, contribution and health score" filterPlaceholder="Filter provider">
      <div className="mb-3 flex flex-wrap gap-2">
        {["health_score", "contribution", "latency", "failures"].map((key) => (
          <button key={key} onClick={() => setSort(key)} className={cn("rounded border px-2 py-1 text-xs", sort === key ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-card")}>sort {key}</button>
        ))}
      </div>
      <div className="overflow-auto">
        <table className="w-full min-w-[980px] text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              {["Provider", "Availability", "Latency", "Coverage", "Competitions", "Seasons", "Signals", "Failures", "Fallbacks", "Contribution", "Atlas", "Health"].map((head) => <th key={head} className="border-b border-border p-2">{head}</th>)}
            </tr>
          </thead>
          <tbody>
            {scored.map(({ source, score, contribution, failures, latency }) => (
              <tr key={String(source.name)} className="border-b border-border/50">
                <td className="p-2 font-medium">{text(source.name)}</td>
                <td className="p-2"><Pill value={source.enabled ? text(source.health, "enabled") : "disabled"} /></td>
                <td className="p-2 font-mono">{latency || "—"} ms</td>
                <td className="p-2">{Array.isArray(source.themes) ? (source.themes as unknown[]).join(", ") : "—"}</td>
                <td className="p-2">{text(source.competition_coverage, "not emitted")}</td>
                <td className="p-2">{text(source.season_coverage, "not emitted")}</td>
                <td className="p-2">{text(source.signal_contribution, "not emitted")}</td>
                <td className="p-2 font-mono">{failures}</td>
                <td className="p-2">{text(source.fallback_count, "not emitted")}</td>
                <td className="p-2 font-mono">{contribution}</td>
                <td className="p-2 font-mono">{contribution}</td>
                <td className="p-2"><span className="font-mono">{score}%</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </EnterpriseWidget>
  );
}

function OperationalTimelineTab({ events, tickets, executions }: { events: Row[]; tickets: Row[]; executions: Row[] }) {
  const [filter, setFilter] = useState("");
  const timeline = useMemo(() => [
    ...events.map((event) => {
      const op = operationalEvent(event);
      return {
        kind: "event",
        at: text(op?.timestamp, text(event.timestamp)),
        severity: text(op?.severity, text(event.severity, text(event.status))),
        component: text(op?.service, text(event.service, "platform")),
        title: text(op?.event_type, text(event.message, text(event.event_type))),
        row: event,
        op,
      };
    }),
    ...tickets.map((ticket) => ({ kind: "ticket", at: text(ticket.last_seen_at, text(ticket.first_seen_at)), severity: text(ticket.severity), component: text(ticket.source, "ticket"), title: text(ticket.error_type, text(ticket.reason)), row: ticket })),
    ...executions.map((execution) => ({ kind: "mission", at: text(execution.started_at, text(execution.created_at)), severity: text(execution.state), component: "mission", title: text(execution.pipeline_name, text(execution.execution_id)), row: execution })),
  ].filter((item) => JSON.stringify(item).toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => String(b.at).localeCompare(String(a.at))), [events, tickets, executions, filter]);
  return (
    <EnterpriseWidget title="Unified operational timeline" summary="Execution ledger: missions, providers, progress, stages, diagnostics, Atlas processing and reports" filterPlaceholder="Filter mission, competition, season, provider, worker, dataset, signal, report, severity, correlation, state or stage" onFilter={setFilter}>
      <div className="space-y-2">
        {timeline.slice(0, 80).map((item, index) => {
          const op = ("op" in item ? item.op : undefined) as Row | undefined;
          return (
            <details key={`${item.kind}-${index}`} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
              <summary className="cursor-pointer">
                <span className="mr-2 font-mono text-xs text-muted-foreground">{item.at}</span>
                <Pill value={item.severity} />
                <span className="ml-2 text-muted-foreground">{item.component}</span>
                <span className="ml-2">{item.title}</span>
                {op ? <span className="ml-2 font-mono text-[11px] text-muted-foreground">{text(op.previous_state)} → {text(op.current_state)}</span> : null}
              </summary>
              {op ? (
                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
                  <Datum label="Schema" value={text(op.schema_version)} />
                  <Datum label="Mission" value={text(op.mission_id, "—")} />
                  <Datum label="Job" value={text(op.job_id, "—")} />
                  <Datum label="Correlation" value={text(op.correlation_id, "—")} />
                  <Datum label="Stage" value={text(op.stage, "—")} />
                  <Datum label="Competition" value={text(op.competition, "—")} />
                  <Datum label="Season" value={text(op.season, "—")} />
                  <Datum label="Provider" value={text(op.provider, "—")} />
                  <Datum label="Dataset" value={text(op.dataset_id, "—")} />
                  <Datum label="Batch" value={text(op.batch_id, "—")} />
                  <Datum label="Signal batch" value={text(op.signal_batch_id, "—")} />
                  <Datum label="Report" value={text(op.report_id, "—")} />
                  <Datum label="Worker" value={text(op.worker_id, "—")} />
                  <Datum label="Operator" value={text(op.operator_id, "—")} />
                  <Datum label="Duration" value={op.duration_ms == null ? "—" : `${op.duration_ms} ms`} />
                  <Datum label="Progress" value={progressSummary(op.progress as Row | undefined)} />
                </div>
              ) : null}
              <pre className="mt-3 max-h-52 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify(item.row, null, 2)}</pre>
            </details>
          );
        })}
        {!timeline.length ? <EmptyState>No timeline items match the current filter.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function progressSummary(progress?: Row): string {
  if (!progress || !Object.keys(progress).length) return "—";
  const percent = progress.total_progress ?? progress.current_progress;
  const steps = progress.completed_steps == null
    ? ""
    : `${progress.completed_steps}/${num(progress.completed_steps) + num(progress.remaining_steps)}`;
  const eta = progress.eta_seconds == null ? "" : `ETA ${Math.round(num(progress.eta_seconds) / 60)}m`;
  return [percent == null ? "" : `${Math.round(num(percent) * 100)}%`, steps, eta].filter(Boolean).join(" · ") || "—";
}

function operationalEvent(event: Row): Row | undefined {
  const metadata = event.metadata as Row | undefined;
  const op = metadata?.operational_event as Row | undefined;
  return op?.schema_version === "insight.operational_event.v1" ? op : undefined;
}

function buildMissionViews(events: Row[], executions: Row[]): MissionView[] {
  const canonical = events
    .map((row, index) => {
      const op = operationalEvent(row);
      if (!op) return null;
      return { row, op, at: text(op.timestamp, text(row.timestamp)), index } satisfies MissionEvent;
    })
    .filter(Boolean) as MissionEvent[];

  const grouped = new Map<string, MissionEvent[]>();
  for (const event of canonical) {
    const missionId = text(event.op.mission_id, "");
    if (!missionId) continue;
    grouped.set(missionId, [...(grouped.get(missionId) ?? []), event]);
  }
  for (const execution of executions) {
    const missionId = text(execution.execution_id ?? execution.mission_id ?? execution.run_id, "");
    if (!missionId || grouped.has(missionId)) continue;
    grouped.set(missionId, []);
  }

  const atlasByReport = new Map<string, MissionEvent[]>();
  const atlasByBatch = new Map<string, MissionEvent[]>();
  for (const event of canonical.filter((item) => text(item.op.service).toLowerCase() === "atlas")) {
    const reportId = text(event.op.report_id, "");
    const batchId = text(event.op.batch_id, "");
    const signalBatchId = text(event.op.signal_batch_id, "");
    if (reportId) atlasByReport.set(reportId, [...(atlasByReport.get(reportId) ?? []), event]);
    if (batchId) atlasByBatch.set(batchId, [...(atlasByBatch.get(batchId) ?? []), event]);
    if (signalBatchId) atlasByBatch.set(signalBatchId, [...(atlasByBatch.get(signalBatchId) ?? []), event]);
  }

  return [...grouped.entries()].map(([missionId, missionEvents]) => {
    const execution = executions.find((row) => text(row.execution_id ?? row.mission_id ?? row.run_id, "") === missionId);
    const sorted = [...missionEvents].sort((a, b) => a.at.localeCompare(b.at));
    const latest = sorted[sorted.length - 1];
    const first = sorted[0];
    const reportIds = unique(sorted.map((event) => text(event.op.report_id, ""))).filter(Boolean);
    const batchIds = unique(sorted.flatMap((event) => [text(event.op.batch_id, ""), text(event.op.signal_batch_id, "")])).filter(Boolean);
    const linkedAtlas = uniqueEvents([
      ...reportIds.flatMap((id) => atlasByReport.get(id) ?? []),
      ...batchIds.flatMap((id) => atlasByBatch.get(id) ?? []),
      ...sorted.filter((event) => text(event.op.service).toLowerCase() === "atlas"),
    ]).sort((a, b) => a.at.localeCompare(b.at));
    const allEvents = uniqueEvents([...sorted, ...linkedAtlas]).sort((a, b) => a.at.localeCompare(b.at));
    const progress = latest?.op.progress as Row | undefined;
    const status = missionStatus(sorted, execution);
    const startedAt = first?.at ?? text(execution?.started_at, text(execution?.created_at));
    const currentStage = text(latest?.op.stage, text(execution?.current, text(execution?.state, "unknown")));
    const diagnostics = missionDiagnostics(allEvents);
    const jobs = missionJobs(allEvents);
    const providers = missionProviders(allEvents);
    const health = diagnostics.some((item) => item.tone === "risk") ? "risk" : diagnostics.some((item) => item.tone === "watch") ? "watch" : "healthy";
    const risk = health === "risk" ? "high" : health === "watch" ? "medium" : "low";
    const current = latest?.op ?? {};
    const elapsed = startedAt !== "—" ? humanElapsed(startedAt, text(latest?.at, "")) : "not emitted";
    const etaSeconds = num(progress?.eta_seconds ?? execution?.eta_seconds);
    const expectedFinish = etaSeconds ? new Date(Date.now() + etaSeconds * 1000).toISOString() : text(progress?.estimated_completion, "not emitted");
    const missionType = text(first?.op.metadata && (first.op.metadata as Row).mission_type, text(execution?.mission_type, text(execution?.pipeline_name, "historical_collection")));
    return {
      missionId,
      missionType,
      owner: text((first?.op.metadata as Row | undefined)?.operator_owned ? "administrator" : first?.op.operator_id, "administrator-owned"),
      priority: text(execution?.priority, text((first?.op.metadata as Row | undefined)?.priority, "not emitted")),
      status,
      currentStage,
      progress: progressSummary(progress) !== "—" ? progressSummary(progress) : execution?.progress == null ? "not emitted" : `${Math.round(num(execution.progress) * 100)}%`,
      startedAt,
      eta: etaSeconds ? `${Math.round(etaSeconds / 60)}m` : text((execution?.estimate as Row | undefined)?.estimated_runtime, "not emitted"),
      elapsed,
      expectedFinish,
      currentProvider: text(current.provider, latestProvider(allEvents)),
      currentCompetition: text(current.competition, latestField(allEvents, "competition")),
      currentSeason: text(current.season, latestField(allEvents, "season")),
      currentWorker: text(current.worker_id, latestField(allEvents, "worker_id")),
      health,
      risk,
      summary: `${allEvents.length} event(s), ${jobs.length} job(s), ${providers.length} provider(s), stage ${currentStage}`,
      events: allEvents,
      stages: missionStages(allEvents, status),
      jobs,
      providers,
      atlas: linkedAtlas,
      diagnostics,
      reports: reportIds,
      batches: batchIds,
    };
  }).sort((a, b) => String(b.events[b.events.length - 1]?.at ?? "").localeCompare(String(a.events[a.events.length - 1]?.at ?? "")));
}

function missionStages(events: MissionEvent[], missionStatusValue: string): MissionStageView[] {
  const names = ["planning", "expansion", "collection", "parsing", "enrichment", "signal_generation", "atlas_ingest", "reasoning", "persistence", "completed"];
  return names.map((name) => {
    const items = events.filter((event) => stageMatches(event, name));
    const errors = items.filter((event) => text(event.op.severity).toUpperCase() === "ERROR" || text(event.op.event_type).includes("failed")).length;
    const warnings = items.filter((event) => ["WARN", "WARNING"].includes(text(event.op.severity).toUpperCase())).length;
    const retries = items.filter((event) => text(event.op.event_type).includes("retry")).length;
    const started = items[0]?.at;
    const finished = [...items].reverse().find((event) => /finished|completed|persisted|received|generated|acknowledged/.test(text(event.op.event_type)))?.at;
    const durationMs = items.reduce((sum, event) => sum + num(event.op.duration_ms), 0);
    const current = events[events.length - 1]?.op.stage;
    const status = items.length
      ? errors ? "error" : finished || name === "completed" && missionStatusValue === "completed" ? "completed" : current === name ? "running" : "observed"
      : "pending";
    return { name, status, started, finished, durationMs, retries, warnings, errors, events: items };
  });
}

function stageMatches(event: MissionEvent, name: string) {
  const stage = text(event.op.stage).toLowerCase();
  const type = text(event.op.event_type).toLowerCase();
  if (name === "expansion") return type.includes("expanded");
  if (name === "collection") return stage.includes("collect") || type.includes("collection") || type.includes("provider_request") || type.includes("raw_records");
  if (name === "atlas_ingest") return type.includes("atlas") || type.includes("batch");
  if (name === "completed") return type.includes("completed") || stage.includes("completed");
  return stage.includes(name) || type.includes(name);
}

function missionJobs(events: MissionEvent[]): MissionJobView[] {
  const byJob = new Map<string, MissionEvent[]>();
  for (const event of events) {
    const jobId = text(event.op.job_id, "");
    if (!jobId) continue;
    byJob.set(jobId, [...(byJob.get(jobId) ?? []), event]);
  }
  return [...byJob.entries()].map(([jobId, items]) => {
    const latest = items[items.length - 1]?.op ?? {};
    const metadata = items.flatMap((event) => [event.op.metadata as Row | undefined]).find(Boolean) ?? {};
    const errors = items.filter((event) => text(event.op.severity).toUpperCase() === "ERROR" || text(event.op.event_type).includes("failed")).length;
    const retries = items.filter((event) => text(event.op.event_type).includes("retry")).length;
    const fallbacks = items.filter((event) => text(event.op.event_type).includes("fallback")).length;
    const records = items.reduce((sum, event) => sum + num((event.op.metadata as Row | undefined)?.records ?? (event.op.metadata as Row | undefined)?.validated ?? (event.op.metadata as Row | undefined)?.raw_records), 0);
    const signals = items.reduce((sum, event) => sum + num((event.op.metadata as Row | undefined)?.signals ?? (event.op.metadata as Row | undefined)?.signals_generated), 0);
    return {
      jobId,
      provider: text(latest.provider, latestField(items, "provider")),
      competition: text(latest.competition, latestField(items, "competition")),
      season: text(latest.season, latestField(items, "season")),
      worker: text(latest.worker_id, latestField(items, "worker_id")),
      status: errors ? "failed" : text(latest.current_state, text(metadata.status, "observed")),
      progress: progressSummary(latest.progress as Row | undefined),
      durationMs: items.reduce((sum, event) => sum + num(event.op.duration_ms), 0),
      records,
      signals,
      errors,
      retries,
      fallbacks,
      events: items,
    };
  });
}

function missionProviders(events: MissionEvent[]) {
  const byProvider = new Map<string, MissionEvent[]>();
  for (const event of events) {
    const provider = text(event.op.provider, "");
    if (!provider) continue;
    byProvider.set(provider, [...(byProvider.get(provider) ?? []), event]);
  }
  return [...byProvider.entries()].map(([provider, items]) => {
    const failures = items.filter((event) => text(event.op.severity).toUpperCase() === "ERROR" || text(event.op.event_type).includes("failed") || text(event.op.event_type).includes("timeout")).length;
    const retries = items.filter((event) => text(event.op.event_type).includes("retry")).length;
    return {
      provider,
      events: items,
      status: failures ? "degraded" : "completed",
      durationMs: items.reduce((sum, event) => sum + num(event.op.duration_ms), 0),
      failures,
      retries,
    };
  });
}

function missionDiagnostics(events: MissionEvent[]): InsightItem[] {
  const diagnostics: InsightItem[] = [];
  const errors = events.filter((event) => text(event.op.severity).toUpperCase() === "ERROR" || text(event.op.event_type).includes("failed"));
  const timeouts = events.filter((event) => text(event.op.event_type).includes("timeout"));
  const slow = events.filter((event) => num(event.op.duration_ms) > 5000);
  const retries = events.filter((event) => text(event.op.event_type).includes("retry"));
  const rejected = events.filter((event) => text(event.op.event_type).includes("rejected"));
  const coverage = events.filter((event) => text(event.op.event_type).includes("coverage"));
  const signals = events.filter((event) => text(event.op.event_type).includes("signal"));
  const behaviors = events.filter((event) => text(event.op.event_type).includes("behavior"));
  const reasoningDelayed = events.filter((event) => text(event.op.stage).includes("reasoning") && num(event.op.duration_ms) > 5000);
  const lowConfidence = events.filter((event) => num((event.op.metadata as Row | undefined)?.confidence) > 0 && num((event.op.metadata as Row | undefined)?.confidence) < 0.5);
  if (errors.length) diagnostics.push({ title: "Mission failure event detected", detail: `${errors.length} error/failed event(s) in this mission window.`, tone: "risk" });
  if (timeouts.length) diagnostics.push({ title: "Provider timeout", detail: `${timeouts.length} timeout event(s) emitted.`, tone: "risk" });
  if (slow.length) diagnostics.push({ title: "Slow operation", detail: `${slow.length} event(s) exceeded 5 seconds duration.`, tone: "watch" });
  if (retries.length > 2) diagnostics.push({ title: "Too many retries", detail: `${retries.length} retry event(s) emitted.`, tone: "watch" });
  if (rejected.length) diagnostics.push({ title: "Rejected records", detail: `${rejected.length} rejection event(s) emitted.`, tone: "watch" });
  if (!coverage.length) diagnostics.push({ title: "Missing coverage update", detail: "No coverage update event is linked to this mission window.", tone: "neutral" });
  if (!signals.length) diagnostics.push({ title: "No signals linked", detail: "No signal generation event is linked to this mission window.", tone: "neutral" });
  if (!behaviors.length) diagnostics.push({ title: "No behaviors linked", detail: "No behavior event is linked to this mission window.", tone: "neutral" });
  if (reasoningDelayed.length) diagnostics.push({ title: "Reasoning delayed", detail: `${reasoningDelayed.length} reasoning event(s) exceeded 5 seconds.`, tone: "watch" });
  if (lowConfidence.length) diagnostics.push({ title: "Low confidence", detail: `${lowConfidence.length} low-confidence event(s) emitted.`, tone: "watch" });
  if (!diagnostics.length) diagnostics.push({ title: "Mission stream stable", detail: "No deterministic diagnostic rule fired for this mission.", tone: "good" });
  return diagnostics;
}

function missionStatus(events: MissionEvent[], execution?: Row) {
  const latest = events[events.length - 1]?.op;
  if (events.some((event) => text(event.op.event_type).includes("mission_completed"))) return "completed";
  if (events.some((event) => text(event.op.event_type).includes("mission_failed"))) return "failed";
  return text(latest?.current_state, text(execution?.state, "unknown"));
}

function latestField(events: MissionEvent[], field: string) {
  for (const event of [...events].reverse()) {
    const value = event.op[field];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return "not emitted";
}

function latestProvider(events: MissionEvent[]) {
  return latestField(events, "provider");
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function uniqueEvents(events: MissionEvent[]) {
  const seen = new Set<string>();
  return events.filter((event) => {
    const key = `${event.at}-${text(event.op.event_type)}-${text(event.op.mission_id)}-${text(event.op.report_id)}-${event.index}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function humanElapsed(start: string, end: string) {
  const started = Date.parse(start);
  const finished = Date.parse(end || new Date().toISOString());
  if (!Number.isFinite(started) || !Number.isFinite(finished)) return "not emitted";
  const seconds = Math.max(0, Math.round((finished - started) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function atlasConfidence(items: MissionEvent[]) {
  const values = items
    .map((event) => num((event.op.metadata as Row | undefined)?.confidence))
    .filter((value) => value > 0);
  if (!values.length) return "not emitted";
  return `${Math.round(100 * values.reduce((sum, value) => sum + value, 0) / values.length)}%`;
}

function withEventStates(services: Row[], events: Row[]): Row[] {
  const latest = new Map<string, Row>();
  for (const event of events) {
    const op = operationalEvent(event);
    if (!op?.service || !op.current_state) continue;
    const key = String(op.service).toLowerCase();
    if (!latest.has(key)) latest.set(key, op);
  }
  return services.map((service) => {
    const key = String(service.service ?? service.name ?? service.display_name ?? "").toLowerCase();
    const op = latest.get(key);
    if (!op) return service;
    return {
      ...service,
      operational_state: op.current_state,
      last_heartbeat: op.timestamp,
      detail: `${text(op.event_type)} (${text(op.schema_version)})`,
    };
  });
}

function ServiceRegistryPanel({ services }: { services: Row[] }) {
  return (
    <EnterpriseWidget title="IOC Service Registry" summary="Distributed service inventory across Robozão and Google Cloud" filterPlaceholder="Filter services">
      <div className="overflow-auto">
        <table className="w-full min-w-[1180px] text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              {["Service", "Environment", "Host", "Region", "Infrastructure", "Version", "Runtime", "State", "Heartbeat", "Dependencies", "Health", "Metrics", "Since", "Restarts"].map((head) => <th key={head} className="border-b border-border p-2">{head}</th>)}
            </tr>
          </thead>
          <tbody>
            {services.map((service) => (
              <tr key={`${service.domain}-${service.service}`} className="border-b border-border/50">
                <td className="p-2 font-medium">{text(service.display_name, text(service.service))}</td>
                <td className="p-2">{text(service.environment, "production")}</td>
                <td className="p-2">{text(service.host)}</td>
                <td className="p-2">{text(service.region)}</td>
                <td className="p-2">{text(service.infrastructure)}</td>
                <td className="p-2 font-mono">{text(service.version)}</td>
                <td className="p-2">{text(service.runtime)}</td>
                <td className="p-2"><Pill value={text(service.operational_state, text(service.status, "unknown"))} /></td>
                <td className="p-2">{text(service.last_heartbeat, text(service.detail))}</td>
                <td className="p-2">{Array.isArray(service.dependencies) ? (service.dependencies as unknown[]).join(", ") : "—"}</td>
                <td className="p-2">{text(service.health_endpoint, text(service.endpoint))}</td>
                <td className="p-2">{text(service.metrics_endpoint, "not exposed")}</td>
                <td className="p-2">{text(service.running_since)}</td>
                <td className="p-2 font-mono">{service.restart_count == null ? "not emitted" : text(service.restart_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </EnterpriseWidget>
  );
}

function LiveStatesPanel({ services }: { services: Row[] }) {
  return (
    <EnterpriseWidget title="Live service states" summary="Operational state, not just health">
      <div className="space-y-2">
        {services.map((service) => (
          <details key={`${service.domain}-${service.service}`} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
            <summary className="cursor-pointer">
              <span className="font-medium">{text(service.display_name, text(service.service))}</span>
              <span className="ml-2"><Pill value={text(service.operational_state, text(service.status, "unknown"))} /></span>
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">{text(service.detail)}</p>
          </details>
        ))}
      </div>
    </EnterpriseWidget>
  );
}

function CurrentActivityPanel({ services }: { services: Row[] }) {
  return (
    <EnterpriseWidget title="Current activity" summary="Operation, mission, job, provider, queue and worker where emitted">
      <div className="space-y-2">
        {services.map((service) => {
          const activity = service.current_activity as Row | undefined;
          return (
            <details key={`${service.domain}-${service.service}`} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
              <summary className="cursor-pointer">{text(service.display_name, text(service.service))} · {text(activity?.operation, text(service.operational_state))}</summary>
              <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
                <Datum label="Current operation" value={text(activity?.operation)} />
                <Datum label="Current mission" value={text(activity?.current_mission, "not emitted")} />
                <Datum label="Current job" value={text(activity?.current_job, "not emitted")} />
                <Datum label="Current provider" value={text(activity?.current_provider, "not emitted")} />
                <Datum label="Current queue" value={text(activity?.current_queue, "not emitted")} />
                <Datum label="Current worker" value={text(activity?.current_worker, "not emitted")} />
              </div>
            </details>
          );
        })}
      </div>
    </EnterpriseWidget>
  );
}

function OperationalMetricsPanel({ services }: { services: Row[] }) {
  const points = services.map((service) => ({ label: text(service.display_name, text(service.service)), value: num((service.metrics as Row | undefined)?.latency_ms ?? service.latency_ms) }));
  return (
    <EnterpriseWidget title="Operational metrics" summary="CPU, memory, latency, queues, retries and throughput where the service emits them">
      <MetricBars points={points} />
      <div className="mt-3 space-y-2">
        {services.map((service) => {
          const metrics = service.metrics as Row | undefined;
          return (
            <details key={`${service.domain}-${service.service}`} className="rounded-lg border border-border bg-background/30 p-3 text-xs">
              <summary className="cursor-pointer">{text(service.display_name, text(service.service))} · {text(service.metrics_summary)}</summary>
              <div className="mt-3 grid gap-2 md:grid-cols-4">
                <Datum label="CPU" value={metrics?.cpu_percent == null ? "not emitted" : `${metrics.cpu_percent}%`} />
                <Datum label="Memory" value={metrics?.memory_mb == null ? "not emitted" : `${metrics.memory_mb} MB`} />
                <Datum label="Disk" value={metrics?.disk_percent == null ? "not emitted" : `${metrics.disk_percent}%`} />
                <Datum label="Network" value={text(metrics?.network, "not emitted")} />
                <Datum label="Latency" value={metrics?.latency_ms == null ? text(service.latency_ms, "not emitted") : `${metrics.latency_ms} ms`} />
                <Datum label="Throughput" value={text(metrics?.throughput, "not emitted")} />
                <Datum label="Queue size" value={text(metrics?.queue_size, "not emitted")} />
                <Datum label="Retry count" value={text(metrics?.retry_count, "not emitted")} />
                <Datum label="Error count" value={text(metrics?.error_count, "not emitted")} />
                <Datum label="Warnings" value={text(metrics?.warning_count, "not emitted")} />
                <Datum label="Events/sec" value={text(metrics?.events_per_sec, "not emitted")} />
                <Datum label="Jobs/sec" value={text(metrics?.jobs_per_sec, "not emitted")} />
                <Datum label="Records/sec" value={text(metrics?.records_per_sec, "not emitted")} />
                <Datum label="Signal/sec" value={text(metrics?.signals_per_sec, "not emitted")} />
                <Datum label="Vector/sec" value={text(metrics?.vectors_per_sec, "not emitted")} />
              </div>
            </details>
          );
        })}
      </div>
    </EnterpriseWidget>
  );
}

function CommunicationGraphPanel({ services }: { services: Row[] }) {
  const edges = services.flatMap((service) =>
    Array.isArray(service.dependencies)
      ? (service.dependencies as unknown[]).map((dep) => ({ from: text(service.service), to: String(dep), status: text(service.status, "unknown") }))
      : [],
  );
  return (
    <EnterpriseWidget title="Live communication graph" summary="Service relationships from registry dependencies">
      <div className="space-y-2">
        {edges.map((edge) => (
          <div key={`${edge.from}-${edge.to}`} className="flex items-center gap-2 rounded-lg border border-border bg-background/30 p-2 text-sm">
            <span className="font-mono">{edge.from}</span>
            <span className="text-muted-foreground">→</span>
            <span className="font-mono">{edge.to}</span>
            <Pill value={edge.status} />
          </div>
        ))}
        {!edges.length ? <EmptyState>No service dependency edges emitted.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function HealthTimelinePanel({ services }: { services: Row[] }) {
  return (
    <EnterpriseWidget title="Health timeline" summary="Heartbeat, restart, deployment and recovery evidence where available">
      <div className="space-y-2">
        {services.map((service) => (
          <details key={`${service.domain}-${service.service}`} className="rounded-lg border border-border bg-background/30 p-3 text-sm">
            <summary className="cursor-pointer">{text(service.display_name, text(service.service))} · <Pill value={text(service.health, "unknown")} /></summary>
            <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
              <Datum label="Last heartbeat" value={text(service.last_heartbeat, text(service.detail))} />
              <Datum label="Last restart" value="not emitted" />
              <Datum label="Last deployment" value={text(service.version, "not emitted")} />
              <Datum label="Last failure" value={String(service.status) === "healthy" ? "none in current snapshot" : text(service.detail)} />
              <Datum label="Last warning" value={String(service.status) === "degraded" ? text(service.detail) : "none in current snapshot"} />
              <Datum label="Last recovery" value="not emitted" />
              <Datum label="Current uptime" value={service.running_since ? `since ${text(service.running_since)}` : "not emitted"} />
              <Datum label="Restart history" value={service.restart_count == null ? "not emitted" : text(service.restart_count)} />
            </div>
          </details>
        ))}
      </div>
    </EnterpriseWidget>
  );
}

function IocAlertsPanel({ services }: { services: Row[] }) {
  const alerts = services.flatMap((service) => {
    const out: InsightItem[] = [];
    const metrics = service.metrics as Row | undefined;
    if (!["healthy", "up"].includes(String(service.status))) out.push({ title: `${text(service.display_name, text(service.service))} is ${text(service.status)}`, detail: text(service.detail), tone: String(service.status) === "degraded" ? "watch" : "risk" });
    if (num(metrics?.retry_count) > 0) out.push({ title: `${text(service.display_name)} retries detected`, detail: `${num(metrics?.retry_count)} retry event(s).`, tone: "watch" });
    if (num(metrics?.error_count) > 0) out.push({ title: `${text(service.display_name)} errors detected`, detail: `${num(metrics?.error_count)} error event(s).`, tone: "risk" });
    if (!service.last_heartbeat && String(service.domain) === "robozao") out.push({ title: `${text(service.display_name)} heartbeat missing`, detail: "No heartbeat emitted in current service snapshot.", tone: "watch" });
    return out;
  });
  return (
    <EnterpriseWidget title="Deterministic alerts" summary="Heartbeat, health, retry, error and provider degradation rules">
      <div className="space-y-2">
        {alerts.map((alert) => <InsightLine key={`${alert.title}-${alert.detail}`} item={alert} />)}
        {!alerts.length ? <EmptyState>No deterministic IOC alerts in the current snapshot.</EmptyState> : null}
      </div>
    </EnterpriseWidget>
  );
}

function CoverageCenterTab({ explorer, atlas, executions, sources }: { explorer: Row; atlas: Row; executions: Row[]; sources: Row[] }) {
  const competitions = new Map<string, number>();
  const seasons = new Map<string, number>();
  for (const execution of executions) {
    for (const item of Array.isArray(execution.completed_tasks) ? execution.completed_tasks as unknown[] : []) {
      if (Array.isArray(item)) {
        competitions.set(String(item[0]), (competitions.get(String(item[0])) ?? 0) + 1);
        seasons.set(String(item[1]), (seasons.get(String(item[1])) ?? 0) + 1);
      }
    }
  }
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <EnterpriseWidget title="Coverage by provider" summary="Provider contribution and data categories">
        <MetricBars points={sources.map((source) => ({ label: text(source.name), value: num(source.contribution ?? source.records_validated) }))} />
      </EnterpriseWidget>
      <EnterpriseWidget title="Coverage by competition" summary="Completed task counts from mission evidence">
        <MetricBars points={[...competitions.entries()].map(([label, value]) => ({ label, value }))} />
        {!competitions.size ? <EmptyState>Competition-level coverage is not emitted in current mission evidence.</EmptyState> : null}
      </EnterpriseWidget>
      <EnterpriseWidget title="Coverage by season" summary="Season counts from mission evidence">
        <MetricBars points={[...seasons.entries()].map(([label, value]) => ({ label, value }))} />
        {!seasons.size ? <EmptyState>Season-level coverage is not emitted in current mission evidence.</EmptyState> : null}
      </EnterpriseWidget>
      <EnterpriseWidget title="Coverage by intelligence artifact" summary="Signals, behaviors, memories and vectors">
        <MetricBars points={[
          { label: "signals", value: num(atlas.signals) },
          { label: "behaviors", value: num(atlas.behaviors) },
          { label: "memories", value: num(atlas.memories) },
          { label: "vectors", value: num(atlas.vectors) },
          { label: "datasets", value: executions.filter((e) => Array.isArray(e.datasets) && (e.datasets as unknown[]).length).length },
        ]} />
      </EnterpriseWidget>
      <EnterpriseWidget title="Coverage gaps" summary="Deterministic gaps from provider contribution and emitted fields">
        <div className="space-y-2">
          {sources.filter((source) => num(source.contribution ?? source.records_validated) === 0).map((source) => <InsightLine key={String(source.name)} item={{ title: `${text(source.name)} has zero contribution`, detail: `Status ${text(source.status)} · health ${text(source.health)}.`, tone: "watch" }} />)}
          {!sources.some((source) => num(source.contribution ?? source.records_validated) === 0) ? <EmptyState>No zero-contribution provider gap detected.</EmptyState> : null}
          {!explorer.coverage_by_team ? <InsightLine item={{ title: "Team coverage not emitted", detail: "The current Explorer dashboard does not emit team-level coverage yet.", tone: "neutral" }} /> : null}
        </div>
      </EnterpriseWidget>
    </div>
  );
}

function ExecutiveSummary({ items, risk }: { items: InsightItem[]; risk: InsightItem }) {
  const t = useT("operations");
  return (
    <section className="rounded-xl border border-primary/20 bg-primary/[0.04] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold"><CheckCircle2 className="h-4 w-4 text-primary" /> {t("executiveSummary")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t("executiveSummarySubtitle")}</p>
        </div>
        <Pill value={risk.tone === "risk" ? "risk" : risk.tone === "watch" ? "watch" : "stable"} />
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => <InsightCard key={item.title} item={item} />)}
      </div>
    </section>
  );
}

function OperationalInsights({ items }: { items: InsightItem[] }) {
  return (
    <Panel title="Operational insights">
      <div className="space-y-2">
        {items.map((item) => <InsightLine key={item.title} item={item} />)}
        {!items.length ? <EmptyState>No deterministic insights available yet.</EmptyState> : null}
      </div>
    </Panel>
  );
}

function RecommendedActions({ items }: { items: InsightItem[] }) {
  return (
    <Panel title="Recommended actions">
      <div className="space-y-2">
        {items.map((item) => <InsightLine key={item.title} item={item} />)}
        {!items.length ? <EmptyState>No operator action required by current telemetry.</EmptyState> : null}
      </div>
    </Panel>
  );
}

function ReadinessDashboard({ items }: { items: ReadinessItem[] }) {
  const average = items.length ? items.reduce((sum, item) => sum + item.score, 0) / items.length : 0;
  return (
    <Panel title={`Readiness dashboard · ${pct(average)}`}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {items.map((item) => (
          <div key={item.label} className="rounded-lg border border-border bg-background/30 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium">{item.label}</span>
              <span className="font-mono text-sm">{pct(item.score)}</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className={cn("h-full", item.score >= 80 ? "bg-emerald-400" : item.score >= 50 ? "bg-amber-400" : "bg-red-400")} style={{ width: pct(item.score) }} />
            </div>
            {item.blocker ? <p className="mt-2 text-[11px] text-muted-foreground">{item.blocker}</p> : null}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function MissionIntelligencePanel({ active, executions }: { active: Row[]; executions: Row[] }) {
  const selected = active[0] ?? executions[0];
  const estimate = selected?.estimate as Row | undefined;
  const ingestion = selected?.atlas_ingestion as Row | undefined;
  const tasks = Array.isArray(selected?.completed_tasks) ? selected.completed_tasks as unknown[] : [];
  return (
    <Panel title="Mission intelligence">
      {selected ? (
        <details open className="text-sm">
          <summary className="cursor-pointer">
            <span className="font-mono">{text(selected.execution_id ?? selected.run_id)}</span>
            <span className="ml-2"><Pill value={text(selected.state, "unknown")} /></span>
          </summary>
          <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
            <Datum label="Planner" value={text(selected.pipeline_name, "mission planner")} />
            <Datum label="Jobs" value={`${num(selected.jobs_completed)}/${num(selected.jobs_total) || num((estimate as Row)?.source_jobs) || "—"}`} />
            <Datum label="Progress" value={`${(num(selected.progress) * 100).toFixed(1)}%`} />
            <Datum label="ETA" value={selected.eta_seconds ? `${Math.round(num(selected.eta_seconds) / 60)}m` : text((estimate as Row)?.estimated_runtime)} />
            <Datum label="Current stage" value={text(selected.current, "not emitted")} />
            <Datum label="Provider" value={text(selected.current_provider, "not emitted")} />
            <Datum label="Retries" value={num(selected.retries)} />
            <Datum label="Fallbacks" value={num(selected.fallbacks)} />
            <Datum label="Signals generated" value={text(selected.signals_generated, "not emitted")} />
            <Datum label="Atlas ingest" value={text(ingestion?.status, "not reported")} />
            <Datum label="Persistence" value={text(selected.persistence_status, selected.generation_root ? "dataset persisted" : "not reported")} />
            <Datum label="Timeline entries" value={tasks.length} />
          </div>
          <pre className="mt-3 max-h-48 overflow-auto rounded bg-background/60 p-2 text-[11px] text-muted-foreground">{JSON.stringify({ estimate, atlas_ingestion: ingestion, completed_tasks: tasks.slice(0, 8) }, null, 2)}</pre>
        </details>
      ) : <EmptyState>No mission executions reported.</EmptyState>}
    </Panel>
  );
}

function ProviderIntelligencePanel({ sources }: { sources: Row[] }) {
  return (
    <Panel title="Provider intelligence">
      {sources.map((source) => {
        const failures = num(source.failures);
        const jobs = num(source.jobs);
        const contribution = num(source.contribution ?? source.records_validated);
        const failureRate = jobs ? failures / jobs : 0;
        return (
          <details key={String(source.name)} className="border-b border-border/50 py-2 text-sm last:border-0">
            <summary className="cursor-pointer">
              <span className="font-medium">{text(source.name)}</span>
              <span className="ml-2 inline-flex gap-1"><Pill value={text(source.status)} /><Pill value={text(source.health)} /></span>
            </summary>
            <div className="mt-3 grid gap-2 text-xs md:grid-cols-3">
              <Datum label="Availability" value={source.enabled ? "enabled" : "disabled"} />
              <Datum label="Latency" value={source.average_latency_ms == null ? "—" : `${source.average_latency_ms} ms`} />
              <Datum label="Coverage" value={Array.isArray(source.themes) ? (source.themes as unknown[]).join(", ") : "not emitted"} />
              <Datum label="Success rate" value={source.success_rate == null ? "—" : `${(num(source.success_rate) * 100).toFixed(1)}%`} />
              <Datum label="Failure rate" value={`${(failureRate * 100).toFixed(1)}%`} />
              <Datum label="Fallback count" value={text(source.fallback_count, "not emitted")} />
              <Datum label="Last success" value={text(source.last_success_at, "not emitted")} />
              <Datum label="Last failure" value={text(source.last_failure_at, "not emitted")} />
              <Datum label="Atlas contribution" value={contribution} />
              <Datum label="Signal contribution" value={text(source.signal_contribution, "not emitted")} />
              <Datum label="Competition coverage" value={text(source.competition_coverage, "not emitted")} />
              <Datum label="Season coverage" value={text(source.season_coverage, "not emitted")} />
            </div>
          </details>
        );
      })}
      {!sources.length ? <EmptyState>No providers reported.</EmptyState> : null}
    </Panel>
  );
}

function InsightCard({ item }: { item: InsightItem }) {
  return <div className={cn("rounded-xl border p-3", toneClass(item.tone))}><p className="text-xs font-semibold">{item.title}</p><p className="mt-1 text-xs text-muted-foreground">{item.detail}</p></div>;
}

function InsightLine({ item }: { item: InsightItem }) {
  return <div className="rounded-lg border border-border bg-background/30 p-3"><div className="flex items-start gap-2"><AlertTriangle className={cn("mt-0.5 h-3.5 w-3.5", item.tone === "risk" ? "text-red-400" : item.tone === "watch" ? "text-amber-400" : "text-emerald-400")} /><div><p className="text-sm font-medium">{item.title}</p><p className="text-xs text-muted-foreground">{item.detail}</p></div></div></div>;
}

function toneClass(tone: InsightItem["tone"]) {
  if (tone === "good") return "border-emerald-500/20 bg-emerald-500/[0.05]";
  if (tone === "watch") return "border-amber-500/20 bg-amber-500/[0.05]";
  if (tone === "risk") return "border-red-500/20 bg-red-500/[0.05]";
  return "border-border bg-card/60";
}

function intelligenceStats(events: Row[], atlas: Row) {
  const atlasEvents = events.filter((event) => !event.service || event.service === "atlas");
  const metadata = atlasEvents.map((event) => event.metadata as Row | undefined).filter(Boolean) as Row[];
  const mean = (keys: string[]) => {
    const values = metadata.flatMap((item) => keys.map((key) => item[key])).filter((value) => typeof value === "number") as number[];
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  };
  return {
    reasoning: atlasEvents.filter((event) => String(event.event_type).includes("reason")).length,
    conflicts: atlasEvents.reduce((sum, event) => sum + (String(event.event_type).includes("conflict") ? 1 : num((event.metadata as Row)?.conflicts)), 0),
    uncertainty: mean(["uncertainty", "mean_uncertainty"]),
    confidence: mean(["confidence", "mean_confidence"]),
    behaviors: num(atlas.behaviors),
    signals: num(atlas.signals),
  };
}

function operationalIntelligence({
  infrastructure, explorer, atlas, executions, tickets, events, dlq, stats,
}: {
  infrastructure?: Row; explorer: Row; atlas: Row; executions: Row[]; tickets: Row[]; events: Row[]; dlq: Row[]; stats: ReturnType<typeof intelligenceStats>;
}) {
  const domains = infrastructure?.domains as Record<string, Row[]> | undefined;
  const services = [...(domains?.robozao ?? []), ...(domains?.google_cloud ?? [])];
  const degradedServices = services.filter((service) => !["healthy", "up"].includes(String(service.status)));
  const sources = Array.isArray(explorer.sources) ? explorer.sources as Row[] : [];
  const unhealthySources = sources.filter((source) =>
    !["online", "healthy", "up"].includes(String(source.health).toLowerCase()) || ["blocked", "deprecated"].includes(String(source.status).toLowerCase()),
  );
  const zeroContribution = sources.filter((source) => num(source.contribution ?? source.records_validated) === 0);
  const activeExecutions = executions.filter((item) => ["pending", "running", "paused"].includes(String(item.state)));
  const openTickets = tickets.filter((ticket) => String(ticket.status).toLowerCase() !== "resolved");
  const highTickets = openTickets.filter((ticket) => ["high", "critical"].includes(String(ticket.severity).toLowerCase()));
  const failedEvents = events.filter((event) => ["error", "critical", "failed"].some((value) => `${event.severity ?? ""} ${event.status ?? ""} ${event.event_type ?? ""}`.toLowerCase().includes(value)));
  const atlasTotal = num(atlas.memories) + num(atlas.vectors) + num(atlas.behaviors) + num(atlas.signals);
  const records = sources.reduce((sum, source) => sum + num(source.records_validated ?? source.contribution), 0);

  const risk: InsightItem =
    highTickets.length || degradedServices.length || failedEvents.length
      ? { title: "Operational risk", detail: `${highTickets.length} high tickets, ${degradedServices.length} degraded services, ${failedEvents.length} failure events.`, tone: "risk" }
      : unhealthySources.length || zeroContribution.length
        ? { title: "Operational risk", detail: `${unhealthySources.length} provider(s) need review; ${zeroContribution.length} provider(s) have zero contribution.`, tone: "watch" }
        : { title: "Operational risk", detail: "No high-risk condition detected in current telemetry.", tone: "good" };

  const summary: InsightItem[] = [
    { title: "Explorer", detail: `${num(explorer.active_jobs)} active job(s), ${num(explorer.failed_jobs)} failed job(s), ${records} validated provider records.`, tone: num(explorer.failed_jobs) ? "risk" : num(explorer.active_jobs) ? "good" : "neutral" },
    { title: "Atlas", detail: `${atlasTotal} intelligence records: ${num(atlas.signals)} signals, ${num(atlas.behaviors)} behaviors, ${num(atlas.memories)} memories, ${num(atlas.vectors)} vectors.`, tone: atlasTotal ? "good" : "watch" },
    { title: "Current mission", detail: activeExecutions.length ? `${activeExecutions.length} active mission execution(s).` : "No active mission execution reported by Mission Center.", tone: activeExecutions.length ? "good" : "watch" },
    { title: "Platform health", detail: `${services.length - degradedServices.length}/${services.length} services healthy.`, tone: degradedServices.length ? "risk" : "good" },
    risk,
    { title: "Operator focus", detail: recommendedActionHeadline({ highTickets, unhealthySources, zeroContribution, activeExecutions, atlas }), tone: highTickets.length || unhealthySources.length ? "watch" : "good" },
  ];

  const insights: InsightItem[] = [
    { title: "Atlas ingestion is populated", detail: `${num(atlas.batches)} batch(es), latest ${text(atlas.last_ingested_at, "not reported")}.`, tone: num(atlas.batches) ? "good" : "watch" },
    { title: "Signal production", detail: `${num(atlas.signals)} signals and ${num(atlas.behaviors)} behavior observations are available to Atlas.`, tone: num(atlas.signals) && num(atlas.behaviors) ? "good" : "watch" },
    { title: "Provider contribution", detail: `${zeroContribution.length} provider(s) currently contribute zero records.`, tone: zeroContribution.length ? "watch" : "good" },
    { title: "Operations history", detail: `${events.length} recent events and ${failedEvents.length} deterministic failure event(s) in the current window.`, tone: failedEvents.length ? "risk" : "good" },
    { title: "DLQ", detail: dlq.length ? `${dlq.length} unreplayed message(s).` : "No unreplayed DLQ messages returned by the current endpoint.", tone: dlq.length ? "risk" : "good" },
    { title: "Confidence telemetry", detail: stats.confidence == null && stats.uncertainty == null ? "Confidence/uncertainty distributions are not emitted in operations events yet." : `Confidence ${stats.confidence}, uncertainty ${stats.uncertainty}.`, tone: stats.confidence == null ? "watch" : "good" },
  ];

  const actions: InsightItem[] = [];
  if (highTickets.length) actions.push({ title: "Review high-priority tickets", detail: `${highTickets.length} high/critical ticket(s) are still open.`, tone: "risk" });
  if (unhealthySources.length) actions.push({ title: "Inspect degraded providers", detail: unhealthySources.map((source) => text(source.name)).join(", "), tone: "watch" });
  if (zeroContribution.length) actions.push({ title: "Review zero-contribution sources", detail: zeroContribution.map((source) => text(source.name)).join(", "), tone: "watch" });
  if (!activeExecutions.length && num(explorer.active_jobs)) actions.push({ title: "Reconcile mission state", detail: "Explorer reports active jobs, but Mission Center has no active execution row.", tone: "watch" });
  if (!num(atlas.signals)) actions.push({ title: "Validate signal ingestion", detail: "Atlas reports zero ingested signals.", tone: "risk" });
  if (!actions.length) actions.push({ title: "Continue monitoring", detail: "No deterministic corrective action is required by current telemetry.", tone: "good" });

  const providerScore = sources.length ? 100 * (sources.length - unhealthySources.length) / sources.length : 0;
  const ticketScore = Math.max(0, 100 - openTickets.length * 8 - highTickets.length * 12);
  const readiness: ReadinessItem[] = [
    { label: "Explorer", score: num(explorer.failed_jobs) ? 65 : num(explorer.active_jobs) ? 90 : 75, blocker: num(explorer.failed_jobs) ? "failed jobs reported" : undefined },
    { label: "Atlas", score: atlasTotal ? 90 : 30, blocker: atlasTotal ? undefined : "no intelligence counts" },
    { label: "Signals", score: num(atlas.signals) ? 90 : 20, blocker: num(atlas.signals) ? undefined : "signals missing" },
    { label: "Memory", score: num(atlas.memories) ? 90 : 25, blocker: num(atlas.memories) ? undefined : "memory missing" },
    { label: "Vectors", score: num(atlas.vectors) ? 85 : 25, blocker: num(atlas.vectors) ? undefined : "vectors missing" },
    { label: "Providers", score: providerScore, blocker: unhealthySources.length ? `${unhealthySources.length} provider(s) need review` : undefined },
    { label: "Realtime", score: 35, blocker: "realtime controls are intentionally not enabled" },
    { label: "Datasets", score: executions.some((e) => Array.isArray(e.datasets) && (e.datasets as unknown[]).length) ? 80 : 40, blocker: "dataset evidence depends on mission executions" },
    { label: "Coverage", score: records ? 80 : 20, blocker: records ? undefined : "no provider records" },
    { label: "Tickets", score: ticketScore, blocker: openTickets.length ? `${openTickets.length} open ticket(s)` : undefined },
  ];

  return { summary, insights, actions, readiness, risk };
}

function recommendedActionHeadline({ highTickets, unhealthySources, zeroContribution, activeExecutions, atlas }: { highTickets: Row[]; unhealthySources: Row[]; zeroContribution: Row[]; activeExecutions: Row[]; atlas: Row }) {
  if (highTickets.length) return "Resolve high-priority operational tickets first.";
  if (unhealthySources.length) return "Inspect provider health before expanding missions.";
  if (zeroContribution.length) return "Review enabled providers with zero contribution.";
  if (activeExecutions.length) return "Monitor mission progress and persistence readiness.";
  if (!num(atlas.signals)) return "Validate Atlas signal ingestion.";
  return "System is monitorable; continue normal supervision.";
}

function EnterpriseWidget({
  title, summary, children, filterPlaceholder, onFilter,
}: {
  title: string;
  summary?: string;
  children: React.ReactNode;
  filterPlaceholder?: string;
  onFilter?: (value: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [filter, setFilter] = useState("");
  const updateFilter = (value: string) => {
    setFilter(value);
    onFilter?.(value);
  };
  return (
    <section className={cn(
      "rounded-xl border border-border bg-card/60 p-3",
      fullscreen ? "fixed inset-4 z-50 overflow-auto bg-background shadow-2xl" : "",
    )}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h2>
          {summary ? <p className="mt-1 text-xs text-muted-foreground">{summary}</p> : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {filterPlaceholder ? (
            <input
              className="input h-7 w-44 text-xs"
              placeholder={filterPlaceholder}
              value={filter}
              onChange={(event) => updateFilter(event.target.value)}
            />
          ) : null}
          <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => setCollapsed((v) => !v)}>{collapsed ? "expand" : "collapse"}</button>
          <button className="rounded border border-border px-2 py-1 text-xs hover:bg-accent" onClick={() => setFullscreen((v) => !v)}>{fullscreen ? "exit" : "fullscreen"}</button>
        </div>
      </div>
      {!collapsed ? <div className="mt-2.5">{children}</div> : null}
    </section>
  );
}

function MetricGrid({ items, compact = false }: { items: Array<[string, string | number]>; compact?: boolean }) {
  return <div className={cn("grid gap-2", compact ? "grid-cols-2" : "grid-cols-2 lg:grid-cols-4")}>
    {items.map(([label, value]) => <div key={label} className="rounded-xl border border-border bg-card/60 p-2.5"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p><p className="mt-1 font-mono text-lg font-semibold">{value}</p></div>)}
  </div>;
}
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-border bg-card/60 p-3"><h2 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h2>{children}</section>;
}
function Datum({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 font-mono">{value}</p></div>;
}
function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
function ExecutionRow({ run }: { run: Row }) {
  const ingestion = run.atlas_ingestion as Row | undefined;
  return <a href={withBasePath(`/data-intelligence/executions/${run.execution_id}`)} className="block border-b border-border/50 py-2 last:border-0 hover:text-primary">
    <div className="flex items-center justify-between gap-2 text-sm"><span className="truncate font-mono">{text(run.execution_id)}</span><Pill value={text(run.state, "unknown")} /></div>
    <p className="mt-1 text-xs text-muted-foreground">{text(run.current, "idle")} · {num(run.records)} records · ingestion {text(ingestion?.status, "not reported")}</p>
  </a>;
}
