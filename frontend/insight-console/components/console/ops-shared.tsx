"use client";

// Shared building blocks for CONSOLE-OPS-A3 operational pages: a polling hook +
// small presentational primitives. Keeps every ops page consistent (realtime,
// honest empty-states, no fake data) without repeating boilerplate.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";

export type Row = Record<string, unknown>;

export function arr(b: Row | null | undefined, ...keys: string[]): Row[] {
  if (!b) return [];
  for (const k of keys) if (Array.isArray(b[k])) return b[k] as Row[];
  return [];
}

export function ts(s?: unknown): string {
  if (!s) return "—";
  const d = new Date(String(s));
  return isNaN(d.getTime()) ? String(s) : d.toLocaleString();
}

/** Poll one or more BFF endpoints every `intervalMs`. Returns merged JSON keyed
 *  by the url's last path segment, plus error + last-updated. */
export function useOps(urls: string[], intervalMs = 7000) {
  const [data, setData] = useState<Record<string, Row>>({});
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const key = urls.join("|");

  const refresh = useCallback(async () => {
    try {
      const out: Record<string, Row> = {};
      await Promise.all(
        urls.map(async (u) => {
          const r = await fetch(withBasePath(u), { cache: "no-store" });
          const name = (u.split("?")[0] ?? u).split("/").filter(Boolean).pop() ?? u;
          out[name] = r.ok ? await r.json() : { __error: `HTTP ${r.status}` };
        }),
      );
      setData(out);
      const errs = Object.values(out).filter((d) => d.__error).map((d) => String(d.__error));
      setError(errs.length === urls.length ? (errs[0] ?? null) : null);
      setUpdated(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "unreachable");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    refresh();
    if (intervalMs <= 0) return;
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, updated, refresh };
}

export function PageHeader({
  icon: Icon, title, subtitle, onRefresh, updated,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string; subtitle: string; onRefresh: () => void; updated: Date | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Icon className="h-5 w-5 text-primary" /> {title}
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {subtitle}
          {updated ? <span className="ml-2">updated {updated.toLocaleTimeString()}</span> : null}
        </p>
      </div>
      <button
        onClick={onRefresh}
        className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent"
      >
        <RefreshCw className="h-3.5 w-3.5" /> Refresh
      </button>
    </div>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      {title ? <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">{title}</p> : null}
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-4 py-3 text-sm text-amber-400">
      {children}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  up: "bg-emerald-500/15 text-emerald-400", healthy: "bg-emerald-500/15 text-emerald-400",
  completed: "bg-emerald-500/15 text-emerald-400", running: "bg-sky-500/15 text-sky-400",
  degraded: "bg-amber-500/15 text-amber-400", partial: "bg-amber-500/15 text-amber-400",
  warning: "bg-amber-500/15 text-amber-400", down: "bg-red-500/15 text-red-400",
  unavailable: "bg-red-500/15 text-red-400", failed: "bg-red-500/15 text-red-400",
  not_configured: "bg-muted text-muted-foreground",
};

export function Pill({ value }: { value: string }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-xs", STATUS_TONE[value.toLowerCase()] ?? "bg-muted text-muted-foreground")}>
      {value}
    </span>
  );
}
