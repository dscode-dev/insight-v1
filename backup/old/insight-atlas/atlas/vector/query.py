"""atlas.query.v1 — perguntar ao Atlas, e o que ele responde.

DESCRITIVO, NUNCA PREDITIVO. Toda resposta daqui é uma frase sobre o que
aconteceu em partidas parecidas — "entre os 25 jogos mais próximos, 48%
terminaram em vitória do mandante". Nenhuma é uma frase sobre esta partida.
A diferença não é de estilo: um número que descreve o passado tem como ser
conferido, e um que prevê o futuro não.

A ESCALA VIAJA JUNTO COM O SCORE. A resposta carrega a mediana de similaridade
entre pares SORTEADOS AO ACASO no mesmo espaço. Sem isso, um 0,78 é um número
sem régua — e foi exatamente assim que 0,886 foi reportado como bom resultado
quando o par mediano já dava 0,807. Quem lê a resposta recebe o que precisa
para saber se 0,78 é perto.

A INCERTEZA É NOMEADA. Não um percentual solto: quais dimensões da lente não
puderam ser preenchidas e quantos vizinhos sobraram depois dos filtros. Foi a
peça mais bem feita do Atlas antigo e é a única que atravessou a reconstrução
sem mudar de ideia.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from atlas.vector.lenses import NAO_DESCREVEM_DESFECHO, Categoria, Lente, lente
from atlas.vector.validation import Medida, nao_medida

SCHEMA = "atlas.query.v1"

#: Quantos vizinhos compõem a descrição. 25 e não 5: medido contra o corpus,
#: o ganho sobre a taxa base em K=5 é +5,5% com margem de 4,9% — real, mas
#: no limite. Em K=25 é +6,5% com a mesma margem. A vizinhança ampla descreve
#: melhor do que o vizinho individual, e a resposta deve usar a que descreve.
VIZINHOS = 25

#: Abaixo disto a descrição é sobre poucos jogos demais para significar algo,
#: e a resposta diz isso em vez de calcular médias de três partidas.
MINIMO_VIZINHOS = 5

#: Fração mínima do peso da lente que precisa estar presente para a resposta
#: descrever alguma coisa.
#:
#: 0,60 é a barra abaixo da qual a lente está olhando outra coisa, e não uma
#: versão mais fraca da mesma coisa.
#:
#: MEDIDO numa partida real do Brasileirão, onde faltam estatística, abertura,
#: over/under e handicap: `resultado` fica com 0,846 e responde; `gols` fica
#: com 0,563 e não responde.
#:
#: `gols` PERDER A AMÉRICA DO SUL AQUI É O RESULTADO CERTO, e não um efeito
#: colateral a corrigir baixando a barra: a régua mede essa lente em -5,8%
#: sobre a taxa base do Brasileirão, ou seja, conclusivamente pior que
#: responder o desfecho mais comum. Os dois portões concordam, por caminhos
#: independentes.
#:
#: (Este comentário já disse "63,6% no pior caso" — número calculado antes de
#: `implied_over_2_5` entrar em `gols`, e falso desde então. Fica registrado
#: porque um número velho aqui é exatamente o tipo de afirmação que o resto
#: deste serviço existe para não deixar passar.)
PESO_MINIMO = 0.60


@dataclass(frozen=True)
class Consulta:
    """O que se pergunta. Estruturado, e o mesmo para as cinco categorias."""

    categoria: Categoria
    competition: str
    season: str
    home_club_id: str
    away_club_id: str
    #: Instante de referência. Só entram vizinhos ANTERIORES a ele — o
    #: Atlas descreve com o que já havia acontecido, nunca com o que veio
    #: depois.
    as_of: datetime
    #: Features conhecidas da partida consultada. As que faltarem entram
    #: como a média do corpus, que padroniza para zero: "não informa nada".
    features: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def from_dict(dados: dict[str, Any]) -> Consulta:
        faltando = [
            campo
            for campo in ("categoria", "competition", "season", "home_club_id", "away_club_id")
            if not str(dados.get(campo) or "").strip()
        ]
        if faltando:
            raise ValueError(f"campos obrigatórios ausentes: {', '.join(faltando)}")
        bruto = dados.get("as_of")
        momento = (
            datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
            if bruto
            else datetime.now(timezone.utc)
        )
        if momento.tzinfo is None:
            raise ValueError("as_of precisa de fuso horário explícito")
        return Consulta(
            categoria=str(dados["categoria"]),  # type: ignore[arg-type]
            competition=str(dados["competition"]),
            season=str(dados["season"]),
            home_club_id=str(dados["home_club_id"]),
            away_club_id=str(dados["away_club_id"]),
            as_of=momento.astimezone(timezone.utc),
            features={
                str(k): float(v)
                for k, v in (dados.get("features") or {}).items()
                if isinstance(v, (int, float))
            },
        )


@dataclass(frozen=True)
class Vizinho:
    uid: str
    competition: str
    season: str
    kickoff: datetime
    home: str
    away: str
    label: str
    similaridade: float
    features: dict[str, float]


def _cosseno_com_pesos(
    consulta: dict[str, float],
    vizinho: dict[str, float],
    lente_: Lente,
    espaco,
) -> float:
    """Similaridade só sobre as dimensões da lente, ponderadas.

    Padroniza cada dimensão pelo espaço gravado antes de comparar — as mesmas
    constantes com que o corpus foi codificado. Comparar um valor cru com um
    padronizado dá um número plausível sobre réguas diferentes.
    """
    indices = {nome: i for i, nome in enumerate(espaco.dimensoes)}
    a: list[float] = []
    b: list[float] = []
    for nome, peso in lente_.pesos.items():
        indice = indices.get(nome)
        if indice is None:
            continue
        media, desvio = espaco.medias[indice], espaco.desvios[indice]
        raiz = math.sqrt(peso)
        a.append(raiz * (consulta.get(nome, media) - media) / desvio)
        b.append(raiz * (vizinho.get(nome, media) - media) / desvio)

    norma_a = math.sqrt(sum(v * v for v in a))
    norma_b = math.sqrt(sum(v * v for v in b))
    if norma_a <= 1e-12 or norma_b <= 1e-12:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norma_a * norma_b)


def descrever(
    consulta: Consulta,
    candidatos: Sequence[Vizinho],
    espaco,
    escala_mediana: float,
    medida: Medida | None = None,
) -> dict[str, Any]:
    """Monta a resposta: vizinhança, descrição, evidência e incerteza."""
    lente_ = lente(consulta.categoria)
    vizinhos = list(candidatos[:VIZINHOS])

    ausentes = [
        nome for nome in lente_.pesos if nome not in consulta.features
    ]
    # QUANTO DA LENTE SOBROU. Contar dimensões ausentes trata `implied_home`
    # (peso 1,0) e `rest_advantage` (peso 0,2) como perdas iguais, e elas não
    # são. O que importa é a fração do peso que ainda participa: uma partida
    # do Brasileirão perde 6 das 12 dimensões de `gols`, mas 36,4% do peso —
    # e é esse número que diz se a resposta ainda descreve alguma coisa.
    peso_total = sum(lente_.pesos.values())
    peso_ausente = sum(lente_.pesos[nome] for nome in ausentes)
    peso_util = (peso_total - peso_ausente) / peso_total if peso_total else 0.0
    resposta: dict[str, Any] = {
        "schema_version": SCHEMA,
        "categoria": lente_.categoria,
        "pergunta": lente_.pergunta,
        "descreve": lente_.descreve,
        # A medição desta lente NESTA competição viaja na resposta. Uma
        # descrição que erra mais que a taxa base tem a MESMA forma de uma
        # que acerta — quem lê não tem como distinguir, então a resposta
        # precisa dizer. E o número é por competição porque a validade nunca
        # foi propriedade da lente: `resultado` mede +10,9% na Europa e
        # -4,8% no Brasileirão, e um número só mentiria sobre um dos dois.
        "validacao": (
            medida.as_dict()
            if medida is not None
            else nao_medida(lente_.categoria, consulta.competition)
        ),
        "as_of": consulta.as_of.isoformat(),
        "consulta": {
            "competition": consulta.competition,
            "season": consulta.season,
            "home_club_id": consulta.home_club_id,
            "away_club_id": consulta.away_club_id,
        },
        "vizinhanca": {
            "encontrados": len(vizinhos),
            "pedidos": VIZINHOS,
            "dimensoes_usadas": [n for n in lente_.pesos if n not in ausentes],
            "dimensoes_ausentes": ausentes,
            # Fica na resposta mesmo quando é 1,0: um campo que só aparece
            # quando há problema ensina quem lê a não procurá-lo.
            "peso_util": round(peso_util, 3),
            "filtros": list(lente_.filtros),
        },
    }

    if peso_util < PESO_MINIMO:
        # A lente não tem com que olhar. Devolver a distribuição de desfechos
        # assim mesmo daria uma resposta com a forma de uma boa, calculada
        # sobre as poucas dimensões que sobraram — que é o modo de falha que
        # esta reconstrução inteira existe para eliminar.
        resposta["descricao"] = None
        resposta["evidencia"] = []
        resposta["incerteza"] = {
            "score": 1.0,
            "motivo": (
                f"esta lente perdeu {round(100 * (1 - peso_util))}% do seu peso "
                f"por falta de dimensão nesta partida; o mínimo para descrever "
                f"é {round(100 * PESO_MINIMO)}%"
            ),
            "dimensoes_ausentes": ausentes,
        }
        return resposta

    if len(vizinhos) < MINIMO_VIZINHOS:
        # Sem base, a resposta é dizer que não há base. Uma média de três
        # jogos apresentada como descrição é pior que silêncio, porque tem
        # a mesma forma de uma resposta boa.
        resposta["descricao"] = None
        resposta["evidencia"] = []
        resposta["incerteza"] = {
            "score": 1.0,
            "motivo": (
                f"apenas {len(vizinhos)} partidas parecidas encontradas; "
                f"o mínimo para descrever é {MINIMO_VIZINHOS}"
            ),
            "dimensoes_ausentes": ausentes,
        }
        return resposta

    similaridades = [v.similaridade for v in vizinhos]
    resposta["vizinhanca"]["similaridade"] = {
        "maior": round(max(similaridades), 4),
        "mediana": round(statistics.median(similaridades), 4),
        "menor": round(min(similaridades), 4),
    }
    # A régua, ao lado do número. Sem ela "0,78" não tem escala.
    resposta["vizinhanca"]["escala"] = {
        "mediana_entre_pares_aleatorios": round(escala_mediana, 4),
        "leitura": (
            "duas partidas sorteadas ao acaso neste espaço ficam nesta "
            "mediana; a similaridade acima só é alta em relação a ela"
        ),
    }

    # MEDIDA CONCLUSIVAMENTE PIOR QUE A TAXA BASE NÃO DESCREVE DESFECHO.
    #
    # Não é o mesmo que "não demonstrada". Uma lente aqui foi medida e ficou
    # ABAIXO de simplesmente responder o resultado mais comum da competição —
    # `gols` e `contexto` estão nesse estado sobre o corpus atual. Servir a
    # distribuição de desfechos assim mesmo entregaria um número que a régua
    # já sabe ser pior que o palpite trivial, com a forma de uma descrição
    # boa. A vizinhança continua na resposta: ela é observável e verdadeira;
    # o que fica retido é a leitura de desfecho em cima dela.
    #
    # `confronto` não entra aqui porque nunca descreveu desfecho — ela
    # devolve o retrospecto, e isso continua valendo.
    if (
        medida is not None
        and medida.pior_que_a_base
        and lente_.categoria not in NAO_DESCREVEM_DESFECHO
    ):
        resposta["descricao"] = None
        resposta["evidencia"] = [
            {
                "uid": v.uid,
                "competition": v.competition,
                "season": v.season,
                "kickoff_utc": v.kickoff.isoformat(),
                "home_club_id": v.home,
                "away_club_id": v.away,
                "desfecho": v.label,
                "similaridade": round(v.similaridade, 4),
            }
            for v in vizinhos[:8]
        ]
        resposta["incerteza"] = {
            "score": 1.0,
            "motivo": (
                f"a régua mediu esta lente em {consulta.competition} e ela "
                f"descreve {abs(medida.ganho):.1%} PIOR que responder o "
                f"desfecho mais comum; os vizinhos continuam listados, a "
                f"leitura de desfecho não"
            ).replace(".", ",", 1),
            "dimensoes_ausentes": ausentes,
        }
        return resposta

    resposta["descricao"] = _descricao(lente_.categoria, vizinhos)
    resposta["evidencia"] = [
        {
            "uid": v.uid,
            "competition": v.competition,
            "season": v.season,
            "kickoff_utc": v.kickoff.isoformat(),
            "home_club_id": v.home,
            "away_club_id": v.away,
            "desfecho": v.label,
            "similaridade": round(v.similaridade, 4),
        }
        for v in vizinhos[:8]
    ]

    # Incerteza: quanto da lente não pôde ser preenchido, e quão rasa ficou
    # a vizinhança. Os dois erodem a descrição por motivos diferentes, e o
    # leitor precisa saber qual dos dois aconteceu.
    fracao_ausente = len(ausentes) / max(1, len(lente_.pesos))
    fracao_rasa = 1.0 - min(1.0, len(vizinhos) / VIZINHOS)
    resposta["incerteza"] = {
        "score": round(min(1.0, 0.6 * fracao_ausente + 0.4 * fracao_rasa), 4),
        "dimensoes_ausentes": ausentes,
        "motivo": _motivo(ausentes, len(vizinhos)),
    }
    return resposta


def _motivo(ausentes: list[str], quantos: int) -> str:
    partes = []
    if ausentes:
        partes.append(
            f"{len(ausentes)} dimensão(ões) da lente sem valor informado "
            f"({', '.join(ausentes[:4])}{'…' if len(ausentes) > 4 else ''})"
        )
    if quantos < VIZINHOS:
        partes.append(f"apenas {quantos} vizinhos de {VIZINHOS} pedidos")
    return "; ".join(partes) or "lente completa e vizinhança cheia"


def _descricao(categoria: str, vizinhos: Sequence[Vizinho]) -> dict[str, Any]:
    """O que os vizinhos fizeram — no passado, sempre no passado."""
    total = len(vizinhos)
    if categoria == "gols":
        gols = [
            v.features.get("expected_goals_total", 0.0) for v in vizinhos
        ]
        return {
            "media_de_gols_esperada_pelos_vizinhos": round(
                sum(gols) / total, 2
            ),
            "nota": (
                "média do perfil ofensivo dos vizinhos antes de cada jogo, "
                "não do placar que saiu"
            ),
        }

    if categoria == "desempenho_time":
        def media(nome: str) -> float:
            return round(
                sum(v.features.get(nome, 0.0) for v in vizinhos) / total, 3
            )

        return {
            "mandante": {
                "forma": media("home_form"),
                "chutes_por_jogo": media("home_shots_rate"),
                "precisao": media("home_accuracy"),
                "cartoes_por_jogo": media("home_discipline"),
            },
            "visitante": {
                "forma": media("away_form"),
                "chutes_por_jogo": media("away_shots_rate"),
                "precisao": media("away_accuracy"),
                "cartoes_por_jogo": media("away_discipline"),
            },
        }

    if categoria == "confronto":
        # REGISTRO, e não descrição. Medido, votar o desfecho aqui acerta 8,2
        # pontos ABAIXO de chutar o resultado mais comum — o retrospecto de
        # dois clubes é amostra pequena e não descreve o próximo jogo. Então
        # esta resposta devolve o fato e diz onde ele para.
        contagem = {"HOME_WIN": 0, "DRAW": 0, "AWAY_WIN": 0}
        for v in vizinhos:
            if v.label in contagem:
                contagem[v.label] += 1
        datas = sorted(v.kickoff for v in vizinhos)
        return {
            "encontros": total,
            "retrospecto": {
                "vitorias_do_mandante_atual": contagem["HOME_WIN"],
                "empates": contagem["DRAW"],
                "vitorias_do_visitante_atual": contagem["AWAY_WIN"],
            },
            "periodo": {
                "de": datas[0].date().isoformat(),
                "ate": datas[-1].date().isoformat(),
            },
            "nota": (
                f"registro dos {total} encontros entre os dois clubes. "
                "NÃO é uma descrição da partida consultada: medido, ler este "
                "retrospecto como tendência acerta 8,2 pontos abaixo de "
                "simplesmente chutar o desfecho mais comum"
            ),
        }

    # resultado e contexto descrevem o desfecho — o que muda entre elas é
    # QUAIS partidas entraram na vizinhança.
    contagem = {"HOME_WIN": 0, "DRAW": 0, "AWAY_WIN": 0}
    for v in vizinhos:
        if v.label in contagem:
            contagem[v.label] += 1
    return {
        "desfechos": {
            chave: {"partidas": valor, "fracao": round(valor / total, 3)}
            for chave, valor in contagem.items()
        },
        "nota": (
            f"entre as {total} partidas mais parecidas segundo esta lente; "
            "descreve o que aconteceu, não o que vai acontecer"
        ),
    }
