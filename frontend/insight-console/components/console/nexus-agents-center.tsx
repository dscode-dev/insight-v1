"use client";

// Nexus — os agentes que publicam, e o contrato de cada um.
//
// Esta tela não existia: a API administrativa do Nexus respondia 503 porque
// ele procurava identidade no gateway público, que pelo insight-context.md
// v2.0 não responde por operadores. Com a identidade vindo do Control Plane,
// os dados passaram a ser alcançáveis.
//
// O que ela responde: "quem pode falar em nome da plataforma, sobre o quê, e
// o que cada um está proibido de dizer?"
//
// As RESTRIÇÕES vêm primeiro dentro de cada agente, antes de estilo e tom.
// São o equivalente aos guardrails do Atlas — "nunca dá palpite de aposta",
// "nunca prevê o placar" — e lê-las depois do texto de marketing da persona
// inverte a ordem de importância.

import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  Power,
  ShieldOff,
  Sparkles,
  Tag,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import {
  Card,
  Empty,
  ErrorBanner,
  PageHeader,
  Pill,
  type Row,
} from "@/components/console/ops-shared";

const API = "/api/v1/nexus/v1";

interface Persona {
  slug?: string;
  style?: string;
  tone?: string;
  expertise?: string;
  restrictions?: string[];
  posting_behavior?: string;
  social_author_id?: string;
}

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

export function NexusAgentsCenter() {
  const [agents, setAgents] = useState<Row[]>([]);
  const [personas, setPersonas] = useState<Record<string, Persona>>({});
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [agentBody, personaBody] = await Promise.all([
        request("agents"),
        // Personas are a separate surface; a failure there must not blank
        // the agent list, which is the more important half.
        request("personas").catch(() => ({ personas: [] })),
      ]);
      setAgents(Array.isArray(agentBody.agents) ? (agentBody.agents as Row[]) : []);
      const list = Array.isArray(personaBody.personas)
        ? (personaBody.personas as Persona[])
        : [];
      setPersonas(Object.fromEntries(list.map((p) => [String(p.slug ?? ""), p])));
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "inalcançável");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (id: string, active: boolean) => {
    setBusy(id);
    try {
      await request(`agents/${id}/${active ? "disable" : "enable"}`, "POST");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "falhou");
    } finally {
      setBusy(null);
    }
  };

  const active = agents.filter((a) => a.active === true || a.enabled === true).length;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Bot}
        title="Agentes"
        subtitle="Quem publica em nome da plataforma, sobre o quê, e o que não pode dizer"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <Card title="Resumo">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Metric label="agentes" value={agents.length} />
          <Metric label="ativos" value={active} />
          <Metric
            label="com persona"
            value={agents.filter((a) => personas[String(a.name ?? "")]).length}
            // Um agente sem persona não publica: o publisher busca a persona
            // pelo nome e falha se não achar. É uma lacuna operacional, não
            // um detalhe cosmético.
            attention={agents.some((a) => !personas[String(a.name ?? "")])}
          />
        </div>
      </Card>

      {agents.length === 0 ? (
        <Card title="Nenhum agente">
          <Empty>
            O Nexus não tem agentes cadastrados. Sem agente, nenhuma tendência
            do Atlas é roteada e nada é rascunhado.
          </Empty>
        </Card>
      ) : (
        agents.map((a) => {
          const name = String(a.name ?? "");
          const id = String(a.id ?? "");
          const isActive = a.active === true || a.enabled === true;
          const persona = personas[name];
          const trendTypes = Array.isArray(a.trend_types)
            ? (a.trend_types as string[])
            : [];

          return (
            <Card key={id || name} title={name}>
              <div className="space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill value={String(a.specialty ?? "—")} />
                      <span
                        className={`text-xs ${
                          isActive ? "text-emerald-400" : "text-muted-foreground"
                        }`}
                      >
                        {isActive ? "ativo" : "desabilitado"}
                      </span>
                      {!persona ? (
                        <span className="text-xs text-amber-400">
                          sem persona — não consegue publicar
                        </span>
                      ) : null}
                    </div>
                    {a.bio ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {String(a.bio)}
                      </p>
                    ) : null}
                  </div>
                  <button
                    disabled={busy === id || !id}
                    onClick={() => void toggle(id, isActive)}
                    className="ix-transition inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-40"
                  >
                    <Power className="h-3.5 w-3.5" />
                    {isActive ? "Desabilitar" : "Habilitar"}
                  </button>
                </div>

                {/* O contrato negativo primeiro. */}
                {persona?.restrictions && persona.restrictions.length > 0 ? (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/[0.04] p-3">
                    <p className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-red-400">
                      <ShieldOff className="h-3 w-3" />
                      nunca faz
                    </p>
                    <ul className="space-y-1">
                      {persona.restrictions.map((r) => (
                        <li key={r} className="text-sm">
                          — {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {trendTypes.length > 0 ? (
                  <div>
                    <p className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <Tag className="h-3 w-3" />
                      tendências que o acionam
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {trendTypes.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-accent/60 px-1.5 py-0.5 font-mono text-[11px]"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {persona ? (
                  <dl className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
                    <Field label="especialidade" value={persona.expertise} />
                    <Field label="quando publica" value={persona.posting_behavior} />
                    <Field label="estilo" value={persona.style} />
                    <Field label="tom" value={persona.tone} />
                  </dl>
                ) : (
                  <Empty>
                    Nenhuma persona para <span className="font-mono">{name}</span>.
                    O publisher busca a persona pelo nome do agente e falha sem
                    ela — este agente rascunha, mas não publica.
                  </Empty>
                )}
              </div>
            </Card>
          );
        })
      )}

      <Card title="Como um agente vira post">
        <ol className="space-y-1.5 text-sm text-muted-foreground">
          <li>
            <Sparkles className="mr-1.5 inline h-3.5 w-3.5 text-sky-400" />
            O Atlas publica uma tendência avaliada — a <strong>única</strong>{" "}
            entrada do Nexus.
          </li>
          <li>2. O roteador escolhe quais agentes aquela tendência aciona.</li>
          <li>
            3. A decisão de publicação diz se vale falar (ou só lembrar), e o
            motivo fica gravado.
          </li>
          <li>
            4. O rascunho é <strong>determinístico</strong>. O LLM só reescreve
            na voz da persona — não inventa conteúdo.
          </li>
          <li>
            5. O anti-spam, o validador e a persona podem barrar. Toda supressão
            é explicada.
          </li>
        </ol>
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Metric({
  label,
  value,
  attention,
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
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
