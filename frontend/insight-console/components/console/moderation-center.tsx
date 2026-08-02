"use client";

// Moderation Center (Store-A Part 6) — the real moderation queue. Lists open
// reports with filters (status / reason), per-report actions (dismiss, remove/
// restore content, suspend/ban user), aggregate stats, and the audited action
// log. Every action POSTs to the Console BFF, which stamps the operator and
// forwards to the Gateway (audited).

import { useCallback, useEffect, useState } from "react";
import {
  ShieldAlert, RefreshCw, Flag, Ban, Clock, Trash2, RotateCcw, Check, X,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";

type Report = {
  id: string;
  reporter_id: string;
  target_type: string;
  target_id: string;
  reason: string;
  description?: string;
  status: string;
  created_at: string;
};
type Stats = {
  open: number; reviewing: number; resolved: number; dismissed: number;
  by_reason: { reason: string; count: number }[] | null;
  top_users: { key: string; count: number }[] | null;
  top_posts: { key: string; count: number }[] | null;
};
type ActionRow = {
  id: string; moderator_id: string; action: string;
  target_type: string; target_id: string; note?: string; created_at: string;
};

const REASON_LABEL: Record<string, string> = {
  inappropriate: "Inappropriate",
  hate: "Hate / harassment",
  spam: "Spam / scam",
  violence: "Violence / threat",
  other: "Other",
};

const STATUSES = ["open", "reviewing", "resolved", "dismissed"] as const;
const REASONS = ["inappropriate", "hate", "spam", "violence", "other"] as const;

function short(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

export function ModerationCenter() {
  const [reports, setReports] = useState<Report[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [status, setStatus] = useState<string>("open");
  const [reason, setReason] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (reason) params.set("reason", reason);
      const [r, s, a] = await Promise.all([
        fetch(withBasePath(`/api/v1/moderation/reports?${params}`), { cache: "no-store" }),
        fetch(withBasePath("/api/v1/moderation/stats"), { cache: "no-store" }),
        fetch(withBasePath("/api/v1/moderation/actions?limit=25"), { cache: "no-store" }),
      ]);
      if (r.ok) setReports((await r.json()).reports ?? []);
      if (s.ok) setStats(await s.json());
      if (a.ok) setActions((await a.json()).actions ?? []);
    } finally {
      setLoading(false);
    }
  }, [status, reason]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const act = useCallback(
    async (report: Report, action: string, suspendDays?: number) => {
      setBusy(report.id + action);
      setError(null);
      try {
        const res = await fetch(withBasePath("/api/v1/moderation/actions"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            report_id: report.id,
            target_type: report.target_type,
            target_id: report.target_id,
            suspend_days: suspendDays,
          }),
        });
        if (!res.ok && res.status !== 204) {
          const body = await res.json().catch(() => ({}));
          setError(body.error ?? `Action failed (${res.status})`);
        }
        await refresh();
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const isContent = (t: string) => t === "post" || t === "comment";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <ShieldAlert className="h-5 w-5 text-primary" /> Moderation Center
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            UGC reports → review → action. Every action is audited.
          </p>
        </div>
        <button
          onClick={refresh}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {/* stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Open", value: stats?.open ?? 0, tone: "text-amber-400" },
          { label: "Reviewing", value: stats?.reviewing ?? 0, tone: "text-sky-400" },
          { label: "Resolved", value: stats?.resolved ?? 0, tone: "text-emerald-400" },
          { label: "Dismissed", value: stats?.dismissed ?? 0, tone: "text-muted-foreground" },
        ].map((c) => (
          <div key={c.label} className="rounded-xl border border-border bg-card/60 p-4">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{c.label}</p>
            <p className={cn("mt-2 font-mono text-2xl font-semibold tabular-nums", c.tone)}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* by-reason + most-reported users */}
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-card/60 p-4">
          <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">Reports by reason</p>
          <div className="space-y-1.5">
            {(stats?.by_reason ?? []).length === 0 && (
              <p className="text-xs text-muted-foreground">No reports.</p>
            )}
            {(stats?.by_reason ?? []).map((r) => (
              <div key={r.reason} className="flex items-center justify-between text-sm">
                <span>{REASON_LABEL[r.reason] ?? r.reason}</span>
                <span className="font-mono text-muted-foreground">{r.count}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card/60 p-4">
          <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">Most-reported users</p>
          <div className="space-y-1.5">
            {(stats?.top_users ?? []).length === 0 && (
              <p className="text-xs text-muted-foreground">None.</p>
            )}
            {(stats?.top_users ?? []).map((u) => (
              <div key={u.key} className="flex items-center justify-between text-sm">
                <span className="font-mono">{short(u.key)}</span>
                <span className="font-mono text-muted-foreground">{u.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter label="Status" value={status} onChange={setStatus} options={["", ...STATUSES]} />
        <Filter label="Reason" value={reason} onChange={setReason} options={["", ...REASONS]} />
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>

      {/* queue */}
      <div className="space-y-2">
        {loading && reports.length === 0 && (
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card/60" />
        )}
        {!loading && reports.length === 0 && (
          <div className="rounded-xl border border-border bg-card/60 p-6 text-center text-sm text-muted-foreground">
            No reports match this filter.
          </div>
        )}
        {reports.map((r) => (
          <div key={r.id} className="rounded-xl border border-border bg-card/60 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <Flag className="h-3.5 w-3.5 text-amber-400" />
                  <span className="text-sm font-semibold">
                    {REASON_LABEL[r.reason] ?? r.reason}
                  </span>
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {r.target_type}
                  </span>
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {r.status}
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  target {short(r.target_id)} · by {short(r.reporter_id)} ·{" "}
                  {new Date(r.created_at).toLocaleString()}
                </p>
                {r.description ? (
                  <p className="mt-1 text-sm text-foreground/90">{r.description}</p>
                ) : null}
              </div>
            </div>

            {r.status === "open" || r.status === "reviewing" ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {isContent(r.target_type) && (
                  <ActBtn icon={Trash2} label="Remove content" tone="danger"
                    busy={busy === r.id + "remove_content"}
                    onClick={() => act(r, "remove_content")} />
                )}
                {isContent(r.target_type) && (
                  <ActBtn icon={RotateCcw} label="Restore"
                    busy={busy === r.id + "restore_content"}
                    onClick={() => act(r, "restore_content")} />
                )}
                {r.target_type === "user" && (
                  <ActBtn icon={Clock} label="Suspend 7d"
                    busy={busy === r.id + "suspend_user"}
                    onClick={() => act(r, "suspend_user", 7)} />
                )}
                {r.target_type === "user" && (
                  <ActBtn icon={Ban} label="Ban user" tone="danger"
                    busy={busy === r.id + "ban_user"}
                    onClick={() => act(r, "ban_user")} />
                )}
                <ActBtn icon={X} label="Dismiss"
                  busy={busy === r.id + "dismiss"}
                  onClick={() => act(r, "dismiss")} />
              </div>
            ) : (
              <p className="mt-2 inline-flex items-center gap-1 text-xs text-emerald-400">
                <Check className="h-3.5 w-3.5" /> {r.status}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* audit log */}
      <div className="rounded-xl border border-border bg-card/60 p-4">
        <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
          Recent actions (audit)
        </p>
        <div className="space-y-1.5">
          {actions.length === 0 && (
            <p className="text-xs text-muted-foreground">No actions yet.</p>
          )}
          {actions.map((a) => (
            <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span>
                <span className="font-semibold">{a.action}</span>{" "}
                <span className="text-muted-foreground">
                  {a.target_type} {short(a.target_id)}
                </span>
              </span>
              <span className="font-mono text-muted-foreground">
                {a.moderator_id} · {new Date(a.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Filter({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
}) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-border bg-card px-2 py-1 text-xs text-foreground"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o === "" ? "all" : o}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActBtn({
  icon: Icon, label, onClick, busy, tone,
}: {
  icon: typeof Ban;
  label: string;
  onClick: () => void;
  busy: boolean;
  tone?: "danger";
}) {
  return (
    <button
      disabled={busy}
      onClick={onClick}
      className={cn(
        "ix-transition inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium disabled:opacity-50",
        tone === "danger"
          ? "border-red-500/30 bg-red-500/[0.06] text-red-400 hover:bg-red-500/[0.12]"
          : "border-border bg-card hover:bg-accent",
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {label}
    </button>
  );
}
