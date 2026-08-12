// Os campos de atlas.match.v1, na ordem em que uma pessoa os preenche.
//
// POR QUE ESTA LISTA EXISTE AQUI. O contrato de verdade vive no Atlas
// (`atlas/intake/contract.py`) e é ele quem aceita ou recusa — nada nesta
// tela valida coisa alguma. O que esta lista carrega é o que o servidor não
// tem como mandar: o rótulo em português, o placeholder com um valor real, e
// a ordem que faz o formulário ser preenchível por um humano.
//
// A CONSEQUÊNCIA DE DIVERGIR É PEQUENA E VISÍVEL, e isso é de propósito: um
// campo que exista aqui e não no contrato é recusado pelo Atlas com
// "campo não faz parte do contrato"; um que exista lá e não aqui é recusado
// com "campo obrigatório ausente". Nos dois casos o operador vê o nome exato
// do campo e o motivo — nunca um formulário que grava silenciosamente errado.

export type CampoTipo = "texto" | "inteiro" | "decimal" | "datahora" | "blocos";

/** Os blocos de `atlas.match.v1`, na ordem em que o contrato os lista. */
export const BLOCOS_DO_CONTRATO = [
  "core",
  "result_halftime",
  "market_close",
  "market_open",
  "market_spread",
  "market_totals",
  "market_handicap",
  "stats",
] as const;

export type BlocoDoContrato = (typeof BLOCOS_DO_CONTRATO)[number];

/** Rótulo e o que cada bloco cobre, para a pessoa marcar sabendo o que marca. */
export const DESCRICAO_DO_BLOCO: Record<BlocoDoContrato, string> = {
  core: "quem jogou, quando e quanto foi — obrigatório, é o que identifica a partida",
  result_halftime: "placar do intervalo (os arquivos sul-americanos não o publicam)",
  market_close: "cotações de fechamento, no apito inicial",
  market_open: "cotações de abertura — a diferença para o fechamento é o movimento de linha",
  market_spread: "média do mercado e melhor preço — a diferença é quanto as casas discordam",
  market_totals: "mercado de total de gols, a pergunta da lente `gols` respondida pelo mercado",
  market_handicap: "handicap asiático — a diferença de gols que o mercado espera",
  stats: "chutes, escanteios, faltas e cartões",
};

/**
 * O campo deve aparecer, dado o que a fonte declarou trazer.
 *
 * `market.bookmaker` fica sob as DUAS metades de propósito: a casa de aposta
 * identifica de quem são as cotações, e uma fonte que traga só a abertura
 * ainda precisa dizer de quem ela é.
 */
export function campoPertenceAoPerfil(
  caminho: string,
  perfil: readonly string[],
): boolean {
  if (caminho.startsWith("stats.")) return perfil.includes("stats");
  if (caminho === "market.bookmaker") {
    return perfil.includes("market_close") || perfil.includes("market_open");
  }
  if (caminho.startsWith("market.closing.")) return perfil.includes("market_close");
  if (caminho.startsWith("market.opening.")) return perfil.includes("market_open");
  if (caminho.startsWith("market.spread.")) return perfil.includes("market_spread");
  if (caminho.startsWith("market.totals.")) return perfil.includes("market_totals");
  if (caminho.startsWith("market.handicap.")) return perfil.includes("market_handicap");
  if (caminho.endsWith("_goals_halftime")) return perfil.includes("result_halftime");
  // identity, result e provenance formam o núcleo, sempre exigido.
  return true;
}

export interface Campo {
  /** Caminho dentro do JSON, como o Atlas o nomeia nas recusas. */
  caminho: string;
  rotulo: string;
  tipo: CampoTipo;
  placeholder: string;
  /** Explicação curta, só onde o nome do campo não basta. */
  ajuda?: string;
}

export interface Bloco {
  chave: string;
  titulo: string;
  descricao: string;
  campos: Campo[];
}

const LADOS = [
  { chave: "home", nome: "mandante" },
  { chave: "away", nome: "visitante" },
] as const;

function estatisticasDoLado(lado: "home" | "away", nome: string): Campo[] {
  return [
    { caminho: `stats.${lado}.shots`, rotulo: `Chutes (${nome})`, tipo: "inteiro", placeholder: "14" },
    { caminho: `stats.${lado}.shots_on_target`, rotulo: `Chutes no alvo (${nome})`, tipo: "inteiro", placeholder: "6", ajuda: "não pode ser maior que o total de chutes" },
    { caminho: `stats.${lado}.corners`, rotulo: `Escanteios (${nome})`, tipo: "inteiro", placeholder: "7" },
    { caminho: `stats.${lado}.fouls`, rotulo: `Faltas (${nome})`, tipo: "inteiro", placeholder: "9" },
    { caminho: `stats.${lado}.yellow_cards`, rotulo: `Cartões amarelos (${nome})`, tipo: "inteiro", placeholder: "1" },
    { caminho: `stats.${lado}.red_cards`, rotulo: `Cartões vermelhos (${nome})`, tipo: "inteiro", placeholder: "0" },
  ];
}

export const BLOCOS: Bloco[] = [
  {
    chave: "identity",
    titulo: "Identidade",
    descricao:
      "É isto que faz uma partida ser aquela partida. O Atlas deriva daqui a chave da linha — nunca do id da fonte, porque três fontes descrevendo o mesmo jogo têm três ids e o jogo é um só.",
    campos: [
      { caminho: "identity.competition", rotulo: "Competição", tipo: "texto", placeholder: "premier_league", ajuda: "minúsculas e underscore" },
      { caminho: "identity.season", rotulo: "Temporada", tipo: "texto", placeholder: "2023-2024", ajuda: "2024 ou 2023-2024" },
      { caminho: "identity.home_club_id", rotulo: "Clube mandante", tipo: "texto", placeholder: "arsenal", ajuda: "club_id do registro, não o nome de exibição" },
      { caminho: "identity.away_club_id", rotulo: "Clube visitante", tipo: "texto", placeholder: "chelsea" },
      { caminho: "identity.kickoff_utc", rotulo: "Início (UTC)", tipo: "datahora", placeholder: "2023-08-12T15:00:00Z", ajuda: "com fuso explícito; o dia entra na identidade" },
    ],
  },
  {
    chave: "result",
    titulo: "Resultado",
    descricao: "Só partida encerrada. Uma partida agendada não tem placar, e guardá-la como histórico poria um 0-0 em toda linha de base.",
    campos: [
      { caminho: "result.status", rotulo: "Situação", tipo: "texto", placeholder: "finished", ajuda: "único valor aceito" },
      { caminho: "result.home_goals", rotulo: "Gols do mandante", tipo: "inteiro", placeholder: "2" },
      { caminho: "result.away_goals", rotulo: "Gols do visitante", tipo: "inteiro", placeholder: "1" },
      { caminho: "result.home_goals_halftime", rotulo: "Gols do mandante no 1º tempo", tipo: "inteiro", placeholder: "1" },
      { caminho: "result.away_goals_halftime", rotulo: "Gols do visitante no 1º tempo", tipo: "inteiro", placeholder: "0" },
    ],
  },
  {
    chave: "market",
    titulo: "Mercado",
    descricao:
      "Abertura e fechamento, os dois: a diferença entre eles é o que o mercado aprendeu até a bola rolar, e um retrato só não expressa isso. Os três blocos abaixo do 1x2 são colunas que o arquivo do football-data já traz e o Atlas ignorava — de 106 colunas baixadas, 29 eram lidas.",
    campos: [
      { caminho: "market.bookmaker", rotulo: "Casa de apostas", tipo: "texto", placeholder: "bet365" },
      { caminho: "market.opening.home", rotulo: "Abertura · mandante", tipo: "decimal", placeholder: "2.10" },
      { caminho: "market.opening.draw", rotulo: "Abertura · empate", tipo: "decimal", placeholder: "3.40" },
      { caminho: "market.opening.away", rotulo: "Abertura · visitante", tipo: "decimal", placeholder: "3.75" },
      { caminho: "market.closing.home", rotulo: "Fechamento · mandante", tipo: "decimal", placeholder: "1.95" },
      { caminho: "market.closing.draw", rotulo: "Fechamento · empate", tipo: "decimal", placeholder: "3.50" },
      { caminho: "market.closing.away", rotulo: "Fechamento · visitante", tipo: "decimal", placeholder: "4.00" },
      {
        caminho: "market.spread.consensus.home",
        rotulo: "Média do mercado · mandante",
        tipo: "decimal",
        placeholder: "1.98",
        ajuda: "coluna AvgC* do football-data",
      },
      { caminho: "market.spread.consensus.draw", rotulo: "Média do mercado · empate", tipo: "decimal", placeholder: "3.55" },
      { caminho: "market.spread.consensus.away", rotulo: "Média do mercado · visitante", tipo: "decimal", placeholder: "3.90" },
      {
        caminho: "market.spread.best.home",
        rotulo: "Melhor preço · mandante",
        tipo: "decimal",
        placeholder: "2.05",
        ajuda:
          "coluna MaxC*. Precisa ser >= a média em cada saída; a soma das três probabilidades cai abaixo de 1,0 em quase metade das partidas, e isso é normal — é arbitragem entre casas.",
      },
      { caminho: "market.spread.best.draw", rotulo: "Melhor preço · empate", tipo: "decimal", placeholder: "3.70" },
      { caminho: "market.spread.best.away", rotulo: "Melhor preço · visitante", tipo: "decimal", placeholder: "4.10" },
      {
        caminho: "market.totals.line",
        rotulo: "Total de gols · linha",
        tipo: "decimal",
        placeholder: "2.5",
        ajuda: "lida do arquivo, nunca suposta",
      },
      { caminho: "market.totals.over", rotulo: "Total de gols · acima", tipo: "decimal", placeholder: "1.85" },
      { caminho: "market.totals.under", rotulo: "Total de gols · abaixo", tipo: "decimal", placeholder: "1.95" },
      {
        caminho: "market.handicap.line",
        rotulo: "Handicap asiático · linha",
        tipo: "decimal",
        placeholder: "-0.25",
        ajuda: "sinal na direção do mandante: negativo é mandante favorito. Zero é uma linha legítima.",
      },
      { caminho: "market.handicap.home", rotulo: "Handicap · mandante", tipo: "decimal", placeholder: "1.92" },
      { caminho: "market.handicap.away", rotulo: "Handicap · visitante", tipo: "decimal", placeholder: "1.98" },
    ],
  },
  {
    chave: "stats",
    titulo: "Estatística",
    descricao:
      "Entram como histórico do clube, nunca como fato da partida sendo consultada — usar os chutes do próprio jogo para descrevê-lo seria vazamento.",
    campos: [
      ...estatisticasDoLado("home", LADOS[0].nome),
      ...estatisticasDoLado("away", LADOS[1].nome),
    ],
  },
  {
    chave: "provenance",
    titulo: "Procedência",
    descricao:
      "Declarada, nunca deduzida. O leitor antigo tirava a fonte do caminho do arquivo, então mover um arquivo mudava quem constava como tendo coletado — e é a fonte que decide qual número vence quando duas discordam de um placar.",
    campos: [
      { caminho: "provenance.source", rotulo: "Fonte", tipo: "texto", placeholder: "football_data" },
      { caminho: "provenance.source_match_id", rotulo: "Id da partida na fonte", tipo: "texto", placeholder: "fd-2324-E0-0000" },
      { caminho: "provenance.collected_at", rotulo: "Coletado em", tipo: "datahora", placeholder: "2026-08-11T00:00:00Z" },
      { caminho: "provenance.url", rotulo: "URL de origem", tipo: "texto", placeholder: "https://www.football-data.co.uk/mmz4281/2324/E0.csv" },
      {
        caminho: "provenance.timezone",
        rotulo: "Fuso em que a fonte publica",
        tipo: "texto",
        placeholder: "Europe/London",
        ajuda:
          "Nome IANA, sem padrão. O football-data publica todos os arquivos em hora do Reino Unido, inclusive os sul-americanos, e não escreve isso em lugar nenhum: lidas como UTC, 210 de 1.785 partidas brasileiras caíam no dia seguinte — e o dia entra na identidade da partida.",
      },
      {
        caminho: "provenance.profile",
        rotulo: "Blocos que esta fonte traz",
        tipo: "blocos",
        placeholder: BLOCOS_DO_CONTRATO.join(","),
        ajuda:
          "Marque só o que a fonte de fato traz. Declarar um bloco e não trazê-lo é recusado; trazer sem declarar também. Os blocos desmarcados somem do formulário e ficam para outra fonte completar.",
      },
    ],
  },
];

export const TODOS_OS_CAMPOS: Campo[] = BLOCOS.flatMap((bloco) => bloco.campos);

/** `{"identity.competition": "premier_league"}` → `{identity:{competition:…}}`. */
export function montarRegistro(
  valores: Record<string, string>,
  schemaVersion: string,
): Record<string, unknown> {
  const saida: Record<string, unknown> = { schema_version: schemaVersion };
  const perfil = lerPerfil(valores);
  for (const campo of TODOS_OS_CAMPOS) {
    // Um bloco não declarado não é mandado vazio: mandá-lo assim seria
    // "trouxe sem declarar", que o Atlas recusa — e recusaria com razão,
    // porque a composição usa o perfil para saber o que ainda procurar.
    if (!campoPertenceAoPerfil(campo.caminho, perfil)) continue;

    if (campo.tipo === "blocos") {
      const alvoProv = (saida.provenance ??= {}) as Record<string, unknown>;
      alvoProv.profile = perfil;
      continue;
    }

    const bruto = (valores[campo.caminho] ?? "").trim();
    const partes = campo.caminho.split(".");
    let alvo = saida;
    for (const parte of partes.slice(0, -1)) {
      if (typeof alvo[parte] !== "object" || alvo[parte] === null) {
        alvo[parte] = {};
      }
      alvo = alvo[parte] as Record<string, unknown>;
    }
    const folha = partes[partes.length - 1]!;
    // Vazio vai como string vazia, e NÃO é omitido. Omitir faria o Atlas
    // responder "campo obrigatório ausente" para algo que a pessoa vê
    // preenchido na tela; mandando vazio, a recusa fala do valor, que é
    // onde ela vai olhar.
    if (bruto === "") {
      alvo[folha] = "";
      continue;
    }
    alvo[folha] =
      campo.tipo === "inteiro" || campo.tipo === "decimal"
        ? Number(bruto)
        : bruto;
  }
  return saida;
}

/**
 * Os blocos marcados no formulário. `core` entra sempre, marcado ou não —
 * uma contribuição sem núcleo não sabe de que partida está falando, e deixar
 * a pessoa desmarcá-lo só produziria uma recusa evitável.
 */
export function lerPerfil(valores: Record<string, string>): BlocoDoContrato[] {
  const marcados = new Set(
    (valores["provenance.profile"] ?? "")
      .split(",")
      .map((b) => b.trim())
      .filter(Boolean),
  );
  marcados.add("core");
  return BLOCOS_DO_CONTRATO.filter((bloco) => marcados.has(bloco));
}

/** Preenche o formulário com os placeholders — o exemplo que passa. */
export function valoresDeExemplo(): Record<string, string> {
  const saida: Record<string, string> = {};
  for (const campo of TODOS_OS_CAMPOS) {
    saida[campo.caminho] = campo.placeholder;
  }
  return saida;
}
