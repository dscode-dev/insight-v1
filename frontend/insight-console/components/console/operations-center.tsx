"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  Bot,
  Brain,
  CheckCircle2,
  Database,
  Gauge,
  GitBranch,
  KeyRound,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

import { Pill } from "@/components/console/ops-shared";
import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type Row = Record<string, unknown>;
type Domain =
  | "Mission"
  | "Explorer"
  | "Atlas"
  | "Datasets"
  | "Providers"
  | "Platform"
  | "Social"
  | "Realtime"
  | "AI";
type Risk = "low" | "medium" | "high" | "critical";
type ControlTab = "Action Catalog" | Domain;
type ControlAction = {
  id: string;
  domain: Domain;
  action: string;
  description: string;
  impact: string;
  affectedServices: string[];
  rollback: string;
  confirmation: string;
  permission: string;
  risk: Risk;
  status?: "preview" | "reserved";
};

const DOMAIN_ORDER: Domain[] = ["Mission", "Explorer", "Atlas", "Datasets", "Providers", "Platform", "Social", "Realtime", "AI"];
const CONTROL_TABS: ControlTab[] = ["Action Catalog", ...DOMAIN_ORDER];
const EXECUTABLE_ACTIONS: Record<string, string> = {
  "explorer.pause": "explorer.pipeline.pause",
  "explorer.resume": "explorer.pipeline.resume",
};
const DOMAIN_ICONS: Record<Domain, typeof GitBranch> = {
  Mission: GitBranch,
  Explorer: Gauge,
  Atlas: Brain,
  Datasets: Database,
  Providers: SlidersHorizontal,
  Platform: Server,
  Social: ShieldAlert,
  Realtime: Play,
  AI: Bot,
};

const ACTIONS: ControlAction[] = [
  action("mission.restart", "Mission", "Restart Mission", "Restart a mission from its last safe checkpoint.", "May requeue mission jobs and emit new operational events.", ["explorer", "postgres", "console"], "Previous mission timeline remains preserved.", "Type mission id and confirm restart preview.", "mission.control", "high"),
  action("mission.pause", "Mission", "Pause Mission", "Pause a running mission after the current safe unit.", "Stops scheduling new jobs for the mission.", ["explorer"], "Resume Mission can continue from queue state.", "Confirm mission pause.", "mission.control", "medium"),
  action("mission.resume", "Mission", "Resume Mission", "Resume a paused mission.", "Allows scheduler to continue queued jobs.", ["explorer"], "Pause Mission can stop scheduling again.", "Confirm mission resume.", "mission.control", "medium"),
  action("mission.cancel", "Mission", "Cancel Mission", "Cancel a mission and prevent further job execution.", "Mission may become terminal and require cloning to rerun.", ["explorer", "postgres"], "No automatic rollback; clone mission is the safe recovery path.", "Type mission id and cancellation reason.", "mission.control", "critical"),
  action("mission.clone", "Mission", "Clone Mission", "Create a new mission using the same objective and scope.", "Creates new mission metadata without mutating the original.", ["explorer", "postgres"], "Delete/ignore cloned mission before execution in IOC-CONTROL-B.", "Preview cloned objective and scope.", "mission.control", "low"),
  action("mission.prioritize", "Mission", "Prioritize Mission", "Change mission queue priority.", "Affects scheduler order for queued missions.", ["explorer"], "Priority can be changed again.", "Confirm new priority value.", "mission.control", "medium"),
  action("mission.export", "Mission", "Export Timeline", "Export mission operational event timeline.", "Read-only export of canonical events.", ["console", "postgres"], "No rollback required.", "Confirm export contents.", "mission.read", "low"),
  action("mission.diagnostics", "Mission", "Open Diagnostics", "Open deterministic diagnostics for a mission.", "Read-only diagnostic navigation.", ["console"], "No rollback required.", "Confirm diagnostic scope.", "mission.read", "low"),
  action("mission.ticket", "Mission", "Create Ticket", "Prepare an operational ticket from mission context.", "Creates a review item in IOC-CONTROL-B.", ["console", "postgres"], "Ticket can be closed or annotated.", "Confirm ticket summary and severity.", "tickets.write", "medium"),

  action("explorer.historical", "Explorer", "Start Historical Collection", "Start a historical knowledge mission.", "Creates mission/jobs and begins provider collection in IOC-CONTROL-B.", ["explorer", "postgres", "redis"], "Mission can be paused/canceled after creation.", "Confirm scope, providers and stop conditions.", "explorer.control", "high"),
  action("explorer.incremental", "Explorer", "Start Incremental Collection", "Start an incremental collection using planner state.", "May add new jobs based on historical gaps.", ["explorer", "postgres"], "Mission can be canceled before completion.", "Confirm incremental plan preview.", "explorer.control", "high"),
  action("explorer.stop", "Explorer", "Stop Collection", "Stop an active collection mission.", "Stops scheduling and may leave partial outputs.", ["explorer"], "Resume or clone may recover depending on state.", "Confirm collection stop.", "explorer.control", "critical"),
  action("explorer.pause", "Explorer", "Pause Collection", "Pause collection scheduling.", "Current provider request may finish first.", ["explorer"], "Resume collection can continue queued jobs.", "Confirm pause.", "explorer.control", "medium"),
  action("explorer.resume", "Explorer", "Resume Collection", "Resume paused collection.", "Restarts scheduling for queued jobs.", ["explorer"], "Pause again if needed.", "Confirm resume.", "explorer.control", "medium"),
  action("explorer.requeue", "Explorer", "Requeue Failed Jobs", "Requeue failed Explorer jobs.", "May call providers again and create new artifacts.", ["explorer", "postgres"], "Requeued jobs can be canceled before execution.", "Confirm job list.", "explorer.control", "high"),
  action("explorer.retry", "Explorer", "Retry Mission", "Retry failed mission units.", "May regenerate telemetry and data artifacts.", ["explorer"], "Mission history remains immutable.", "Confirm retry scope.", "explorer.control", "high"),
  action("explorer.force_provider", "Explorer", "Force Provider", "Force a provider for a mission/job.", "Overrides provider manager selection in IOC-CONTROL-B.", ["explorer"], "Provider selection can be reset.", "Confirm provider and reason.", "providers.control", "high"),
  action("explorer.disable_provider", "Explorer", "Disable Provider", "Disable a provider from collection selection.", "May reduce coverage for future missions.", ["explorer"], "Provider can be re-enabled.", "Confirm provider disable.", "providers.control", "high"),
  action("explorer.diagnostics", "Explorer", "Run Diagnostics", "Run Explorer operational diagnostics.", "Read-only diagnostic probe in this sprint.", ["explorer", "console"], "No rollback required.", "Confirm diagnostic target.", "explorer.read", "low"),

  action("atlas.generate", "Atlas", "Generate Intelligence", "Generate an intelligence report for a context.", "Executes Atlas runtime in IOC-CONTROL-B.", ["atlas", "postgres", "pgvector"], "Generated report remains auditable.", "Confirm match/context input.", "atlas.control", "medium"),
  action("atlas.signals", "Atlas", "Recalculate Signals", "Recalculate signal state for a context or batch.", "May update derived signal interpretation.", ["atlas"], "Previous event history remains preserved.", "Confirm signal scope.", "atlas.control", "high"),
  action("atlas.behaviors", "Atlas", "Recalculate Behaviors", "Recalculate behavior patterns.", "May alter behavior observations for future reports.", ["atlas"], "Can be recalculated again.", "Confirm behavior scope.", "atlas.control", "high"),
  action("atlas.memory", "Atlas", "Recalculate Memory", "Rebuild deterministic memory context.", "May affect H2H/team memory lookup outputs.", ["atlas", "postgres"], "Snapshots can be regenerated.", "Confirm memory scope.", "atlas.control", "high"),
  action("atlas.similarity", "Atlas", "Recalculate Similarity", "Recompute deterministic similarity for a context.", "May change neighbor evidence.", ["atlas"], "Can be recomputed.", "Confirm similarity scope.", "atlas.control", "medium"),
  action("atlas.vectors", "Atlas", "Rebuild Vectors", "Rebuild deterministic vector memory.", "Can be expensive and affects vector neighbors.", ["atlas", "pgvector"], "Vector table backups required before execution.", "Confirm vector scope and backup.", "atlas.control", "critical"),
  action("atlas.batch", "Atlas", "Reprocess Batch", "Reprocess an Atlas ingestion batch.", "May rewrite derived intelligence artifacts.", ["atlas", "postgres", "pgvector"], "Lineage preserved; rollback depends on batch snapshot.", "Confirm batch id.", "atlas.control", "high"),
  action("atlas.diagnostics", "Atlas", "Run Diagnostics", "Run Atlas runtime diagnostics.", "Read-only diagnostic inspection in this sprint.", ["atlas", "console"], "No rollback required.", "Confirm diagnostic scope.", "atlas.read", "low"),

  action("dataset.validate", "Datasets", "Validate Dataset", "Validate file/schema/category compatibility.", "Read-only validation until registration.", ["console", "atlas"], "No rollback required.", "Confirm dataset id/file.", "datasets.write", "low"),
  action("dataset.register", "Datasets", "Register Dataset", "Register a validated dataset with manifest and lineage.", "Makes dataset available for Atlas consumption.", ["console", "postgres", "atlas"], "Registration can be superseded by new version.", "Confirm manifest/checksum.", "datasets.write", "high"),
  action("dataset.persist", "Datasets", "Persist Dataset", "Persist Explorer output into Atlas-managed storage.", "Moves collected intelligence into Atlas scope.", ["explorer", "atlas", "postgres"], "Requires lineage to undo safely.", "Confirm source generation.", "datasets.write", "high"),
  action("dataset.signals", "Datasets", "Generate Signals", "Generate signals from a dataset.", "Creates derived signal artifacts.", ["explorer", "atlas"], "Derived signals can be regenerated.", "Confirm dataset and signal catalog version.", "signals.write", "medium"),
  action("dataset.reprocess", "Datasets", "Reprocess Dataset", "Reprocess dataset into intelligence artifacts.", "May create new batches and vectors.", ["atlas", "pgvector"], "Lineage preserves prior version.", "Confirm dataset version.", "datasets.write", "high"),
  action("dataset.merge", "Datasets", "Merge Dataset", "Merge compatible datasets.", "Creates a new lineage branch.", ["postgres", "atlas"], "Original datasets remain immutable.", "Confirm merge plan.", "datasets.write", "high"),
  action("dataset.export", "Datasets", "Export Dataset", "Export dataset artifacts.", "Read-only export.", ["console", "postgres"], "No rollback required.", "Confirm export format.", "datasets.read", "low"),
  action("dataset.delete", "Datasets", "Delete Dataset", "Delete a dataset version.", "Potentially destructive and blocked until IOC-CONTROL-B safety gates.", ["postgres", "atlas"], "Rollback requires backup/manifest restore.", "Type dataset id and confirm irreversible action.", "datasets.delete", "critical"),

  action("provider.enable", "Providers", "Enable Provider", "Enable provider in selection registry.", "May allow future missions to use provider.", ["explorer"], "Provider can be disabled.", "Confirm provider and priority.", "providers.control", "medium"),
  action("provider.disable", "Providers", "Disable Provider", "Disable provider from new jobs.", "May reduce coverage and fallback options.", ["explorer"], "Provider can be re-enabled.", "Confirm provider and reason.", "providers.control", "high"),
  action("provider.fallback", "Providers", "Force Fallback", "Force fallback provider selection.", "Overrides provider manager in IOC-CONTROL-B.", ["explorer"], "Fallback can be cleared.", "Confirm provider pair and job/mission.", "providers.control", "high"),
  action("provider.priority", "Providers", "Change Priority", "Change provider priority.", "Affects future provider selection.", ["explorer"], "Priority can be changed again.", "Confirm priority order.", "providers.control", "medium"),
  action("provider.connection", "Providers", "Run Connection Test", "Test provider connectivity.", "Read-only provider health probe.", ["explorer"], "No rollback required.", "Confirm provider.", "providers.read", "low"),
  action("provider.credentials", "Providers", "Inspect Credentials", "Inspect credential presence/status, never secret value.", "Read-only status check.", ["explorer"], "No rollback required.", "Confirm credential scope.", "providers.read", "medium"),
  action("provider.rate", "Providers", "Rate Limit Information", "Inspect provider rate limit metadata.", "Read-only operational information.", ["explorer"], "No rollback required.", "Confirm provider.", "providers.read", "low"),
  action("provider.health", "Providers", "Health Information", "Inspect provider health and latency.", "Read-only operational information.", ["explorer"], "No rollback required.", "Confirm provider.", "providers.read", "low"),

  action("platform.restart_service", "Platform", "Restart Service", "Restart a production service.", "Temporary service interruption.", ["docker", "service"], "Docker restart can recover prior container image.", "Confirm service, compose root and maintenance window.", "platform.control", "critical"),
  action("platform.inspect_service", "Platform", "Inspect Service", "Inspect service status and metadata.", "Read-only platform check.", ["docker", "service"], "No rollback required.", "Confirm service.", "platform.read", "low"),
  action("platform.logs", "Platform", "Open Logs", "Open service logs.", "Read-only log inspection.", ["docker"], "No rollback required.", "Confirm service and time range.", "platform.read", "low"),
  action("platform.restart_worker", "Platform", "Restart Worker", "Restart a detached worker.", "May interrupt current work unit.", ["explorer", "docker"], "Worker can be restarted again.", "Confirm worker id.", "platform.control", "high"),
  action("platform.queue", "Platform", "Inspect Queue", "Inspect queues and pending work.", "Read-only queue inspection.", ["redis", "explorer"], "No rollback required.", "Confirm queue.", "platform.read", "low"),
  action("platform.redis", "Platform", "Inspect Redis", "Inspect Redis health/status.", "Read-only infrastructure check.", ["redis"], "No rollback required.", "Confirm Redis scope.", "platform.read", "low"),
  action("platform.postgres", "Platform", "Inspect PostgreSQL", "Inspect PostgreSQL health/status.", "Read-only infrastructure check.", ["postgres"], "No rollback required.", "Confirm database scope.", "platform.read", "low"),
  action("platform.pgvector", "Platform", "Inspect pgvector", "Inspect vector extension and tables.", "Read-only vector storage check.", ["postgres", "pgvector"], "No rollback required.", "Confirm vector scope.", "platform.read", "low"),
  action("platform.rabbitmq", "Platform", "Inspect RabbitMQ", "Reserved future queue inspection.", "No current runtime effect.", ["rabbitmq"], "Not applicable.", "Reserved until RabbitMQ exists.", "platform.read", "low", "reserved"),

  action("social.post_moderation", "Social", "Post Moderation", "Reserved for IOC-SOCIAL-*.", "No current runtime effect.", ["social"], "Not applicable.", "Delivered in IOC-SOCIAL-*.", "social.moderate", "medium", "reserved"),
  action("social.comment_moderation", "Social", "Comment Moderation", "Reserved for IOC-SOCIAL-*.", "No current runtime effect.", ["social"], "Not applicable.", "Delivered in IOC-SOCIAL-*.", "social.moderate", "medium", "reserved"),
  action("social.user_actions", "Social", "User Actions", "Reserved for IOC-SOCIAL-*.", "No current runtime effect.", ["social"], "Not applicable.", "Delivered in IOC-SOCIAL-*.", "social.control", "high", "reserved"),
  action("realtime.score", "Realtime", "Manual Score Updates", "Reserved for REALTIME-*.", "No current runtime effect.", ["sport-hub"], "Not applicable.", "Delivered in REALTIME-*.", "realtime.control", "critical", "reserved"),
  action("realtime.events", "Realtime", "Manual Match Events", "Reserved for REALTIME-*.", "No current runtime effect.", ["sport-hub"], "Not applicable.", "Delivered in REALTIME-*.", "realtime.control", "critical", "reserved"),
  action("realtime.controls", "Realtime", "Realtime Controls", "Reserved for REALTIME-*.", "No current runtime effect.", ["explorer", "sport-hub"], "Not applicable.", "Delivered in REALTIME-*.", "realtime.control", "critical", "reserved"),
  action("ai.controls", "AI", "AI Controls", "Reserved. Nexus/GPT are intentionally not enabled in this sprint.", "No current runtime effect.", ["nexus"], "Not applicable.", "Requires future AI governance sprint.", "ai.control", "critical", "reserved"),
];

function action(id: string, domain: Domain, actionName: string, description: string, impact: string, affectedServices: string[], rollback: string, confirmation: string, permission: string, risk: Risk, status: "preview" | "reserved" = "preview"): ControlAction {
  return { id, domain, action: actionName, description, impact, affectedServices, rollback, confirmation, permission, risk, status };
}

async function json(path: string): Promise<Row> {
  const response = await fetch(withBasePath(path), { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

const rows = (body: Row | undefined, key: string): Row[] => Array.isArray(body?.[key]) ? body?.[key] as Row[] : [];
const text = (value: unknown, fallback = "—") => value === undefined || value === null || value === "" ? fallback : String(value);

export function OperationsCenter() {
  const [data, setData] = useState<Record<string, Row>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [activeTab, setActiveTab] = useState<ControlTab>("Action Catalog");
  const [selected, setSelected] = useState<ControlAction>(ACTIONS[0]!);
  const [filter, setFilter] = useState("");
  const t = useT("control-panel");

  const refresh = useCallback(async () => {
    const requests = {
      events: "/api/v1/ops/events?limit=200",
      operations: "/api/v1/control/operations",
      executions: "/api/v1/data-intelligence/executions",
      explorer: "/api/v1/data-intelligence/data-intelligence/dashboard",
      platform: "/api/operations/status",
      dlq: "/api/v1/dlq?unreplayed=1&limit=100",
    };
    const settled = await Promise.allSettled(Object.entries(requests).map(async ([key, path]) => [key, await json(path)] as const));
    const next: Record<string, Row> = {};
    const nextErrors: string[] = [];
    for (const item of settled) {
      if (item.status === "fulfilled") next[item.value[0]] = item.value[1];
      else nextErrors.push(item.reason instanceof Error ? item.reason.message : "unknown control context error");
    }
    setData(next);
    setErrors(nextErrors);
    setUpdated(new Date());
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const context = useMemo(() => controlContext(data), [data]);
  const visibleActions = useMemo(() => ACTIONS.filter((item) => JSON.stringify(item).toLowerCase().includes(filter.toLowerCase())), [filter]);
  const tabActions = useMemo(
    () => activeTab === "Action Catalog" ? visibleActions : visibleActions.filter((item) => item.domain === activeTab),
    [activeTab, visibleActions],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <ShieldCheck className="h-5 w-5 text-primary" /> {t("title")}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("subtitle")}
            {updated ? ` · ${updated.toLocaleTimeString()}` : ""}
          </p>
        </div>
        <button onClick={refresh} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs hover:bg-accent">
          <RefreshCw className="h-3.5 w-3.5" /> {t("refreshContext")}
        </button>
      </div>

      <SafetyBanner errors={errors} />
      <ControlContextPanel context={context} />

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
        <section className="rounded-xl border border-border bg-card/60 p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("controlSurface")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t("controlSurfaceHint", { count: ACTIONS.length })}</p>
            </div>
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder={t("filterPlaceholder")}
              className="input h-8 w-full max-w-sm text-xs"
            />
          </div>
          <ControlTabs activeTab={activeTab} onChange={setActiveTab} visibleActions={visibleActions} />
          <div key={activeTab} className="mt-3 animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/30 px-3 py-2">
              <span className="text-sm font-medium">{activeTab === "Action Catalog" ? t("actionCatalog") : t(`domain.${activeTab}`)}</span>
              <span className="text-xs text-muted-foreground">{t("visibleActions", { count: tabActions.length })}</span>
            </div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {tabActions.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelected(item)}
                  className={cn(
                    "rounded-lg border p-3 text-left transition hover:bg-accent",
                    selected.id === item.id ? "border-primary/50 bg-primary/10" : "border-border bg-card/50",
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{item.action}</span>
                    <span className="flex gap-1"><Pill value={item.status === "reserved" ? "reserved" : "preview"} /><RiskPill risk={item.risk} /></span>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{item.description}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Pill value={item.domain} />
                    <span className="font-mono text-[11px] text-muted-foreground">{item.permission}</span>
                  </div>
                </button>
              ))}
              {!tabActions.length ? <p className="rounded-lg border border-border p-4 text-sm text-muted-foreground">{t("noControls", { tab: activeTab === "Action Catalog" ? t("actionCatalog") : t(`domain.${activeTab}`) })}</p> : null}
            </div>
          </div>
        </section>

        <ControlPreview action={selected} context={context} operations={rows(data.operations, "operations")} onRefresh={refresh} />
      </div>
    </div>
  );
}

function ControlTabs({ activeTab, onChange, visibleActions }: { activeTab: ControlTab; onChange: (tab: ControlTab) => void; visibleActions: ControlAction[] }) {
  const t = useT("control-panel");
  return (
    <div className="-mx-1 flex flex-wrap gap-1 border-y border-border px-1 py-2">
      {CONTROL_TABS.map((tab) => {
        const count = tab === "Action Catalog" ? visibleActions.length : visibleActions.filter((item) => item.domain === tab).length;
        const Icon = tab === "Action Catalog" ? SlidersHorizontal : DOMAIN_ICONS[tab];
        return (
          <button
            key={tab}
            onClick={() => onChange(tab)}
            className={cn(
              "ix-transition inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs",
              activeTab === tab ? "border-primary/40 bg-primary/10 text-primary shadow-sm shadow-primary/5" : "border-border bg-card/70 hover:bg-accent",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {tab === "Action Catalog" ? t("actionCatalog") : t(`domain.${tab}`)}
            <span className="rounded-full bg-background/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{count}</span>
          </button>
        );
      })}
    </div>
  );
}

function SafetyBanner({ errors }: { errors: string[] }) {
  const t = useT("control-panel");
  return (
    <section className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-3">
      <div className="flex items-start gap-3">
        <Ban className="mt-0.5 h-4 w-4 text-amber-300" />
        <div>
          <p className="text-sm font-semibold text-amber-200">{t("executionDisabledTitle")}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("executionDisabledBody")}</p>
          {errors.length ? (
            <details className="mt-2 text-xs text-amber-200">
              <summary>{t("contextDegraded", { count: errors.length })}</summary>
              {errors.map((error) => <div key={error} className="font-mono">{error}</div>)}
            </details>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ControlContextPanel({ context }: { context: ReturnType<typeof controlContext> }) {
  const t = useT("control-panel");
  return (
    <section className="grid gap-2 md:grid-cols-5">
      <Metric label={t("metricEvents")} value={context.events} />
      <Metric label={t("metricMissions")} value={context.missions} />
      <Metric label={t("metricProviders")} value={context.providers} />
      <Metric label={t("metricServices")} value={context.services} />
      <Metric label={t("metricDlq")} value={context.dlq} tone={context.dlq ? "risk" : "good"} />
    </section>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: number | string; tone?: "good" | "risk" | "neutral" }) {
  return (
    <div className={cn("rounded-xl border p-3", tone === "good" ? "border-emerald-500/20 bg-emerald-500/[0.04]" : tone === "risk" ? "border-red-500/20 bg-red-500/[0.04]" : "border-border bg-card/60")}>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg font-semibold">{value}</p>
    </div>
  );
}

function ControlPreview({ action, operations, onRefresh }: { action: ControlAction; context: ReturnType<typeof controlContext>; operations: Row[]; onRefresh: () => void }) {
  const t = useT("control-panel");
  const Icon = DOMAIN_ICONS[action.domain];
  const [busy, setBusy] = useState("");
  const [localOperation, setLocalOperation] = useState<Row | null>(null);
  const canonicalAction = EXECUTABLE_ACTIONS[action.id];
  const operation = localOperation ?? operations.find((item) =>
    String(item.action_id ?? item.operation_type) === (canonicalAction ?? action.id)
  ) ?? null;
  const execute = async () => {
    if (!canonicalAction) return;
    setBusy("create");
    try {
      const payload = operationPayload(action);
      const response = await fetch(withBasePath("/api/v1/control/operations"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json() as { operation?: Row };
      if (body.operation) setLocalOperation(body.operation);
      onRefresh();
    } finally {
      setBusy("");
    }
  };
  return (
    <aside className="self-start rounded-xl border border-border bg-card/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="inline-flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground"><Icon className="h-4 w-4 text-primary" /> {t(`domain.${action.domain}`)}</p>
          <h2 className="mt-1 text-lg font-semibold">{action.action}</h2>
        </div>
        <div className="flex gap-1"><Pill value={action.status === "reserved" ? "reserved" : "preview"} /><RiskPill risk={action.risk} /></div>
      </div>

      <div className="mt-4 grid gap-2 text-sm xl:grid-cols-2 2xl:grid-cols-1">
        <PreviewRow icon={CheckCircle2} label={t("description")} value={action.description} />
        <PreviewRow icon={AlertTriangle} label={t("impact")} value={action.impact} />
        <PreviewRow icon={Server} label={t("affectedServices")} value={action.affectedServices.join(", ")} />
        <PreviewRow icon={RotateCcw} label={t("rollback")} value={action.rollback} />
        <PreviewRow icon={KeyRound} label={t("permission")} value={action.permission} />
        <PreviewRow icon={ShieldCheck} label={t("confirmation")} value={action.confirmation} />
      </div>

      <div className="mt-4 rounded-lg border border-border bg-background/50 p-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("operationPreview")}</p>
        <pre className="mt-2 whitespace-pre-wrap break-words rounded bg-background/70 p-3 text-[11px] text-muted-foreground">{JSON.stringify({
          ...operationPayload(action),
          operation_id: operation?.operation_id ?? "not_created",
          lifecycle: operation?.status ?? operation?.current_status ?? "draft",
          approval_status: operation?.approval_status ?? "not_started",
        }, null, 2)}</pre>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <button disabled={!canonicalAction || Boolean(busy)} onClick={execute} className="rounded-lg border border-border bg-card px-3 py-2 text-sm hover:bg-accent disabled:opacity-50">
          {busy === "create" ? t("creating") : operation ? t("createNew") : t("create")}
        </button>
      </div>

      {operation ? <OperationLifecycle operation={operation} /> : null}

      {!canonicalAction ? (
        <button disabled className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground opacity-70">
          <Ban className="h-4 w-4" /> {t("executeDisabled")}
        </button>
      ) : null}
    </aside>
  );
}

function operationPayload(action: ControlAction) {
  return {
    intent: "create",
    operation_type: action.id,
    action_id: EXECUTABLE_ACTIONS[action.id] ?? action.id,
    domain: action.domain,
    requested_action: action.action,
    action_name: action.action,
    target_service: action.affectedServices[0] ?? "console",
    target_resource: action.id,
    risk_level: action.risk,
    affected_services: action.affectedServices,
    rollback_availability: action.rollback,
    required_permission: action.permission,
    preview_payload: {
      description: action.description,
      impact: action.impact,
      confirmation: action.confirmation,
      status: action.status ?? "preview",
      execution_enabled: Boolean(EXECUTABLE_ACTIONS[action.id]),
      executable_in: "IOC-CONTROL-B2",
    },
  };
}

function OperationLifecycle({ operation }: { operation: Row }) {
  const t = useT("control-panel");
  const audit = Array.isArray(operation.audit_trail) ? operation.audit_trail as Row[] : [];
  const events = Array.isArray(operation.operational_events) ? operation.operational_events as Row[] : [];
  return (
    <div className="mt-4 rounded-lg border border-border bg-background/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("operationLifecycle")}</p>
          <p className="mt-1 font-mono text-xs">{text(operation.operation_id)}</p>
        </div>
        <div className="flex gap-1"><Pill value={text(operation.status ?? operation.current_status)} /><Pill value={text(operation.approval_status, "not_required")} /></div>
      </div>
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <MiniDatum label={t("createdBy")} value={text(operation.requested_by ?? operation.created_by)} />
        <MiniDatum label={t("correlation")} value={text(operation.correlation_id)} />
        <MiniDatum label={t("permission")} value={permissionSummary(operation.permission_evaluation as Row | undefined, t)} />
        <MiniDatum label={t("dryRunLabel")} value={operation.dry_run ? t("dryRunCompleted") : t("dryRunNotRun")} />
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">{t("auditTrail", { count: audit.length })}</summary>
        <div className="mt-2 space-y-1">
          {audit.map((item, index) => <div key={String(item.audit_id ?? index)} className="rounded border border-border/60 p-2 text-xs"><span className="font-mono">{text(item.transition)}</span> · {text(item.status)} · {text(item.at)}</div>)}
        </div>
      </details>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">{t("operationalEvents", { count: events.length })}</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words rounded bg-background/70 p-2 text-[11px] text-muted-foreground">{JSON.stringify(events.slice(-8), null, 2)}</pre>
      </details>
    </div>
  );
}

function MiniDatum({ label, value }: { label: string; value: string }) {
  return <div><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 font-mono">{value}</p></div>;
}

function permissionSummary(value: Row | undefined, t: (key: string) => string) {
  if (!value) return t("permNotEvaluated");
  return value.granted
    ? `${t("permGranted")} · ${text(value.current_role)}`
    : `${t("permDenied")} · ${text(value.reason)}`;
}

function PreviewRow({ icon: Icon, label, value }: { icon: typeof CheckCircle2; label: string; value: string }) {
  return (
    <div className="flex gap-3 rounded-lg border border-border bg-background/30 p-3">
      <Icon className="mt-0.5 h-4 w-4 text-primary" />
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
        <p className="mt-1 text-sm">{value}</p>
      </div>
    </div>
  );
}

function RiskPill({ risk }: { risk: Risk }) {
  const value = `risk:${risk}`;
  return <Pill value={value} />;
}

function controlContext(data: Record<string, Row>) {
  const events = rows(data.events, "events");
  const executions = Array.isArray(data.executions) ? data.executions as Row[] : [];
  const explorer = data.explorer ?? {};
  const platformDomains = data.platform?.domains as Record<string, Row[]> | undefined;
  const services = [...(platformDomains?.robozao ?? []), ...(platformDomains?.google_cloud ?? [])];
  const sources = Array.isArray(explorer.sources) ? explorer.sources as Row[] : [];
  const dlq = rows(data.dlq, "items");
  const missionIds = new Set<string>();
  for (const event of events) {
    const op = ((event.metadata as Row | undefined)?.operational_event ?? {}) as Row;
    if (op.mission_id) missionIds.add(String(op.mission_id));
  }
  for (const execution of executions) {
    const id = execution.execution_id ?? execution.mission_id ?? execution.run_id;
    if (id) missionIds.add(String(id));
  }
  return {
    events: events.length,
    missions: missionIds.size,
    providers: sources.length,
    services: services.length,
    dlq: dlq.length,
  };
}
