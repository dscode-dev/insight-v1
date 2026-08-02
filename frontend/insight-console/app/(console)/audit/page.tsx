"use client";

// /audit — Sprint 8 Part 9.
//
// Reads the immutable audit log via /api/v1/audit. Cursor-based
// pagination; every column is filterable via the query string the
// BFF passes through to the admin API.

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { withBasePath } from "@/lib/base-path";
import { formatOperationalTime, formatRelative } from "@/lib/utils";

interface AuditEvent {
  id: string;
  action: string;
  actor_id: string;
  actor_display_name: string;
  target_type: string;
  target_id: string;
  service: string;
  request_id?: string | null;
  correlation_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface AuditPage {
  items: AuditEvent[];
  next_cursor?: string | null;
}

export default function AuditPageView() {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    action: "",
    service: "",
    target_type: "",
    target_id: "",
    correlation_id: "",
  });
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  const load = useCallback(
    async (mode: "reset" | "more") => {
      setLoading(true);
      setError(null);
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) {
        if (v) qs.set(k, v);
      }
      qs.set("limit", "50");
      if (mode === "more" && next) qs.set("cursor", next);
      try {
        const res = await fetch(withBasePath(`/api/v1/audit?${qs.toString()}`), { cache: "no-store" });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setError(body.error ?? `http_${res.status}`);
          return;
        }
        const body = (await res.json()) as AuditPage;
        setItems((prev) => (mode === "reset" ? body.items : [...prev, ...body.items]));
        setNext(body.next_cursor ?? null);
      } catch {
        setError("network_error");
      } finally {
        setLoading(false);
      }
    },
    [filters, next],
  );

  useEffect(() => {
    load("reset");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  function setFilter(key: keyof typeof filters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Audit Center</h1>
          <p className="text-sm text-muted-foreground">
            Immutable journal of every administrative action across the platform.
          </p>
        </div>
        <a
          href="/audit/publications"
          className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          Publication audit →
        </a>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
            <FilterField
              label="Action"
              value={filters.action}
              placeholder="DLQ_REPLAYED"
              onChange={(v) => setFilter("action", v)}
            />
            <FilterField
              label="Service"
              value={filters.service}
              placeholder="sports-hub"
              onChange={(v) => setFilter("service", v)}
            />
            <FilterField
              label="Target type"
              value={filters.target_type}
              placeholder="dlq_entry"
              onChange={(v) => setFilter("target_type", v)}
            />
            <FilterField
              label="Target id"
              value={filters.target_id}
              placeholder="…uuid…"
              onChange={(v) => setFilter("target_id", v)}
            />
            <FilterField
              label="Correlation id"
              value={filters.correlation_id}
              placeholder="req_xxx"
              onChange={(v) => setFilter("correlation_id", v)}
            />
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card>
          <CardContent className="pt-5">
            <p className="text-sm text-destructive">
              Failed to load audit log: <span className="mono">{error}</span>
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{items.length} event(s)</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="table-operational">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Service</th>
                <th>Target</th>
                <th>Correlation</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((ev) => (
                <tr key={ev.id}>
                  <td className="mono text-xs">
                    <div>{formatRelative(ev.created_at)}</div>
                    <div className="text-muted-foreground">
                      {formatOperationalTime(ev.created_at)}
                    </div>
                  </td>
                  <td>
                    <Badge variant="outline">{ev.action}</Badge>
                  </td>
                  <td>
                    <div>{ev.actor_display_name}</div>
                    <div className="mono text-xs text-muted-foreground">
                      {ev.actor_id}
                    </div>
                  </td>
                  <td className="mono">{ev.service}</td>
                  <td className="mono text-xs">
                    <div>{ev.target_type}</div>
                    <div className="text-muted-foreground">{ev.target_id}</div>
                  </td>
                  <td className="mono text-xs text-muted-foreground">
                    {ev.correlation_id ?? "—"}
                  </td>
                  <td className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setSelected(ev)}
                    >
                      View
                    </Button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={7}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No matching events.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="mt-4 flex justify-center">
            {next && (
              <Button
                variant="outline"
                disabled={loading}
                onClick={() => load("more")}
              >
                {loading ? "Loading…" : "Load more"}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {selected && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Event detail</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                Close
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="overflow-auto rounded-md border border-border bg-muted/30 p-3 text-xs mono">
              {JSON.stringify(selected, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function FilterField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-muted-foreground">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-9 rounded-md border border-input bg-background px-3 text-sm mono"
      />
    </div>
  );
}
