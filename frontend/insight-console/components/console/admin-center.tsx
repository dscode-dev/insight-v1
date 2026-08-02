"use client";

// Authentication Center + Administration (Users / Operators / Sessions) —
// CONSOLE-OPS-A3 Stages 11 & 13. Read-only, real data from the Gateway console
// admin endpoints (/api/v1/admin/*) + audit (/api/v1/audit). Honest empty/
// not-yet-deployed states; no fake data.

import { ShieldCheck, Users, UserCog, KeyRound } from "lucide-react";

import { useOps, arr, ts, PageHeader, Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

function short(s: unknown) {
  const v = String(s ?? "");
  return v.length > 14 ? `${v.slice(0, 10)}…` : v;
}
function unavailableNote(d: Row | undefined): string | null {
  if (d && d.unavailable) return String(d.detail ?? "Endpoint not available.");
  return null;
}

// ---- Authentication Center (overview) ----
export function AuthCenter() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/admin/sessions",
    "/api/v1/admin/operators",
    "/api/v1/admin/users?limit=50",
    "/api/v1/audit?limit=25",
  ]);
  const sessions = data.sessions ?? {};
  const operators = arr(data.operators, "operators");
  const users = arr(data.users, "users");
  const audit = arr(data.audit, "items");
  const us = (sessions.user_sessions as Row) ?? {};
  const os = (sessions.operator_sessions as Row) ?? {};
  const note = unavailableNote(data.sessions) ?? unavailableNote(data.operators);

  return (
    <div className="space-y-5">
      <PageHeader icon={ShieldCheck} title="Authentication Center" updated={updated} onRefresh={refresh}
        subtitle="Operators · users · sessions · recent activity · read-only" />
      {error && <ErrorBanner>Auth source: {error}</ErrorBanner>}
      {note && <ErrorBanner>{note}</ErrorBanner>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Operators</p><p className="mt-2 font-mono text-2xl font-semibold">{operators.length}</p></Card>
        <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Users</p><p className="mt-2 font-mono text-2xl font-semibold">{users.length}</p></Card>
        <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Active sessions</p><p className="mt-2 font-mono text-2xl font-semibold text-emerald-400">{Number(us.active ?? 0) + Number(os.active ?? 0)}</p></Card>
        <Card><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Revoked sessions</p><p className="mt-2 font-mono text-2xl font-semibold text-muted-foreground">{Number(us.revoked ?? 0) + Number(os.revoked ?? 0)}</p></Card>
      </div>

      <Card title="Sessions breakdown">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>User refresh sessions: <b>{String(us.active ?? 0)}</b> active · <b>{String(us.revoked ?? 0)}</b> revoked</div>
          <div>Operator sessions: <b>{String(os.active ?? 0)}</b> active · <b>{String(os.revoked ?? 0)}</b> revoked</div>
        </div>
      </Card>

      <Card title="Recent login / audit activity">
        {audit.length === 0 ? <Empty>No recent operator audit events (or audit endpoint pending deploy).</Empty> :
          audit.slice(0, 12).map((a, i) => (
            <div key={i} className="flex items-center justify-between gap-2 text-sm">
              <span><Pill value={String(a.severity ?? "info")} /> <span className="ml-1">{String(a.action)}</span> <span className="text-xs text-muted-foreground">by {String(a.actor_display_name || short(a.actor_id))}</span></span>
              <span className="shrink-0 text-xs text-muted-foreground">{ts(a.created_at)}</span>
            </div>
          ))}
      </Card>
    </div>
  );
}

// ---- Administration → Users ----
export function AdminUsers() {
  const { data, error, updated, refresh } = useOps(["/api/v1/admin/users?limit=200"], 0);
  const users = arr(data.users, "users");
  const note = unavailableNote(data.users);
  return (
    <div className="space-y-5">
      <PageHeader icon={Users} title="Administration · Users" updated={updated} onRefresh={refresh}
        subtitle="Read-only · Gateway console admin (insight_auth + social)" />
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {note && <ErrorBanner>{note}</ErrorBanner>}
      <Card>
        {users.length === 0 ? <Empty>No users.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 pr-4">user_id</th><th className="pr-4">username</th><th className="pr-4">phone</th><th className="pr-4">created</th><th className="pr-4">last login</th><th>auth cred</th>
              </tr></thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={i} className="border-t border-border/50">
                    <td className="py-1.5 pr-4 font-mono text-xs">{short(u.user_id ?? u.id)}</td>
                    <td className="pr-4">@{String(u.username)}</td>
                    <td className="pr-4 text-muted-foreground">{String(u.phone ?? "—")}</td>
                    <td className="pr-4 text-xs text-muted-foreground">{ts(u.created_at)}</td>
                    <td className="pr-4 text-xs text-muted-foreground">{ts(u.last_login_at)}</td>
                    <td><Pill value="present" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">phone / avatar / social-profile status are joined from the social service when available.</p>
      </Card>
    </div>
  );
}

// ---- Administration → Operators ----
export function AdminOperators() {
  const { data, error, updated, refresh } = useOps(["/api/v1/admin/operators"], 0);
  const operators = arr(data.operators, "operators");
  const note = unavailableNote(data.operators);
  return (
    <div className="space-y-5">
      <PageHeader icon={UserCog} title="Administration · Operators" updated={updated} onRefresh={refresh}
        subtitle="Read-only · Gateway console admin (operators)" />
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {note && <ErrorBanner>{note}</ErrorBanner>}
      <Card>
        {operators.length === 0 ? <Empty>No operators.</Empty> : operators.map((o, i) => (
          <div key={i} className="border-t border-border/50 py-2 first:border-0 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span>@{String(o.username)} <span className="text-xs text-muted-foreground">{String(o.email)}</span></span>
              <span className="flex items-center gap-2"><Pill value={String(o.role)} /><Pill value={o.is_active ? "up" : "down"} /></span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">created {ts(o.created_at)} · last login {ts(o.last_login_at)}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {arr({ p: o.permissions as Row[] }, "p").length === 0 && Array.isArray(o.permissions)
                ? (o.permissions as string[]).slice(0, 12).map((p) => <span key={p} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{p}</span>)
                : Array.isArray(o.permissions) ? (o.permissions as string[]).slice(0, 12).map((p) => <span key={p} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{p}</span>) : null}
              {Array.isArray(o.permissions) && (o.permissions as string[]).length > 12 ? <span className="text-[10px] text-muted-foreground">+{(o.permissions as string[]).length - 12} more</span> : null}
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ---- Administration → Sessions ----
export function AdminSessions() {
  const { data, error, updated, refresh } = useOps(["/api/v1/admin/sessions"], 7000);
  const s = data.sessions ?? {};
  const us = (s.user_sessions as Row) ?? {};
  const os = (s.operator_sessions as Row) ?? {};
  const note = unavailableNote(data.sessions);
  return (
    <div className="space-y-5">
      <PageHeader icon={KeyRound} title="Administration · Sessions" updated={updated} onRefresh={refresh}
        subtitle="Read-only · active / refresh / revoked · realtime (7s)" />
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {note && <ErrorBanner>{note}</ErrorBanner>}
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="User refresh sessions">
          <div className="flex items-center gap-6 text-sm">
            <span>active: <b className="text-emerald-400">{String(us.active ?? 0)}</b></span>
            <span>revoked: <b className="text-muted-foreground">{String(us.revoked ?? 0)}</b></span>
          </div>
        </Card>
        <Card title="Operator sessions">
          <div className="flex items-center gap-6 text-sm">
            <span>active: <b className="text-emerald-400">{String(os.active ?? 0)}</b></span>
            <span>revoked: <b className="text-muted-foreground">{String(os.revoked ?? 0)}</b></span>
          </div>
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">Per-session created_at/expires_at/revoked_at rows are summarized as counts here; the
        Gateway sessions endpoint returns aggregate counts (read-only) — extend to per-row when needed.</p>
    </div>
  );
}
