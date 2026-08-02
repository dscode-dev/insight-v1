"use client";

// Live tiles — polls the BFF every 5s for scheduler + providers state.
//
// Each upstream is fetched independently so one outage degrades that
// tile without breaking the others (Sprint 8 Part 16: crash resistance).
// Failures render as the StatusBadge "down" pill + the upstream error.

import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle, CardValue } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { withBasePath } from "@/lib/base-path";
import { formatRelative } from "@/lib/utils";

interface HubProxy {
  upstream_ok: boolean;
  status_code: number;
  data: unknown;
  error?: string | null;
}

type SchedulerData = {
  scheduler_running?: boolean;
  ticks_total?: number;
  jobs_created_total?: number;
  queue_size?: number;
  stream_depth?: number;
  pending_messages?: number;
  retry_queue_size?: number;
  active_consumers?: number;
  redis_connected?: boolean;
  last_tick_at?: string | null;
};

type ProvidersData = {
  providers?: Array<{
    source_id?: string;
    reachable?: boolean;
    average_latency_ms?: number;
    requests_total?: number;
    requests_failed_total?: number;
    completed_jobs?: number;
    failed_jobs?: number;
    queued_jobs?: number;
    running_jobs?: number;
  }>;
};

async function fetchProxy<T>(path: string): Promise<{ ok: boolean; data: T | null; error: string | null }> {
  try {
    const res = await fetch(withBasePath(path), { cache: "no-store" });
    if (!res.ok) return { ok: false, data: null, error: `http_${res.status}` };
    const body = (await res.json()) as HubProxy;
    if (!body.upstream_ok) {
      return { ok: false, data: null, error: body.error ?? "upstream_down" };
    }
    return { ok: true, data: body.data as T, error: null };
  } catch {
    return { ok: false, data: null, error: "network_error" };
  }
}

export default function DashboardLiveTiles() {
  const [scheduler, setScheduler] = useState<{ ok: boolean; data: SchedulerData | null; error: string | null }>(
    { ok: false, data: null, error: null },
  );
  const [providers, setProviders] = useState<{ ok: boolean; data: ProvidersData | null; error: string | null }>(
    { ok: false, data: null, error: null },
  );

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      const [s, p] = await Promise.all([
        fetchProxy<SchedulerData>("/api/v1/scheduler/status"),
        fetchProxy<ProvidersData>("/api/v1/providers/status"),
      ]);
      if (cancelled) return;
      setScheduler(s);
      setProviders(p);
    }
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const sd = scheduler.data;
  const totalQueued = providers.data?.providers?.reduce(
    (sum, p) => sum + (p.queued_jobs ?? 0),
    0,
  );
  const totalFailed = providers.data?.providers?.reduce(
    (sum, p) => sum + (p.failed_jobs ?? 0),
    0,
  );

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Scheduler</CardTitle>
            <StatusBadge
              status={scheduler.error ? "down" : sd?.scheduler_running ? "ok" : "down"}
            />
          </div>
        </CardHeader>
        <CardContent>
          <CardValue>{sd?.ticks_total ?? "—"}</CardValue>
          <p className="mt-1 text-xs text-muted-foreground">
            ticks · {sd?.jobs_created_total ?? 0} jobs created
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            last tick {formatRelative(sd?.last_tick_at)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Queue (Redis)</CardTitle>
            <StatusBadge
              status={scheduler.error ? "down" : sd?.redis_connected ? "ok" : "down"}
            />
          </div>
        </CardHeader>
        <CardContent>
          <CardValue>{sd?.stream_depth ?? "—"}</CardValue>
          <p className="mt-1 text-xs text-muted-foreground">
            stream · {sd?.pending_messages ?? 0} pending · {sd?.retry_queue_size ?? 0} retry
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {sd?.active_consumers ?? 0} consumers
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Providers (queued jobs)</CardTitle>
            <StatusBadge status={providers.error ? "down" : "ok"} />
          </div>
        </CardHeader>
        <CardContent>
          <CardValue>{totalQueued ?? "—"}</CardValue>
          <p className="mt-1 text-xs text-muted-foreground">
            across {providers.data?.providers?.length ?? 0} provider(s)
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Provider failures (cumulative)</CardTitle>
            <StatusBadge status={(totalFailed ?? 0) === 0 ? "ok" : "warning"} />
          </div>
        </CardHeader>
        <CardContent>
          <CardValue>{totalFailed ?? "—"}</CardValue>
          <p className="mt-1 text-xs text-muted-foreground">
            inspect details on the Live Operations page
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
