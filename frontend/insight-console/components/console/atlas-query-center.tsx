"use client";

// Simulador de consulta ao Atlas — o mesmo caminho, a mesma resposta.
//
// A tela chama `POST /v1/query`, que é exatamente o endpoint que o fluxo de
// produção chama ao montar um post de tendência ou contexto. Não há caminho
// paralelo, nem modo de demonstração: o que aparece aqui é o payload que o
// Nexus receberia, byte por byte.
//
// POR QUE O JSON CRU APARECE JUNTO DA LEITURA BONITA. Uma renderização é uma
// interpretação, e o que se quer conferir aqui é o contrato. Ver só os
// cartões faria a tela responder "o Atlas disse isso" quando ela na verdade
// diz "eu entendi isso". Os dois lado a lado deixam a diferença visível.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Brain,
  Code2,
  Loader2,
  Layers,
  Play,
  RotateCcw,
  Ruler,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader } from "@/components/console/ops-shared";
import { cn } from "@/lib/utils";

const API = "/api/v1/data-intelligence/atlas/query";

interface Validacao {
  ganho: number | null;
  margem: number | null;
  conclusiva: boolean;
  descreve_desfecho: boolean;
  /** Conclusivamente ABAIXO da taxa base desta competição. */
  pior_que_a_base?: boolean;
  /** A competição em que foi medida. A validade não é da lente: `gols` mede
   *  +5,8% na Premier League e −5,8% no Brasileirão. */
  competicao: string;
  taxa_base?: number;
  avaliadas?: number;
  medida_em?: string;
  leitura: string;
}

interface CategoriaInfo {
  categoria: string;
  pergunta: string;
  descreve: string;
  dimensoes: string[];
  filtros: string[];
  /** A lente diz se PODE descrever desfecho quando a medida for conclusiva.
   *  Quanto ela vale depende da competição, e vem na resposta da consulta. */
  descreve_desfecho_quando_conclusiva: boolean;
}

interface Resposta {
  schema_version: string;
  categoria: string;
  pergunta: string;
  descreve: string;
  validacao: Validacao;
  as_of: string;
  vizinhanca: {
    encontrados: number;
    pedidos: number;
    dimensoes_usadas: string[];
    filtros: string[];
    similaridade?: { maior: number; mediana: number; menor: number };
    escala?: { mediana_entre_pares_aleatorios: number; leitura: string };
  };
  descricao: Record<string, unknown> | null;
  evidencia: Array<Record<string, unknown>>;
  incerteza: { score: number; motivo: string; dimensoes_ausentes: string[] };
}

/** Valores de exemplo por dimensão. Reais, na escala em que o Atlas os lê. */
const EXEMPLOS: Record<string, string> = {
  implied_home: "0.55", implied_draw: "0.24", implied_away: "0.21",
  favourite_margin: "0.31", line_movement: "0.03", overround: "0.05",
  elo_delta: "0.35", home_form: "2.2", away_form: "1.4",
  h2h_advantage: "0.2", rest_advantage: "0.1", season_progress: "0.71",
  home_attack: "1.8", away_attack: "1.1", home_defense: "0.9", away_defense: "1.4",
  expected_goals_total: "2.9",
  home_shots_rate: "14.2", away_shots_rate: "10.1",
  home_accuracy: "0.38", away_accuracy: "0.33",
  home_corners_rate: "6.1", away_corners_rate: "4.4",
  home_discipline: "1.8", away_discipline: "2.2",
};

async function chamar(caminho: string, corpo?: unknown): Promise<unknown> {
  const resposta = await fetch(withBasePath(`${API}${caminho}`), {
    method: corpo === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: corpo === undefined ? undefined : { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = (await resposta.json().catch(() => ({}))) as Record<string, unknown>;
  if (!resposta.ok) {
    const detalhe = dados.detail ?? dados.error ?? `HTTP ${resposta.status}`;
    throw new Error(typeof detalhe === "string" ? detalhe : JSON.stringify(detalhe));
  }
  return dados;
}

export function AtlasQueryCenter() {
  const [categorias, setCategorias] = useState<CategoriaInfo[] | null>(null);
  const [escolhida, setEscolhida] = useState("resultado");
  const [identidade, setIdentidade] = useState({
    competition: "premier_league",
    season: "2024-2025",
    home_club_id: "arsenal",
    away_club_id: "chelsea",
    as_of: "2025-03-01T15:00:00Z",
  });
  const [features, setFeatures] = useState<Record<string, string>>({});
  const [resposta, setResposta] = useState<Resposta | null>(null);
  //: As cinco respostas de uma vez. Na rede social cada lente vira um post
  //: diferente sobre a MESMA partida, então ver as cinco lado a lado é o que
  //: mostra o que o feed produziria — uma de cada vez mostra uma fatia.
  const [todas, setTodas] = useState<Resposta[] | null>(null);
  const [cru, setCru] = useState<string>("");
  const [erro, setErro] = useState<string | null>(null);
  const [consultando, setConsultando] = useState(false);
  const [verCru, setVerCru] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const dados = (await chamar("/categorias")) as { categorias: CategoriaInfo[] };
        setCategorias(dados.categorias ?? []);
      } catch (caught) {
        setErro(caught instanceof Error ? caught.message : "indisponível");
      }
    })();
  }, []);

  const atual = useMemo(
    () => categorias?.find((c) => c.categoria === escolhida) ?? null,
    [categorias, escolhida],
  );

  const preencher = useCallback(() => {
    if (!atual) return;
    setFeatures(
      Object.fromEntries(atual.dimensoes.map((d) => [d, EXEMPLOS[d] ?? "0"])),
    );
  }, [atual]);

  const consultar = useCallback(async () => {
    if (!atual) return;
    setConsultando(true);
    setErro(null);
    try {
      const corpo = {
        categoria: escolhida,
        ...identidade,
        features: Object.fromEntries(
          atual.dimensoes
            .filter((d) => (features[d] ?? "").trim() !== "")
            .map((d) => [d, Number(features[d])]),
        ),
      };
      const dados = (await chamar("", corpo)) as Resposta;
      setResposta(dados);
      setTodas(null);
      setCru(JSON.stringify(dados, null, 2));
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "falhou");
      setResposta(null);
    } finally {
      setConsultando(false);
    }
  }, [atual, escolhida, identidade, features]);

  const consultarTodas = useCallback(async () => {
    if (!categorias) return;
    setConsultando(true);
    setErro(null);
    try {
      // Sequencial, não em paralelo: cinco reconstruções simultâneas da régua
      // de cada lente disputariam o mesmo pool de conexões, e o ganho de
      // alguns segundos não paga o risco de esgotá-lo.
      const respostas: Resposta[] = [];
      for (const c of categorias) {
        const corpo = {
          categoria: c.categoria,
          ...identidade,
          features: Object.fromEntries(
            c.dimensoes
              .filter((d) => (features[d] ?? "").trim() !== "" || EXEMPLOS[d])
              .map((d) => [
                d,
                Number((features[d] ?? "").trim() || EXEMPLOS[d] || "0"),
              ]),
          ),
        };
        respostas.push((await chamar("", corpo)) as Resposta);
      }
      setTodas(respostas);
      setResposta(null);
      setCru(JSON.stringify(respostas, null, 2));
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "falhou");
    } finally {
      setConsultando(false);
    }
  }, [categorias, identidade, features]);

  return (
    <div className="space-y-5">
      <PageHeader
        icon={Brain}
        title="Consulta ao Atlas"
        subtitle="O mesmo endpoint que o fluxo de produção chama ao montar um post · a resposta é a de produção, sem tradução"
        updated={null}
        onRefresh={() => void consultar()}
      />

      {erro && <ErrorBanner>{erro}</ErrorBanner>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card title="Categoria">
            {categorias === null ? (
              <Empty>carregando…</Empty>
            ) : (
              <div className="space-y-1.5">
                {categorias.map((c) => (
                  <button
                    key={c.categoria}
                    onClick={() => {
                      setEscolhida(c.categoria);
                      setFeatures({});
                      setResposta(null);
                    }}
                    className={cn(
                      "ix-transition block w-full rounded-lg border px-3 py-2 text-left",
                      escolhida === c.categoria
                        ? "border-primary/40 bg-primary/10"
                        : "border-border bg-card hover:bg-accent",
                    )}
                  >
                    <span className="flex items-center gap-1.5 font-mono text-xs font-semibold">
                      {c.categoria}
                      {/* A medição da lente, no momento da escolha. Escolher
                          uma lente que erra mais que a taxa base sem saber
                          disso é o que a validação existe para impedir. */}
                      {/* A lente que nunca descreve desfecho é marcada aqui;
                          o quanto ela vale nesta competição só se sabe depois
                          da consulta, e aparece na resposta. */}
                      {!c.descreve_desfecho_quando_conclusiva && (
                        <AlertTriangle className="h-3 w-3 text-amber-500" />
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                      {c.pergunta}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card title="Partida">
            <div className="grid gap-2">
              {(
                [
                  ["competition", "Competição", "premier_league"],
                  ["season", "Temporada", "2024-2025"],
                  ["home_club_id", "Mandante", "arsenal"],
                  ["away_club_id", "Visitante", "chelsea"],
                  ["as_of", "Instante da consulta", "2025-03-01T15:00:00Z"],
                ] as const
              ).map(([campo, rotulo, exemplo]) => (
                <label key={campo} className="block text-[11px] text-muted-foreground">
                  {rotulo}
                  <input
                    value={identidade[campo]}
                    placeholder={exemplo}
                    onChange={(e) =>
                      setIdentidade((a) => ({ ...a, [campo]: e.target.value }))
                    }
                    className="mt-0.5 w-full rounded-lg border border-border bg-card px-2 py-1.5 font-mono text-xs text-foreground"
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-[10px] leading-snug text-muted-foreground">
              Só entram como vizinhos jogos anteriores ao instante da consulta —
              é o corte que impede a resposta de usar o que ainda não aconteceu.
            </p>
          </Card>
        </div>

        <div className="space-y-4">
          {atual && <LenteInfo lente={atual} />}

          <Card title={`Sinais da partida (${atual?.dimensoes.length ?? 0})`}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <p className="flex-1 text-[11px] text-muted-foreground">
                Só as dimensões desta lente. O que ficar em branco entra como a
                média do corpus, que significa &ldquo;não informa nada&rdquo; — e
                aparece na incerteza da resposta.
              </p>
              <button
                onClick={preencher}
                className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-accent"
              >
                <RotateCcw className="h-3 w-3" /> Preencher com exemplo
              </button>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              {(atual?.dimensoes ?? []).map((dimensao) => (
                <label
                  key={dimensao}
                  className="block font-mono text-[10px] text-muted-foreground"
                >
                  {dimensao}
                  <input
                    value={features[dimensao] ?? ""}
                    placeholder={EXEMPLOS[dimensao] ?? "0"}
                    inputMode="decimal"
                    onChange={(e) =>
                      setFeatures((a) => ({ ...a, [dimensao]: e.target.value }))
                    }
                    className="mt-0.5 w-full rounded-lg border border-border bg-card px-2 py-1 font-mono text-xs text-foreground placeholder:text-muted-foreground/50"
                  />
                </label>
              ))}
            </div>
            <button
              onClick={() => void consultar()}
              disabled={consultando || !atual}
              className="ix-transition mt-3 inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {consultando ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Consultar
            </button>
            <button
              onClick={() => void consultarTodas()}
              disabled={consultando || !categorias}
              className="ix-transition mt-3 ml-2 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
            >
              <Layers className="h-3.5 w-3.5" /> Consultar as cinco lentes
            </button>
            <p className="mt-1.5 text-[10px] leading-snug text-muted-foreground">
              Na rede social cada lente vira um post diferente sobre a mesma
              partida. Consultar as cinco mostra o que o feed produziria — os
              campos em branco entram com o exemplo.
            </p>
          </Card>
        </div>
      </div>

      {todas && (
        <Card title="As cinco lentes sobre a mesma partida">
          <p className="mb-3 text-[11px] text-muted-foreground">
            É isto que o feed produziria: um post por lente. Duas delas vêm
            marcadas — `confronto` devolve registro, não descrição, e `contexto`
            não tem evidência de descrever desfecho.
          </p>
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {todas.map((r) => (
              <LenteResumo key={r.categoria} resposta={r} />
            ))}
          </div>
        </Card>
      )}

      {(resposta || todas) && (
        <>
          {resposta && <RespostaPainel resposta={resposta} />}
          <Card title="Resposta exata do Atlas">
            <div className="mb-2 flex items-center gap-2">
              <button
                onClick={() => setVerCru((v) => !v)}
                className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-accent"
              >
                <Code2 className="h-3 w-3" /> {verCru ? "Ocultar" : "Mostrar"} JSON
              </button>
              <span className="text-[11px] text-muted-foreground">
                {resposta?.schema_version ?? todas?.[0]?.schema_version} — é este
                payload que o Nexus recebe
                {todas ? ` (${todas.length} respostas, uma por lente)` : ""}
              </span>
            </div>
            {verCru && (
              <pre className="max-h-[28rem] overflow-auto rounded-lg border border-border bg-background/60 p-3 font-mono text-[11px] leading-relaxed">
                {cru}
              </pre>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function LenteResumo({ resposta }: { resposta: Resposta }) {
  const v = resposta.validacao;
  const viz = resposta.vizinhanca;

  // TRÊS ESTADOS, NÃO DOIS — e a rede social publica um post por lente, então
  // a diferença entre eles é a diferença entre publicar e não publicar:
  //
  //   conclusiva        a régua mediu a lente NESTA competição e ela descreve
  //   não demonstrada   medida, e a diferença cabe na margem: nada a favor
  //   pior que a base   medida, e ABAIXO do palpite trivial: descrição retida
  //   não medida        nunca apurada aqui; não há o que afirmar
  const semMedida = v.ganho === null;
  const pior = v.pior_que_a_base === true;
  const tom = pior
    ? "border-red-500/40 bg-red-500/[0.06]"
    : v.conclusiva
      ? "border-emerald-500/30 bg-emerald-500/[0.05]"
      : "border-amber-500/30 bg-amber-500/[0.05]";

  return (
    <div className={cn("rounded-xl border p-3", tom)}>
      <p className="flex items-center gap-1.5 font-mono text-xs font-semibold">
        {resposta.categoria}
        {(pior || semMedida || !v.conclusiva) && (
          <AlertTriangle
            className={cn("h-3 w-3", pior ? "text-red-400" : "text-amber-500")}
          />
        )}
      </p>
      <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
        {resposta.pergunta}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px]">
        <span className={pior ? "text-red-400" : v.conclusiva ? "text-emerald-400" : "text-amber-400"}>
          {semMedida
            ? "não medida aqui"
            : `${v.ganho! > 0 ? "+" : ""}${(v.ganho! * 100).toFixed(1)}% vs base`}
        </span>
        {!semMedida && v.margem !== null && (
          <span className="text-muted-foreground">
            margem {(v.margem * 100).toFixed(1)}%
          </span>
        )}
        <span className="text-muted-foreground">em {v.competicao}</span>
      </div>

      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted-foreground">
        <span>{viz.encontrados} viz.</span>
        {viz.similaridade && <span>sim {viz.similaridade.mediana.toFixed(3)}</span>}
        {viz.escala && (
          <span>régua {viz.escala.mediana_entre_pares_aleatorios.toFixed(3)}</span>
        )}
        <span>incerteza {resposta.incerteza.score.toFixed(2)}</span>
      </div>

      <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">
        {v.leitura}
      </p>

      {resposta.descricao === null ? (
        <p
          className={cn(
            "mt-2 text-[11px] leading-relaxed",
            pior ? "text-red-400" : "text-amber-400",
          )}
        >
          {resposta.incerteza.motivo}
        </p>
      ) : (
        <pre className="mt-2 max-h-40 overflow-auto rounded-lg border border-border bg-background/40 p-2 font-mono text-[10px] leading-relaxed">
          {JSON.stringify(resposta.descricao, null, 1)}
        </pre>
      )}
    </div>
  );
}


function LenteInfo({ lente }: { lente: CategoriaInfo }) {
  // SEM NÚMERO DE VALIDAÇÃO AQUI, e isso é a mudança.
  //
  // Este painel descreve a lente; a lente não tem mais um valor próprio.
  // `resultado` mede +12,4% na Premier League e +0,9% no Brasileirão — um
  // número nesta tela seria lido como "o valor da lente", que é justamente
  // a afirmação que deixou de existir. O valor aparece na RESPOSTA, ao lado
  // da competição consultada.
  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      <p className="text-sm font-semibold">{lente.pergunta}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{lente.descreve}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {lente.dimensoes.map((d) => (
          <span
            key={d}
            className="rounded border border-border bg-background/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
          >
            {d}
          </span>
        ))}
      </div>
      {lente.filtros.length > 0 && (
        <p className="mt-1.5 font-mono text-[10px] text-muted-foreground">
          filtros duros: {lente.filtros.join(", ")}
        </p>
      )}
      {!lente.descreve_desfecho_quando_conclusiva && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-amber-400">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          Esta lente nunca descreve desfecho — ela devolve o retrospecto entre
          os dois clubes. Ler o registro como probabilidade da partida é o erro
          que o formato da resposta impede.
        </p>
      )}
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        Quanto esta lente vale depende da competição. Consulte uma partida para
        ver a medida apurada naquele campeonato.
      </p>
    </div>
  );
}


function RespostaPainel({ resposta }: { resposta: Resposta }) {
  const v = resposta.vizinhanca;
  return (
    <Card title="O que o Atlas respondeu">
      <div className="grid gap-2 sm:grid-cols-4">
        <Numero rotulo="vizinhos" valor={`${v.encontrados} / ${v.pedidos}`} />
        <Numero
          rotulo="similaridade (mediana)"
          valor={v.similaridade ? v.similaridade.mediana.toFixed(3) : "—"}
        />
        <Numero
          rotulo="régua (par aleatório)"
          valor={
            v.escala ? v.escala.mediana_entre_pares_aleatorios.toFixed(3) : "—"
          }
          icone={Ruler}
        />
        <Numero
          rotulo="incerteza"
          valor={resposta.incerteza.score.toFixed(3)}
          tom={resposta.incerteza.score > 0.4 ? "alerta" : undefined}
        />
      </div>

      {v.escala && (
        <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
          {v.escala.leitura}
        </p>
      )}

      {resposta.descricao === null ? (
        <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-400">
          Sem descrição: {resposta.incerteza.motivo}
        </div>
      ) : (
        <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-background/40 p-3 font-mono text-[11px] leading-relaxed">
          {JSON.stringify(resposta.descricao, null, 2)}
        </pre>
      )}

      <p className="mt-2 text-[11px] text-muted-foreground">
        {resposta.incerteza.motivo}
      </p>

      {resposta.evidencia.length > 0 && (
        <div className="mt-3">
          <h4 className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            Evidência — as partidas que sustentam a descrição
          </h4>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/40 text-left uppercase tracking-wider text-muted-foreground">
                  <th className="px-2 py-1.5">Data</th>
                  <th className="px-2 py-1.5">Partida</th>
                  <th className="px-2 py-1.5">Desfecho</th>
                  <th className="px-2 py-1.5 text-right">Similaridade</th>
                </tr>
              </thead>
              <tbody>
                {resposta.evidencia.map((linha, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="px-2 py-1 font-mono">
                      {String(linha.kickoff_utc ?? "").slice(0, 10)}
                    </td>
                    <td className="px-2 py-1 font-mono">
                      {String(linha.home_club_id)} × {String(linha.away_club_id)}
                    </td>
                    <td className="px-2 py-1">{String(linha.desfecho)}</td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums">
                      {Number(linha.similaridade).toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}

function Numero({
  rotulo,
  valor,
  tom,
  icone: Icone,
}: {
  rotulo: string;
  valor: string;
  tom?: "alerta";
  icone?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-background/40 px-3 py-2">
      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
        {Icone && <Icone className="h-3 w-3" />}
        {rotulo}
      </p>
      <p
        className={cn(
          "font-mono text-base font-semibold tabular-nums",
          tom === "alerta" && "text-amber-400",
        )}
      >
        {valor}
      </p>
    </div>
  );
}
