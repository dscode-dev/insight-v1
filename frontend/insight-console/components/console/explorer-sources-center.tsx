"use client";

// Explorer — fontes de dados e tickets operacionais.
//
// Substitui os modos `sources` e `tickets` do antigo
// `data-intelligence-center`, que renderizavam uma tabela genérica de
// colunas sem contexto. O problema não era falta de dado: era não
// responder a pergunta que o operador tem ao abrir a tela.
//
// Para Fontes: "essa fonte está trazendo dado, e o dado presta?"
// Para Tickets: "o que está quebrado e desde quando?"

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Power,
  RefreshCw,
  Server,
  Ticket as TicketIcon,
  XCircle,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader, Pill, ts, type Row } from "@/components/console/ops-shared";

const API = "/api/v1/data-intelligence";

async function request(path: string, method = "GET", body?: unknown) {
  const res = await fetch(withBasePath(`${API}/${path}`), {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(payload.detail ?? payload.error ?? `HTTP ${res.status}`));
  }
  return payload;
}

/* ================================================================== */
/*  FONTES                                                            */
/* ================================================================== */

export function ExplorerSourcesCenter() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const catalog = await request("pipelines/catalog");
      setRows(Array.isArray(catalog.sources) ? (catalog.sources as Row[]) : []);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "inalcançável");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 20000);
    return () => clearInterval(id);
  }, [refresh]);

  const toggle = async (name: string, enabled: boolean) => {
    setBusy(name);
    try {
      await request(enabled ? "sources/disable" : "sources/enable", "POST", { source: name });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "falhou");
    } finally {
      setBusy(null);
    }
  };

  const active = rows.filter((r) => r.enabled === true).length;
  const neverRan = rows.filter((r) => num(r.jobs_run) === 0).length;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Server}
        title="Fontes de dados"
        subtitle="De onde o Explorer coleta — e o quanto cada uma está entregando"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      {/* O aviso que importa: fonte cadastrada não é fonte coletando. */}
      {rows.length > 0 && neverRan === rows.length ? (
        <ErrorBanner>
          Nenhuma das {rows.length} fontes rodou um job ainda. Cadastrar a
          fonte não inicia coleta — isso acontece quando um pipeline é
          executado, em <strong>Pipelines</strong>.
        </ErrorBanner>
      ) : null}

      <Card title="Resumo">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="cadastradas" value={rows.length} />
          <Metric label="habilitadas" value={active} />
          <Metric
            label="nunca rodaram"
            value={neverRan}
            attention={neverRan > 0}
          />
          <Metric
            label="registros validados"
            value={rows.reduce((s, r) => s + num(r.records_validated), 0)}
          />
        </div>
      </Card>

      <Card title="Fontes">
        {rows.length === 0 ? (
          <Empty>Nenhuma fonte cadastrada.</Empty>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => {
              const name = String(row.name ?? "");
              const enabled = row.enabled === true;
              const collected = num(row.records_collected);
              const validated = num(row.records_validated);
              // Taxa sobre o COLETADO: é a pergunta "o dado dessa fonte
              // presta?", diferente de "quanto ela trouxe".
              const rate = collected === 0 ? null : (validated / collected) * 100;

              return (
                <div
                  key={name}
                  className={`rounded-lg border p-3 ${
                    enabled ? "border-border/60" : "border-border/30 opacity-60"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{name}</span>
                        <Pill value={String(row.trust_level ?? "unknown")} />
                        {!enabled ? (
                          <span className="text-xs text-muted-foreground">desabilitada</span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        prioridade {num(row.priority)} · {num(row.jobs_run)} jobs ·
                        última execução {row.last_run ? ts(row.last_run) : "nunca"}
                      </p>
                    </div>

                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          coletados
                        </p>
                        <p className="text-sm font-semibold">{collected}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          aproveitamento
                        </p>
                        {/* "—" e não 0%: sem coleta não existe taxa, e
                            0% sugeriria que a fonte entregou lixo. */}
                        <p className={`text-sm font-semibold ${rate === null ? "text-muted-foreground" : ""}`}>
                          {rate === null ? "—" : `${rate.toFixed(0)}%`}
                        </p>
                      </div>
                      <button
                        disabled={busy === name}
                        onClick={() => void toggle(name, enabled)}
                        className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-40"
                      >
                        <Power className="h-3.5 w-3.5" />
                        {enabled ? "Desabilitar" : "Habilitar"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ================================================================== */
/*  TICKETS                                                           */
/* ================================================================== */

export function ExplorerTicketsCenter() {
  const [rows, setRows] = useState<Row[]>([]);
  const [status, setStatus] = useState<"open" | "">("open");
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await request(`tickets?status=${status}`);
      setRows(Array.isArray(data) ? (data as Row[]) : []);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "inalcançável");
    }
  }, [status]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 20000);
    return () => clearInterval(id);
  }, [refresh]);

  const reprocess = async (id: string) => {
    setBusy(id);
    try {
      await request("tickets/reprocess", "POST", { ticket_id: id });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "falhou");
    } finally {
      setBusy(null);
    }
  };

  // Agrupar por tipo é o que transforma uma lista em diagnóstico: dez
  // tickets de `source_offline` da mesma fonte são UM problema.
  const byType = new Map<string, Row[]>();
  for (const row of rows) {
    const key = String(row.error_type ?? "unknown");
    byType.set(key, [...(byType.get(key) ?? []), row]);
  }

  return (
    <div className="space-y-4">
      <PageHeader
        icon={TicketIcon}
        title="Tickets"
        subtitle="Problemas que a coleta registrou para alguém resolver"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <div className="flex gap-2">
        {([["open", "Abertos"], ["", "Todos"]] as const).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setStatus(value)}
            className={`ix-transition rounded-lg border px-3 py-1.5 text-xs ${
              status === value ? "border-primary bg-accent" : "border-border/60"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <Card title={status === "open" ? "Nenhum ticket aberto" : "Nenhum ticket"}>
          <div className="flex items-center gap-2 text-sm text-emerald-400">
            <CheckCircle2 className="h-4 w-4" />
            {status === "open"
              ? "A coleta não registrou problemas pendentes."
              : "Nenhum ticket foi registrado."}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Tickets são abertos automaticamente quando uma fonte fica fora
            do ar, um coletor quebra ou a validação falha — não são criados
            à mão.
          </p>
        </Card>
      ) : (
        <>
          <Card title="Por tipo de problema">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[...byType.entries()].map(([type, items]) => (
                <Metric key={type} label={type} value={items.length} attention />
              ))}
            </div>
          </Card>

          {[...byType.entries()].map(([type, items]) => (
            <Card key={type} title={type}>
              <div className="space-y-2">
                {items.map((row) => {
                  const id = String(row.ticket_id ?? "");
                  return (
                    <div key={id} className="rounded-lg border border-border/60 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <SeverityIcon severity={String(row.severity ?? "")} />
                            <span className="text-sm">
                              {String(row.source ?? "—")} · {String(row.competition ?? "—")}
                              {row.season ? ` · ${String(row.season)}` : ""}
                            </span>
                          </div>
                          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                            {id} · {ts(row.created_at ?? row.opened_at)}
                            {num(row.retry_count) > 0 ? ` · ${num(row.retry_count)} tentativas` : ""}
                          </p>
                        </div>
                        <button
                          disabled={busy === id}
                          onClick={() => void reprocess(id)}
                          className="ix-transition inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-40"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Reprocessar
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

/* ================================================================== */

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "high" || severity === "critical") {
    return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />;
  }
  return <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />;
}

function Metric({
  label, value, attention,
}: {
  label: string;
  value: number | string;
  attention?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        attention ? "border-amber-500/40 bg-amber-500/[0.04]" : "border-border/60"
      }`}
    >
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}
