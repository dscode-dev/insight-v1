"use client";

// Explorer curation — the human promote/reject queue.
//
// Records that the pipeline could not validate automatically land here
// and wait for a person. The queue, the verdict endpoints and the whole
// flow existed server-side with NO console surface at all, which meant
// the queue only ever grew.
//
// Worth stating on the screen, because it is not obvious: promoting a
// record appends its envelope to the VALIDATED lake layer, and that is
// exactly the layer Atlas's StrengthSyncWatcher reads. A promotion here
// propagates into Atlas's team-strength ratings — this is upstream of
// Atlas, not a side ledger.

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ClipboardList, Loader2, RotateCcw, XCircle } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader, ts, type Row } from "@/components/console/ops-shared";

const API = "/api/v1/explorer-ops";

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

type Status = "pending" | "promoted" | "rejected";

export function ExplorerCurationCenter() {
  const [status, setStatus] = useState<Status>("pending");
  const [items, setItems] = useState<Row[]>([]);
  const [stats, setStats] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const payload = await request(`review?status=${status}`);
      setItems(Array.isArray(payload.items) ? payload.items : []);
      setStats((payload.stats as Row) ?? null);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unreachable");
    }
  }, [status]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const decide = async (externalId: string, verdict: "promote" | "reject") => {
    setBusy(externalId);
    try {
      await request(`review/${verdict}`, "POST", { external_id: externalId });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "action failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        icon={ClipboardList}
        title="Curation"
        subtitle="Human review queue — records the pipeline could not validate on its own"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <Card title="Queue">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(["pending", "promoted", "rejected"] as const).map((key) => (
            <button
              key={key}
              onClick={() => setStatus(key)}
              className={`ix-transition rounded-lg border p-3 text-left ${
                status === key ? "border-primary bg-accent" : "border-border/60"
              }`}
            >
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{key}</p>
              <p className="mt-1 text-lg font-semibold">{Number(stats?.[key] ?? 0)}</p>
            </button>
          ))}
        </div>
      </Card>

      {status === "pending" ? (
        <p className="text-xs text-muted-foreground">
          Promoting appends the record&apos;s envelope to the <strong>validated</strong>{" "}
          lake layer, which Atlas reads to update team-strength ratings. Rejecting
          writes it to the rejected report instead.
        </p>
      ) : null}

      <Card title={`${status} records`}>
        {items.length === 0 ? (
          <Empty>
            {status === "pending"
              ? "Nothing awaiting review."
              : `No ${status} records.`}
          </Empty>
        ) : (
          <div className="space-y-2">
            {items.map((item) => {
              const externalId = String(item.external_id ?? "");
              return (
                <div
                  key={`${item.competition}:${item.season}:${externalId}`}
                  className="rounded-lg border border-border/60 p-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-mono text-xs">{externalId}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {String(item.competition ?? "—")} · {String(item.season ?? "—")} ·{" "}
                        {String(item.source ?? "—")}
                        {item.reason ? ` · ${String(item.reason)}` : ""}
                      </p>
                      {item.recorded_at ? (
                        <p className="mt-0.5 text-[11px] text-muted-foreground">
                          {ts(item.recorded_at)}
                        </p>
                      ) : null}
                    </div>
                    {status === "pending" ? (
                      <div className="flex shrink-0 gap-2">
                        <button
                          disabled={busy === externalId}
                          onClick={() => void decide(externalId, "promote")}
                          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
                        >
                          {busy === externalId ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-3.5 w-3.5" />
                          )}
                          Promote
                        </button>
                        <button
                          disabled={busy === externalId}
                          onClick={() => void decide(externalId, "reject")}
                          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-xs text-red-400 hover:bg-red-500/20 disabled:opacity-40"
                        >
                          <XCircle className="h-3.5 w-3.5" /> Reject
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <ReplayTask onError={setError} onDone={refresh} />
    </div>
  );
}

function ReplayTask({
  onError,
  onDone,
}: {
  onError: (message: string) => void;
  onDone: () => void;
}) {
  const [competition, setCompetition] = useState("");
  const [season, setSeason] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Card title="Re-collect a task">
      <p className="mb-3 text-xs text-muted-foreground">
        Re-runs collection for one (competition, season). Use when the queue shows
        a systematic source problem rather than individual bad records.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs">
          <span className="mb-1 block text-muted-foreground">Competition</span>
          <input
            value={competition}
            onChange={(e) => setCompetition(e.target.value)}
            className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
          />
        </label>
        <label className="text-xs">
          <span className="mb-1 block text-muted-foreground">Season</span>
          <input
            value={season}
            onChange={(e) => setSeason(e.target.value)}
            className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
          />
        </label>
        <button
          disabled={busy || !competition || !season}
          onClick={async () => {
            setBusy(true);
            try {
              await request("review/replay", "POST", { competition, season });
              onDone();
            } catch (e) {
              onError(e instanceof Error ? e.message : "replay failed");
            } finally {
              setBusy(false);
            }
          }}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          Re-collect
        </button>
      </div>
    </Card>
  );
}
