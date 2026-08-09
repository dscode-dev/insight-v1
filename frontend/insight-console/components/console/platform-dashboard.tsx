"use client";

// Painel operacional do plano de inteligência.
//
// SUBSTITUI o `operational-command-center` (1.606 linhas) como landing
// page. Aquele buscava sete endpoints, dos quais QUATRO não existem
// (`/api/v1/ops/events`, `/ops/tickets`, `/ops/history`, `/dlq`) — o
// operador via um painel majoritariamente vazio sem saber se era falta
// de dado ou falta de rota.
//
// A regra aqui: cada número exibido vem de um endpoint verificado
// respondendo com dado real. Quando um valor não pôde ser medido, a
// tela diz "—" e não zero. Zero é uma medição; "—" é a ausência dela, e
// confundir os dois é como se cria incidente falso.

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ClipboardList,
  Database,
  Gauge,
  ShieldCheck,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, ErrorBanner, PageHeader, Pill, ts, type Row } from "@/components/console/ops-shared";

/** Uma fonte do painel. `error` distingue "não medido" de "medido como zero". */
interface Source<T = Row> {
  data: T | null;
  error: string | null;
}

const EMPTY: Source = { data: null, error: null };

async function load(path: string): Promise<Source> {
  try {
    const res = await fetch(withBasePath(`/api/v1${path}`), { cache: "no-store" });
    if (!res.ok) {
      return { data: null, error: `HTTP ${res.status}` };
    }
    return { data: (await res.json()) as Row, error: null };
  } catch (e) {
    return { data: null, error: e instanceof Error ? e.message : "inalcançável" };
  }
}

export function PlatformDashboard() {
  const [jobs, setJobs] = useState<Source>(EMPTY);
  const [quality, setQuality] = useState<Source>(EMPTY);
  const [review, setReview] = useState<Source>(EMPTY);
  const [runtime, setRuntime] = useState<Source>(EMPTY);
  const [engine, setEngine] = useState<Source>(EMPTY);
  const [replays, setReplays] = useState<Source>(EMPTY);
  const [decisions, setDecisions] = useState<Source>(EMPTY);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    // Em paralelo e cada uma isolada: uma fonte fora do ar mostra o
    // próprio erro, sem apagar o resto do painel.
    const [j, q, r, rt, e, rp, d] = await Promise.all([
      load("/explorer-ops/jobs"),
      load("/explorer-ops/quality"),
      load("/explorer-ops/review?status=pending"),
      load("/explorer-ops/runtime"),
      load("/quality-gate/engine-state"),
      load("/quality-gate/replays"),
      load("/quality-gate/decisions"),
    ]);
    setJobs(j); setQuality(q); setReview(r); setRuntime(rt);
    setEngine(e); setReplays(rp); setDecisions(d);
    setUpdated(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15000);
    return () => clearInterval(id);
  }, [refresh]);

  const down = [jobs, quality, review, runtime, engine, replays, decisions]
    .filter((s) => s.error !== null).length;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Gauge}
        title="Painel da plataforma"
        subtitle="Plano de inteligência — Explorer, Atlas e Anvil · atualiza a cada 15s"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {down > 0 ? (
        <ErrorBanner>
          {down} de 7 fontes não responderam. Os cartões correspondentes
          mostram &ldquo;—&rdquo; em vez de zero: o dado não foi medido,
          o que é diferente de ser zero.
        </ErrorBanner>
      ) : null}

      <ExplorerSection jobs={jobs} quality={quality} review={review} runtime={runtime} />
      <AtlasSection engine={engine} replays={replays} decisions={decisions} />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ExplorerSection({
  jobs, quality, review, runtime,
}: {
  jobs: Source; quality: Source; review: Source; runtime: Source;
}) {
  const active = arrLen(jobs.data?.active);
  const summary = (quality.data?.summary as Row) ?? null;
  const stats = (review.data?.stats as Row) ?? null;
  const status = (runtime.data?.status as Row) ?? null;
  const storage = (runtime.data?.storage as Row) ?? null;

  // Denominador explícito: a taxa é sobre o que foi CLASSIFICADO, não
  // sobre o coletado. Registro coletado e ainda não processado não pode
  // contar como reprovado.
  const classified =
    num(summary?.records_validated) + num(summary?.records_review) + num(summary?.records_rejected);
  const validationRate =
    summary === null || classified === 0
      ? null
      : (num(summary.records_validated) / classified) * 100;

  return (
    <Card title="Explorer — coleta e qualidade do dado">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Metric
          icon={Activity}
          label="coletas ativas"
          value={jobs.error ? null : active}
          hint={jobs.error ?? undefined}
        />
        <Metric
          icon={ClipboardList}
          label="fila de curadoria"
          value={review.error ? null : num(stats?.pending)}
          hint={review.error ?? "aguardando decisão humana"}
          tone={num(stats?.pending) > 0 ? "attention" : undefined}
        />
        <Metric
          icon={Gauge}
          label="taxa de validação"
          value={validationRate === null ? null : `${validationRate.toFixed(1)}%`}
          hint={
            quality.error ??
            (classified === 0 ? "nenhum registro classificado ainda" : `sobre ${classified} registros`)
          }
        />
        <Metric
          icon={AlertTriangle}
          label="rejeitados"
          value={quality.error ? null : num(summary?.records_rejected)}
          hint={quality.error ?? "preservados em reports/rejected"}
        />
        <Metric
          icon={Database}
          label="lake"
          value={runtime.error ? null : `${num(storage?.total_mb)} MB`}
          hint={runtime.error ?? undefined}
        />
      </div>

      {status !== null ? (
        <p className="mt-3 text-xs text-muted-foreground">
          scheduler <Pill value={String(status.scheduler_status ?? "unknown")} />
          {" · "}plano {num(status.plan_completed)}/{num(status.plan_total)}
          {" · "}jobs {num(status.jobs_completed)}/{num(status.jobs_total)}
        </p>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function AtlasSection({
  engine, replays, decisions,
}: {
  engine: Source; replays: Source; decisions: Source;
}) {
  const strength = (engine.data?.strength as Row) ?? null;
  const embeddings = (engine.data?.embeddings as Row) ?? null;
  const coverage = Array.isArray(embeddings?.coverage) ? (embeddings.coverage as Row[]) : [];
  const executions = Array.isArray(replays.data?.executions) ? (replays.data!.executions as Row[]) : [];
  const decided = Array.isArray(decisions.data?.decisions) ? (decisions.data!.decisions as Row[]) : [];

  const spread = num(strength?.elo_spread);
  // Um replay concluído sem decisão registrada é trabalho parado
  // esperando um humano — é o número mais acionável desta seção.
  const decidedHashes = new Set(decided.map((d) => String(d.replay_hash)));
  const awaiting = executions.filter(
    (e) => String(e.status) === "completed" && !decidedHashes.has(String(e.replay_hash ?? "")),
  ).length;

  return (
    <Card title="Atlas — motor de inteligência">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Metric
          icon={ShieldCheck}
          label="replays aguardando decisão"
          value={replays.error ? null : awaiting}
          hint={replays.error ?? "ATLAS_V1_FROZEN exige aprovação humana"}
          tone={awaiting > 0 ? "attention" : undefined}
        />
        <Metric
          icon={ShieldCheck}
          label="decisões registradas"
          value={decisions.error ? null : decided.length}
          hint={decisions.error ?? undefined}
        />
        <Metric
          icon={Activity}
          label="times no motor de força"
          value={engine.error ? null : num(strength?.teams_tracked)}
          hint={engine.error ?? undefined}
        />
        <Metric
          icon={Gauge}
          label="dispersão de Elo"
          value={engine.error ? null : spread.toFixed(1)}
          // Este é o número que diz se o motor está QUENTE. Contagem de
          // times não diz: um time semeado devolve 1500, que parece uma
          // nota perfeitamente plausível.
          hint={
            engine.error ??
            (spread < 1 ? "perto de zero — ainda não diferenciou ninguém" : "motor aquecido")
          }
          tone={!engine.error && spread < 1 ? "attention" : undefined}
        />
        <Metric
          icon={Database}
          label="partidas com embedding"
          value={engine.error ? null : coverage.reduce((sum, c) => sum + num(c.matches), 0)}
          hint={engine.error ?? (coverage.length > 1 ? "v1 e v2 coexistem" : undefined)}
        />
      </div>

      {coverage.length > 0 ? (
        <div className="mt-3 space-y-0.5">
          {coverage.map((c) => (
            <p key={String(c.embedding_version)} className="text-xs text-muted-foreground">
              <span className="font-mono">{String(c.embedding_version)}</span>{" "}
              ({String(c.dimensions ?? "?")}d) — {num(c.matches)} partidas
              {c.newest ? ` · mais recente ${ts(c.newest)}` : ""}
            </p>
          ))}
          {coverage.length > 1 ? (
            <p className="pt-1 text-xs text-amber-400">
              Cobertura desigual entre versões significa que uma busca v2
              roda sobre um corpus menor — e ela não avisa.
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function Metric({
  icon: Icon, label, value, hint, tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  /** `null` = não medido. Renderiza "—", nunca zero. */
  value: string | number | null;
  hint?: string;
  tone?: "attention";
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        tone === "attention" ? "border-amber-500/40 bg-amber-500/[0.04]" : "border-border/60"
      }`}
    >
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold ${value === null ? "text-muted-foreground" : ""}`}>
        {value === null ? "—" : value}
      </p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function arrLen(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}
