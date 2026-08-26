"""O contrato temporal do motor de features — e a distinção que ele existe para
carregar.

    EffectiveTime   ≠   KnowledgeTime

`EffectiveTime` é QUANDO O FATO PERTENCE À REALIDADE ESPORTIVA: o gol aconteceu
aos 63:21. `KnowledgeTime` é QUANDO AQUELE FATO PODERIA LEGITIMAMENTE SER
CONHECIDO pelo sistema: o provedor publicou 63:22, e a correção chegou 64:10.

POR QUE ISSO NÃO É PREZIOSISMO. Uma feature histórica que só existe para ser
comparada com uma partida ao vivo precisa ter sido calculada com a informação
que estaria disponível AO VIVO naquele minuto. Se o replay histórico aplica,
aos 63:30, uma correção que só ficou conhecida às 64:10, ele produz um estado
que nenhuma partida ao vivo jamais terá — e o modelo aprende a comparar com um
mundo que não existe.

    HistoricalState_t  ~  InformationThatWouldHaveBeenAvailableLive_t
    HistoricalState_t  ≠  RetrospectiveFinalTruth_t

O RELÓGIO DA PARTIDA NÃO É UM INTEIRO (§7, §8, §9). `minute: int` como
contrato temporal global confunde `45+3` com `48`, e confunde o minuto 45 do
primeiro tempo com o do segundo. O que existe aqui é uma POSIÇÃO — fase,
minuto, acréscimo e desempate — porque é isso que ordena fatos de futebol.

DUAS RÉGUAS, E ELAS NÃO SE CONVERTEM UMA NA OUTRA. A posição na partida ordena
o que aconteceu DENTRO do jogo; o instante de parede ordena o que se soube
FORA dele — a cotação vista às 20:47, a escalação publicada uma hora antes. Um
`as-of` pode declarar as duas, e um fato é elegível pela régua que ele de fato
tem. Converter uma na outra exigiria saber o instante exato de cada minuto de
jogo, incluindo paralisações — e o corpus não sabe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.canonical import instant_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant, MatchClock, Period


@final
class TemporalMode(StrEnum):
    """Sob qual verdade o estado é reconstruído (§28).

    AS DUAS SÃO LEGÍTIMAS E RESPONDEM PERGUNTAS DIFERENTES:

        AS_KNOWN          «o que se sabia aos 63 minutos»
        CANONICAL_FINAL   «o que hoje sabemos que era verdade aos 63 minutos»

    A primeira é a única que serve para gerar feature comparável com partida ao
    vivo. A segunda serve para auditoria e análise retrospectiva — e usá-la
    para treinar ou comparar seria dar ao histórico um privilégio que o presente
    nunca tem.
    """

    AS_KNOWN = "AS_KNOWN"
    CANONICAL_FINAL = "CANONICAL_FINAL"

    @property
    def is_causal(self) -> bool:
        """Se este modo exige causalidade de CONHECIMENTO.

        `CANONICAL_FINAL` continua respeitando a causalidade de OCORRÊNCIA — um
        gol aos 80 não entra num estado de 63 em modo nenhum. O que ele
        dispensa é a prova de quando aquilo foi sabido.
        """
        return self is TemporalMode.AS_KNOWN


#: O desempate de uma posição que não o declara. Ele é o MAIOR inteiro da
#: prática, e não zero: um corte «até o minuto 63» inclui TODOS os eventos do
#: minuto 63, e só um corte com sequência declarada exclui os que vierem depois
#: dela dentro do mesmo relógio (§71).
SEM_DESEMPATE: Final[int] = 1_000_000_000


@final
@dataclass(frozen=True, slots=True, order=True)
class MatchTimePoint:
    """Uma posição DENTRO da partida, com ordem total (§10).

    A ORDEM É `(fase, minuto, acréscimo, desempate)` e ela vem de
    `Period.order` — a mesma tabela que o registro canônico de eventos usa.
    Duas cópias produziriam duas ordens para os mesmos fatos.

    `sequence` É O DESEMPATE E É OPCIONAL (§71). Quando o corte declara uma
    sequência, ele é sensível a ela: dois eventos no mesmo relógio entram ou
    não conforme a posição. Quando não declara, o corte inclui TUDO daquele
    relógio — a decisão é explícita porque as duas leituras são defensáveis, e
    a diferença entre elas aparece exatamente nos empates.
    """

    #: A ordem de comparação é a dos campos, e por isso `_ordem` vem primeiro:
    #: `dataclass(order=True)` compara na ordem de declaração, e a fase precisa
    #: pesar mais que o minuto.
    _ordem: int
    minute: int
    stoppage: int
    sequence: int

    def __post_init__(self) -> None:
        if self.minute < 0 or self.stoppage < 0:
            raise ValidationError(
                f"posição temporal com relógio negativo: {self.minute}+{self.stoppage}"
            )

    @classmethod
    def of(
        cls,
        period: Period,
        minute: int = 0,
        stoppage: int = 0,
        *,
        sequence: int | None = None,
    ) -> Self:
        return cls(
            _ordem=period.order,
            minute=minute,
            stoppage=stoppage,
            sequence=SEM_DESEMPATE if sequence is None else sequence,
        )

    @classmethod
    def from_clock(cls, clock: MatchClock, *, sequence: int | None = None) -> Self:
        """A posição de um fato que carrega `MatchClock` — o caso do evento."""
        return cls.of(clock.period, clock.minute, clock.stoppage, sequence=sequence)

    @property
    def period(self) -> Period:
        return _FASE_POR_ORDEM[self._ordem]

    @property
    def has_tiebreak(self) -> bool:
        return self.sequence != SEM_DESEMPATE

    @property
    def is_pre_match(self) -> bool:
        return self.period is Period.PRE_MATCH

    @property
    def is_post_match(self) -> bool:
        """Depois do apito final.

        `FULL_TIME` é a única fase que descreve o jogo TERMINADO. A disputa de
        pênaltis não é: ela ainda é jogo, e um estado durante ela não pode
        enxergar o resultado da própria disputa.
        """
        return self.period is Period.FULL_TIME

    def as_canonical(self) -> dict[str, object]:
        return {
            "minute": self.minute,
            "period": self.period.value,
            "sequence": None if not self.has_tiebreak else self.sequence,
            "stoppage": self.stoppage,
        }

    def __str__(self) -> str:
        relogio = f"{self.minute}+{self.stoppage}" if self.stoppage else str(self.minute)
        desempate = "" if not self.has_tiebreak else f"#{self.sequence}"
        return f"{self.period.value}:{relogio}{desempate}"


_FASE_POR_ORDEM: Final[dict[int, Period]] = {fase.order: fase for fase in Period}


@final
@dataclass(frozen=True, slots=True)
class FeatureAsOf:
    """O CORTE. Ele é o contrato temporal inteiro de um cálculo (§7).

    O QUE ELE DECLARA, e por que cada campo existe:

        match_id            de qual partida é este estado
        position            até onde, DENTRO da partida (o corte efetivo)
        knowledge_cutoff    até quando, no relógio de parede, o conhecimento
                            é admitido — quando o chamador sabe dizer
        mode                sob qual verdade (§28)

    `knowledge_cutoff` É OPCIONAL E A AUSÊNCIA TEM CONSEQUÊNCIA. Sem ele, um
    fato cuja elegibilidade só se prova por carimbo de parede — uma cotação
    vista às 20:47 — não tem como ser provado elegível, e o guarda o recusa
    em modo causal. Isso é fail-closed por desenho (§27, §137): a alternativa
    seria assumir que a cotação já existia, que é exatamente o vazamento que
    este PR existe para tornar difícil.

    ELE NÃO É UM `datetime` COM UM MINUTO PENDURADO. As duas réguas coexistem
    porque medem coisas diferentes, e o `as-of` carrega as duas sem convertê-las
    uma na outra.
    """

    match_id: MatchId
    position: MatchTimePoint
    mode: TemporalMode = TemporalMode.AS_KNOWN
    knowledge_cutoff: Instant | None = None

    @classmethod
    def at(
        cls,
        match_id: MatchId,
        period: Period,
        minute: int = 0,
        stoppage: int = 0,
        *,
        sequence: int | None = None,
        mode: TemporalMode = TemporalMode.AS_KNOWN,
        knowledge_cutoff: Instant | None = None,
    ) -> Self:
        return cls(
            match_id=match_id,
            position=MatchTimePoint.of(period, minute, stoppage, sequence=sequence),
            mode=mode,
            knowledge_cutoff=knowledge_cutoff,
        )

    @classmethod
    def pre_match(
        cls,
        match_id: MatchId,
        *,
        mode: TemporalMode = TemporalMode.AS_KNOWN,
        knowledge_cutoff: Instant | None = None,
    ) -> Self:
        """O estado ANTES do apito inicial — o corte do §81."""
        return cls.at(match_id, Period.PRE_MATCH, mode=mode, knowledge_cutoff=knowledge_cutoff)

    @property
    def has_knowledge_cutoff(self) -> bool:
        return self.knowledge_cutoff is not None

    @property
    def is_pre_match(self) -> bool:
        return self.position.is_pre_match

    @property
    def is_post_match(self) -> bool:
        return self.position.is_post_match

    def covers(self, point: MatchTimePoint) -> bool:
        """Se aquela posição está DENTRO do corte efetivo.

        `<=` E NÃO `<`: um estado «aos 63» inclui o que aconteceu aos 63. O
        desempate por sequência é o que permite cortar no meio de um minuto,
        quando o chamador precisa disso.
        """
        return point <= self.position

    def knows(self, moment: Instant | None) -> bool | None:
        """Se aquele instante de parede já era conhecido no corte.

        DEVOLVE TRÊS RESPOSTAS, e a terceira é o ponto: `None` significa «não
        dá para provar» — o fato não tem carimbo, ou o corte não declarou até
        quando o conhecimento vale. Quem chama decide o que fazer com a
        dúvida, e em modo causal a resposta é recusar.
        """
        if moment is None or self.knowledge_cutoff is None:
            return None
        return moment <= self.knowledge_cutoff

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra na impressão do snapshot (§145)."""
        return {
            "knowledge_cutoff": (
                None if self.knowledge_cutoff is None else instant_text(self.knowledge_cutoff)
            ),
            "match_id": str(self.match_id),
            "mode": self.mode.value,
            "position": self.position.as_canonical(),
        }

    def __str__(self) -> str:
        conhecimento = (
            "" if self.knowledge_cutoff is None else f" ≤{instant_text(self.knowledge_cutoff)}"
        )
        return f"{self.match_id} @ {self.position} [{self.mode.value}]{conhecimento}"
