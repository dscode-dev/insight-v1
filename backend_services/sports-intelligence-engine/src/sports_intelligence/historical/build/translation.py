"""A tradução entre a saída fundida e os contratos canônicos — campo a campo.

POR QUE ELA É UM MÓDULO E NÃO UM `**kwargs`. `Match(**fused_fields)` aceita
qualquer chave que a fusão tenha produzido e silencia a que ela não produziu;
o agregado canônico passa a ser desenhado pelo mapeamento de fonte, e uma
coluna renomeada num CSV vira uma mudança no domínio.

Aqui cada papel semântico é lido POR NOME, convertido POR TIPO, e a falha de
conversão vira `None` — nunca zero, nunca um default plausível (§44).

O QUE A V1 NÃO CONSEGUE LER, e é declarado em vez de inventado:

    prorrogação e pênaltis   não há papel semântico para eles. `ScoreFacts`
                             sai só com tempo normal, e os outros dois escopos
                             ficam `None` — que é «não sabemos», e não «não
                             houve» (§34)
    escalação                nenhum papel carrega lista de jogadores
    eventos                  idem, e por isso não há construtor de eventos
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from sports_intelligence.domain.build.facts import ScoreFacts
from sports_intelligence.domain.fusion.models import (
    ODDS_OBSERVATION_KIND,
    Observation,
    ObservationSet,
)
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate
from sports_intelligence.domain.odds.models import BookmakerRef, OddsSelection
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.sources.semantics import SemanticRole

#: Quantos segmentos o discriminante de odds da fusão tem, e onde a casa está.
#: O formato vem do PR-03.2 e é `1X2|{casa}|{papel=valor}|...`.
_SEGMENTO_DA_CASA: Final[int] = 1
_MINIMO_DE_SEGMENTOS: Final[int] = 3

#: Que seleção do mercado 1X2 cada papel de odds carrega. Uma tabela porque a
#: correspondência é do CONTRATO — e um `if` por papel espalhado divergiria.
ODDS_ROLE_SELECTION: Final[dict[SemanticRole, OddsSelection]] = {
    SemanticRole.ODDS_HOME: OddsSelection.HOME,
    SemanticRole.ODDS_DRAW: OddsSelection.DRAW,
    SemanticRole.ODDS_AWAY: OddsSelection.AWAY,
}


def read_score_facts(candidate: FusedMatchCandidate) -> ScoreFacts:
    """O placar do candidato, com ausência preservada.

    UM CAMPO EM CONFLITO NÃO RESOLVIDO LÊ COMO AUSENTE, e é o comportamento
    certo: `selected_value is None` significa que a fusão não escolheu, e
    escolher aqui seria tomar por conta a decisão que ela recusou tomar (§45).
    Quem transforma isso em recusa de build é a política — este módulo só não
    mente sobre o que leu.
    """
    return ScoreFacts(
        regular_home=_inteiro(candidate, SemanticRole.HOME_SCORE),
        regular_away=_inteiro(candidate, SemanticRole.AWAY_SCORE),
        # OS OUTROS DOIS ESCOPOS FICAM `None` PORQUE NÃO HÁ COMO LÊ-LOS.
        # `SemanticRole` não tem papel para prorrogação nem para pênaltis, e
        # derivá-los do placar de tempo normal produziria um jogo decidido em
        # 90 minutos onde houve prorrogação — ou o contrário (§34).
        extra_home=None,
        extra_away=None,
        penalties_home=None,
        penalties_away=None,
    )


def odds_observations_of(candidate: FusedMatchCandidate) -> ObservationSet | None:
    """O conjunto de odds do candidato, ou `None` quando não há.

    `None` E NÃO UM CONJUNTO VAZIO: «a fonte não trabalha com odds» e «a fonte
    trabalha e não trouxe nenhuma para esta partida» são coisas diferentes, e
    um conjunto vazio as apagaria na mesma linha de relatório.
    """
    conjunto = next(
        (c for c in candidate.observation_sets if c.kind == ODDS_OBSERVATION_KIND),
        None,
    )
    if conjunto is None or not len(conjunto):
        return None
    return conjunto


def _inteiro(candidate: FusedMatchCandidate, role: SemanticRole) -> int | None:
    """O valor inteiro de um papel, ou `None`.

    `None` COBRE TRÊS CASOS DIFERENTES — campo ausente, conflito não resolvido
    e texto que não converte — e todos os três significam a mesma coisa para
    quem constrói: não sabemos. O que os distingue é o `QualityIssue` que o
    avaliador já emitiu, e é lá que a distinção é útil.
    """
    campo = candidate.field(role.value)
    if campo is None or campo.selected_value is None:
        return None
    try:
        return int(Decimal(campo.selected_value.strip()))
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def bookmaker_of(observation: Observation) -> BookmakerRef | None:
    """A casa de apostas de uma observação fundida.

    ELA VEM DO DISCRIMINANTE, e não de `values` — porque é lá que ela está. O
    PR-03.2 fixou o discriminante como `1X2|{casa}|{papel=valor}|...` e deixou
    em `values` só as cotações; a casa é o que DISTINGUE uma observação das
    outras do conjunto, e por isso vive na chave.

    LER `values[BOOKMAKER_NAME]` PRIMEIRO é deliberado e hoje não encontra
    nada: se um dia o contrato fundido passar a carregar a casa como valor,
    este módulo já a prefere, e o dia em que o discriminante mudar de formato
    não vira uma família de odds silenciosamente vazia.

    `None` QUANDO NÃO DÁ PARA SABER. Sem casa, duas cotações seriam a mesma
    coisa e uma sumiria como duplicata — que é exatamente o defeito que o
    PR-03.1 mediu e corrigiu (§43).
    """
    declarada = observation.values.get(SemanticRole.BOOKMAKER_NAME.value)
    if declarada is not None and declarada.strip():
        return _casa(declarada)
    partes = observation.discriminator.split("|")
    if len(partes) < _MINIMO_DE_SEGMENTOS:
        return None
    return _casa(partes[_SEGMENTO_DA_CASA])


def _casa(raw: str) -> BookmakerRef | None:
    """O slug da casa, ou `None` quando o texto não vira um.

    `BookmakerRef` EXIGE MINÚSCULAS, DÍGITOS E UNDERSCORE (PR-01). `William
    Hill` vira `william_hill`; um texto que nem assim converte devolve `None`
    em vez de derrubar a família inteira — uma casa ilegível é uma observação
    perdida, e não um corpus perdido.
    """
    normalizada = "_".join(raw.strip().lower().split())
    if not normalizada:
        return None
    try:
        return BookmakerRef(normalizada)
    except (ValidationError, ValueError):
        return None


def decimal_odds_of(raw: str) -> Decimal | None:
    """Uma cotação decimal, ou `None` quando o texto não é uma.

    `Decimal` E NÃO `float`, como no PR-01: cotações vêm como texto decimal e
    serão comparadas e agrupadas; `float` introduz ruído de representação que
    aparece quando duas casas cotam o mesmo preço e a comparação diz que não.
    """
    try:
        valor = Decimal(raw.strip())
    except (ArithmeticError, InvalidOperation, ValueError):
        return None
    return valor if valor > Decimal(1) else None
