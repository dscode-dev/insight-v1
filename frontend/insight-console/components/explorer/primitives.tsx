"use client";

// Explorer Operations Center — visual primitives (ML-B.6 Part 12).
// Pure SVG + Tailwind tokens; no chart dependency. Dark-first, dense,
// Linear/Vercel-grade spacing and typography.

import { cn } from "@/lib/utils";

export function formatBytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

export function formatNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US");
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

type Tone = "default" | "success" | "warning" | "danger" | "info" | "muted";

const TONE: Record<Tone, string> = {
  default: "bg-secondary text-secondary-foreground",
  success: "bg-emerald-500/15 text-emerald-400 ring-1 ring-inset ring-emerald-500/25",
  warning: "bg-amber-500/15 text-amber-400 ring-1 ring-inset ring-amber-500/25",
  danger: "bg-red-500/15 text-red-400 ring-1 ring-inset ring-red-500/25",
  info: "bg-blue-500/15 text-blue-400 ring-1 ring-inset ring-blue-500/25",
  muted: "bg-muted text-muted-foreground",
};

export function LiveDot({ live }: { live: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
      <span className={cn("relative flex h-2 w-2")}>
        {live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/60" />}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", live ? "bg-emerald-400" : "bg-muted-foreground/40")} />
      </span>
      {live ? "live" : "offline"}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted/60", className)} />;
}

export function OpsSkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <Skeleton className="h-8 w-full max-w-xl" />
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-56" />)}
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, hint, tone = "muted" }: {
  icon?: React.ReactNode; title: string; hint?: string; tone?: "muted" | "success";
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      {icon ? <div className={cn("text-2xl", tone === "success" ? "text-emerald-400" : "text-muted-foreground/50")}>{icon}</div> : null}
      <p className={cn("text-sm font-medium", tone === "success" ? "text-emerald-400" : "text-foreground")}>{title}</p>
      {hint ? <p className="max-w-sm text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Pill({ children, tone = "default", className }: {
  children: React.ReactNode; tone?: Tone; className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
      TONE[tone], className)}>
      {children}
    </span>
  );
}

export function StatCard({ label, value, sub, tone = "default", icon }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: Tone;
  icon?: React.ReactNode;
}) {
  const accent = {
    default: "text-foreground", success: "text-emerald-400", warning: "text-amber-400",
    danger: "text-red-400", info: "text-blue-400", muted: "text-muted-foreground",
  }[tone];
  return (
    <div className="rounded-xl border border-border bg-card/60 p-4 transition-colors hover:border-border/80">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
        {icon ? <span className="text-muted-foreground/70">{icon}</span> : null}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold tabular-nums tracking-tight", accent)}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

export function Panel({ title, action, children, className }: {
  title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-border bg-card/60", className)}>
      {title ? (
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          {action}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

// Horizontal proportion bar (validated / review / rejected etc.)
export function StackBar({ segments, height = 8 }: {
  segments: { value: number; tone: Tone; label?: string }[]; height?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const color: Record<Tone, string> = {
    default: "bg-foreground/40", success: "bg-emerald-500", warning: "bg-amber-500",
    danger: "bg-red-500", info: "bg-blue-500", muted: "bg-muted-foreground/40",
  };
  return (
    <div className="flex w-full overflow-hidden rounded-full bg-muted" style={{ height }}>
      {segments.map((s, i) => (
        <div key={i} className={color[s.tone]} style={{ width: `${(s.value / total) * 100}%` }}
          title={s.label ? `${s.label}: ${s.value}` : String(s.value)} />
      ))}
    </div>
  );
}

// Donut for a single ratio 0..1.
export function Donut({ value, size = 72, label }: { value: number; size?: number; label?: string }) {
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value || 0));
  const tone = v >= 0.85 ? "#34d399" : v >= 0.6 ? "#fbbf24" : "#f87171";
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth={6} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth={6}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v)} />
      </svg>
      <div className="absolute text-center">
        <div className="text-sm font-semibold tabular-nums">{(v * 100).toFixed(0)}%</div>
        {label ? <div className="text-[9px] text-muted-foreground">{label}</div> : null}
      </div>
    </div>
  );
}

// Sparkline from a numeric series (0..1 scaled by max).
export function Sparkline({ data, width = 160, height = 36 }: {
  data: number[]; width?: number; height?: number;
}) {
  if (!data.length) return <div className="h-9 text-xs text-muted-foreground">no data</div>;
  const max = Math.max(...data, 1);
  const step = width / Math.max(1, data.length - 1);
  const pts = data.map((d, i) => `${i * step},${height - (d / max) * (height - 4) - 2}`).join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline points={pts} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.5} />
    </svg>
  );
}

export function Bars({ data }: { data: { label: string; value: number; tone?: Tone }[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  const color: Record<Tone, string> = {
    default: "bg-primary", success: "bg-emerald-500", warning: "bg-amber-500",
    danger: "bg-red-500", info: "bg-blue-500", muted: "bg-muted-foreground/50",
  };
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-3 text-xs">
          <span className="w-32 shrink-0 truncate text-muted-foreground">{d.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div className={cn("h-full rounded-full", color[d.tone ?? "default"])}
              style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
          <span className="w-14 shrink-0 text-right tabular-nums">{formatNum(d.value)}</span>
        </div>
      ))}
    </div>
  );
}
