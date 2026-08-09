"use client";

// Atlas — o que o motor sabe, o que lhe falta e o que ele NÃO faz.
//
// A versão anterior despejava cada campo da resposta num <pre> com
// JSON.stringify. Todos os dados estavam ali e nenhum era legível: o
// operador via seis blocos de JSON e não conseguia dizer o que era
// diagnóstico, o que era lacuna e o que era ação.
//
// Aqui cada campo é renderizado conforme o que ELE significa. A ordem
// também mudou: primeiro o que limita a confiança (riscos e lacunas),
// depois o que o motor mede, por último a evolução dos modelos — porque
// a pergunta operacional real é "posso confiar nisso agora?".

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Lightbulb,
  ShieldOff,
  TrendingUp,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader, type Row } from "@/components/console/ops-shared";

interface Signal {
  signal?: string;
  strength?: number | null;
  evidence?: string;
}

export function AtlasKnowledgeCenter() {
  const [body, setBody] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(
        withBasePath("/api/v1/data-intelligence/atlas/knowledge"),
        { cache: "no-store" },
      );
      const payload = (await res.json()) as Row;
      if (!res.ok) throw new Error(String(payload.detail ?? `HTTP ${res.status}`));
      setBody(payload);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "inalcançável");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!body) return <Empty>Carregando o conhecimento do Atlas…</Empty>;

  const risks = strings(body.risks);
  const missing = strings(body.missing);
  const improve = strings(body.should_improve);
  const signals = Array.isArray(body.signals_that_matter)
    ? (body.signals_that_matter as Signal[])
    : [];
  const patterns = Array.isArray(body.patterns) ? (body.patterns as Row[]) : [];
  const tendencies = Array.isArray(body.tendencies) ? (body.tendencies as Row[]) : [];
  const regime = (body.regime_intelligence as Row) ?? null;
  const guardrails = (body.guardrails as Record<string, boolean>) ?? {};
  const evolution = (body.evolution as Row) ?? null;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={BookOpen}
        title="Conhecimento do Atlas"
        subtitle="O que o motor sabe, o que lhe falta e o que ele deliberadamente não faz"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {/* Vem primeiro de propósito: é o que decide se dá para confiar
          nas conclusões abaixo. */}
      {risks.length > 0 || missing.length > 0 ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {risks.length > 0 ? (
            <Card title="O que limita a confiança agora">
              <ul className="space-y-1.5">
                {risks.map((r) => (
                  <li key={r} className="flex items-start gap-2 text-sm text-amber-400">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {missing.length > 0 ? (
            <Card title="O que está faltando no dado">
              <ul className="space-y-1.5">
                {missing.map((m) => (
                  <li key={m} className="text-sm text-muted-foreground">
                    — {m}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      ) : null}

      <Card title="Sinais que o motor mede">
        {signals.length === 0 ? (
          <Empty>Nenhum sinal medido ainda.</Empty>
        ) : (
          <div className="space-y-2">
            {signals.map((s, i) => (
              <div key={`${s.signal}-${i}`} className="rounded-lg border border-border/60 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{s.signal ?? "—"}</span>
                  {/* null NÃO é zero: significa que o sinal não pôde ser
                      medido, e mostrá-lo como 0.00 sugeriria força
                      nenhuma quando o certo é "não sei". */}
                  <span
                    className={`font-mono text-sm ${
                      s.strength == null ? "text-muted-foreground" : ""
                    }`}
                  >
                    {s.strength == null ? "não medido" : s.strength.toFixed(2)}
                  </span>
                </div>
                {s.evidence ? (
                  <p className="mt-0.5 text-xs text-muted-foreground">{s.evidence}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Padrões identificados">
          {patterns.length === 0 ? (
            <Empty>
              Nenhum padrão — normalmente falta de histórico, não ausência de padrão.
            </Empty>
          ) : (
            <ItemList rows={patterns} />
          )}
        </Card>
        <Card title="Tendências identificadas">
          {tendencies.length === 0 ? (
            <Empty>Nenhuma tendência identificada.</Empty>
          ) : (
            <ItemList rows={tendencies} />
          )}
        </Card>
      </div>

      {improve.length > 0 ? (
        <Card title="O que melhoraria a inteligência">
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

      {regime !== null ? (
        <Card title="Regime ativo">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <span>
              <span className="text-muted-foreground">regime</span>{" "}
              <span className="font-mono">{String(regime.regime_id ?? "—")}</span>
            </span>
            <span>
              <span className="text-muted-foreground">candidato</span>{" "}
              <span className="font-mono">{String(regime.candidate ?? "—")}</span>
            </span>
            <span>
              <span className="text-muted-foreground">modificador</span>{" "}
              {Number(regime.confidence_modifier ?? 0).toFixed(2)}
            </span>
            <span className={regime.activated ? "text-emerald-400" : "text-muted-foreground"}>
              {regime.activated ? "ativado" : "não ativado"}
            </span>
          </div>
          {regime.reason ? (
            <p className="mt-1 text-xs text-muted-foreground">{String(regime.reason)}</p>
          ) : null}
        </Card>
      ) : null}

      {/* Os guardrails são o contrato mais importante do Atlas: ele é
          descritivo, nunca preditivo. Mostrar isso na tela evita que
          alguém peça "só uma probabilidadezinha". */}
      {Object.keys(guardrails).length > 0 ? (
        <Card title="Guardrails — o que o Atlas NÃO faz por definição">
          <div className="flex flex-wrap gap-2">
            {Object.entries(guardrails).map(([name, enabled]) => (
              <span
                key={name}
                className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs ${
                  enabled ? "bg-red-500/15 text-red-400" : "bg-emerald-500/10 text-emerald-400"
                }`}
              >
                {enabled ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : (
                  <ShieldOff className="h-3 w-3" />
                )}
                {name}
                {enabled ? " ATIVO" : " bloqueado"}
              </span>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Todos bloqueados é o estado correto. Qualquer um ativo significa que o
            Atlas passou a emitir previsão, aposta ou recomendação — o que o
            contrato dele proíbe.
          </p>
        </Card>
      ) : null}

      {evolution !== null ? <Evolution evolution={evolution} /> : null}
    </div>
  );
}

function Evolution({ evolution }: { evolution: Row }) {
  const models = (evolution.models as Record<string, Row>) ?? {};
  const entries = Object.entries(models);
  return (
    <Card title="Evolução dos modelos">
      {entries.length === 0 ? (
        <Empty>Nenhum modelo registrado.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="pb-2">Modelo</th>
                <th className="pb-2">Situação</th>
                <th className="pb-2">Dataset</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([name, model]) => {
                const status = String(model.status ?? "—");
                const promoted = status === "promoted";
                return (
                  <tr key={name} className="border-t border-border/50">
                    <td className="py-2 font-mono text-xs">{name}</td>
                    <td className="py-2">
                      <span
                        className={`inline-flex items-center gap-1 text-xs ${
                          promoted ? "text-emerald-400" : "text-muted-foreground"
                        }`}
                      >
                        {promoted ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : (
                          <TrendingUp className="h-3 w-3" />
                        )}
                        {status}
                      </span>
                    </td>
                    <td className="py-2 font-mono text-[11px] text-muted-foreground">
                      {String(model.dataset ?? "—")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">
            <span className="font-mono">candidate_unpromoted</span> é o estado
            esperado na V1: o pipeline de ML do Atlas é experimental e nenhum
            modelo foi promovido para produção.
          </p>
        </div>
      )}
    </Card>
  );
}

/** Renderiza itens de forma legível, sem cair em JSON cru. */
function ItemList({ rows }: { rows: Row[] }) {
  return (
    <div className="space-y-2">
      {rows.slice(0, 20).map((row, i) => {
        const scalars = Object.entries(row).filter(
          ([, v]) => v === null || typeof v !== "object",
        );
        return (
          <div key={i} className="rounded-lg border border-border/60 p-2.5">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-3">
              {scalars.map(([k, v]) => (
                <div key={k}>
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="font-mono">{v === null ? "—" : String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })}
      {rows.length > 20 ? (
        <p className="text-xs text-muted-foreground">+{rows.length - 20} adicionais</p>
      ) : null}
    </div>
  );
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}
