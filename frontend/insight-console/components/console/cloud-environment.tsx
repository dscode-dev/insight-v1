"use client";

// Cloud Environment — Gateway-mediated platform status plus Robozao Gateway status.

import { useCallback, useEffect, useRef, useState } from "react";
import { Cloud, RefreshCw, Server, Database, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";

type Service = {
  name: string; kind: "service" | "datastore"; status: "up" | "down" | "degraded";
  latency_ms: number | null; version: string | null; detail: string; endpoint: string;
};
type Payload = { services: Service[]; summary: { total: number; up: number; down: number }; checked_at: string };
type RobozaoPayload = {
  vpn_connected: boolean;
  robozao_reachable: boolean;
  operator_validated: boolean;
  services: Record<string, string>;
  registry: Array<{ service: string; endpoint: string; status: string; latency_ms: number; detail: string }>;
  checked_at: string;
  source: string;
  detail?: string;
};

const STATUS = {
  up: { tone: "text-emerald-400", dot: "bg-emerald-400", ring: "ring-emerald-500/25", Icon: CheckCircle2, label: "Operational" },
  degraded: { tone: "text-amber-400", dot: "bg-amber-400", ring: "ring-amber-500/25", Icon: AlertTriangle, label: "Degraded" },
  down: { tone: "text-red-400", dot: "bg-red-400", ring: "ring-red-500/25", Icon: XCircle, label: "Down" },
} as const;

export function CloudEnvironment() {
  const [data, setData] = useState<Payload | null>(null);
  const [robozao, setRobozao] = useState<RobozaoPayload | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cloudRes, robozaoRes] = await Promise.all([
        fetch(withBasePath("/api/cloud/services"), { cache: "no-store" }),
        fetch(withBasePath("/api/ops/robozao/status"), { cache: "no-store" }),
      ]);
      if (cloudRes.ok) setData(await cloudRes.json());
      if (robozaoRes.ok) setRobozao(await robozaoRes.json());
      setUpdated(new Date());
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 8000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [refresh]);

  const services = data?.services ?? [];
  const summary = data?.summary;
  const allUp = summary && summary.down === 0 && summary.total > 0;
  const robozaoOnline = Boolean(robozao?.robozao_reachable);
  const vpnOnline = Boolean(robozao?.vpn_connected);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Cloud className="h-5 w-5 text-primary" /> Infrastructure Detail
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Drill-down retained for compatibility. The operational overview now lives on Dashboard ·{" "}
            {summary ? (
              <span className={allUp ? "text-emerald-400" : "text-amber-400"}>
                {summary.up}/{summary.total} services healthy
              </span>
            ) : "checking…"}
            {updated ? <span className="ml-2">updated {updated.toLocaleTimeString()}</span> : null}
          </p>
        </div>
        <button onClick={refresh}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent">
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {/* status banner */}
      <div className={cn("ix-transition flex items-center gap-3 rounded-xl border px-4 py-3",
        allUp ? "border-emerald-500/25 bg-emerald-500/[0.06]" : "border-amber-500/25 bg-amber-500/[0.06]")}>
        <span className={cn("relative flex h-2.5 w-2.5")}>
          <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
            allUp ? "bg-emerald-400" : "bg-amber-400")} />
          <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", allUp ? "bg-emerald-400" : "bg-amber-400")} />
        </span>
        <span className="text-sm font-medium">
          {loading && !data ? "Probing cloud services…"
            : allUp ? "All cloud services operational"
            : `${summary?.down ?? 0} service(s) need attention`}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {[
          { label: "Gateway", ok: Boolean(allUp), detail: allUp ? "Online" : "Needs attention" },
          { label: "Robozão", ok: robozaoOnline, detail: robozaoOnline ? "Online" : "Offline" },
          { label: "VPN", ok: vpnOnline, detail: vpnOnline ? "Connected" : "Disconnected" },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-border bg-card/60 px-4 py-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</p>
            <div className="mt-1 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold">{item.detail}</span>
              <span className={cn("h-2 w-2 rounded-full", item.ok ? "bg-emerald-400" : "bg-red-400")} />
            </div>
          </div>
        ))}
      </div>

      {/* service grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(loading && !data ? Array.from({ length: 5 }) : services).map((svc, i) => {
          const s = svc as Service | undefined;
          if (!s) return <div key={i} className="h-32 animate-pulse rounded-xl border border-border bg-card/60" />;
          const st = STATUS[s.status];
          const KindIcon = s.kind === "service" ? Server : Database;
          return (
            <div key={s.name}
              className={cn("ix-transition rounded-xl border border-border bg-card/60 p-4 ring-1 ring-inset hover:border-border/80", st.ring)}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary ring-1 ring-inset ring-border">
                    <KindIcon className="h-4 w-4 text-muted-foreground" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold">{s.name}</p>
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{s.kind}</p>
                  </div>
                </div>
                <span className={cn("inline-flex items-center gap-1 text-xs font-medium", st.tone)}>
                  <span className={cn("h-1.5 w-1.5 rounded-full", st.dot)} /> {st.label}
                </span>
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Version</dt>
                  <dd className="mt-0.5 font-mono text-foreground">{s.version ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Latency</dt>
                  <dd className="mt-0.5 font-mono text-foreground">{s.latency_ms != null ? `${s.latency_ms}ms` : "—"}</dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Health</dt>
                  <dd className={cn("mt-0.5 font-mono", st.tone)}>{s.status}</dd>
                </div>
              </dl>
              <p className="mt-3 truncate text-[11px] text-muted-foreground" title={s.endpoint}>
                {s.detail} · <span className="font-mono">{s.endpoint}</span>
              </p>
            </div>
          );
        })}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Live status comes through Insight Gateway and Robozao Gateway contracts.
        The Console does not probe databases or operational services directly.
      </p>
    </div>
  );
}
