"use client";

// Atlas — consulta de inteligência histórica.
//
// A versão anterior tinha o código inteiro em linhas únicas (ilegível) e
// terminava num <pre> com JSON.stringify da cobertura. Pior: exibia
// `sample_size`, `confidence` e `uncertainty` como quatro números sem
// contexto, lado a lado com listas de tendências — dando peso igual a
// "o que o Atlas concluiu" e "quão confiável isso é".
//
// A inversão aqui é deliberada: a CONFIABILIDADE vem primeiro. Um
// relatório com `sample_size: 0` e `confidence: 0` não é um relatório
// fraco, é a ausência de um — e a tela precisa dizer isso antes de
// mostrar qualquer conclusão, ou alguém vai ler tendência em cima de
// nada.

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Brain, Lightbulb, Search, ShieldOff } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, PageHeader, Pill, type Row } from "@/components/console/ops-shared";

const TYPES = ["competition", "team", "season", "dataset", "trend"] as const;
type AnalysisType = (typeof TYPES)[number];

interface Signal {
  signal?: string;
  strength?: number | null;
  evidence?: string;
}

export function AtlasIntelligenceWorkspace() {
  const [type, setType] = useState<AnalysisType>("competition");
  const [query, setQuery] = useState("brasileirao_serie_a");
  const [report, setReport] = useState<Row | null>(null);
  const [comparison, setComparison] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const analyze = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetch(
        withBasePath("/api/v1/data-intelligence/atlas/analyze"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ analysis_type: type, query }),
        },
      );
      const body = (await res.json()) as Row;
      if (!res.ok) throw new Error(String(body.detail ?? `HTTP ${res.status}`));
      setReport(body);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "inalcançável");
    } finally {
      setBusy(false);
    }
  }, [type, query]);

  useEffect(() => {
    fetch(withBasePath("/api/v1/data-intelligence/atlas/comparison"), { cache: "no-store" })
      .then((r) => r.json())
      .then(setComparison)
      .catch(() => undefined);
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Brain}
        title="Inteligência do Atlas"
        subtitle="Padrões, tendências e regimes medidos sobre o histórico — sem previsão, sem LLM"
        onRefresh={() => void analyze()}
        updated={null}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <Card title="Consulta">
        <div className="flex flex-wrap gap-2">
          <select
            className="input max-w-44"
            value={type}
            onChange={(e) => setType(e.target.value as AnalysisType)}
          >
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <input
            className="input min-w-64 flex-1"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void analyze();
            }}
            placeholder="brasileirao_serie_a · flamengo · 2024 · mld5"
          />
          <Button onClick={() => void analyze()} disabled={busy}>
            <Search className="h-4 w-4" />
            {busy ? "Analisando…" : "Analisar"}
          </Button>
        </div>
      </Card>

      {report ? (
        <Report report={report} />
      ) : (
        <Empty>
          Escolha um escopo e analise. O Atlas só descreve evidência
          histórica medida — ele não estima o que não observou.
        </Empty>
      )}

      <ModelComparison body={comparison} />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Report({ report }: { report: Row }) {
  const context = (report.context as Row) ?? {};
  const confidence = (report.confidence as Row) ?? {};
  const sample = num(context.sample_size);
  const conf = num(confidence.confidence);

  const tendencies = Array.isArray(report.tendencies) ? (report.tendencies as Row[]) : [];
  const regimes = strings(report.regimes);
  const signals = Array.isArray(report.signals) ? (report.signals as Signal[]) : [];
  const risks = strings(report.risks);
  const missing = strings(report.missing_information);
  const improve = strings(report.improvement_suggestions);
  const guardrails = (report.guardrails as Record<string, boolean>) ?? {};

  // Sem amostra não existe conclusão. Dizer isso ANTES de renderizar
  // tendências evita que alguém leia uma lista vazia como "não há
  // tendências" quando o correto é "não houve o que medir".
  const noEvidence = sample === 0;

  return (
    <div className="space-y-4">
      <Card title="Confiabilidade desta análise">
        {noEvidence ? (
          <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/[0.06] p-3">
            <p className="flex items-center gap-2 text-sm text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              Nenhum registro histórico correspondeu a esta consulta.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              As seções abaixo estarão vazias — isso significa &ldquo;não
              houve o que medir&rdquo;, não &ldquo;não existe padrão&rdquo;.
              Colete histórico em <strong>Pipelines</strong> antes de
              interpretar este relatório.
            </p>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric
            label="amostra"
            value={sample}
            attention={noEvidence}
            hint={noEvidence ? "sem registros" : "registros considerados"}
          />
          <Metric
            label="confiança"
            value={conf.toFixed(2)}
            attention={conf < 0.3}
            hint={String(confidence.basis ?? "")}
          />
          <Metric
            label="incerteza"
            value={num(confidence.uncertainty).toFixed(2)}
            attention={num(confidence.uncertainty) > 0.7}
            hint="1,00 = nada pôde ser afirmado"
          />
          <Metric
            label="calibração (ECE)"
            value={num(confidence.calibration).toFixed(4)}
            hint="quanto menor, melhor"
          />
        </div>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <ListCard
          title="Tendências medidas"
          items={tendencies.map((t) => `${t.tendency} (${t.delta})`)}
          empty={noEvidence ? "sem amostra para medir" : "nenhuma tendência medida"}
        />
        <ListCard
          title="Regimes"
          items={regimes}
          empty="nenhum regime identificado"
        />
      </div>

      <Card title="Sinais">
        {signals.length === 0 ? (
          <Empty>Nenhum sinal.</Empty>
        ) : (
          <div className="space-y-1.5">
            {signals.map((s, i) => (
              <div
                key={`${s.signal}-${i}`}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border/40 pb-1.5 last:border-0"
              >
                <span className="text-sm">{s.signal ?? "—"}</span>
                <span className="flex items-baseline gap-3">
                  <span className="text-xs text-muted-foreground">{s.evidence ?? ""}</span>
                  {/* null = não medido. 0.00 diria "força nenhuma", que
                      é uma afirmação diferente. */}
                  <span
                    className={`font-mono text-sm ${
                      s.strength == null ? "text-muted-foreground" : ""
                    }`}
                  >
                    {s.strength == null ? "não medido" : s.strength.toFixed(2)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <ListCard title="Riscos" items={risks} tone="warn" empty="nenhum risco apontado" />
        <ListCard title="Informação faltante" items={missing} empty="nada faltando" />
      </div>

      {improve.length > 0 ? (
        <Card title="O que melhoraria esta análise">
          <ul className="space-y-1.5">
            {improve.map((s) => (
              <li key={s} className="flex items-start gap-2 text-sm">
                <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-400" />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Coverage context={context} />

      {Object.keys(guardrails).length > 0 ? (
        <Card title="Guardrails">
          <div className="flex flex-wrap gap-2">
            {Object.entries(guardrails).map(([name, on]) => (
              <span
                key={name}
                className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs ${
                  on ? "bg-red-500/15 text-red-400" : "bg-emerald-500/10 text-emerald-400"
                }`}
              >
                {on ? <AlertTriangle className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                {name}
                {on ? " ATIVO" : " bloqueado"}
              </span>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

/** Cobertura, em tabela — substitui o <pre> com JSON.stringify. */
function Coverage({ context }: { context: Row }) {
  const groups: [string, Row][] = [
    ["fontes", (context.source_coverage as Row) ?? {}],
    ["competições", (context.competition_coverage as Row) ?? {}],
    ["temporadas", (context.season_coverage as Row) ?? {}],
  ];
  const total = groups.reduce((s, [, g]) => s + Object.keys(g).length, 0);

  return (
    <Card title="Cobertura do histórico consultado">
      {total === 0 ? (
        <Empty>
          Nenhuma cobertura — a consulta não encontrou registros em fonte,
          competição ou temporada alguma.
        </Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-3">
          {groups.map(([label, group]) => (
            <div key={label}>
              <p className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                {label}
              </p>
              {Object.keys(group).length === 0 ? (
                <p className="text-xs text-muted-foreground">—</p>
              ) : (
                <ul className="space-y-0.5">
                  {Object.entries(group).map(([k, v]) => (
                    <li key={k} className="flex justify-between text-xs">
                      <span className="truncate font-mono">{k}</span>
                      <span className="ml-2 shrink-0">{String(v)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ModelComparison({ body }: { body: Row | null }) {
  const models = (body?.models as Record<string, Row>) ?? {};
  const entries = Object.entries(models);

  return (
    <Card title="Comparação de modelos candidatos">
      {entries.length === 0 ? (
        <Empty>Nenhum modelo registrado.</Empty>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="pb-2">Versão</th>
                  <th className="pb-2">Situação</th>
                  <th className="pb-2">Holdout</th>
                  <th className="pb-2">Acurácia balanceada</th>
                  <th className="pb-2">Incerteza</th>
                  <th className="pb-2">ECE</th>
                  <th className="pb-2">Recall de empate</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([name, m]) => (
                  <tr key={name} className="border-t border-border/50">
                    <td className="py-1.5 font-mono">{name}</td>
                    <td className="py-1.5"><Pill value={String(m.status ?? "—")} /></td>
                    <td className="py-1.5">{String(m.holdout ?? "—")}</td>
                    <td className="py-1.5">{String(m.balanced_accuracy ?? "—")}</td>
                    <td className="py-1.5">{String(m.uncertainty ?? "—")}</td>
                    <td className="py-1.5">{String(m.ece ?? "—")}</td>
                    <td className="py-1.5">{String(m.draw_recall ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Estes modelos pertencem ao pipeline experimental
            (<span className="font-mono">atlas/outcome</span>), que está
            <strong> fora do escopo da V1</strong>. Nenhum é promovido, e
            nada aqui alimenta o que o Atlas publica.
          </p>
        </>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function ListCard({
  title, items, empty, tone,
}: {
  title: string;
  items: string[];
  empty: string;
  tone?: "warn";
}) {
  return (
    <Card title={title}>
      {items.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((v, i) => (
            <li
              key={`${v}-${i}`}
              className={tone === "warn" ? "text-amber-400" : undefined}
            >
              • {v}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Metric({
  label, value, hint, attention,
}: {
  label: string;
  value: string | number;
  hint?: string;
  attention?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        attention ? "border-amber-500/40 bg-amber-500/[0.04]" : "border-border/60"
      }`}
    >
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}
