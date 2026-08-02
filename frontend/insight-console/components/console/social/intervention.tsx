"use client";

// CONSOLE-SOCIAL-B — Social Enforcement intervention controls. Client component
// consumed inside investigation context (user/agent/post/comment/report). It:
//  - shows the REAL current enforcement state (read model, never a decorative flag);
//  - offers typed, per-action commands with a professional confirmation flow;
//  - requires a mandatory reason (+ optional expiry for suspension, linked report);
//  - states the EXACT enforced impact (matching the backend);
//  - NEVER shows optimistic success — it waits for server confirmation and renders
//    pending / success / conflict(state-changed) / unauthorized / unavailable / timeout;
//  - refreshes the enforcement state + calls onDone after a successful mutation.
//
// The browser calls only the Console BFF (/api/v1/social/*). Operator identity is
// server-derived; the payload carries reason/expiry/report only — never an actor.

import { useEffect, useState } from "react";

import { withBasePath } from "@/lib/base-path";

export type TargetType = "user" | "post" | "comment" | "agent" | "report";

type ActionDef = {
  key: string;
  label: string;
  path: (id: string) => string;
  destructive: boolean;
  needsExpiry?: boolean;
  impact: string;
  resulting: string;
};

// Impact copy MUST match enforced backend semantics (CONSOLE_SOCIAL_B_*_POLICY).
const ACTIONS: Record<TargetType, ActionDef[]> = {
  user: [
    { key: "suspend", label: "Suspend", path: (id) => `users/${id}/suspend`, destructive: true, needsExpiry: true, resulting: "suspended",
      impact: "New participation (post, comment, like, follow, boost, save) is blocked and active sessions are revoked. Public reads still work. Existing content stays visible unless separately hidden." },
    { key: "unsuspend", label: "Unsuspend", path: (id) => `users/${id}/unsuspend`, destructive: false, resulting: "active",
      impact: "Participation is restored. The user may authenticate and act again." },
    { key: "ban", label: "Ban", path: (id) => `users/${id}/ban`, destructive: true, resulting: "banned",
      impact: "All participation is blocked indefinitely and active sessions are revoked. Reversal requires an explicit Unban. Existing content stays visible unless separately hidden." },
    { key: "unban", label: "Unban", path: (id) => `users/${id}/unban`, destructive: false, resulting: "active",
      impact: "The ban is lifted. The user may authenticate and participate again." },
  ],
  post: [
    { key: "hide", label: "Hide", path: (id) => `posts/${id}/hide`, destructive: true, resulting: "hidden",
      impact: "The post is removed from consumer surfaces (feed, detail, profile, saved). It is NOT deleted and stays visible to operator investigation." },
    { key: "restore", label: "Restore", path: (id) => `posts/${id}/restore`, destructive: false, resulting: "visible",
      impact: "The post reappears on consumer surfaces." },
  ],
  comment: [
    { key: "hide", label: "Hide", path: (id) => `comments/${id}/hide`, destructive: true, resulting: "hidden",
      impact: "The comment is removed from consumer surfaces. Thread structure is preserved (replies remain; the hidden parent is not shown to consumers). Not deleted; visible to operators." },
    { key: "restore", label: "Restore", path: (id) => `comments/${id}/restore`, destructive: false, resulting: "visible",
      impact: "The comment reappears on consumer surfaces." },
  ],
  agent: [
    { key: "deactivate", label: "Deactivate", path: (id) => `agents/${id}/deactivate`, destructive: true, resulting: "inactive",
      impact: "The agent can no longer publish through ANY path (Nexus/workers) — enforced at the publication choke point. Historical content is preserved. No ownership/user linkage is implied." },
    { key: "reactivate", label: "Reactivate", path: (id) => `agents/${id}/reactivate`, destructive: false, resulting: "active",
      impact: "The agent may publish again." },
  ],
  report: [
    { key: "review", label: "Mark reviewing", path: (id) => `reports/${id}/review`, destructive: false, resulting: "reviewing",
      impact: "The report moves to 'reviewing'. No content/user side effects." },
    { key: "resolve", label: "Resolve", path: (id) => `reports/${id}/resolve`, destructive: false, resulting: "resolved",
      impact: "The report is closed as resolved. No content/user side effects (use the content/user actions for those)." },
    { key: "dismiss", label: "Dismiss", path: (id) => `reports/${id}/dismiss`, destructive: false, resulting: "dismissed",
      impact: "The report is dismissed. No content/user side effects." },
  ],
};

type Phase = "idle" | "pending" | "success" | "error";
type Result = { phase: Phase; code?: string; status?: number; state?: string };

const ERR: Record<string, string> = {
  "403": "Unauthorized — your operator role lacks the required capability.",
  "401": "Unauthorized — operator session invalid.",
  "409": "State changed — the target is no longer in a valid state for this action. Reload and re-check.",
  "404": "Target not found.",
  "400": "Invalid request.",
  "503": "Enforcement service unavailable — no change was made.",
  "504": "Timeout — the result is UNKNOWN. Reload to verify before retrying.",
  "502": "Upstream error — no confirmed change. Reload to verify.",
};

export function InterventionControls({
  targetType,
  targetId,
  targetLabel,
  reportId,
  onDone,
}: {
  targetType: TargetType;
  targetId: string;
  targetLabel: string;
  reportId?: string;
  onDone?: () => void;
}) {
  const [open, setOpen] = useState<ActionDef | null>(null);
  const [reason, setReason] = useState("");
  const [days, setDays] = useState<string>("");
  const [res, setRes] = useState<Result>({ phase: "idle" });
  const [state, setState] = useState<{ value: string; expires?: string } | null>(null);
  const [tick, setTick] = useState(0);

  // enforcement state read model (users/posts/comments only — agents/reports have
  // their own state surfaced by their detail views).
  const stateType = targetType === "user" ? "user" : targetType === "post" ? "post" : targetType === "comment" ? "comment" : null;
  useEffect(() => {
    if (!stateType) return;
    let alive = true;
    fetch(withBasePath(`/api/v1/social/enforcement/${stateType}/${targetId}`), { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => alive && b && setState({ value: String(b.state ?? "unknown"), expires: b.expires_at }))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [stateType, targetId, tick]);

  const actions = ACTIONS[targetType];

  async function submit() {
    if (!open) return;
    if (reason.trim().length === 0) {
      setRes({ phase: "error", code: "reason_required" });
      return;
    }
    setRes({ phase: "pending" });
    const body: Record<string, unknown> = { reason: reason.trim() };
    if (open.needsExpiry && days.trim() !== "") body.suspend_days = Number(days);
    if (reportId) body.report_id = reportId;
    try {
      const r = await fetch(withBasePath(`/api/v1/social/${open.path(targetId)}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(body),
      });
      const b = await r.json().catch(() => ({}));
      if (r.ok) {
        setRes({ phase: "success", state: String((b as Record<string, unknown>).resulting_state ?? open.resulting) });
        setTick((t) => t + 1);
        onDone?.();
      } else {
        setRes({ phase: "error", code: String((b as Record<string, unknown>).code ?? (b as Record<string, unknown>).error ?? r.status), status: r.status });
      }
    } catch {
      setRes({ phase: "error", code: "network", status: 0 });
    }
  }

  function close() {
    setOpen(null);
    setReason("");
    setDays("");
    setRes({ phase: "idle" });
  }

  return (
    <div className="rounded border border-neutral-800 bg-neutral-900/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wide text-neutral-500">Enforcement</div>
        {state ? (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <StatePill value={state.value} />
            {state.expires ? <span className="text-neutral-500">until {new Date(state.expires).toLocaleString()}</span> : null}
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {actions.map((a) => (
          <button
            key={a.key}
            onClick={() => {
              setRes({ phase: "idle" });
              setOpen(a);
            }}
            className={`rounded px-2 py-1 text-xs font-medium ${
              a.destructive
                ? "border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20"
                : "border border-neutral-700 bg-neutral-800/60 text-neutral-200 hover:bg-neutral-800"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-lg rounded-lg border border-neutral-700 bg-neutral-950 p-5 shadow-xl">
            <div className="mb-1 text-sm font-semibold text-neutral-100">
              {open.label} — <span className="text-neutral-400">{targetLabel}</span>
            </div>
            <div className="mb-3 flex items-center gap-2 text-xs text-neutral-400">
              <span>current</span>
              <StatePill value={state?.value ?? "—"} />
              <span>→</span>
              <StatePill value={open.resulting} />
            </div>
            <p className="mb-3 rounded border border-neutral-800 bg-neutral-900/60 p-2 text-xs leading-relaxed text-neutral-300">
              {open.impact}
            </p>

            {res.phase === "success" ? (
              <div className="mb-3 rounded border border-emerald-500/30 bg-emerald-500/10 p-2 text-xs text-emerald-300">
                Confirmed by server. Resulting state: <b>{res.state}</b>.
              </div>
            ) : res.phase === "error" ? (
              <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
                {res.code === "reason_required" ? "A reason is required." : ERR[String(res.status ?? res.code)] ?? `Failed (${res.code ?? res.status}).`}
              </div>
            ) : null}

            {res.phase !== "success" ? (
              <>
                <label className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500">Reason (required)</label>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  maxLength={512}
                  disabled={res.phase === "pending"}
                  className="mb-3 w-full rounded border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
                  placeholder="Why is this intervention being performed? (audited)"
                />
                {open.needsExpiry ? (
                  <div className="mb-3">
                    <label className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500">Suspension days (optional; blank = indefinite)</label>
                    <input
                      type="number"
                      min={1}
                      max={3650}
                      value={days}
                      onChange={(e) => setDays(e.target.value)}
                      disabled={res.phase === "pending"}
                      className="w-32 rounded border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
                    />
                  </div>
                ) : null}
                {reportId ? <div className="mb-3 text-[11px] text-neutral-500">Linked report: {reportId.slice(0, 8)}…</div> : null}
              </>
            ) : null}

            <div className="flex justify-end gap-2">
              <button onClick={close} className="rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800">
                {res.phase === "success" ? "Close" : "Cancel"}
              </button>
              {res.phase !== "success" ? (
                <button
                  onClick={submit}
                  disabled={res.phase === "pending"}
                  className={`rounded px-3 py-1.5 text-xs font-medium ${
                    open.destructive ? "bg-red-600 text-white hover:bg-red-500" : "bg-neutral-200 text-neutral-900 hover:bg-white"
                  } disabled:opacity-50`}
                >
                  {res.phase === "pending" ? "Applying…" : `Confirm ${open.label}`}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StatePill({ value }: { value: string }) {
  const cls =
    value === "banned" || value === "hidden" || value === "inactive"
      ? "bg-red-500/15 text-red-300"
      : value === "suspended" || value === "reviewing"
        ? "bg-amber-500/15 text-amber-300"
        : value === "active" || value === "visible"
          ? "bg-emerald-500/15 text-emerald-300"
          : "bg-neutral-700/40 text-neutral-300";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls}`}>{value}</span>;
}
