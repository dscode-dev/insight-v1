"use client";

// Agents Operations (CONSOLE-OPS-A3 Stage 9) — Insight workers ONLY (no unrelated
// content). Sourced from the Robozão control plane (/api/ops/robozao/status) for
// service health + the operations DB (/api/v1/ops/events) for last activity.

import { Bot } from "lucide-react";

import { useOps, arr, ts, PageHeader, Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

const WORKERS: { service: string; label: string; kind: string }[] = [
  { service: "explorer", label: "Explorer workers", kind: "collection" },
  { service: "atlas", label: "Atlas jobs", kind: "training" },
  { service: "nexus", label: "Nexus providers", kind: "publication" },
  { service: "sport-hub", label: "Sport-Hub workers", kind: "ingest" },
  { service: "qwen-runtime", label: "Qwen local runtime", kind: "llm" },
  { service: "robozao-gateway", label: "Robozão Gateway", kind: "control-plane" },
];

export function AgentsOps() {
  const { data, error, updated, refresh } = useOps([
    "/api/ops/robozao/status",
    "/api/v1/ops/events?limit=200",
  ]);

  const status = data.status ?? {};
  const services = arr(status, "services", "registry");
  const events = arr(data.events, "events");

  const byService = (id: string) =>
    services.find((s) => {
      const sid = String((s.identity as Row)?.service_id ?? s.service_id ?? s.service ?? "");
      return sid.includes(id) || id.includes(sid);
    });
  const lastEvent = (id: string) => events.find((e) => String(e.service ?? "").includes(id));

  return (
    <div className="space-y-5">
      <PageHeader icon={Bot} title="Agents Operations" updated={updated} onRefresh={refresh}
        subtitle="Insight workers & background jobs · realtime (7s) · control plane + operations DB" />
      {error && <ErrorBanner>Control plane: {error}</ErrorBanner>}

      <div className="grid gap-3 md:grid-cols-2">
        {WORKERS.map((w) => {
          const svc = byService(w.service);
          const ev = lastEvent(w.service);
          const st = String(svc?.status ?? (svc ? "up" : "unknown"));
          const err = svc?.error ?? svc?.reason;
          return (
            <Card key={w.service}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{w.label}</span>
                <Pill value={st} />
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                service: <span className="font-mono">{w.service}</span> · {w.kind}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                last activity: {ev ? `${String(ev.event_type)} · ${ts(ev.timestamp)}` : "—"}
              </div>
              {err ? <div className="mt-1 text-xs text-red-400">{String(err)}</div> : null}
            </Card>
          );
        })}
      </div>
      {services.length === 0 && (
        <Empty>Control plane returned no services — Robozão Gateway may be unreachable. Worker
          identities are listed above with unknown status until it responds.</Empty>
      )}
    </div>
  );
}
