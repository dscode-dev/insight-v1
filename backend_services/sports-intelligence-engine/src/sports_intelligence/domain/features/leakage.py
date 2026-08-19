"""O guarda de vazamento temporal — a peça que este PR existe para entregar.

A PERGUNTA QUE ELE RESPONDE, fato a fato: *este fato poderia ter sido conhecido
no corte?* E ele responde em três estados, não dois:

    ALLOWED   pode entrar
    DENIED    existe, e é do futuro — ou de uma classe proibida no modo
    UNKNOWN   não dá para provar

A TERCEIRA RESPOSTA É A IMPORTANTE (§66, §137). Um sistema que só sabe dizer
sim ou não é obrigado a chutar quando não sabe, e o chute confortável é sempre
o mesmo: «provavelmente já era conhecido». `UNKNOWN` existe para que a dúvida
tenha nome, e o modo causal a trata como recusa.

`DENIED` ≠ `SOURCE_UNAVAILABLE` (§67). «O fato existe e vem do futuro» e «o
fato não existe» produzem a mesma ausência no resultado e exigem investigações
opostas: a primeira é um corte errado ou uma feature mal declarada; a segunda é
cobertura faltando. Confundi-las custa horas de depuração no dia em que um
número não bate.

O GUARDA É PURO. Ele não lê banco, não conhece repositório e não sabe o que é
um evento canônico — recebe o CARIMBO do fato, o corte e a política, e decide.
É isso que permite testá-lo com dez casos em memória e provar as propriedades
do §160 ao §163 sem subir nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.features.availability import (
    FactKind,
    TemporalAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.temporal import (
    FeatureAsOf,
    MatchTimePoint,
    TemporalMode,
)
from sports_intelligence.domain.shared.temporal import Instant


@final
class LeakageVerdict(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"

    @property
    def admits(self) -> bool:
        """Só `ALLOWED` admite o fato. `UNKNOWN` não é um talvez otimista."""
        return self is LeakageVerdict.ALLOWED


@final
class LeakageReason(StrEnum):
    """Por que um fato não entrou. Catálogo FECHADO (§68).

    STRING LIVRE AQUI SERIA O MESMO QUE NADA: «não elegível» não distingue um
    corte mal escolhido de uma política restritiva, e é justamente essa
    distinção que alguém precisa às duas da manhã.
    """

    #: A posição do fato na partida é posterior ao corte.
    EFFECTIVE_TIME_AFTER_CUTOFF = "EFFECTIVE_TIME_AFTER_CUTOFF"
    #: O fato só ficou conhecido depois do corte de conhecimento.
    KNOWLEDGE_TIME_AFTER_CUTOFF = "KNOWLEDGE_TIME_AFTER_CUTOFF"
    #: Só existe depois do apito final — resultado, agregado final.
    POST_MATCH_ONLY = "POST_MATCH_ONLY"
    #: Existe no corpus sem evidência de quando ficou disponível.
    RETROSPECTIVE_ONLY = "RETROSPECTIVE_ONLY"
    #: A classe temporal do fato não é conhecida.
    UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"
    #: O fato exige carimbo de parede e o corte não declara conhecimento.
    MISSING_KNOWLEDGE_CUTOFF = "MISSING_KNOWLEDGE_CUTOFF"
    #: O fato exige carimbo de parede e não o tem.
    MISSING_OBSERVATION_TIMESTAMP = "MISSING_OBSERVATION_TIMESTAMP"
    #: O modo temporal do corte não autoriza esta classe de fato.
    WRONG_TEMPORAL_MODE = "WRONG_TEMPORAL_MODE"
    #: Um normalizador ajustado com dado posterior ao corte (§87).
    NORMALIZER_FUTURE_FIT = "NORMALIZER_FUTURE_FIT"


@final
@dataclass(frozen=True, slots=True)
class FactTiming:
    """O CARIMBO de um fato candidato — tudo que o guarda precisa saber dele.

    ELE NÃO É O FATO. O guarda não recebe o evento, a cotação nem a escalação:
    recebe quando aquilo aconteceu, quando pôde ser sabido e de que família é.
    Um guarda que recebesse o fato inteiro acabaria olhando o conteúdo dele
    para decidir — e a decisão temporal não depende do conteúdo.

    `effective` É OPCIONAL porque nem todo fato tem posição na partida: uma
    cotação pré-jogo tem instante de parede e nenhuma posição. `knowledge`
    é opcional pelo motivo oposto: quase nenhum fato histórico tem carimbo de
    observação, e é essa ausência que a política classifica.
    """

    kind: FactKind
    effective: MatchTimePoint | None = None
    knowledge: Instant | None = None
    #: Um rótulo para o diagnóstico — id do evento, chave da cotação. Ele NÃO
    #: entra em decisão nenhuma; existe para a mensagem dizer QUAL fato.
    label: str = ""

    @classmethod
    def event(
        cls,
        effective: MatchTimePoint,
        *,
        revision: bool = False,
        knowledge: Instant | None = None,
        label: str = "",
    ) -> Self:
        return cls(
            kind=FactKind.EVENT_REVISION if revision else FactKind.EVENT_ORIGINAL,
            effective=effective,
            knowledge=knowledge,
            label=label,
        )


@final
@dataclass(frozen=True, slots=True)
class LeakageDecision:
    """O veredito, com motivo quando não é `ALLOWED`.

    O MOTIVO É OBRIGATÓRIO NA RECUSA (§46). Uma recusa sem motivo é uma
    ausência que ninguém consegue explicar seis meses depois — que é
    exatamente quando alguém pergunta por que a feature de março está vazia.
    """

    verdict: LeakageVerdict
    reason: LeakageReason | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.verdict is not LeakageVerdict.ALLOWED and self.reason is None:
            raise ValueError("recusa sem motivo tipado")
        if self.verdict is LeakageVerdict.ALLOWED and self.reason is not None:
            raise ValueError("permissão com motivo de recusa")

    @classmethod
    def allowed(cls) -> Self:
        return cls(verdict=LeakageVerdict.ALLOWED)

    @classmethod
    def denied(cls, reason: LeakageReason, detail: str = "") -> Self:
        return cls(verdict=LeakageVerdict.DENIED, reason=reason, detail=detail)

    @classmethod
    def unknown(cls, reason: LeakageReason, detail: str = "") -> Self:
        return cls(verdict=LeakageVerdict.UNKNOWN, reason=reason, detail=detail)

    @property
    def admits(self) -> bool:
        return self.verdict.admits

    def __str__(self) -> str:
        if self.reason is None:
            return self.verdict.value
        return f"{self.verdict.value}: {self.reason.value}" + (
            f" ({self.detail})" if self.detail else ""
        )


@final
@dataclass(frozen=True, slots=True)
class TemporalLeakageGuard:
    """Decide, fato a fato, se ele pode entrar num cálculo (§66).

    A ORDEM DAS GUARDAS É A DECISÃO, como no PR-04.4.1:

        1. a CLASSE do fato        pós-jogo, retrospectivo, desconhecido
        2. a OCORRÊNCIA            a posição na partida contra o corte
        3. o CONHECIMENTO          o carimbo de parede contra o corte

    A classe vem primeiro porque ela é categórica: um `MatchResult` não deixa
    de ser pós-jogo por ter acontecido «antes» do corte em algum sentido. A
    ocorrência vem antes do conhecimento porque ela é a régua que TODO fato
    intra-jogo tem, e o conhecimento é a que quase nenhum tem.
    """

    policy: TemporalAvailabilityPolicy

    def evaluate(self, timing: FactTiming, as_of: FeatureAsOf) -> LeakageDecision:
        disponibilidade = self.policy.availability_of(timing.kind)
        pela_classe = self._pela_classe(disponibilidade, as_of)
        if pela_classe is not None:
            return pela_classe
        pela_ocorrencia = self._pela_ocorrencia(timing, as_of)
        if pela_ocorrencia is not None:
            return pela_ocorrencia
        return self._pelo_conhecimento(timing, disponibilidade, as_of)

    # ------------------------------------------------------------ classe --

    def _pela_classe(
        self, disponibilidade: TemporalAvailability, as_of: FeatureAsOf
    ) -> LeakageDecision | None:
        """A classe do fato contra o modo e a fase do corte."""
        if disponibilidade is TemporalAvailability.POST_MATCH_ONLY:
            # SÓ DEPOIS DO APITO (§13, §73). Um estado aos 63 minutos não
            # consulta o placar final nem a estatística agregada do jogo — e
            # não é uma questão de rigor: `HOME_SHOTS = 14` no minuto 63 é
            # simplesmente falso.
            if as_of.is_post_match:
                return None
            return LeakageDecision.denied(
                LeakageReason.POST_MATCH_ONLY,
                f"o corte está em {as_of.position} e o fato só existe no fim do jogo",
            )
        if disponibilidade is TemporalAvailability.RETROSPECTIVE_ONLY:
            # RETROSPECTIVO (§26, §78). Em modo canônico-final ele entra: a
            # pergunta ali é «o que hoje sabemos». Em modo causal, não.
            if as_of.mode is TemporalMode.CANONICAL_FINAL:
                return None
            return LeakageDecision.denied(
                LeakageReason.RETROSPECTIVE_ONLY,
                "não há evidência de quando este fato ficou disponível, e o modo "
                "AS_KNOWN não aplica retroativamente o que só se soube depois",
            )
        if disponibilidade is TemporalAvailability.UNKNOWN:
            if self.policy.allow_unknown_when_effective_precedes:
                return None
            return LeakageDecision.unknown(
                LeakageReason.UNKNOWN_AVAILABILITY,
                "a política não sabe classificar temporalmente esta família",
            )
        return None

    # -------------------------------------------------------- ocorrência --

    @staticmethod
    def _pela_ocorrencia(timing: FactTiming, as_of: FeatureAsOf) -> LeakageDecision | None:
        """A posição na partida contra o corte efetivo (§4, §21).

        ELA VALE NOS DOIS MODOS. `CANONICAL_FINAL` dispensa a prova de
        conhecimento, e não a causalidade de ocorrência: um gol aos 80 não faz
        parte do estado aos 63 sob verdade nenhuma.
        """
        if timing.effective is None:
            return None
        if as_of.covers(timing.effective):
            return None
        return LeakageDecision.denied(
            LeakageReason.EFFECTIVE_TIME_AFTER_CUTOFF,
            f"o fato está em {timing.effective} e o corte em {as_of.position}",
        )

    # ------------------------------------------------------ conhecimento --

    @staticmethod
    def _pelo_conhecimento(
        timing: FactTiming,
        disponibilidade: TemporalAvailability,
        as_of: FeatureAsOf,
    ) -> LeakageDecision:
        """O carimbo de parede contra o corte de conhecimento (§5, §6, §17).

        TRÊS SITUAÇÕES, e as três têm resposta própria:

            o fato TEM carimbo e o corte também   compara-se, e pronto
            o fato PRECISA de carimbo e não tem   `UNKNOWN`, fail-closed
            o fato não precisa                    a classe já bastou
        """
        if not as_of.mode.is_causal:
            # Em modo canônico-final o conhecimento não é conferido — a
            # pergunta é o que hoje se sabe, e não o que se sabia então.
            return LeakageDecision.allowed()

        sabido = as_of.knows(timing.knowledge)
        if sabido is True:
            return LeakageDecision.allowed()
        if sabido is False:
            return LeakageDecision.denied(
                LeakageReason.KNOWLEDGE_TIME_AFTER_CUTOFF,
                f"conhecido em {timing.knowledge} e o corte admite até "
                f"{as_of.knowledge_cutoff}",
            )

        # `None`: não deu para comparar. A classe decide se isso é fatal.
        if not disponibilidade.needs_wall_clock_proof:
            # `PRE_MATCH_KNOWN` e `OCCURRENCE_OBSERVABLE` se resolvem pela
            # posição, que já passou. Exigir carimbo delas recusaria o corpus
            # histórico inteiro, que não os tem.
            return LeakageDecision.allowed()
        if timing.knowledge is None:
            return LeakageDecision.unknown(
                LeakageReason.MISSING_OBSERVATION_TIMESTAMP,
                "esta família só é elegível com carimbo de observação, e o fato "
                "não o carrega",
            )
        return LeakageDecision.unknown(
            LeakageReason.MISSING_KNOWLEDGE_CUTOFF,
            "o fato tem carimbo de observação e o corte não declara até quando o "
            "conhecimento vale — sem os dois lados não há comparação",
        )
