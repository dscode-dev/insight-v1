"use client";

// /dlq — Sprint 8 Part 8.
//
// Lists real dead-letter entries (the admin API /v1/console/dlq → Sports Hub
// /v1/dlq). This sprint is deliberately read-only. Operators can:
//   - filter by provider / failure_type / unreplayed
//   - click a row to open the detail dialog

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { withBasePath } from "@/lib/base-path";
import { formatOperationalTime, formatRelative } from "@/lib/utils";

interface DlqItem {
  id: string;
  job_id: string;
  provider_id: string;
  competition_id: string;
  sync_type: string;
  reason: string;
  failure_type: string;
  attempts: number;
  failed_at: string;
  replayed_at?: string | null;
}

interface DlqPage {
  items: DlqItem[];
  limit: number;
  offset: number;
}

const FAILURE_VARIANTS: Record<string, "warning" | "destructive" | "outline" | "success"> = {
  transient: "warning",
  provider: "warning",
  infrastructure: "destructive",
  validation: "destructive",
  permanent: "destructive",
};

export default function DlqPage() {
  const [items, setItems] = useState<DlqItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("");
  const [failureType, setFailureType] = useState("");
  const [unreplayed, setUnreplayed] = useState(true);
  const [selected, setSelected] = useState<DlqItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (provider) qs.set("provider", provider);
    if (failureType) qs.set("failure_type", failureType);
    if (unreplayed) qs.set("unreplayed", "1");
    qs.set("limit", "100");
    try {
      const res = await fetch(withBasePath(`/api/v1/dlq?${qs.toString()}`), { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.error ?? `http_${res.status}`);
        setItems([]);
        return;
      }
      const body = (await res.json()) as DlqPage;
      setItems(body.items);
    } catch {
      setError("network_error");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [provider, failureType, unreplayed]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Dead Letter Queue</h1>
        <p className="text-sm text-muted-foreground">
          Read-only terminal failure visibility: origin, attempts, timestamps
          and payload identifiers. Operational actions are intentionally excluded.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Provider</label>
              <input
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                placeholder="api_football"
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Failure type</label>
              <select
                value={failureType}
                onChange={(e) => setFailureType(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">any</option>
                <option value="transient">transient</option>
                <option value="provider">provider</option>
                <option value="infrastructure">infrastructure</option>
                <option value="validation">validation</option>
                <option value="permanent">permanent</option>
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={unreplayed}
                onChange={(e) => setUnreplayed(e.target.checked)}
              />
              Unreplayed only
            </label>
            <div className="flex-1" />
            <Button variant="outline" onClick={load} disabled={loading}>
              {loading ? "Loading…" : "Refresh"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card>
          <CardContent className="pt-5">
            <p className="text-sm text-destructive">
              Failed to load DLQ: <span className="mono">{error}</span>
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{items.length} {unreplayed ? "unreplayed " : ""}failures</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="table-operational">
            <thead>
              <tr>
                <th>When</th>
                <th>Provider</th>
                <th>Sync type</th>
                <th>Reason</th>
                <th>Failure</th>
                <th>Attempts</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && !loading && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-muted-foreground">
                    No matching failures.
                  </td>
                </tr>
              )}
              {items.map((it) => {
                return (
                  <tr key={it.id}>
                    <td className="mono text-xs">
                      <div>{formatRelative(it.failed_at)}</div>
                      <div className="text-muted-foreground">
                        {formatOperationalTime(it.failed_at)}
                      </div>
                    </td>
                    <td>{it.provider_id}</td>
                    <td className="mono">{it.sync_type}</td>
                    <td className="mono text-xs">{it.reason}</td>
                    <td>
                      <Badge variant={FAILURE_VARIANTS[it.failure_type] ?? "outline"}>
                        {it.failure_type}
                      </Badge>
                    </td>
                    <td className="mono">{it.attempts}</td>
                    <td>
                      {it.replayed_at ? (
                        <Badge variant="success">replayed</Badge>
                      ) : (
                        <Badge variant="outline">pending</Badge>
                      )}
                    </td>
                    <td className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSelected(it)}
                      >
                        Details
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {selected && (
        <DlqDetail item={selected} onClose={() => setSelected(null)} />
      )}

    </div>
  );
}

function DlqDetail({ item, onClose }: { item: DlqItem; onClose: () => void }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Failure detail</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">DLQ id</dt>
          <dd className="mono">{item.id}</dd>
          <dt className="text-muted-foreground">Job id</dt>
          <dd className="mono">{item.job_id}</dd>
          <dt className="text-muted-foreground">Provider</dt>
          <dd>{item.provider_id}</dd>
          <dt className="text-muted-foreground">Competition</dt>
          <dd className="mono">{item.competition_id}</dd>
          <dt className="text-muted-foreground">Sync type</dt>
          <dd className="mono">{item.sync_type}</dd>
          <dt className="text-muted-foreground">Reason</dt>
          <dd className="mono">{item.reason}</dd>
          <dt className="text-muted-foreground">Failure type</dt>
          <dd>
            <Badge variant={FAILURE_VARIANTS[item.failure_type] ?? "outline"}>
              {item.failure_type}
            </Badge>
          </dd>
          <dt className="text-muted-foreground">Attempts</dt>
          <dd className="mono">{item.attempts}</dd>
          <dt className="text-muted-foreground">Failed at</dt>
          <dd className="mono">{formatOperationalTime(item.failed_at)}</dd>
          <dt className="text-muted-foreground">Replayed at</dt>
          <dd className="mono">
            {item.replayed_at ? formatOperationalTime(item.replayed_at) : "—"}
          </dd>
        </dl>
      </CardContent>
    </Card>
  );
}
