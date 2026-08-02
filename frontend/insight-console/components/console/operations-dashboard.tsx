"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, ServerCog } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";
import type {
  OperationsSnapshot,
  ServiceAdapterSnapshot,
} from "@/lib/operations-adapters";

const STATUS_TONE = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  unavailable: "bg-red-400",
  unknown: "bg-zinc-400",
} as const;

export function OperationsDashboard() {
  const [data, setData] = useState<OperationsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(withBasePath("/api/operations/status"), { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "operations_unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 10000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <ServerCog className="h-5 w-5 text-primary" />
            Operations
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Internal portal view for Robozão and Google Cloud domains.
          </p>
        </div>
        <button
          onClick={refresh}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Operations adapters unavailable: {error}
        </div>
      ) : null}

      <DomainSection
        title="Robozão"
        subtitle="Internal operations domain · local network/VPN only"
        services={data?.domains.robozao ?? []}
        loading={loading}
      />
      <DomainSection
        title="Google Cloud"
        subtitle="Public platform domain · accessed through Insight Gateway"
        services={data?.domains.google_cloud ?? []}
        loading={loading}
      />
    </div>
  );
}

function DomainSection({
  title,
  subtitle,
  services,
  loading,
}: {
  title: string;
  subtitle: string;
  services: ServiceAdapterSnapshot[];
  loading: boolean;
}) {
  const rows: Array<ServiceAdapterSnapshot | null> =
    loading && services.length === 0 ? Array.from({ length: 4 }, () => null) : services;

  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Badge variant="outline">{services.length || (loading ? "..." : 0)} services</Badge>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {rows.map((svc, index) => {
          if (!svc) {
            return <div key={index} className="h-40 animate-pulse rounded-lg border border-border bg-card/60" />;
          }
          return <ServiceCard key={`${svc.domain}-${svc.service}`} service={svc} />;
        })}
      </div>
    </section>
  );
}

function ServiceCard({ service }: { service: ServiceAdapterSnapshot }) {
  return (
    <article className="rounded-lg border border-border bg-card/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{service.display_name}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{service.runtime}</p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs">
          <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_TONE[service.status])} />
          {service.status}
        </span>
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Transport</dt>
          <dd className="mt-0.5 font-mono">{service.preferred_transport}</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Latency</dt>
          <dd className="mt-0.5 font-mono">{service.latency_ms == null ? "-" : `${service.latency_ms}ms`}</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Version</dt>
          <dd className="mt-0.5 font-mono">{service.version ?? "-"}</dd>
        </div>
      </dl>
      <p className="mt-3 line-clamp-2 text-xs text-muted-foreground">{service.detail}</p>
      <p className="mt-2 truncate text-[11px] text-muted-foreground" title={service.endpoint}>
        {service.endpoint}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {service.capabilities.slice(0, 5).map((capability) => (
          <span
            key={capability}
            className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground"
          >
            {capability}
          </span>
        ))}
      </div>
    </article>
  );
}
