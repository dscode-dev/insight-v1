"use client";

// Ingestão do Atlas — o que ele tem, o que entra, e o que foi recusado.
//
// A tela é deliberadamente burra sobre as regras: ela não valida nada. O
// contrato vive no Atlas e é ele quem aceita ou recusa, então o que aparece
// aqui é sempre a resposta real do serviço — nunca uma segunda opinião do
// navegador que pode discordar dela.
//
// Isso é o oposto do que costuma ser tentador num formulário de 27 campos.
// Validar no cliente daria retorno mais rápido e criaria uma terceira cópia
// das regras, ao lado do contrato e da porta HTTP. Duas cópias já produziram
// o bug que motivou toda esta reconstrução.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileUp,
  FlaskConical,
  Loader2,
  PlusCircle,
  RotateCcw,
  Upload,
  XCircle,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader } from "@/components/console/ops-shared";
import {
  BLOCOS,
  BLOCOS_DO_CONTRATO,
  DESCRICAO_DO_BLOCO,
  campoPertenceAoPerfil,
  lerPerfil,
  montarRegistro,
  valoresDeExemplo,
  type Campo,
} from "@/lib/atlas-intake-fields";
import { cn } from "@/lib/utils";

const API = "/api/v1/data-intelligence/atlas/intake";

interface LinhaErro {
  field: string;
  reason: string;
}

interface LinhaRelatorio {
  index: number;
  accepted: boolean;
  uid: string | null;
  replaced: boolean;
  label: string;
  errors: LinhaErro[];
  /** Blocos que a composição ainda não tem. Não vazio = guardada, não virou partida. */
  missing_blocks?: string[];
}

interface Relatorio {
  submitted: number;
  accepted: number;
  added: number;
  replaced: number;
  /** Aceitas e guardadas, esperando outra fonte. Nem novas nem atualizadas. */
  pending?: number;
  rejected: number;
  total_before: number;
  total_after: number;
  delta: number;
  by_field: Record<string, number>;
  missing_blocks?: Record<string, number>;
  lines: LinhaRelatorio[];
  simulated?: boolean;
}

interface Cobertura {
  competition: string;
  season: string;
  matches: number;
  first_match: string | null;
  last_match: string | null;
  sources: number;
}

interface Recusa {
  rejected_at: string;
  via: string;
  by: string;
  competition: string | null;
  season: string | null;
  source_match_id: string | null;
  errors: LinhaErro[];
}

async function chamar(caminho: string, corpo?: unknown): Promise<unknown> {
  const resposta = await fetch(withBasePath(`${API}${caminho}`), {
    method: corpo === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: corpo === undefined ? undefined : { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = (await resposta.json().catch(() => ({}))) as Record<string, unknown>;
  if (!resposta.ok) {
    // 207 é sucesso (o corpo traz o resultado de cada linha) e não cai aqui.
    // Só chega neste ponto o lote que NÃO foi processado.
    const detalhe = dados.detail ?? dados.error ?? `HTTP ${resposta.status}`;
    throw new Error(typeof detalhe === "string" ? detalhe : JSON.stringify(detalhe));
  }
  return dados;
}

function dataCurta(valor: string | null): string {
  if (!valor) return "—";
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? valor : d.toLocaleDateString("pt-BR");
}

export function AtlasIntakeCenter() {
  const [cobertura, setCobertura] = useState<Cobertura[] | null>(null);
  const [total, setTotal] = useState(0);
  const [recusas, setRecusas] = useState<Recusa[]>([]);
  const [schemaVersion, setSchemaVersion] = useState("atlas.match.v1");
  const [erro, setErro] = useState<string | null>(null);
  const [relatorio, setRelatorio] = useState<Relatorio | null>(null);
  const [atualizado, setAtualizado] = useState<Date | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const [cob, rej, contrato] = await Promise.all([
        chamar("/coverage"),
        chamar("/rejections?limit=25"),
        chamar("/contract"),
      ]);
      const c = cob as { total: number; by_season: Cobertura[] };
      setCobertura(c.by_season ?? []);
      setTotal(c.total ?? 0);
      setRecusas(((rej as { rejections: Recusa[] }).rejections ?? []).slice(0, 25));
      setSchemaVersion(
        (contrato as { schema_version?: string }).schema_version ?? "atlas.match.v1",
      );
      setErro(null);
      setAtualizado(new Date());
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "indisponível");
      setCobertura((atual) => atual ?? []);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const enviar = useCallback(
    async (registros: unknown[], simular: boolean, marcador: string) => {
      setOcupado(marcador);
      setErro(null);
      try {
        const resposta = (await chamar(
          `/matches${simular ? "?simular=true" : ""}`,
          { matches: registros },
        )) as Relatorio;
        setRelatorio(resposta);
        if (!simular) await carregar();
      } catch (caught) {
        setErro(caught instanceof Error ? caught.message : "falhou");
      } finally {
        setOcupado(null);
      }
    },
    [carregar],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        icon={Database}
        title="Ingestão do Atlas"
        subtitle={`Contrato ${schemaVersion} · o Atlas aceita ou recusa; esta tela não valida nada por conta própria`}
        updated={atualizado}
        onRefresh={() => void carregar()}
      />

      {erro && <ErrorBanner>{erro}</ErrorBanner>}

      <CoberturaPainel total={total} linhas={cobertura} />

      <div className="grid gap-4 xl:grid-cols-2">
        <EnvioEmLote
          ocupado={ocupado}
          onEnviar={(registros, simular) =>
            enviar(registros, simular, simular ? "lote-simular" : "lote")
          }
        />
        <EnvioDeUmaLinha
          schemaVersion={schemaVersion}
          ocupado={ocupado}
          onEnviar={(registro, simular) =>
            enviar([registro], simular, simular ? "linha-simular" : "linha")
          }
        />
      </div>

      {relatorio && <RelatorioPainel relatorio={relatorio} />}

      <RecusasPainel recusas={recusas} />
    </div>
  );
}

function CoberturaPainel({
  total,
  linhas,
}: {
  total: number;
  linhas: Cobertura[] | null;
}) {
  return (
    <Card title="O que o Atlas tem">
      {linhas === null ? (
        <Empty>carregando…</Empty>
      ) : linhas.length === 0 ? (
        <Empty>
          Nenhuma partida ingerida ainda. A tabela nasce vazia de propósito: a
          leitura de diretório saiu, e o que estava no lake ainda não passou
          pelo contrato novo.
        </Empty>
      ) : (
        <>
          <p className="mb-3 text-2xl font-semibold tabular-nums">
            {total.toLocaleString("pt-BR")}{" "}
            <span className="text-sm font-normal text-muted-foreground">
              partidas
            </span>
          </p>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-muted/40 text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-3 py-2">Competição</th>
                  <th className="px-3 py-2">Temporada</th>
                  <th className="px-3 py-2 text-right">Partidas</th>
                  <th className="px-3 py-2">Primeira</th>
                  <th className="px-3 py-2">Última</th>
                  <th className="px-3 py-2 text-right">Fontes</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((linha) => (
                  <tr
                    key={`${linha.competition}/${linha.season}`}
                    className="border-t border-border"
                  >
                    <td className="px-3 py-1.5 font-mono">{linha.competition}</td>
                    <td className="px-3 py-1.5 font-mono">{linha.season}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {linha.matches.toLocaleString("pt-BR")}
                    </td>
                    <td className="px-3 py-1.5">{dataCurta(linha.first_match)}</td>
                    <td className="px-3 py-1.5">{dataCurta(linha.last_match)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {linha.sources}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

function EnvioEmLote({
  ocupado,
  onEnviar,
}: {
  ocupado: string | null;
  onEnviar: (registros: unknown[], simular: boolean) => void;
}) {
  const [nome, setNome] = useState<string | null>(null);
  const [registros, setRegistros] = useState<unknown[]>([]);
  const [ilegiveis, setIlegiveis] = useState(0);

  const ler = async (arquivo: File) => {
    const texto = await arquivo.text();
    const linhas = texto.split("\n").map((l) => l.trim()).filter(Boolean);
    const lidos: unknown[] = [];
    let quebradas = 0;
    for (const linha of linhas) {
      try {
        lidos.push(JSON.parse(linha));
      } catch {
        // Mandada assim mesmo: o Atlas recusa com "não é JSON válido" e a
        // linha aparece no relatório pelo número. Filtrar aqui esconderia
        // do operador que ela existe.
        quebradas += 1;
        lidos.push({ __linha_ilegivel__: linha.slice(0, 200) });
      }
    }
    setNome(arquivo.name);
    setRegistros(lidos);
    setIlegiveis(quebradas);
  };

  const trabalhando = ocupado === "lote" || ocupado === "lote-simular";

  return (
    <Card title="Envio em lote">
      <p className="mb-3 text-xs text-muted-foreground">
        Arquivo <code className="rounded bg-muted px-1">.jsonl</code>: um
        registro por linha. Cada linha é avaliada sozinha — uma errada não
        derruba as outras.
      </p>

      <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border bg-background/40 px-3 py-4 text-xs hover:bg-accent">
        <FileUp className="h-4 w-4 text-muted-foreground" />
        <span>{nome ?? "Escolher arquivo .jsonl"}</span>
        <input
          type="file"
          accept=".jsonl,.json,.txt"
          className="hidden"
          onChange={(evento) => {
            const arquivo = evento.target.files?.[0];
            if (arquivo) void ler(arquivo);
          }}
        />
      </label>

      {nome && (
        <p className="mt-2 text-xs text-muted-foreground">
          {registros.length} linha{registros.length === 1 ? "" : "s"} lida
          {registros.length === 1 ? "" : "s"}
          {ilegiveis > 0 && (
            <span className="text-amber-500">
              {" "}
              · {ilegiveis} não são JSON e serão recusadas pelo Atlas
            </span>
          )}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Botao
          onClick={() => onEnviar(registros, true)}
          desabilitado={registros.length === 0 || trabalhando}
          carregando={ocupado === "lote-simular"}
          icone={FlaskConical}
        >
          Simular
        </Botao>
        <Botao
          onClick={() => onEnviar(registros, false)}
          desabilitado={registros.length === 0 || trabalhando}
          carregando={ocupado === "lote"}
          icone={Upload}
          destaque
        >
          Ingerir
        </Botao>
      </div>
    </Card>
  );
}

function EnvioDeUmaLinha({
  schemaVersion,
  ocupado,
  onEnviar,
}: {
  schemaVersion: string;
  ocupado: string | null;
  onEnviar: (registro: unknown, simular: boolean) => void;
}) {
  const [valores, setValores] = useState<Record<string, string>>({});
  const trabalhando = ocupado === "linha" || ocupado === "linha-simular";

  const perfil = useMemo(() => lerPerfil(valores), [valores]);

  // Só os campos que o perfil declarado torna exigíveis. Contar os escondidos
  // faria a tela cobrar um bloco que a fonte disse não trazer.
  const faltando = useMemo(
    () =>
      BLOCOS.flatMap((b) => b.campos).filter(
        (campo) =>
          campo.tipo !== "blocos" &&
          campoPertenceAoPerfil(campo.caminho, perfil) &&
          !(valores[campo.caminho] ?? "").trim(),
      ).length,
    [valores, perfil],
  );

  const definir = (caminho: string) => (valor: string) =>
    setValores((atual) => ({ ...atual, [caminho]: valor }));

  return (
    <Card title="Envio de uma partida">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <p className="flex-1 text-xs text-muted-foreground">
          Todo campo de um bloco declarado é obrigatório — é o contrato, não a
          tela. Desmarcar um bloco não afrouxa nada: a contribuição fica
          guardada e a partida só entra no Atlas quando outra fonte trouxer o
          que falta.
        </p>
        <button
          onClick={() => setValores(valoresDeExemplo())}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11px] font-medium hover:bg-accent"
        >
          <RotateCcw className="h-3 w-3" /> Preencher com o exemplo
        </button>
      </div>

      <div className="max-h-[26rem] space-y-4 overflow-y-auto pr-1">
        {BLOCOS.map((bloco) => (
          <section key={bloco.chave}>
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-primary">
              {bloco.titulo}
            </h4>
            <p className="mb-2 mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {bloco.descricao}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {bloco.campos
                .filter((campo) => campoPertenceAoPerfil(campo.caminho, perfil))
                .map((campo) =>
                  campo.tipo === "blocos" ? (
                    <SeletorDeBlocos
                      key={campo.caminho}
                      campo={campo}
                      perfil={perfil}
                      onChange={definir(campo.caminho)}
                    />
                  ) : (
                    <CampoEntrada
                      key={campo.caminho}
                      campo={campo}
                      valor={valores[campo.caminho] ?? ""}
                      onChange={definir(campo.caminho)}
                    />
                  ),
                )}
            </div>
          </section>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Botao
          onClick={() => onEnviar(montarRegistro(valores, schemaVersion), true)}
          desabilitado={trabalhando}
          carregando={ocupado === "linha-simular"}
          icone={FlaskConical}
        >
          Simular
        </Botao>
        <Botao
          onClick={() => onEnviar(montarRegistro(valores, schemaVersion), false)}
          desabilitado={trabalhando}
          carregando={ocupado === "linha"}
          icone={PlusCircle}
          destaque
        >
          Ingerir
        </Botao>
        {/* Contagem, não bloqueio: quem manda incompleto recebe do Atlas a
            lista exata do que falta, com o nome do campo. Travar o botão
            esconderia essa resposta atrás de um palpite da tela. */}
        {faltando > 0 && (
          <span className="text-[11px] text-muted-foreground">
            {faltando} campo{faltando === 1 ? "" : "s"} em branco
          </span>
        )}
      </div>
    </Card>
  );
}

/** As caixas que dizem o que a fonte traz — e que governam o formulário. */
function SeletorDeBlocos({
  campo,
  perfil,
  onChange,
}: {
  campo: Campo;
  perfil: readonly string[];
  onChange: (valor: string) => void;
}) {
  function alternar(bloco: string) {
    const proximo = perfil.includes(bloco)
      ? perfil.filter((b) => b !== bloco)
      : [...perfil, bloco];
    onChange(proximo.join(","));
  }

  return (
    <div className="sm:col-span-2 text-[11px] text-muted-foreground">
      <span className="flex items-baseline gap-1">
        {campo.rotulo}
        <span className="text-red-400" aria-hidden>
          *
        </span>
      </span>
      <div className="mt-1 grid gap-1.5 sm:grid-cols-2">
        {BLOCOS_DO_CONTRATO.map((bloco) => {
          // `core` não se desmarca: sem ele a contribuição não sabe de que
          // partida está falando, e a única coisa que permitir desmarcá-lo
          // produziria é uma recusa evitável.
          const fixo = bloco === "core";
          return (
            <label
              key={bloco}
              className={cn(
                "flex items-start gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5",
                fixo && "opacity-70",
              )}
            >
              <input
                type="checkbox"
                checked={perfil.includes(bloco)}
                disabled={fixo}
                onChange={() => alternar(bloco)}
                className="mt-0.5"
              />
              <span>
                <span className="font-mono text-foreground">{bloco}</span>
                <span className="block text-[10px] text-muted-foreground/80">
                  {DESCRICAO_DO_BLOCO[bloco]}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      {campo.ajuda && (
        <span className="mt-1 block text-[10px] text-muted-foreground/80">
          {campo.ajuda}
        </span>
      )}
    </div>
  );
}

function CampoEntrada({
  campo,
  valor,
  onChange,
}: {
  campo: Campo;
  valor: string;
  onChange: (valor: string) => void;
}) {
  return (
    <label className="block text-[11px] text-muted-foreground">
      <span className="flex items-baseline gap-1">
        {campo.rotulo}
        <span className="text-red-400" aria-hidden>
          *
        </span>
      </span>
      <input
        value={valor}
        required
        inputMode={
          campo.tipo === "inteiro"
            ? "numeric"
            : campo.tipo === "decimal"
              ? "decimal"
              : undefined
        }
        placeholder={campo.placeholder}
        onChange={(evento) => onChange(evento.target.value)}
        className="mt-0.5 w-full rounded-lg border border-border bg-card px-2 py-1.5 font-mono text-xs text-foreground placeholder:text-muted-foreground/50"
      />
      {campo.ajuda && (
        <span className="mt-0.5 block text-[10px] text-muted-foreground/80">
          {campo.ajuda}
        </span>
      )}
    </label>
  );
}

function RelatorioPainel({ relatorio }: { relatorio: Relatorio }) {
  const recusadas = relatorio.lines.filter((linha) => !linha.accepted);
  const simulado = relatorio.simulated === true;

  return (
    <Card title={simulado ? "Simulação — nada foi gravado" : "Resultado da ingestão"}>
      <div className="grid gap-1px grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <Numero rotulo="enviados" valor={relatorio.submitted} />
        <Numero rotulo="aceitos" valor={relatorio.accepted} tom="bom" />
        {!simulado && <Numero rotulo="novos" valor={relatorio.added} />}
        {!simulado && <Numero rotulo="atualizados" valor={relatorio.replaced} />}
        {!simulado && (relatorio.pending ?? 0) > 0 && (
          <Numero
            rotulo="aguardando"
            valor={relatorio.pending ?? 0}
            nota="falta bloco"
          />
        )}
        <Numero rotulo="recusados" valor={relatorio.rejected} tom={relatorio.rejected ? "ruim" : undefined} />
        {!simulado && (
          <Numero
            rotulo="no Atlas"
            valor={relatorio.total_after}
            nota={`${relatorio.delta >= 0 ? "+" : ""}${relatorio.delta}`}
          />
        )}
      </div>

      {Object.keys(relatorio.missing_blocks ?? {}).length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            Blocos que faltam — o que buscar na próxima fonte
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(relatorio.missing_blocks ?? {}).map(([bloco, quantas]) => (
              <span
                key={bloco}
                className="rounded border border-amber-500/30 bg-amber-500/[0.06] px-2 py-0.5 font-mono text-[11px] text-amber-400"
              >
                {quantas}× {bloco}
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
            Estas contribuições foram gravadas e não foram recusadas. Elas ainda
            não são partidas: a composição espera outra fonte trazer o bloco que
            falta, e a ingestão que o trouxer completa a partida sem que nada do
            que já veio se perca.
          </p>
        </div>
      )}

      {Object.keys(relatorio.by_field).length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            Recusas por campo
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(relatorio.by_field).map(([campo, quantas]) => (
              <span
                key={campo}
                className="rounded border border-red-500/30 bg-red-500/[0.06] px-2 py-0.5 font-mono text-[11px] text-red-400"
              >
                {quantas}× {campo}
              </span>
            ))}
          </div>
        </div>
      )}

      {recusadas.length > 0 && (
        <div className="mt-4 space-y-1.5">
          <h4 className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Detalhe ({recusadas.length})
          </h4>
          <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {recusadas.map((linha) => (
              <div
                key={linha.index}
                className="rounded-lg border border-border bg-background/40 px-3 py-2"
              >
                <p className="flex items-center gap-1.5 text-xs">
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
                  <span className="font-mono text-muted-foreground">
                    linha {linha.index + 1}
                  </span>
                  <span>{linha.label}</span>
                </p>
                <ul className="mt-1 space-y-0.5 pl-5">
                  {linha.errors.map((erro, i) => (
                    <li key={i} className="text-[11px] text-muted-foreground">
                      <span className="font-mono text-foreground">{erro.field}</span>:{" "}
                      {erro.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {relatorio.rejected === 0 && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5" />
          {simulado
            ? "Todas as linhas passariam no contrato."
            : "Todas as linhas foram aceitas."}
        </p>
      )}
    </Card>
  );
}

function Numero({
  rotulo,
  valor,
  nota,
  tom,
}: {
  rotulo: string;
  valor: number;
  nota?: string;
  tom?: "bom" | "ruim";
}) {
  return (
    <div className="rounded-lg border border-border bg-background/40 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {rotulo}
      </p>
      <p
        className={cn(
          "text-lg font-semibold tabular-nums",
          tom === "bom" && "text-emerald-400",
          tom === "ruim" && "text-red-400",
        )}
      >
        {valor.toLocaleString("pt-BR")}
        {nota && (
          <span className="ml-1 text-[11px] font-normal text-muted-foreground">
            {nota}
          </span>
        )}
      </p>
    </div>
  );
}

function RecusasPainel({ recusas }: { recusas: Recusa[] }) {
  return (
    <Card title="Recusas recentes">
      <p className="mb-3 text-xs text-muted-foreground">
        Gravadas pelo Atlas, não só devolvidas. Quem enviou pode ter ignorado a
        resposta — sem isto, &ldquo;o Atlas não tem essa partida&rdquo;
        continuaria sendo mistério em vez de consulta.
      </p>
      {recusas.length === 0 ? (
        <Empty>Nenhuma recusa registrada.</Empty>
      ) : (
        <div className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
          {recusas.map((recusa, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-background/40 px-3 py-2 text-xs"
            >
              <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-muted-foreground">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                <span>{new Date(recusa.rejected_at).toLocaleString("pt-BR")}</span>
                <span className="rounded bg-muted px-1 font-mono text-[10px]">
                  {recusa.via}
                </span>
                <span>{recusa.by}</span>
                {recusa.source_match_id && (
                  <span className="font-mono text-[10px]">
                    {recusa.source_match_id}
                  </span>
                )}
              </p>
              <ul className="mt-1 space-y-0.5 pl-5">
                {(recusa.errors ?? []).map((erro, j) => (
                  <li key={j} className="text-[11px] text-muted-foreground">
                    <span className="font-mono text-foreground">{erro.field}</span>:{" "}
                    {erro.reason}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Botao({
  children,
  onClick,
  desabilitado,
  carregando,
  icone: Icone,
  destaque,
}: {
  children: React.ReactNode;
  onClick: () => void;
  desabilitado?: boolean;
  carregando?: boolean;
  icone: React.ComponentType<{ className?: string }>;
  destaque?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={desabilitado}
      className={cn(
        "ix-transition inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium disabled:opacity-50",
        destaque
          ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
          : "border-border bg-card hover:bg-accent",
      )}
    >
      {carregando ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Icone className="h-3.5 w-3.5" />
      )}
      {children}
    </button>
  );
}
