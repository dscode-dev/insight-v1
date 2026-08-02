"use client";

// CONSOLE-SOCIAL-A1 — Social Observatory operator workspaces. Client components
// that consume the Console BFF (/api/v1/social/*). The browser never reaches
// Social. Dense, investigation-oriented; honest loading/empty/partial/unavailable/
// unauthorized/error states; author_type preserved end-to-end; deep-linkable.

import { useEffect, useState } from "react";
import Link from "next/link";

import { withBasePath } from "@/lib/base-path";
import { InterventionControls, type TargetType } from "@/components/console/social/intervention";

type Row = Record<string, unknown>;
const s = (v: unknown, f = "—") => (v === null || v === undefined || v === "" ? f : String(v));
const n = (v: unknown) => (typeof v === "number" ? v : Number(v ?? 0) || 0);

// ---- fetch hook with canonical state distinction ----
type Load<T> = { phase: "loading" | "success" | "error"; data: T | null; code: string | null; status: number };

function useSocial<T = Row>(path: string | null): Load<T> & { reload: () => void } {
  const [st, setSt] = useState<Load<T>>({ phase: "loading", data: null, code: null, status: 0 });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setSt((p) => ({ ...p, phase: "loading" }));
    fetch(withBasePath(path), { cache: "no-store" })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!alive) return;
        if (r.ok) setSt({ phase: "success", data: body as T, code: null, status: r.status });
        else setSt({ phase: "error", data: null, code: String((body as Row)?.code ?? (body as Row)?.error ?? "error"), status: r.status });
      })
      .catch(() => alive && setSt({ phase: "error", data: null, code: "UNAVAILABLE", status: 0 }));
    return () => {
      alive = false;
    };
  }, [path, tick]);
  return { ...st, reload: () => setTick((t) => t + 1) };
}

// ---- primitives ----
function StateBlock({ load, empty }: { load: Load<unknown>; empty?: boolean }) {
  if (load.phase === "loading") return <div className="p-6 text-sm text-neutral-400">Loading…</div>;
  if (load.phase === "error") {
    const map: Record<string, string> = {
      UNAUTHORIZED: "Unauthorized — your operator session cannot read this.",
      FORBIDDEN: "Forbidden — missing capability.",
      SERVICE_UNAVAILABLE: "Social read plane unavailable (source down).",
      TIMEOUT: "Upstream timeout — state unknown, not empty.",
      NOT_FOUND: "Not found.",
      CAPABILITY_UNSUPPORTED: "Unsupported.",
    };
    return (
      <div className="p-6 text-sm text-amber-400">
        {map[load.code ?? ""] ?? `Error (${load.code ?? load.status})`}
      </div>
    );
  }
  if (empty) return <div className="p-6 text-sm text-neutral-500">No records.</div>;
  return null;
}

function AuthorType({ t }: { t: unknown }) {
  const v = String(t ?? "");
  const cls =
    v === "agent" ? "bg-violet-500/15 text-violet-300" : v === "admin" ? "bg-amber-500/15 text-amber-300" : "bg-sky-500/15 text-sky-300";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls}`}>{v || "?"}</span>;
}

function AuthorCell({ author }: { author: Row | undefined }) {
  const a = author ?? {};
  const type = String(a["type"] ?? "");
  const label = String(a["display_name"] ?? "") || String(a["username"] ?? "");
  const href = type === "user" ? `/social/users/${a["id"]}` : type === "agent" ? `/social/agents/${a["id"]}` : "";
  const resolved = a["resolved"] !== false && (label || type === "admin");
  const name = resolved ? label || (type === "admin" ? "Admin" : "") : "";
  const inner = (
    <span className="inline-flex items-center gap-1.5">
      <AuthorType t={type} />
      {name ? (
        <span className="text-neutral-200">{name}</span>
      ) : (
        <span className="text-neutral-500" title="identity unavailable — id/type preserved">
          {`unresolved ${String(a["id"] ?? "").slice(0, 8)}`}
        </span>
      )}
      {a["username"] && name !== `@${a["username"]}` ? <span className="text-neutral-500">@{s(a["username"])}</span> : null}
    </span>
  );
  return href && resolved ? (
    <Link href={withBasePath(href)} className="hover:underline">
      {inner}
    </Link>
  ) : (
    inner
  );
}

function Metric({ label, value, muted }: { label: string; value: React.ReactNode; muted?: boolean }) {
  return (
    <div className="rounded border border-neutral-800 bg-neutral-900/40 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`text-lg tabular-nums ${muted ? "text-neutral-500" : "text-neutral-100"}`}>{value}</div>
    </div>
  );
}

function Bread({ items }: { items: Array<{ label: string; href?: string }> }) {
  return (
    <nav className="mb-3 flex items-center gap-1.5 text-xs text-neutral-500">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 ? <span>/</span> : null}
          {it.href ? (
            <Link href={withBasePath(it.href)} className="hover:text-neutral-300">
              {it.label}
            </Link>
          ) : (
            <span className="text-neutral-300">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

const H = "border-b border-neutral-800 px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-neutral-500";
const TD = "border-b border-neutral-900 px-3 py-2 align-top text-neutral-300";
const dt = (v: unknown) => (v ? new Date(String(v)).toLocaleString() : "—");

// ================= OVERVIEW =================
export function SocialOverview() {
  const [win, setWin] = useState("7d");
  const load = useSocial(`/api/v1/social/overview?window=${win}`);
  const d = (load.data ?? {}) as Row;
  const totals = (d["totals"] ?? {}) as Row;
  const authorship = (d["authorship"] ?? {}) as Row;
  const recent = (d["recent"] ?? {}) as Row;
  const unavailable = Array.isArray(d["unavailable"]) ? (d["unavailable"] as string[]) : [];
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-neutral-100">Social Overview</h1>
        <select aria-label="time window" value={win} onChange={(e) => setWin(e.target.value)} className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-300">
          {["1d", "7d", "30d", "90d"].map((w) => (
            <option key={w} value={w}>Last {w}</option>
          ))}
        </select>
      </div>
      {load.phase !== "success" ? (
        <StateBlock load={load} />
      ) : (
        <>
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Totals · source {s(d["source"])}</div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-5">
              <Metric label="Users" value={n(totals["users"]).toLocaleString()} />
              <Metric label="Agents" value={`${n(totals["active_agents"])}/${n(totals["agents"])}`} />
              <Metric label="Posts" value={n(totals["posts"]).toLocaleString()} />
              <Metric label="Comments" value={n(totals["comments"]).toLocaleString()} />
              <Metric label="Follows" value={n(totals["follows"]).toLocaleString()} />
              <Metric label="Active boosts" value={n(totals["active_boosts"]).toLocaleString()} />
              <Metric label="Communities" value={n(totals["communities"]).toLocaleString()} />
              <Metric label="Saves (aggregate)" value={n(totals["saves"]).toLocaleString()} />
            </div>
          </section>
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Content origin (author_type)</div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              <Metric label="Posts · user" value={n(authorship["posts_by_user"]).toLocaleString()} />
              <Metric label="Posts · agent" value={n(authorship["posts_by_agent"]).toLocaleString()} />
              <Metric label="Posts · admin" value={n(authorship["posts_by_admin"]).toLocaleString()} />
              <Metric label="Comments · user" value={n(authorship["comments_by_user"]).toLocaleString()} />
              <Metric label="Comments · agent" value={n(authorship["comments_by_agent"]).toLocaleString()} />
            </div>
          </section>
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Recent · {s(recent["window"])}</div>
            <div className="grid grid-cols-3 gap-2 md:grid-cols-3">
              <Metric label="Posts" value={n(recent["posts"]).toLocaleString()} />
              <Metric label="Comments" value={n(recent["comments"]).toLocaleString()} />
              <Metric label="Authoring users" value={n(recent["authoring_users"]).toLocaleString()} />
            </div>
          </section>
          {unavailable.length > 0 ? (
            <section>
              <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Unavailable (no source of truth)</div>
              <div className="flex flex-wrap gap-2">
                {unavailable.map((u) => (
                  <Metric key={u} label={u} value="unknown" muted />
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

// ================= ACTIVITY =================
export function SocialActivity() {
  const [kind, setKind] = useState("");
  const load = useSocial(`/api/v1/social/activity?limit=100${kind ? `&kind=${kind}` : ""}`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  const link = (t: string, id: string) =>
    t === "post" ? `/social/posts/${id}` : t === "user" || t === "account" ? `/social/users/${id}` : "";
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-neutral-100">Activity Stream</h1>
        <span className="text-xs text-neutral-500">provenance: projection (durable rows, not an event log)</span>
      </div>
      <div className="flex gap-2 text-sm">
        <select aria-label="activity kind" value={kind} onChange={(e) => setKind(e.target.value)} className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-neutral-300">
          {["", "post_created", "comment_created", "follow_created", "boost_activated"].map((k) => (
            <option key={k} value={k}>{k || "all kinds"}</option>
          ))}
        </select>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>When</th><th className={H}>Kind</th><th className={H}>Actor</th><th className={H}>Target</th></tr></thead>
          <tbody>
            {items.filter((it) => !kind || it["kind"] === kind).map((it) => {
              const actor = (it["actor"] ?? {}) as Row;
              const target = (it["target"] ?? {}) as Row;
              const tHref = link(String(target["type"]), String(target["id"]));
              return (
                <tr key={String(it["id"]) + String(it["kind"])}>
                  <td className={TD}>{dt(it["at"])}</td>
                  <td className={TD}><span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[11px]">{s(it["kind"])}</span></td>
                  <td className={TD}><AuthorType t={actor["type"]} /> <span className="text-neutral-500">{String(actor["id"]).slice(0, 8)}</span></td>
                  <td className={TD}>{tHref ? <Link className="hover:underline" href={withBasePath(tHref)}>{s(target["type"])} {String(target["id"]).slice(0, 8)}</Link> : `${s(target["type"])} ${String(target["id"]).slice(0, 8)}`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

// ================= USERS =================
export function SocialUsers() {
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const load = useSocial(`/api/v1/social/users?limit=50${applied ? `&q=${encodeURIComponent(applied)}` : ""}`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Users</h1>
      <form onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }} className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search username / display name" className="w-72 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-200" />
        <button type="submit" className="rounded border border-neutral-700 px-3 py-1 text-sm text-neutral-300 hover:bg-neutral-800">Search</button>
      </form>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>User</th><th className={H}>Rep</th><th className={H}>Tier</th><th className={H}>Posts</th><th className={H}>Comments</th><th className={H}>Followers</th><th className={H}>Following</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((u) => (
              <tr key={s(u["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><Link href={withBasePath(`/social/users/${u["id"]}`)} className="text-neutral-100 hover:underline">{s(u["display_name"])}</Link> <span className="text-neutral-500">@{s(u["username"])}</span></td>
                <td className={TD}>{n(u["reputation"])}</td><td className={TD}>{s(u["tier"])}</td>
                <td className={TD}>{n(u["post_count"])}</td><td className={TD}>{n(u["comment_count"])}</td>
                <td className={TD}>{n(u["follower_count"])}</td><td className={TD}>{n(u["following_count"])}</td>
                <td className={TD}>{dt(u["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

export function SocialUserDetail({ id }: { id: string }) {
  const load = useSocial(`/api/v1/social/users/${id}`);
  const d = (load.data ?? {}) as Row;
  const idn = (d["identity"] ?? {}) as Row;
  const content = (d["content"] ?? {}) as Row;
  const rel = (d["relationships"] ?? {}) as Row;
  const posts = (d["recent_posts"] as Row[]) ?? [];
  return (
    <div className="space-y-4">
      <Bread items={[{ label: "Social", href: "/social" }, { label: "Users", href: "/social/users" }, { label: s(idn["display_name"], id) }]} />
      {load.phase !== "success" ? <StateBlock load={load} /> : (
        <>
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">{s(idn["display_name"])}</h1>
            <span className="text-neutral-500">@{s(idn["username"])}</span>
            <AuthorType t="user" />
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
            <Metric label="Reputation" value={n(idn["reputation"])} /><Metric label="Tier" value={s(idn["tier"])} />
            <Metric label="Posts" value={n(content["post_count"])} /><Metric label="Comments" value={n(content["comment_count"])} />
            <Metric label="Followers" value={n(rel["follower_count"])} /><Metric label="Following" value={n(rel["following_count"])} />
          </div>
          <div className="text-xs text-neutral-500">id {s(idn["id"])} · created {dt(idn["created_at"])} · communities {n(rel["community_count"])}</div>
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Recent posts</div>
            <PostMiniList posts={posts} />
          </section>
        </>
      )}
    </div>
  );
}

function PostMiniList({ posts }: { posts: Row[] }) {
  if (posts.length === 0) return <div className="text-sm text-neutral-500">No posts.</div>;
  return (
    <div className="divide-y divide-neutral-900 rounded border border-neutral-800">
      {posts.map((p) => (
        <Link key={s(p["id"])} href={withBasePath(`/social/posts/${p["id"]}`)} className="block px-3 py-2 hover:bg-neutral-900/40">
          <div className="text-sm text-neutral-300">{s(p["preview"])}</div>
          <div className="text-[11px] text-neutral-500">{dt(p["created_at"])} · {n(p["comment_count"])} comments · {n(p["boost_count"])} boosts · {s(p["visibility"])}</div>
        </Link>
      ))}
    </div>
  );
}

// ================= AGENTS =================
export function SocialAgents() {
  const load = useSocial(`/api/v1/social/agents`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Agents</h1>
      <p className="text-xs text-neutral-500">Platform agents. Agents have no owner user in Social (following ≠ ownership).</p>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Agent</th><th className={H}>Status</th><th className={H}>Posts</th><th className={H}>Comments</th><th className={H}>Followers</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={s(a["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><Link href={withBasePath(`/social/agents/${a["id"]}`)} className="text-neutral-100 hover:underline">{s(a["name"])}</Link> <span className="text-neutral-500">@{s(a["slug"])}</span> <AuthorType t="agent" /></td>
                <td className={TD}>{a["active"] ? <span className="text-emerald-400">active</span> : <span className="text-neutral-500">inactive</span>}{a["verified"] ? " · verified" : ""}</td>
                <td className={TD}>{n(a["post_count"])}</td><td className={TD}>{n(a["comment_count"])}</td>
                <td className={TD}>{n(a["follower_count"])}</td><td className={TD}>{dt(a["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

export function SocialAgentDetail({ id }: { id: string }) {
  const load = useSocial(`/api/v1/social/agents/${id}`);
  const d = (load.data ?? {}) as Row;
  const idn = (d["identity"] ?? {}) as Row;
  const content = (d["content"] ?? {}) as Row;
  const rel = (d["relationships"] ?? {}) as Row;
  const posts = (d["recent_posts"] as Row[]) ?? [];
  return (
    <div className="space-y-4">
      <Bread items={[{ label: "Social", href: "/social" }, { label: "Agents", href: "/social/agents" }, { label: s(idn["name"], id) }]} />
      {load.phase !== "success" ? <StateBlock load={load} /> : (
        <>
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">{s(idn["name"])}</h1>
            <span className="text-neutral-500">@{s(idn["slug"])}</span>
            <AuthorType t="agent" />
            {idn["active"] ? <span className="text-xs text-emerald-400">active</span> : <span className="text-xs text-neutral-500">inactive</span>}
          </div>
          <p className="max-w-2xl text-sm text-neutral-400">{s(idn["bio"])}</p>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Metric label="Posts" value={n(content["post_count"])} /><Metric label="Comments" value={n(content["comment_count"])} />
            <Metric label="Followers" value={n(rel["follower_count"])} /><Metric label="Identity type" value="Platform agent" muted />
          </div>
          <div className="text-xs text-neutral-500">id {s(idn["id"])} · verified {String(idn["verified"])} · created {dt(idn["created_at"])}</div>
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Recent posts</div>
            <PostMiniList posts={posts} />
          </section>
        </>
      )}
    </div>
  );
}

// ================= POSTS =================
export function SocialPosts() {
  const [atype, setAtype] = useState("");
  const [boosted, setBoosted] = useState(false);
  const load = useSocial(`/api/v1/social/posts?limit=50${atype ? `&author_type=${atype}` : ""}${boosted ? "&boosted=true" : ""}`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Posts</h1>
      <div className="flex items-center gap-2 text-sm">
        <select aria-label="author type" value={atype} onChange={(e) => setAtype(e.target.value)} className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-neutral-300">
          {["", "user", "agent", "admin"].map((t) => <option key={t} value={t}>{t || "all authors"}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-neutral-400"><input type="checkbox" checked={boosted} onChange={(e) => setBoosted(e.target.checked)} /> boosted only</label>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Author</th><th className={H}>Preview</th><th className={H}>Vis</th><th className={H}>Cmts</th><th className={H}>Likes</th><th className={H}>Boosts</th><th className={H}>Saves</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((p) => (
              <tr key={s(p["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><AuthorCell author={p["author"] as Row} /></td>
                <td className={TD}><Link href={withBasePath(`/social/posts/${p["id"]}`)} className="text-neutral-200 hover:underline">{s(p["preview"])}</Link></td>
                <td className={TD}>{s(p["visibility"])}</td><td className={TD}>{n(p["comment_count"])}</td>
                <td className={TD}>{n(p["like_count"])}</td><td className={TD}>{n(p["boost_count"])}</td><td className={TD}>{n(p["save_count"])}</td>
                <td className={TD}>{dt(p["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

export function SocialPostDetail({ id }: { id: string }) {
  const load = useSocial(`/api/v1/social/posts/${id}`);
  const d = (load.data ?? {}) as Row;
  const post = (d["post"] ?? {}) as Row;
  const eng = (d["engagement"] ?? {}) as Row;
  const comments = (d["comments"] as Row[]) ?? [];
  const boosts = (d["boosts"] as Row[]) ?? [];
  const roots = comments.filter((c) => !c["parent_id"]);
  const repliesOf = (pid: string) => comments.filter((c) => c["parent_id"] === pid);
  return (
    <div className="space-y-4">
      <Bread items={[{ label: "Social", href: "/social" }, { label: "Posts", href: "/social/posts" }, { label: String(id).slice(0, 8) }]} />
      {load.phase !== "success" ? <StateBlock load={load} /> : (
        <>
          <div className="rounded border border-neutral-800 bg-neutral-900/30 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm"><AuthorCell author={post["author"] as Row} /><span className="text-neutral-600">·</span><span className="text-neutral-500">{dt(post["created_at"])}</span>{post["deleted"] ? <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[11px] text-red-300">deleted</span> : null}</div>
            <div className="whitespace-pre-wrap text-neutral-100">{s(post["content"])}</div>
            <div className="mt-2 text-xs text-neutral-500">visibility {s(post["visibility"])} · id {s(post["id"])}</div>
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <Metric label="Comments" value={n(eng["comment_count"])} /><Metric label="Likes" value={n(eng["like_count"])} />
            <Metric label="Active boosts" value={n(eng["boost_count"])} /><Metric label="Saves (aggregate)" value={n(eng["save_count"])} />
            <Metric label="Author type" value={s(post["author_type"])} />
          </div>
          {boosts.length > 0 ? (
            <section>
              <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Boosts</div>
              <div className="flex flex-wrap gap-2 text-xs">
                {boosts.map((b) => (
                  <span key={s(b["id"])} className="rounded border border-neutral-800 px-2 py-1 text-neutral-400">{s(b["boost_type"])} · w{n(b["weight"])} · {s(b["status"])}{b["expires_at"] ? ` · exp ${dt(b["expires_at"])}` : ""}</span>
                ))}
              </div>
            </section>
          ) : null}
          <section>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Comments ({comments.length}) — depth ≤ 2</div>
            <div className="space-y-2">
              {roots.map((c) => (
                <div key={s(c["id"])} className="rounded border border-neutral-800">
                  <CommentRow c={c} />
                  {repliesOf(String(c["id"])).map((r) => (
                    <div key={s(r["id"])} className="ml-6 border-l border-neutral-800"><CommentRow c={r} reply /></div>
                  ))}
                </div>
              ))}
              {comments.length === 0 ? <div className="text-sm text-neutral-500">No comments.</div> : null}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function CommentRow({ c, reply }: { c: Row; reply?: boolean }) {
  return (
    <div className={`px-3 py-2 ${reply ? "bg-neutral-900/20" : ""}`}>
      <div className="mb-1 flex items-center gap-2 text-xs"><AuthorCell author={c["author"] as Row} /><span className="text-neutral-600">·</span><span className="text-neutral-500">{dt(c["created_at"])}</span><span className="text-neutral-600">· depth {n(c["depth"])}</span></div>
      <div className="whitespace-pre-wrap text-sm text-neutral-300">{s(c["content"])}</div>
    </div>
  );
}

// ================= A2: COMMENTS OBSERVATORY =================
export function SocialComments() {
  const [atype, setAtype] = useState("");
  const load = useSocial(`/api/v1/social/comments?limit=50${atype ? `&author_type=${atype}` : ""}`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Comments</h1>
      <div className="flex items-center gap-2 text-sm">
        <select aria-label="author type" value={atype} onChange={(e) => setAtype(e.target.value)} className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-neutral-300">
          {["", "user", "agent", "admin"].map((t) => <option key={t} value={t}>{t || "all authors"}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Author</th><th className={H}>Comment</th><th className={H}>Depth</th><th className={H}>Replies</th><th className={H}>On post</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={s(c["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><AuthorCell author={c["author"] as Row} /></td>
                <td className={TD}><Link href={withBasePath(`/social/investigate/comment/${c["id"]}`)} className="text-neutral-200 hover:underline">{s(c["content"])}</Link></td>
                <td className={TD}>{n(c["depth"])}</td><td className={TD}>{n(c["reply_count"])}</td>
                <td className={TD}><Link href={withBasePath(`/social/posts/${c["post_id"]}`)} className="text-neutral-400 hover:underline">{s(c["post_preview"], "post")}</Link></td>
                <td className={TD}>{dt(c["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

// ================= A2: COMMUNITIES =================
export function SocialCommunities() {
  const load = useSocial(`/api/v1/social/communities`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Communities</h1>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Community</th><th className={H}>Kind</th><th className={H}>Members</th><th className={H}>Moderators</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={s(c["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><Link href={withBasePath(`/social/communities/${c["id"]}`)} className="text-neutral-100 hover:underline">{s(c["name"])}</Link> <span className="text-neutral-500">@{s(c["slug"])}</span><div className="text-[11px] text-neutral-500">{s(c["topic"])}</div></td>
                <td className={TD}>{s(c["kind"])}</td><td className={TD}>{n(c["member_count"])}</td><td className={TD}>{n(c["moderator_count"])}</td>
                <td className={TD}>{dt(c["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

export function SocialCommunityDetail({ id }: { id: string }) {
  const load = useSocial(`/api/v1/social/communities/${id}`);
  const d = (load.data ?? {}) as Row;
  const idn = (d["identity"] ?? {}) as Row;
  const mem = (d["membership"] ?? {}) as Row;
  const members = (d["recent_members"] as Row[]) ?? [];
  const mods = (d["moderators"] as Row[]) ?? [];
  return (
    <div className="space-y-4">
      <Bread items={[{ label: "Social", href: "/social" }, { label: "Communities", href: "/social/communities" }, { label: s(idn["name"], id) }]} />
      {load.phase !== "success" ? <StateBlock load={load} /> : (
        <>
          <div className="flex items-baseline gap-3"><h1 className="text-lg font-semibold text-neutral-100">{s(idn["name"])}</h1><span className="text-neutral-500">@{s(idn["slug"])}</span></div>
          <p className="text-sm text-neutral-400">{s(idn["topic"])}</p>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4"><Metric label="Members" value={n(mem["member_count"])} /><Metric label="Moderators" value={n(mem["moderator_count"])} /><Metric label="Kind" value={s(idn["kind"])} /></div>
          <section><div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Moderators</div><MemberList members={mods} /></section>
          <section><div className="mb-1.5 text-xs uppercase tracking-wide text-neutral-500">Recent members</div><MemberList members={members} /></section>
        </>
      )}
    </div>
  );
}
function MemberList({ members }: { members: Row[] }) {
  if (members.length === 0) return <div className="text-sm text-neutral-500">None.</div>;
  return <div className="flex flex-wrap gap-2">{members.map((m) => (
    <Link key={s(m["id"])} href={withBasePath(`/social/users/${m["id"]}`)} className="rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800">{s(m["display_name"])} <span className="text-neutral-500">@{s(m["username"])}</span>{m["is_moderator"] ? <span className="ml-1 text-amber-400">mod</span> : null}</Link>
  ))}</div>;
}

// ================= A2: BOOSTS =================
export function SocialBoosts() {
  const [status, setStatus] = useState("");
  const load = useSocial(`/api/v1/social/boosts?limit=50${status ? `&status=${status}` : ""}`);
  const items = (((load.data as Row)?.["items"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Boost Observability</h1>
      <p className="text-xs text-neutral-500">Read-only. Boost weights/ranking are not modifiable here.</p>
      <select aria-label="boost status" value={status} onChange={(e) => setStatus(e.target.value)} className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-300">
        {["", "active", "expired", "revoked"].map((t) => <option key={t} value={t}>{t || "all status"}</option>)}
      </select>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Post</th><th className={H}>Type</th><th className={H}>Weight</th><th className={H}>Status</th><th className={H}>Expires</th><th className={H}>Created</th></tr></thead>
          <tbody>
            {items.map((b) => (
              <tr key={s(b["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><Link href={withBasePath(`/social/posts/${b["post_id"]}`)} className="text-neutral-200 hover:underline">{s(b["post_preview"], String(b["post_id"]).slice(0, 8))}</Link></td>
                <td className={TD}>{s(b["boost_type"])}</td><td className={TD}>{n(b["weight"])}</td>
                <td className={TD}>{s(b["status"])}</td><td className={TD}>{b["expires_at"] ? dt(b["expires_at"]) : "—"}</td><td className={TD}>{dt(b["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

// ================= A2: REPORTS (Gateway-owned) =================
export function SocialReports() {
  const load = useSocial(`/api/v1/social/reports?limit=100`);
  const items = (((load.data as Row)?.["reports"] as Row[]) ?? []);
  const [sel, setSel] = useState<Row | null>(null);
  const invLink = (tt: string, tid: string) => {
    const t = tt === "post" || tt === "comment" || tt === "user" ? tt : "user";
    return `/social/investigate/${t}/${tid}`;
  };
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Reports</h1>
      <p className="text-xs text-neutral-500">Source: Insight Gateway (moderation domain). Report lifecycle transitions are operator-authed + audited.</p>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Target</th><th className={H}>Reason</th><th className={H}>Status</th><th className={H}>Description</th><th className={H}>Created</th><th className={H}>Lifecycle</th></tr></thead>
          <tbody>
            {items.map((r) => (
              <tr key={s(r["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><Link href={withBasePath(invLink(String(r["target_type"]), String(r["target_id"])))} className="text-neutral-200 hover:underline">{s(r["target_type"])} {String(r["target_id"]).slice(0, 8)}</Link></td>
                <td className={TD}>{s(r["reason"])}</td>
                <td className={TD}><span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[11px]">{s(r["status"])}</span></td>
                <td className={TD}>{s(r["description"], "—")}</td><td className={TD}>{dt(r["created_at"])}</td>
                <td className={TD}><button onClick={() => setSel(sel && sel["id"] === r["id"] ? null : r)} className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-300 hover:bg-neutral-800">{sel && sel["id"] === r["id"] ? "Close" : "Manage"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
      {sel ? (
        <InterventionControls
          targetType="report"
          targetId={String(sel["id"])}
          targetLabel={`report ${String(sel["id"]).slice(0, 8)}… (${s(sel["target_type"])} ${String(sel["target_id"]).slice(0, 8)})`}
          reportId={String(sel["id"])}
          onDone={() => load.reload()}
        />
      ) : null}
    </div>
  );
}

// ================= A2: MODERATION HISTORY (Gateway-owned) =================
export function SocialModeration() {
  const load = useSocial(`/api/v1/social/moderation?limit=100`);
  const items = (((load.data as Row)?.["actions"] as Row[]) ?? []);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-neutral-100">Moderation History</h1>
      <p className="text-xs text-neutral-500">Gateway moderation domain — distinct from the Administrative Audit spine. Read-only.</p>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead><tr><th className={H}>Action</th><th className={H}>Target</th><th className={H}>Moderator</th><th className={H}>Note</th><th className={H}>When</th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={s(a["id"])} className="hover:bg-neutral-900/40">
                <td className={TD}><span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[11px]">{s(a["action"])}</span></td>
                <td className={TD}>{s(a["target_type"])} {String(a["target_id"]).slice(0, 8)}</td>
                <td className={TD}>{s(a["moderator_id"])}</td><td className={TD}>{s(a["note"], "—")}</td><td className={TD}>{dt(a["created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {load.phase !== "success" ? <StateBlock load={load} /> : items.length === 0 ? <StateBlock load={load} empty /> : null}
      </div>
    </div>
  );
}

// ================= A2: INVESTIGATION WORKSPACE =================
function ProvChip({ p }: { p: string }) {
  const map: Record<string, string> = { DURABLE_ROW_PROJECTION: "bg-sky-500/15 text-sky-300", MODERATION_RECORD: "bg-amber-500/15 text-amber-300", ADMINISTRATIVE_AUDIT: "bg-emerald-500/15 text-emerald-300" };
  return <span className={`rounded px-1.5 py-0.5 text-[10px] ${map[p] ?? "bg-neutral-800 text-neutral-400"}`}>{p.replace(/_/g, " ").toLowerCase()}</span>;
}
function PanelBox({ title, panel, children }: { title: string; panel?: Row; children: React.ReactNode }) {
  const state = String(panel?.["state"] ?? "available");
  return (
    <section className="rounded border border-neutral-800">
      <div className="flex items-center justify-between border-b border-neutral-800 px-3 py-1.5">
        <span className="text-xs font-medium uppercase tracking-wide text-neutral-400">{title}</span>
        {state !== "available" ? <span className="text-[11px] text-amber-400">unavailable ({s(panel?.["error"], "source down")})</span> : <span className="text-[11px] text-emerald-500">ok</span>}
      </div>
      <div className="p-3">{state === "available" ? children : <span className="text-sm text-neutral-500">Source unavailable — not shown as empty.</span>}</div>
    </section>
  );
}

export function InvestigationWorkspace({ entityType, id }: { entityType: string; id: string }) {
  const inv = useSocial(`/api/v1/social/investigation/${entityType}/${id}`);
  const tl = useSocial(`/api/v1/social/timeline/${entityType}/${id}`);
  const d = (inv.data ?? {}) as Row;
  const panels = (d["panels"] ?? {}) as Row;
  const partial = d["partial"] === true;
  const rels = (((panels["relationships"] as Row)?.["data"] as Row)?.["relationships"] as Row[]) ?? [];
  const boosts = (((panels["amplification"] as Row)?.["data"] as Row)?.["items"] as Row[]) ?? [];
  const trust = ((panels["trust_safety"] as Row)?.["data"] as Row) ?? {};
  const reports = (trust["reports"] as Row[]) ?? [];
  const modActions = (trust["actions"] as Row[]) ?? [];
  const audit = (((panels["administrative_audit"] as Row)?.["data"] as Row)?.["items"] as Row[]) ?? [];
  const tlItems = ((tl.data as Row)?.["items"] as Row[]) ?? [];
  return (
    <div className="space-y-4">
      <Bread items={[{ label: "Social", href: "/social" }, { label: "Investigate" }, { label: `${entityType} ${String(id).slice(0, 8)}` }]} />
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-100">Investigation · {entityType}</h1>
        <AuthorType t={entityType} />
        {partial ? <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-300">partial data</span> : null}
      </div>
      {["user", "post", "comment", "agent"].includes(entityType) ? (
        <InterventionControls
          targetType={entityType as TargetType}
          targetId={id}
          targetLabel={`${entityType} ${String(id).slice(0, 8)}…`}
          onDone={() => {
            inv.reload();
            tl.reload();
          }}
        />
      ) : null}
      {inv.phase !== "success" ? <StateBlock load={inv} /> : (
        <>
          <div className="flex flex-wrap gap-1.5 text-[11px] text-neutral-500">
            {((d["sources"] as Row[]) ?? []).map((sc, i) => (
              <span key={i} className={`rounded border px-1.5 py-0.5 ${sc["state"] === "available" ? "border-neutral-800" : "border-amber-800 text-amber-400"}`}>{s(sc["panel"])}:{s(sc["state"])}</span>
            ))}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <PanelBox title="Correlated timeline" panel={{ state: tl.phase === "error" ? "unavailable" : "available" }}>
              <div className="space-y-1.5">
                {tlItems.slice(0, 40).map((it) => (
                  <div key={s(it["id"]) + s(it["kind"])} className="flex items-center gap-2 text-xs">
                    <span className="w-36 shrink-0 text-neutral-500">{dt(it["at"])}</span>
                    <ProvChip p={String(it["provenance"])} />
                    <span className="text-neutral-300">{s(it["summary"], s(it["kind"]))}</span>
                  </div>
                ))}
                {tlItems.length === 0 ? <span className="text-sm text-neutral-500">No timeline items.</span> : null}
              </div>
            </PanelBox>
            <PanelBox title="Relationships" panel={panels["relationships"] as Row}>
              <div className="space-y-1 text-sm">
                {rels.slice(0, 40).map((r, i) => (
                  <div key={i} className="flex items-center gap-2"><span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[11px]">{s(r["type"])} {s(r["direction"])}</span><span className="text-neutral-300">{s((r["target"] as Row)?.["label"], String((r["target"] as Row)?.["id"]).slice(0, 8))}</span><AuthorType t={(r["target"] as Row)?.["type"]} /></div>
                ))}
                {rels.length === 0 ? <span className="text-neutral-500">No relationships.</span> : null}
              </div>
            </PanelBox>
            <PanelBox title="Amplification (boosts)" panel={panels["amplification"] as Row}>
              <div className="space-y-1 text-sm">{boosts.slice(0, 20).map((b) => <div key={s(b["id"])} className="text-neutral-400">{s(b["boost_type"])} · w{n(b["weight"])} · {s(b["status"])}</div>)}{boosts.length === 0 ? <span className="text-neutral-500">No boosts.</span> : null}</div>
            </PanelBox>
            <PanelBox title="Trust & Safety" panel={panels["trust_safety"] as Row}>
              <div className="space-y-1 text-sm">
                <div className="text-neutral-500">Reports: {reports.length} · Moderation actions: {modActions.length}</div>
                {reports.slice(0, 10).map((r) => <div key={s(r["id"])} className="text-neutral-400">report · {s(r["reason"])} · {s(r["status"])}</div>)}
                {modActions.slice(0, 10).map((a) => <div key={s(a["id"])} className="text-amber-300/80">moderation · {s(a["action"])}</div>)}
              </div>
            </PanelBox>
            <PanelBox title="Administrative audit (correlated)" panel={panels["administrative_audit"] as Row}>
              <div className="space-y-1 text-sm">{audit.slice(0, 15).map((e) => <div key={s(e["eventId"])} className="text-neutral-400"><span className="text-emerald-400/70">{s((e["action"] as Row)?.["capability"])}</span> · {s((e["outcome"] as Row)?.["status"])} · {dt(e["occurredAt"])}</div>)}{audit.length === 0 ? <span className="text-neutral-500">No correlated audit events.</span> : null}</div>
            </PanelBox>
          </div>
        </>
      )}
    </div>
  );
}
