"use client";

// Explorer jobs / quality / runtime — the operational surfaces that had
// no console consumer.
//
// One component with three modes rather than three near-identical
// pages: they share the fetch shape, the error handling and the
// scheduler controls, and splitting them would have meant three copies
// of the "cancel is global, not per-job" caveat below.

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  Gauge,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader, Pill, ts, type Row } from "@/components/console/ops-shared";

const API = "/api/v1/explorer-ops";

export type RuntimeMode = "jobs" | "quality" | "runtime";

async function request(path: string, method = "GET", body?: unknown) {
  const response = await fetch(withBasePath(`${API}/${path}`), {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      String(payload.detail ?? payload.message ?? payload.error ?? `HTTP ${response.status}`),
    );
  }
  return payload;
}

const TITLES: Record<RuntimeMode, { title: string; subtitle: string; icon: typeof Activity }> = {
  jobs: {
    title: "Collection Jobs",
    subtitle: "Explorer workers — active tasks, history and scheduler control",
    icon: Activity,
  },
  quality: {
    title: "Data Quality",
    subtitle: "Validation rates, entity resolution and duplicate detection",
    icon: Gauge,
  },
  runtime: {
    title: "Explorer Runtime",
    subtitle: "Scheduler, storage, sources and live configuration",
    icon: Database,
  },
};

export function ExplorerRuntimeCenter({ mode }: { mode: RuntimeMode }) {
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await request(mode));
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unreachable");
    }
  }, [mode]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const meta = TITLES[mode];

  return (
    <div className="space-y-4">
      <PageHeader
        icon={meta.icon}
        title={meta.title}
        subtitle={meta.subtitle}
        onRefresh={() => void refresh()}
        updated={updated}
      />
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      {data === null ? (
        <Empty>Loading…</Empty>
      ) : mode === "jobs" ? (
        <JobsView data={data} onError={setError} onChanged={refresh} />
      ) : mode === "quality" ? (
        <QualityView data={data} />
      ) : (
        <RuntimeView data={data} onError={setError} onChanged={refresh} />
      )}
    </div>
  );
}

function JobsView({
  data,
  onError,
  onChanged,
}: {
  data: Row;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const active = Array.isArray(data.active) ? (data.active as Row[]) : [];
  const history = Array.isArray(data.history) ? (data.history as Row[]) : [];

  return (
    <>
      <SchedulerControls onError={onError} onChanged={onChanged} />

      <Card title={`Active (${active.length})`}>
        {active.length === 0 ? <Empty>No job running.</Empty> : <JobTable rows={active} />}
      </Card>

      <Card title="History">
        {history.length === 0 ? <Empty>No job history.</Empty> : <JobTable rows={history} />}
      </Card>
    </>
  );
}

function JobTable({ rows }: { rows: Row[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="pb-2">Competition</th>
            <th className="pb-2">Season</th>
            <th className="pb-2">Source</th>
            <th className="pb-2">Status</th>
            <th className="pb-2 text-right">Collected</th>
            <th className="pb-2 text-right">Validated</th>
            <th className="pb-2 text-right">Review</th>
            <th className="pb-2">Finished</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.job_id ?? i}`} className="border-t border-border/50">
              <td className="py-2">{String(row.competition ?? "—")}</td>
              <td className="py-2">{String(row.season ?? "—")}</td>
              <td className="py-2">{String(row.source ?? "—")}</td>
              <td className="py-2"><Pill value={String(row.status ?? "unknown")} /></td>
              <td className="py-2 text-right">{Number(row.records_collected ?? 0)}</td>
              <td className="py-2 text-right">{Number(row.records_validated ?? 0)}</td>
              <td className="py-2 text-right">{Number(row.records_review ?? 0)}</td>
              <td className="py-2 text-xs text-muted-foreground">
                {ts(row.finished_at ?? row.started_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SchedulerControls({
  onError,
  onChanged,
}: {
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (action: "pause" | "resume" | "cancel") => {
    setBusy(action);
    try {
      await request(`scheduler/${action}`, "POST", {});
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card title="Scheduler">
      {/* These act on the WHOLE scheduler, not a selected row. Putting
          them next to a job would misrepresent their blast radius, so
          they live in their own card with the scope spelled out. */}
      <p className="mb-3 text-xs text-muted-foreground">
        These apply to the entire scheduler — <strong>cancel</strong> stops every
        running collection job, not a single one.
      </p>
      <div className="flex flex-wrap gap-2">
        {([
          ["pause", Pause, "border-border"],
          ["resume", Play, "border-border"],
          ["cancel", Square, "border-red-500/40 text-red-400"],
        ] as const).map(([action, Icon, tone]) => (
          <button
            key={action}
            disabled={busy !== null}
            onClick={() => void act(action)}
            className={`ix-transition inline-flex items-center gap-1.5 rounded-lg border ${tone} bg-card px-3 py-1.5 text-xs font-medium capitalize hover:bg-accent disabled:opacity-40`}
          >
            {busy === action ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
            {action}
          </button>
        ))}
      </div>
    </Card>
  );
}

function QualityView({ data }: { data: Row }) {
  const summary = (data.summary as Row) ?? {};
  const entity = (data.entityResolution as Row) ?? {};
  const duplicates = (data.duplicates as Row) ?? {};
  const datasets = (data.datasets as Row) ?? {};

  const considered =
    Number(summary.records_validated ?? 0) +
    Number(summary.records_review ?? 0) +
    Number(summary.records_rejected ?? 0);

  return (
    <>
      <Card title="Validation">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Metric label="collected" value={Number(summary.records_collected ?? 0)} />
          <Metric label="validated" value={Number(summary.records_validated ?? 0)} />
          <Metric label="in review" value={Number(summary.records_review ?? 0)} />
          <Metric label="rejected" value={Number(summary.records_rejected ?? 0)} />
          <Metric
            label="validation rate"
            value={considered ? `${((Number(summary.records_validated ?? 0) / considered) * 100).toFixed(1)}%` : "—"}
          />
        </div>
      </Card>

      <Card title="Duplicates">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Metric label="removed" value={Number(duplicates.total_duplicates_removed ?? 0)} />
          <Metric
            label="overall rate"
            value={`${(Number(duplicates.overall_duplicate_rate ?? 0) * 100).toFixed(2)}%`}
          />
        </div>
        {duplicates.method ? (
          <p className="mt-2 text-[11px] text-muted-foreground">{String(duplicates.method)}</p>
        ) : null}
      </Card>

      <Card title="Entity resolution">
        <RawGrid body={entity} />
      </Card>

      <Card title="Dataset scores">
        <RawGrid body={datasets} />
      </Card>
    </>
  );
}

function RuntimeView({
  data,
  onError,
  onChanged,
}: {
  data: Row;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const status = (data.status as Row) ?? {};
  const scheduler = (data.scheduler as Row) ?? {};
  const storage = (data.storage as Row) ?? {};
  const config = (data.config as Row) ?? {};

  return (
    <>
      <Card title="Status">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="scheduler" value={String(status.scheduler_status ?? "—")} />
          <Metric label="plan done" value={`${status.plan_completed ?? 0}/${status.plan_total ?? 0}`} />
          <Metric label="jobs" value={`${status.jobs_completed ?? 0}/${status.jobs_total ?? 0}`} />
          <Metric label="storage" value={`${storage.total_mb ?? 0} MB`} />
        </div>
        {scheduler.current ? (
          <p className="mt-2 text-xs text-muted-foreground">
            current: {JSON.stringify(scheduler.current)}
          </p>
        ) : null}
      </Card>

      <Card title="Storage by layer">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries((storage.layers_bytes as Record<string, number>) ?? {}).map(
            ([layer, bytes]) => (
              <Metric key={layer} label={layer} value={`${(bytes / 1e6).toFixed(1)} MB`} />
            ),
          )}
        </div>
        {storage.note ? (
          <p className="mt-2 text-[11px] text-muted-foreground">{String(storage.note)}</p>
        ) : null}
      </Card>

      <Card title="Live configuration">
        <RawGrid body={config} />
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await request("runtime/reload", "POST", {});
              onChanged();
            } catch (e) {
              onError(e instanceof Error ? e.message : "reload failed");
            } finally {
              setBusy(false);
            }
          }}
          className="ix-transition mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Reload config from disk
        </button>
      </Card>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border/60 p-3">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

/** Renders whatever scalar fields a payload has, without inventing any. */
function RawGrid({ body }: { body: Row }) {
  const entries = Object.entries(body).filter(
    ([, value]) => value === null || typeof value !== "object",
  );
  if (entries.length === 0) {
    return <Empty>No data reported.</Empty>;
  }
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt className="text-muted-foreground">{key}</dt>
          <dd className="font-mono">{String(value ?? "—")}</dd>
        </div>
      ))}
    </dl>
  );
}
