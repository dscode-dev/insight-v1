"use client";

// Nexus — o que foi publicado, o que foi barrado, e por quê.
//
// A regra que organiza a tela: uma publicação que NÃO aconteceu é tão
// informativa quanto uma que aconteceu, desde que o motivo esteja junto.
// "Explicar toda supressão" é um não-negociável da plataforma, então as
// suprimidas aparecem com o mesmo destaque das publicadas — não escondidas
// atrás de um filtro.
//
// A tela também distingue três estados que se parecem numa lista vazia:
//   · o publisher está desligado por configuração
//   · está ligado, mas nenhuma tendência chegou do Atlas
//   · está ligado e rodando, e nada foi julgado digno de publicar
// Tratar os três como "nenhum resultado" já mandou gente investigar o
// serviço errado.

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Newspaper,
  RefreshCw,
  ShieldOff,
  Ticket as TicketIcon,
  XCircle,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import {
  Card,
  Empty,
  ErrorBanner,
  PageHeader,
  Pill,
  ts,
  type Row,
} from "@/components/console/ops-shared";

const API = "/api/v1/nexus/v1";

/** Uma fonte da tela. `error` separa "não medido" de "medido como zero". */
interface Source<T> {
  data: T | null;
  error: string | null;
}

async function load<T>(path: string, pick: (body: Row) => T): Promise<Source<T>> {
  try {
    const res = await fetch(withBasePath(`${API}/${path}`), { cache: "no-store" });
    const body = (await res.json().catch(() => ({}))) as Row;
    if (!res.ok) {
      return { data: null, error: String(body.detail ?? body.error ?? `HTTP ${res.status}`) };
    }
    return { data: pick(body), error: null };
  } catch (e) {
    return { data: null, error: e instanceof Error ? e.message : "inalcançável" };
  }
}

function rowsOf(body: Row, ...keys: string[]): Row[] {
  for (const k of keys) if (Array.isArray(body[k])) return body[k] as Row[];
  return Array.isArray(body) ? (body as unknown as Row[]) : [];
}

export function NexusPublicationsCenter() {
  const [candidates, setCandidates] = useState<Source<Row[]>>({ data: null, error: null });
  const [tickets, setTickets] = useState<Source<Row[]>>({ data: null, error: null });
  const [health, setHealth] = useState<Source<Row[]>>({ data: null, error: null });
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [c, t, h] = await Promise.all([
      load(`publications/candidates`, (b) => rowsOf(b, "candidates", "items")),
      load(`publications/tickets`, (b) => rowsOf(b, "tickets", "items")),
      load(`llm/health`, (b) => rowsOf(b, "providers", "health", "items")),
    ]);
    setCandidates(c);
    setTickets(t);
    setHealth(h);
    setUpdated(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30000);
    return () => clearInterval(id);
  }, [refresh]);

  const publishTicket = async (id: string) => {
    setBusy(id);
    try {
      const res = await fetch(withBasePath(`${API}/publications/tickets/${id}/publish`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(String(body.detail ?? body.error ?? `HTTP ${res.status}`));
      }
      await refresh();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "falhou");
    } finally {
      setBusy(null);
    }
  };

  const rows = candidates.data ?? [];
  const byStatus = new Map<string, Row[]>();
  for (const row of rows) {
    const key = String(row.status ?? "unknown").toLowerCase();
    byStatus.set(key, [...(byStatus.get(key) ?? []), row]);
  }
  const providers = health.data ?? [];
  // Nenhum provedor registrado é o sinal de que o publisher está desligado —
  // vem da configuração, não de uma falha.
  const publisherOff = health.error === null && providers.length === 0;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Newspaper}
        title="Publicações"
        subtitle="O que os agentes publicaram, o que foi barrado, e o motivo"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      {candidates.error ? <ErrorBanner>{candidates.error}</ErrorBanner> : null}

      {publisherOff ? (
        <Card title="Publicação desligada">
          <p className="text-sm">
            Nenhum provedor de LLM está registrado, então o publisher não está
            rodando e nada é publicado no Social.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Os rascunhos continuam sendo gerados e enfileirados — eles não são
            perdidos. Para ligar são necessários{" "}
            <span className="font-mono">NEXUS_PUBLISHER_ENABLED</span>, pelo
            menos um <span className="font-mono">NEXUS_ENABLE_*</span> com
            credencial, e <span className="font-mono">NEXUS_SOCIAL_GRPC_ADDR</span>.
            Faltando qualquer um, o serviço recusa subir em vez de abrir um
            ticket por rascunho.
          </p>
        </Card>
      ) : null}

      <Card title="Resultado das tentativas">
        {rows.length === 0 ? (
          <Empty>
            {candidates.error
              ? "Não foi possível medir."
              : publisherOff
                ? "Nenhuma tentativa — o publisher está desligado."
                : "Nenhuma tentativa de publicação ainda. Isso é esperado enquanto o Atlas não estiver emitindo tendências."}
          </Empty>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[...byStatus.entries()].map(([status, items]) => (
              <StatusMetric key={status} status={status} count={items.length} />
            ))}
          </div>
        )}
      </Card>

      {/* Barradas com o motivo — o mesmo destaque das publicadas. */}
      {[...byStatus.entries()]
        .filter(([status]) => status !== "published")
        .map(([status, items]) => (
          <Card key={status} title={statusLabel(status)}>
            <div className="space-y-2">
              {items.slice(0, 20).map((row, i) => (
                <div
                  key={String(row.id ?? i)}
                  className="rounded-lg border border-border/60 p-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {String(row.agent_name ?? row.agent ?? "—")}
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {ts(row.created_at)}
                    </span>
                  </div>
                  {/* O motivo é o conteúdo da linha, não uma nota de rodapé. */}
                  <p className="mt-1 text-sm text-amber-400">
                    {String(row.status_reason ?? "sem motivo registrado")}
                  </p>
                  {row.title ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {String(row.title)}
                    </p>
                  ) : null}
                </div>
              ))}
              {items.length > 20 ? (
                <p className="text-xs text-muted-foreground">
                  +{items.length - 20} adicionais
                </p>
              ) : null}
            </div>
          </Card>
        ))}

      {byStatus.has("published") ? (
        <Card title="Publicadas">
          <div className="space-y-2">
            {(byStatus.get("published") ?? []).slice(0, 20).map((row, i) => (
              <div
                key={String(row.id ?? i)}
                className="rounded-lg border border-border/60 p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">
                    {String(row.agent_name ?? row.agent ?? "—")}
                  </span>
                  <span className="flex items-center gap-2">
                    <Pill value={String(row.provider ?? "—")} />
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {ts(row.published_at ?? row.created_at)}
                    </span>
                  </span>
                </div>
                <p className="mt-1 text-sm">{String(row.title ?? "—")}</p>
                {/* Perda de escrituração pós-publicação: o post saiu, mas uma
                    guarda ficou sem registro. Precisa aparecer, porque afeta
                    o próximo post do mesmo agente. */}
                {String(row.status_reason ?? "").startsWith(
                  "published_with_bookkeeping_loss",
                ) ? (
                  <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-400">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    O post foi publicado, mas uma guarda não foi gravada (
                    {String(row.status_reason).split(": ")[1]}). O agente pode
                    postar de novo antes do cooldown ou se repetir.
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <Card title="Tickets — revisão humana">
        {tickets.error ? (
          <Empty>Não foi possível medir: {tickets.error}</Empty>
        ) : (tickets.data ?? []).length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-emerald-400">
            <CheckCircle2 className="h-4 w-4" />
            Nenhum ticket aberto.
          </div>
        ) : (
          <div className="space-y-2">
            {(tickets.data ?? []).map((row, i) => {
              const id = String(row.id ?? i);
              return (
                <div key={id} className="rounded-lg border border-amber-500/40 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium">
                        {String(row.agent_name ?? "—")} ·{" "}
                        {String(row.suggested_title ?? "—")}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {String(row.suggested_summary ?? "")}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                        {id} · {ts(row.created_at)}
                      </p>
                    </div>
                    <button
                      disabled={busy === id}
                      onClick={() => void publishTicket(id)}
                      className="ix-transition inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-40"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Publicar
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Um ticket é aberto quando <strong>todos</strong> os provedores de LLM
          falham. O Nexus nunca publica um texto genérico no lugar — o
          conteúdo sugerido acima vem do rascunho determinístico, não de um
          modelo.
        </p>
      </Card>

      <Card title="Provedores de LLM">
        {health.error ? (
          <Empty>Não foi possível medir: {health.error}</Empty>
        ) : providers.length === 0 ? (
          <Empty>
            Nenhum provedor registrado. Habilitar o adaptador, ter credencial e
            ligar o publisher são três chaves distintas.
          </Empty>
        ) : (
          <div className="space-y-1.5">
            {providers.map((p, i) => {
              const status = String(p.status ?? "unknown");
              return (
                <div
                  key={String(p.provider ?? p.name ?? i)}
                  className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2"
                >
                  <span className="font-mono text-sm">
                    {String(p.provider ?? p.name ?? "—")}
                  </span>
                  <span className="flex items-center gap-1.5 text-xs">
                    <ProviderIcon status={status} />
                    {status}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          A cadeia faz failover a quente: um provedor offline é pulado, um
          degradado é pulado se houver alternativa saudável. Esgotada a cadeia,
          abre-se um ticket.
        </p>
      </Card>
    </div>
  );
}

function ProviderIcon({ status }: { status: string }) {
  if (status === "healthy") {
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
  }
  if (status === "degraded") {
    return <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />;
  }
  return <XCircle className="h-3.5 w-3.5 text-red-400" />;
}

function StatusMetric({ status, count }: { status: string; count: number }) {
  const good = status === "published";
  return (
    <div
      className={`rounded-lg border p-3 ${
        good
          ? "border-emerald-500/40 bg-emerald-500/[0.04]"
          : "border-amber-500/40 bg-amber-500/[0.04]"
      }`}
    >
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
        {good ? (
          <CheckCircle2 className="h-3 w-3" />
        ) : status === "suppressed" ? (
          <ShieldOff className="h-3 w-3" />
        ) : status === "ticketed" ? (
          <TicketIcon className="h-3 w-3" />
        ) : (
          <XCircle className="h-3 w-3" />
        )}
        {statusLabel(status)}
      </p>
      <p className="mt-1 text-lg font-semibold">{count}</p>
    </div>
  );
}

function statusLabel(status: string): string {
  switch (status) {
    case "published":
      return "publicadas";
    case "suppressed":
      return "barradas pelo anti-spam";
    case "invalid":
      return "reprovadas na validação";
    case "ticketed":
      return "viraram ticket";
    case "failed":
      return "falharam no Social";
    default:
      return status;
  }
}
