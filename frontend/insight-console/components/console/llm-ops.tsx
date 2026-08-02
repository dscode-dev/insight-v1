"use client";

// LLM Operations (CONSOLE-OPS-A3 Stage 10) — provider config/status for Claude,
// GPT, Gemini, Qwen. Sourced from /api/v1/providers/status (+ control plane for
// Qwen). Honest: missing credentials → "not configured", never fake healthy.

import { Cpu } from "lucide-react";

import { useOps, arr, ts, PageHeader, Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

const PROVIDERS = [
  { id: "claude", label: "Claude", provider: "anthropic" },
  { id: "gpt", label: "GPT", provider: "openai" },
  { id: "gemini", label: "Gemini", provider: "google" },
  { id: "qwen", label: "Qwen", provider: "ollama (local)" },
];

function find(rows: Row[], id: string): Row | undefined {
  return rows.find((r) => {
    const n = String(r.name ?? r.provider ?? r.id ?? "").toLowerCase();
    return n.includes(id);
  });
}

export function LlmOps() {
  const { data, error, updated, refresh } = useOps([
    "/api/v1/providers/status",
    "/api/ops/robozao/status",
  ]);

  const provRows = arr(data.status, "providers", "items");
  const rzStatus = data.status; // robozao status payload (qwen lives here)
  const rzServices = arr(rzStatus, "services");
  const qwenSvc = rzServices.find((s) => String((s.identity as Row)?.service_id ?? s.service_id ?? "").includes("qwen"));

  return (
    <div className="space-y-5">
      <PageHeader icon={Cpu} title="LLM Operations" updated={updated} onRefresh={refresh}
        subtitle="Provider configuration & health · realtime (7s)" />
      {error && <ErrorBanner>Provider status: {error}</ErrorBanner>}

      <div className="grid gap-3 md:grid-cols-2">
        {PROVIDERS.map((p) => {
          const row = p.id === "qwen" ? (qwenSvc ?? find(provRows, "qwen")) : find(provRows, p.id);
          const configured = row ? (row.configured ?? row.enabled ?? true) : false;
          const health = p.id === "qwen"
            ? (qwenSvc ? String(qwenSvc.status ?? "up") : "not_configured")
            : (row ? String(row.health ?? row.status ?? "unknown") : "not_configured");
          const err = row?.error ?? row?.reason;
          return (
            <Card key={p.id}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{p.label}</span>
                <Pill value={configured ? health : "not_configured"} />
              </div>
              <div className="mt-1 grid grid-cols-2 gap-x-4 text-xs text-muted-foreground">
                <span>provider: <b className="text-foreground">{p.provider}</b></span>
                <span>configured: <b className="text-foreground">{String(!!configured)}</b></span>
                <span>enabled: <b className="text-foreground">{String(row?.enabled ?? configured)}</b></span>
                <span>last check: <b className="text-foreground">{ts(row?.last_check ?? rzStatus?.checked_at)}</b></span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                source: {p.id === "qwen" ? "Robozão control plane" : "providers/status"}
              </div>
              {err ? <div className="mt-1 text-xs text-red-400">{String(err)}</div> : null}
              {!configured && p.id !== "qwen" ? (
                <div className="mt-1 text-xs text-muted-foreground">Not configured — no provider credentials present.</div>
              ) : null}
            </Card>
          );
        })}
      </div>
      {provRows.length === 0 && !qwenSvc && (
        <Empty>No provider status available yet. Cloud LLM providers show &quot;not configured&quot;
          until Nexus exposes provider status; Qwen reports via the Robozão control plane.</Empty>
      )}
    </div>
  );
}
