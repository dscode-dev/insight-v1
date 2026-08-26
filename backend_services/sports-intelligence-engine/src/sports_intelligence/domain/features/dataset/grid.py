"""A grade de cortes — a decisão mais cara deste PR, e a mais fácil de errar.

A PERGUNTA. Uma partida produz quantos `FeatureSnapshot`? A resposta define o
tamanho do dataset, o custo de construí-lo, e — silenciosamente — o que o motor
vai conseguir comparar em produção. Ela não é «quantos couberem».

O CRITÉRIO É A COMPARABILIDADE AO VIVO (§14 ao §39). Em produção o motor recebe
um estado ao vivo num minuto de relógio e pergunta «que estados históricos se
parecem com este?». Um corte histórico que não possa existir ao vivo é um corte
que nunca será consultado — e que, pior, entra na população que ajusta escalas e
define vizinhança. A grade é, portanto, o conjunto dos cortes que a produção
consegue reproduzir.

    PRE_MATCH                        1 corte
    FIRST_HALF   minutos 1..45      45 cortes
    SECOND_HALF  minutos 46..90     45 cortes
                                    ──────────
                                    91 cortes por partida

O QUE FICA DE FORA, E POR QUÊ (o catálogo de exclusões deste módulo):

    acréscimo (`45+2`)      o corpus não publica quantos minutos de acréscimo
                            houve, então `45+1` existe num jogo e não noutro —
                            e a grade deixaria de ser a MESMA entre partidas
    HALF_TIME               não é minuto de jogo: nenhum relógio ao vivo marca
                            «intervalo, minuto 3»
    FULL_TIME / pós-jogo    o placar final está lá dentro; um snapshot ali é
                            treinar com a resposta
    PENALTY_SHOOTOUT        não tem relógio de partida, e as features móveis
                            são todas definidas sobre minutos
    prorrogação sem prova   materializar 91..120 «por garantia» inventaria
                            estado para 97% dos jogos, que terminam aos 90

A PRORROGAÇÃO EXIGE PROVA CANÔNICA (§33). Ela entra na grade quando o corpus
DIZ que houve prorrogação — evento em período de prorrogação, ou `MatchResult`
com placar de prorrogação. Sem prova, não há prorrogação; com prova, os minutos
91..120 entram como os outros.

O CORTE INTRA-JOGO NÃO TEM `knowledge_cutoff`, E ISSO É DELIBERADO (§28, §29).
A tentação é `kickoff + minuto`: parece o instante de parede daquele minuto do
jogo, e é uma FABRICAÇÃO — ela ignora o intervalo, os acréscimos, as
interrupções, e erra por dez a vinte minutos exatamente nos jogos mais
irregulares. Um corte de conhecimento fabricado é pior que corte nenhum, porque
ele parece prova. A causalidade intra-jogo é sustentada pela POSIÇÃO
(`MatchTimePoint`), que o corpus publica de verdade.

O CORTE PRÉ-JOGO PODE TER INSTANTE, e o dele é real: o pontapé inicial
canônico. «Antes do apito» é uma afirmação de parede que o corpus sustenta, e
usá-la impede que uma cotação publicada depois do apito entre num snapshot
rotulado como pré-jogo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Self, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant, Period

#: O nome da política. Ele descreve o CRITÉRIO, e não o formato: «grade de
#: minuto» diria o que ela produz, e «comparável ao vivo» diz por que ela
#: produz isso — que é a parte que alguém precisa contestar para mudá-la.
LIVE_COMPARABLE_MINUTE_GRID_V1: Final[str] = "LIVE_COMPARABLE_MINUTE_GRID_V1"

#: Os limites do tempo regulamentar, em minutos de relógio.
FIRST_HALF_LAST_MINUTE: Final[int] = 45
SECOND_HALF_LAST_MINUTE: Final[int] = 90
#: A prorrogação, quando há prova dela.
EXTRA_TIME_FIRST_LAST_MINUTE: Final[int] = 105
EXTRA_TIME_SECOND_LAST_MINUTE: Final[int] = 120

#: Quantos cortes a grade padrão produz para uma partida sem prorrogação.
#: Ele é CONSTANTE de propósito — é a propriedade que faz duas partidas serem
#: comparáveis linha a linha.
REGULATION_GRID_SIZE: Final[int] = 91


@final
class GridExclusionReason(StrEnum):
    """Por que um corte concebível NÃO está na grade. Catálogo fechado (§30).

    ELE EXISTE PARA SER LIDO, e não para ser consumido por código: nenhuma
    linha materializada carrega estes motivos, porque as linhas excluídas não
    são materializadas. O catálogo é a resposta escrita a «por que o dataset
    não tem o minuto 45+2?», e o teste que o percorre garante que a resposta
    não se perde na primeira refatoração.
    """

    #: O acréscimo não é publicado como duração, então `45+1` existe em alguns
    #: jogos e não em outros. Uma grade com ele deixa de ser a mesma grade.
    STOPPAGE_TIME_NOT_UNIFORM = "STOPPAGE_TIME_NOT_UNIFORM"
    #: O intervalo não tem relógio de partida.
    HALF_TIME_HAS_NO_CLOCK = "HALF_TIME_HAS_NO_CLOCK"
    #: Depois do apito final o resultado é conhecido — snapshot ali é vazamento.
    POST_MATCH_KNOWS_THE_ANSWER = "POST_MATCH_KNOWS_THE_ANSWER"
    #: Pênaltis não têm minuto de jogo, e as janelas móveis são por minuto.
    SHOOTOUT_HAS_NO_MATCH_CLOCK = "SHOOTOUT_HAS_NO_MATCH_CLOCK"
    #: Prorrogação sem evidência no corpus seria estado inventado.
    EXTRA_TIME_WITHOUT_EVIDENCE = "EXTRA_TIME_WITHOUT_EVIDENCE"
    #: O minuto zero do primeiro tempo é o próprio `PRE_MATCH`; materializar os
    #: dois produziria duas linhas para o mesmo estado com chaves diferentes.
    MINUTE_ZERO_IS_PRE_MATCH = "MINUTE_ZERO_IS_PRE_MATCH"


@final
@dataclass(frozen=True, slots=True)
class GridExclusion:
    """Uma exclusão declarada: o que ficou de fora e por quê."""

    subject: str
    reason: GridExclusionReason

    def as_canonical(self) -> dict[str, object]:
        return {"reason": self.reason.value, "subject": self.subject}


#: O catálogo. Ele entra no manifesto — «o que não está aqui» é pergunta de
#: manifesto tanto quanto «o que está» (§101).
GRID_EXCLUSIONS_V1: Final[tuple[GridExclusion, ...]] = (
    GridExclusion("FIRST_HALF 45+n", GridExclusionReason.STOPPAGE_TIME_NOT_UNIFORM),
    GridExclusion("SECOND_HALF 90+n", GridExclusionReason.STOPPAGE_TIME_NOT_UNIFORM),
    GridExclusion("FIRST_HALF minuto 0", GridExclusionReason.MINUTE_ZERO_IS_PRE_MATCH),
    GridExclusion("HALF_TIME", GridExclusionReason.HALF_TIME_HAS_NO_CLOCK),
    GridExclusion("EXTRA_TIME_BREAK", GridExclusionReason.HALF_TIME_HAS_NO_CLOCK),
    GridExclusion("FULL_TIME", GridExclusionReason.POST_MATCH_KNOWS_THE_ANSWER),
    GridExclusion("PENALTY_SHOOTOUT", GridExclusionReason.SHOOTOUT_HAS_NO_MATCH_CLOCK),
    GridExclusion(
        "EXTRA_TIME_FIRST/SECOND sem prova canônica",
        GridExclusionReason.EXTRA_TIME_WITHOUT_EVIDENCE,
    ),
)


@final
class ExtraTimeRule(StrEnum):
    """O que fazer com a prorrogação. Catálogo fechado, e `ALWAYS` não existe.

    A AUSÊNCIA DE `ALWAYS` É A DECISÃO. Materializar 91..120 em toda partida
    produziria trinta linhas de estado inventado para cada jogo que terminou
    aos 90 — e elas entrariam na população que ajusta escalas.
    """

    #: Entra quando o corpus PROVA que houve prorrogação.
    ONLY_WITH_CANONICAL_EVIDENCE = "ONLY_WITH_CANONICAL_EVIDENCE"
    #: Nunca entra. Grade estritamente regulamentar.
    NEVER = "NEVER"


@final
class PreMatchCutoffRule(StrEnum):
    """De onde sai o instante de conhecimento do corte pré-jogo."""

    #: O pontapé canônico da partida — real, publicado, e o que «antes do
    #: apito» significa.
    CANONICAL_KICKOFF = "CANONICAL_KICKOFF"
    #: Sem instante. A causalidade fica só na posição.
    NONE = "NONE"


@final
@dataclass(frozen=True, slots=True)
class GridPoint:
    """Um corte da grade, com o lugar dele NA grade.

    `index` NÃO É DECORAÇÃO. Ele é a coordenada estável do corte dentro da
    partida — `0` é sempre o pré-jogo, `1` é sempre o minuto 1 —, e é por ele
    que duas partidas se alinham numa comparação coluna a coluna sem que
    ninguém precise reinterpretar `(período, minuto)`.
    """

    index: int
    as_of: FeatureAsOf
    label: str

    @property
    def period(self) -> Period:
        return self.as_of.position.period

    @property
    def minute(self) -> int:
        return self.as_of.position.minute


@final
@dataclass(frozen=True, slots=True)
class ExtraTimeEvidence:
    """A prova de que houve prorrogação — e de onde ela veio (§33).

    DUAS FONTES, E AS DUAS SÃO CANÔNICAS. Um evento carimbado num período de
    prorrogação prova que ela foi jogada; um `MatchResult` com placar de
    prorrogação prova o mesmo por outro caminho. Qualquer uma basta; nenhuma
    delas é inferida de `stage` nem de regulamento.
    """

    proven: bool
    source: str = ""

    @classmethod
    def none(cls) -> ExtraTimeEvidence:
        return cls(proven=False)


_PERIODOS_DE_PRORROGACAO: Final[frozenset[Period]] = frozenset(
    {Period.EXTRA_TIME_FIRST, Period.EXTRA_TIME_SECOND}
)


def extra_time_evidence(
    *,
    events: Iterable[CanonicalMatchEvent] = (),
    result: MatchResult | None = None,
) -> ExtraTimeEvidence:
    """A prova canônica de prorrogação, ou a ausência dela.

    A ORDEM DAS FONTES É DECLARADA para que a `source` seja determinística:
    duas execuções sobre os mesmos fatos precisam apontar a mesma prova, senão
    o manifesto muda sem que o conteúdo mude.
    """
    for evento in events:
        if evento.clock.period in _PERIODOS_DE_PRORROGACAO:
            return ExtraTimeEvidence(proven=True, source="CANONICAL_EVENT_IN_EXTRA_TIME")
    if result is not None and result.extra_time is not None:
        return ExtraTimeEvidence(proven=True, source="MATCH_RESULT_EXTRA_TIME_SCORE")
    return ExtraTimeEvidence.none()


def canonical_kickoff(match: Match) -> Instant:
    """O pontapé que vale para a grade E para a divisão (§41).

    UM SÓ, E DEFINIDO AQUI. `actual_kickoff` quando existe, `scheduled_kickoff`
    quando não. Se a grade usasse um e a divisão usasse o outro, uma partida
    adiada cairia numa metade e teria o corte pré-jogo carimbado na outra — e o
    vazamento seria por horário, que é o tipo que ninguém procura.
    """
    return match.actual_kickoff or match.scheduled_kickoff


@final
@dataclass(frozen=True, slots=True)
class SnapshotGridPolicy:
    """QUAIS cortes uma partida contribui ao dataset. Versionada e impressa.

    ELA É UM CONTRATO, e não uma configuração de execução. Duas construções sob
    grades diferentes produzem datasets que NÃO são comparáveis — um tem 91
    linhas por partida e o outro tem 19 —, e a impressão é o que impede que a
    diferença passe despercebida no manifesto.
    """

    name: str = LIVE_COMPARABLE_MINUTE_GRID_V1
    version: int = 1
    include_pre_match: bool = True
    first_half_last_minute: int = FIRST_HALF_LAST_MINUTE
    second_half_last_minute: int = SECOND_HALF_LAST_MINUTE
    extra_time: ExtraTimeRule = ExtraTimeRule.ONLY_WITH_CANONICAL_EVIDENCE
    pre_match_cutoff: PreMatchCutoffRule = PreMatchCutoffRule.CANONICAL_KICKOFF
    mode: TemporalMode = TemporalMode.AS_KNOWN

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de grade sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de grade inválida: {self.version}")
        if self.first_half_last_minute < 1:
            raise ValidationError(
                "primeiro tempo sem minuto nenhum: a grade não teria corte intra-jogo"
            )
        if self.second_half_last_minute <= self.first_half_last_minute:
            raise ValidationError(
                f"segundo tempo terminando em {self.second_half_last_minute} e primeiro "
                f"em {self.first_half_last_minute}: os minutos do segundo tempo continuam "
                "a contagem do primeiro, e inverter isso produziria grade vazia"
            )
        if self.mode is not TemporalMode.AS_KNOWN:
            raise ValidationError(
                f"grade em modo {self.mode.value}: a comparabilidade ao vivo exige "
                "AS_KNOWN, e qualquer outro modo produziria população que a produção "
                "nunca consegue reproduzir"
            )

    # -------------------------------------------------------------- forma --

    @property
    def regulation_size(self) -> int:
        """Quantos cortes uma partida sem prorrogação contribui."""
        return (1 if self.include_pre_match else 0) + self.second_half_last_minute

    def as_canonical(self) -> dict[str, object]:
        return {
            "exclusions": [e.as_canonical() for e in GRID_EXCLUSIONS_V1],
            "extra_time": self.extra_time.value,
            "first_half_last_minute": self.first_half_last_minute,
            "include_pre_match": self.include_pre_match,
            "mode": self.mode.value,
            "name": self.name,
            "pre_match_cutoff": self.pre_match_cutoff.value,
            "second_half_last_minute": self.second_half_last_minute,
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @classmethod
    def from_canonical(cls, forma: Mapping[str, Any]) -> Self:
        """A política de volta, da forma canônica que a versão guardou.

        NOME E VERSÃO NÃO BASTAM, e é por isso que este método existe. Uma
        reconstrução por `SnapshotGridPolicy(name=…, version=…)` traria os
        limites PADRÃO — e uma grade de cinco cortes voltaria com noventa e um.
        A impressão denunciaria, mas denunciar não é reconstruir: a versão
        precisa ser auto-descritiva, e a forma canônica é o que a descreve.

        AS EXCLUSÕES NÃO VOLTAM DAQUI. Elas são catálogo do módulo, e não
        parâmetro: uma versão que carregasse a própria lista de exclusões
        poderia declarar uma que o código não conhece.
        """
        return cls(
            name=str(forma["name"]),
            version=int(forma["version"]),
            include_pre_match=bool(forma["include_pre_match"]),
            first_half_last_minute=int(forma["first_half_last_minute"]),
            second_half_last_minute=int(forma["second_half_last_minute"]),
            extra_time=ExtraTimeRule(forma["extra_time"]),
            pre_match_cutoff=PreMatchCutoffRule(forma["pre_match_cutoff"]),
            mode=TemporalMode(forma["mode"]),
        )

    # -------------------------------------------------------------- grade --

    def points_for(
        self,
        match_id: MatchId,
        *,
        kickoff: Instant,
        extra_time: ExtraTimeEvidence | None = None,
    ) -> tuple[GridPoint, ...]:
        """Os cortes daquela partida, em ordem crescente de índice.

        A ORDEM É A DA PARTIDA e é a mesma da materialização: o pré-jogo, o
        primeiro tempo, o segundo, a prorrogação quando provada. Materializar
        fora de ordem quebraria a impressão de conteúdo, que é ordenada por
        construção.
        """
        prova = extra_time or ExtraTimeEvidence.none()
        pontos: list[GridPoint] = []
        indice = 0
        if self.include_pre_match:
            pontos.append(
                GridPoint(
                    index=indice,
                    as_of=FeatureAsOf.pre_match(
                        match_id,
                        mode=self.mode,
                        knowledge_cutoff=(
                            kickoff
                            if self.pre_match_cutoff is PreMatchCutoffRule.CANONICAL_KICKOFF
                            else None
                        ),
                    ),
                    label="PRE_MATCH",
                )
            )
            indice += 1

        for minuto in range(1, self.first_half_last_minute + 1):
            pontos.append(self._ponto(match_id, Period.FIRST_HALF, minuto, indice))
            indice += 1
        for minuto in range(self.first_half_last_minute + 1, self.second_half_last_minute + 1):
            pontos.append(self._ponto(match_id, Period.SECOND_HALF, minuto, indice))
            indice += 1

        if self.extra_time is ExtraTimeRule.ONLY_WITH_CANONICAL_EVIDENCE and prova.proven:
            for minuto in range(self.second_half_last_minute + 1, EXTRA_TIME_FIRST_LAST_MINUTE + 1):
                pontos.append(self._ponto(match_id, Period.EXTRA_TIME_FIRST, minuto, indice))
                indice += 1
            for minuto in range(
                EXTRA_TIME_FIRST_LAST_MINUTE + 1, EXTRA_TIME_SECOND_LAST_MINUTE + 1
            ):
                pontos.append(self._ponto(match_id, Period.EXTRA_TIME_SECOND, minuto, indice))
                indice += 1
        return tuple(pontos)

    def _ponto(self, match_id: MatchId, period: Period, minute: int, index: int) -> GridPoint:
        """Um corte intra-jogo. SEM `knowledge_cutoff` — ver o cabeçalho."""
        return GridPoint(
            index=index,
            as_of=FeatureAsOf.at(match_id, period, minute, mode=self.mode),
            label=f"{_SIGLA[period]}_{minute:03d}",
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.regulation_size} cortes)"


_SIGLA: Final[dict[Period, str]] = {
    Period.FIRST_HALF: "1H",
    Period.SECOND_HALF: "2H",
    Period.EXTRA_TIME_FIRST: "ET1",
    Period.EXTRA_TIME_SECOND: "ET2",
}

#: A grade de produção. Uma constante para que o caminho normal não construa
#: uma política nova a cada chamada — e para que o teste que confere a
#: impressão tenha um alvo estável.
DEFAULT_SNAPSHOT_GRID: Final[SnapshotGridPolicy] = SnapshotGridPolicy()


def grid_periods(policy: SnapshotGridPolicy) -> Sequence[Period]:
    """Os períodos que a grade pode produzir. Para as guardas e os testes."""
    periodos: list[Period] = []
    if policy.include_pre_match:
        periodos.append(Period.PRE_MATCH)
    periodos.extend((Period.FIRST_HALF, Period.SECOND_HALF))
    if policy.extra_time is ExtraTimeRule.ONLY_WITH_CANONICAL_EVIDENCE:
        periodos.extend((Period.EXTRA_TIME_FIRST, Period.EXTRA_TIME_SECOND))
    return tuple(periodos)
