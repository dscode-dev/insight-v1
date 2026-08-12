"""Como várias fontes viram uma partida só.

    contribuições de N fontes  →  um documento  →  atlas.match_record

POR QUE COMPOR EM VEZ DE SOBRESCREVER. Nenhuma fonte pública traz uma partida
completa. O CSV do football-data para o Brasileirão traz placar e mercado de
fechamento e não traz um chute sequer; uma raspagem traz chutes e não traz
mercado. Escrever a partida direto, como era, faria a segunda ingestão apagar
o bloco da primeira — sem erro, sem log, com a linha parecendo completa.

O QUE TORNA ISSO SEGURO É A IDENTIDADE, e ela foi medida antes de o código
existir: as 1.899 partidas de Brasileirão que temos do ESPN encontram todas as
1.899 contrapartidas no CSV público, no mesmo dia UTC. Duas fontes
independentes, acordo total. Antes de converter o fuso do CSV — que é hora do
Reino Unido, não UTC — 210 delas caíam no dia errado e teriam virado partidas
separadas.

DAÍ A REGRA: uma fonte nova só entra depois de provar alinhamento contra uma
que já temos. É barato de fazer e é o que separa cruzar dados de misturá-los.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: Os blocos que uma fonte pode trazer. Um registro declara quais traz, e tem
#: de estar completo PARA ELES — ausência vira afirmação, nunca esquecimento.
#:
#: `result_halftime` é um bloco separado e não parte do núcleo porque os
#: arquivos sul-americanos não publicam o placar do intervalo, e exigi-lo no
#: núcleo recusaria 11.830 partidas por um dado que NENHUMA das 25 dimensões
#: do vetor usa. Ele fica — as ligas europeias o têm, e a virada do segundo
#: tempo é um sinal descritivo que ainda pode virar dimensão — mas fica onde
#: sua ausência custa só ele mesmo.
BLOCOS = (
    "core",
    "result_halftime",
    "market_close",
    "market_open",
    # As três metades a mais do mercado, separadas porque a disponibilidade
    # delas é separada: `market_spread` existe em 100% de TODAS as
    # competições que temos; `market_totals` e `market_handicap` existem em
    # 100% dos arquivos europeus e em 0% dos sul-americanos.
    "market_spread",
    "market_totals",
    "market_handicap",
    "stats",
)

#: Que caminho do contrato cada bloco ocupa. Vários blocos podem dividir a
#: mesma chave: `core` e `result_halftime` vivem os dois em `result`, como as
#: duas metades do mercado vivem em `market`.
CAMINHOS: dict[str, tuple[str, ...]] = {
    "core": ("identity", "result", "provenance"),
    "result_halftime": ("result",),
    "market_close": ("market",),
    "market_open": ("market",),
    "market_spread": ("market",),
    "market_totals": ("market",),
    "market_handicap": ("market",),
    "stats": ("stats",),
}

#: Ordem de precedência: quem vence quando duas fontes discordam de um FATO.
#:
#: Descendente de quanta revisão um número recebeu antes de ser publicado.
#: StatsBomb é dado de evento curado à mão; football_data é um arquivo mantido
#: há duas décadas; espn é placar de tempo real, corrigido rápido e raramente
#: auditado depois; wikipedia é editada por qualquer um.
#:
#: DECLARADA, e não aprendida. Uma precedência ajustada por qual fonte acerta
#: mais no corpus atual seria uma regra que muda quando o corpus muda — e a
#: pergunta "de quem é este placar" precisa ter a mesma resposta amanhã.
PRECEDENCIA: tuple[str, ...] = (
    "statsbomb",
    "football_data",
    "openfootball",
    "espn",
    "wikipedia",
)

#: Fatos que têm UM valor verdadeiro. Duas fontes discordando aqui significa
#: que uma está errada, e isso é registrado.
#:
#: Mercado e estatística ficam de fora de propósito: duas casas de aposta com
#: cotações diferentes não estão em desacordo — estão medindo coisas
#: diferentes. Tratar isso como conflito encheria a tabela de ruído e
#: esconderia o desacordo que importa.
FATOS_UNICOS: tuple[str, ...] = (
    "result.home_goals",
    "result.away_goals",
    "result.home_goals_halftime",
    "result.away_goals_halftime",
    "identity.kickoff_utc",
)


#: Os blocos que uma partida precisa ter para ENTRAR NO CORPUS, por
#: competição. É a barra que separa `match_contribution` de `match_record`.
#:
#: POR QUE NÃO É UMA BARRA SÓ. Nenhuma fonte pública publica chutes,
#: escanteios ou cartões históricos do Brasileirão ou do futebol argentino, e
#: os arquivos que existem trazem só cotação de fechamento. Uma barra única
#: nos quatro blocos não deixa essas 11.830 partidas mais completas — deixa o
#: Atlas sem elas, respondendo só sobre a Europa.
#:
#: O QUE ISSO CUSTA, MEDIDO POR LENTE. Sem estatística e sem abertura, o peso
#: que sobrevive é: confronto 100%, resultado 92,5%, desempenho_time 66,7%,
#: contexto 66,7%, gols 63,6%. As duas lentes conclusivas quase não dependem
#: do que falta.
#:
#: O QUE TORNA ISSO HONESTO é o construtor OMITIR a dimensão que não pode
#: calcular, em vez de gravar 0,0. Zero chutes não é "não sei", é "quase
#: nenhum" — e faria toda partida brasileira parecer parecida entre si por um
#: motivo que não existe. Omitida, a dimensão não entra no cosseno nem na
#: norma, e a resposta lista o que faltou.
#:
#: DECLARADA por competição, e não deduzida do que costuma chegar: uma barra
#: que se ajusta ao que a fonte manda aceita silenciosamente a próxima fonte
#: que empobrecer.
EXIGENCIA_PADRAO: tuple[str, ...] = ("core", "market_close", "market_open", "stats")

EXIGENCIA_POR_COMPETICAO: dict[str, tuple[str, ...]] = {
    # América do Sul: só existe cotação de fechamento em fonte pública, e
    # estatística de partida não existe em nenhuma. `result_halftime` também
    # não é publicado.
    "brasileirao": ("core", "market_close"),
    "argentina_liga_profesional": ("core", "market_close"),
    "argentina_copa_liga_profesional": ("core", "market_close"),
}


def exigencia(competicao: str) -> tuple[str, ...]:
    """Os blocos que esta competição precisa para virar linha do Atlas."""
    return EXIGENCIA_POR_COMPETICAO.get(competicao, EXIGENCIA_PADRAO)


@dataclass(frozen=True)
class Contribuicao:
    """O que uma fonte disse sobre uma partida."""

    source: str
    profile: tuple[str, ...]
    document: dict[str, Any]

    @property
    def posicao(self) -> int:
        """Onde a fonte está na precedência. Desconhecida vai para o fim —
        nunca ganha de uma fonte declarada, mas ainda contribui blocos que
        ninguém mais trouxe."""
        try:
            return PRECEDENCIA.index(self.source)
        except ValueError:
            return len(PRECEDENCIA)


@dataclass(frozen=True)
class Conflito:
    field: str
    winning_source: str
    winning_value: Any
    losing_source: str
    losing_value: Any

    def __str__(self) -> str:
        return (
            f"{self.field}: {self.winning_source}={self.winning_value!r} "
            f"venceu {self.losing_source}={self.losing_value!r}"
        )


@dataclass
class Composicao:
    document: dict[str, Any]
    #: bloco → fonte que o forneceu. É a resposta para "de onde veio isto".
    origem: dict[str, str] = field(default_factory=dict)
    conflitos: list[Conflito] = field(default_factory=list)
    fontes: tuple[str, ...] = ()

    @property
    def perfil(self) -> tuple[str, ...]:
        """Os blocos que a composição REALMENTE tem, somados de todas as
        fontes. Pode ser maior que o de qualquer contribuição isolada — que é
        o ponto de compor."""
        return tuple(b for b in BLOCOS if b in self.origem)


def _ler(documento: dict[str, Any], caminho: str) -> Any:
    alvo: Any = documento
    for parte in caminho.split("."):
        if not isinstance(alvo, dict) or parte not in alvo:
            return None
        alvo = alvo[parte]
    return alvo


def perfil_de(documento: dict[str, Any]) -> tuple[str, ...]:
    """Que blocos um documento traz, olhando o que ele preencheu.

    Deduzido e não declarado pelo remetente, de propósito: um perfil digitado
    pode dizer `stats` sobre um documento sem estatística, e aí a composição
    acreditaria numa contribuição vazia e não procuraria a de verdade.
    """
    presentes: list[str] = []
    resultado = documento.get("result")
    if isinstance(documento.get("identity"), dict) and isinstance(resultado, dict):
        presentes.append("core")
    if isinstance(resultado, dict) and resultado.get("home_goals_halftime") is not None:
        presentes.append("result_halftime")
    mercado = documento.get("market")
    if isinstance(mercado, dict):
        if isinstance(mercado.get("closing"), dict):
            presentes.append("market_close")
        if isinstance(mercado.get("opening"), dict):
            presentes.append("market_open")
        if isinstance(mercado.get("spread"), dict):
            presentes.append("market_spread")
        if isinstance(mercado.get("totals"), dict):
            presentes.append("market_totals")
        if isinstance(mercado.get("handicap"), dict):
            presentes.append("market_handicap")
    if isinstance(documento.get("stats"), dict):
        presentes.append("stats")
    return tuple(b for b in BLOCOS if b in presentes)


def compor(contribuicoes: Iterable[Contribuicao]) -> Composicao | None:
    """Junta as contribuições de uma partida num documento só.

    A ordem é por precedência: a fonte mais confiável escreve primeiro, e as
    seguintes só preenchem o que ainda está vazio. Assim uma fonte de baixa
    precedência contribui o bloco que ninguém trouxe sem sobrescrever o que
    uma fonte melhor já disse.
    """
    ordenadas: Sequence[Contribuicao] = sorted(
        contribuicoes, key=lambda c: (c.posicao, c.source)
    )
    if not ordenadas:
        return None

    documento: dict[str, Any] = {}
    origem: dict[str, str] = {}
    dono_do_campo: dict[str, tuple[str, Any]] = {}
    conflitos: list[Conflito] = []

    for contribuicao in ordenadas:
        for bloco in perfil_de(contribuicao.document):
            if bloco in origem:
                continue
            for chave in CAMINHOS[bloco]:
                valor = contribuicao.document.get(chave)
                if valor is None:
                    continue
                if isinstance(valor, dict) and isinstance(documento.get(chave), dict):
                    # Blocos que dividem uma chave (`core` e `result_halftime`
                    # em `result`, as duas metades do mercado em `market`).
                    # Quem chega depois preenche só o que falta, em vez de
                    # trocar o objeto inteiro e levar junto o que já estava.
                    documento[chave] = {**valor, **documento[chave]}
                else:
                    documento[chave] = valor
            origem[bloco] = contribuicao.source

        # Desacordo sobre um fato: registrado mesmo quando o bloco já foi
        # preenchido por outra fonte — é justamente aí que ele aparece.
        for campo in FATOS_UNICOS:
            valor = _ler(contribuicao.document, campo)
            if valor is None:
                continue
            anterior = dono_do_campo.get(campo)
            if anterior is None:
                dono_do_campo[campo] = (contribuicao.source, valor)
            elif anterior[1] != valor:
                conflitos.append(
                    Conflito(
                        field=campo,
                        winning_source=anterior[0],
                        winning_value=anterior[1],
                        losing_source=contribuicao.source,
                        losing_value=valor,
                    )
                )

    if "core" not in origem:
        # Sem identidade não há partida a compor. Nenhuma fonte de mercado ou
        # estatística sabe sozinha de que jogo está falando.
        return None

    # A procedência da composição é a da fonte que venceu o núcleo — é ela
    # que respondeu quem jogou e quanto foi.
    documento.setdefault("schema_version", ordenadas[0].document.get("schema_version"))

    # O perfil declarado na procedência composta é o da COMPOSIÇÃO, não o da
    # fonte que venceu o núcleo. Sem isto o documento sai inconsistente
    # consigo mesmo — traria a estatística de outra fonte declarando não
    # trazê-la — e seria recusado pelo próprio contrato que o gerou.
    procedencia = documento.get("provenance")
    if isinstance(procedencia, dict):
        documento["provenance"] = {
            **procedencia,
            "profile": [b for b in BLOCOS if b in origem],
        }

    return Composicao(
        document=documento,
        origem=origem,
        conflitos=conflitos,
        fontes=tuple(c.source for c in ordenadas),
    )
