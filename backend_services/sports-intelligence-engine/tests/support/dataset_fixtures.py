"""O cenário do PR-05.5.1 — um corpus pequeno com VÁRIAS partidas.

POR QUE CLONAR EM VEZ DE ESCREVER PARTIDAS NOVAS. O cenário da V2 tem uma
partida só, com eventos, escalações e cotações conferidos à mão; escrever cinco
partidas independentes duplicaria essa conferência cinco vezes e as cinco
divergiriam no primeiro ajuste. Aqui a MESMA história é reencenada sob
identidades diferentes e apitos diferentes — o que muda entre elas é
exatamente o que o dataset precisa distinguir: identidade, calendário e metade.

O APITO É O QUE SEPARA AS METADES. As partidas são espaçadas de sete em sete
dias, e a fronteira da divisão cai no meio: as primeiras vão para `REFERENCE`,
as últimas para `EVALUATION`. Uma fronteira que caísse fora produziria uma
metade vazia — e é um caso que o teste PEDE, não um que ele sofre.

AS COTAÇÕES ACOMPANHAM O APITO. Elas são carimbadas relativas ao pontapé de
CADA partida; deixá-las no instante da partida original faria o corte pré-jogo
— que usa o apito canônico como corte de conhecimento — recusar todas as
cotações de todas as partidas menos uma.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.features.dataset.split import (
    FeatureDatasetSplitPolicy,
)
from sports_intelligence.domain.features.state.builder import CanonicalMatchStateInput
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.temporal import Instant, instant
from tests.support.feature_fixtures import KICKOFF
from tests.support.v2_fixtures import FAMILIAS_V2, entrada_v2

#: A raiz das identidades do cenário. Ela é fixa para que os ids — e portanto a
#: ORDEM da varredura — sejam os mesmos em toda execução: a impressão de
#: conteúdo é ordenada, e um cenário com ids aleatórios teria impressão
#: diferente a cada rodada.
_RAIZ: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "insight.pr0551")

#: Quantas partidas o cenário pequeno tem.
PARTIDAS_DO_CENARIO: Final[int] = 6

#: O intervalo entre uma partida e a seguinte.
INTERVALO: Final[timedelta] = timedelta(days=7)

#: A fronteira da divisão. Ela cai depois da terceira partida: três em
#: `REFERENCE` e três em `EVALUATION`, contadas à mão.
FRONTEIRA: Final[Instant] = instant(datetime(2026, 4, 1, 0, 0, tzinfo=UTC))

#: Quantas partidas caem de cada lado sob `FRONTEIRA`. Conferidas à mão:
#: os apitos são 14/03, 21/03, 28/03, 04/04, 11/04 e 18/04 de 2026.
REFERENCIA_ESPERADA: Final[int] = 3
AVALIACAO_ESPERADA: Final[int] = 3

FAMILIAS: Final[frozenset[CoverageFamily]] = FAMILIAS_V2

VERSION_ID: Final[str] = "77777777-7777-4777-8777-777777777777"


def id_de_partida(indice: int) -> MatchId:
    return MatchId(uuid.uuid5(_RAIZ, f"partida-{indice:02d}"))


def apito_de(indice: int) -> Instant:
    return instant(KICKOFF + INTERVALO * indice)


def clonar(entrada: CanonicalMatchStateInput, indice: int) -> CanonicalMatchStateInput:
    """A mesma história sob outra identidade e outro apito.

    O DESLOCAMENTO É APLICADO A TUDO QUE TEM INSTANTE. Um clone que mudasse o
    apito e deixasse as cotações no lugar produziria mercado indisponível em
    cinco das seis partidas — e o teste passaria a medir o deslocamento em vez
    do dataset.
    """
    partida = id_de_partida(indice)
    apito = apito_de(indice)
    deslocamento = INTERVALO * indice
    raiz = partida.value

    eventos = tuple(
        replace(
            evento,
            id=uuid.uuid5(raiz, str(evento.id)),
            match_id=partida,
            supersedes=(
                None if evento.supersedes is None else uuid.uuid5(raiz, str(evento.supersedes))
            ),
            provenance=_deslocar_procedencia(evento.provenance, deslocamento),
        )
        for evento in entrada.candidate_events
    )
    escalacoes = tuple(replace(escalacao, match_id=partida) for escalacao in entrada.lineups)
    cotacoes = tuple(
        replace(
            cotacao,
            match_id=partida,
            observed_at=_deslocar(cotacao.observed_at, deslocamento),
            provenance=_deslocar_procedencia(cotacao.provenance, deslocamento),
        )
        for cotacao in entrada.odds
    )
    return CanonicalMatchStateInput(
        match=replace(entrada.match, id=partida, scheduled_kickoff=apito),
        competition_code=entrada.competition_code,
        season_label=entrada.season_label,
        published_families=entrada.published_families,
        candidate_events=eventos,
        lineups=escalacoes,
        odds=cotacoes,
        result=entrada.result,
        knowledge=entrada.knowledge,
    )


def _deslocar_procedencia(procedencia: DataProvenance, deslocamento: timedelta) -> DataProvenance:
    """Desloca os carimbos de conhecimento junto com o apito.

    SEM ISTO A CAUSALIDADE MENTIRIA. O corte pré-jogo usa o apito canônico como
    limite de conhecimento; um fato carimbado no apito da PRIMEIRA partida
    seria «do passado» para todas as outras, e o cenário testaria uma
    causalidade que não é a de nenhuma delas.

    OS QUATRO CARIMBOS ANDAM JUNTOS, e é obrigatório: `ObservationTimes` exige
    `occurred_at <= observed_at <= received_at <= ingested_at`, e deslocar um só
    quebraria a ordem — com uma mensagem sobre fuso mal lido, que é o defeito
    que a guarda existe para pegar e não o que estaria acontecendo.
    """
    tempos = procedencia.times
    return replace(
        procedencia,
        times=replace(
            tempos,
            occurred_at=instant(tempos.occurred_at + deslocamento),
            observed_at=instant(tempos.observed_at + deslocamento),
            received_at=instant(tempos.received_at + deslocamento),
            ingested_at=instant(tempos.ingested_at + deslocamento),
        ),
    )


def _deslocar(momento: Instant | None, deslocamento: timedelta) -> Instant | None:
    """O instante deslocado, ou `None` quando ele não existe.

    `None` CONTINUA `None`: uma cotação sem carimbo de observação é um fato
    sobre a fonte, e inventar um instante para ela faria o cenário provar uma
    causalidade que o corpus não sustenta.
    """
    return None if momento is None else instant(momento + deslocamento)


def corpus_do_cenario(
    *, partidas: int = PARTIDAS_DO_CENARIO
) -> dict[MatchId, CanonicalMatchStateInput]:
    """As `n` partidas do cenário, prontas para a fonte de estado."""
    base = entrada_v2()
    return {id_de_partida(indice): clonar(base, indice) for indice in range(partidas)}


def origem_do_cenario(*, families: frozenset[CoverageFamily] = FAMILIAS) -> CorpusSource:
    from sports_intelligence.domain.datasets.content import ContentHash
    from sports_intelligence.domain.shared.versioning import DatasetVersion

    return CorpusSource(
        version_id=VERSION_ID,
        version=DatasetVersion(major=1, minor=0),
        corpus_fingerprint=ContentHash("b" * 64),
        published_families=families,
    )


def divisao(*, fronteira: Instant = FRONTEIRA) -> FeatureDatasetSplitPolicy:
    return FeatureDatasetSplitPolicy(reference_end_exclusive=fronteira)


def grade() -> SnapshotGridPolicy:
    return DEFAULT_SNAPSHOT_GRID
