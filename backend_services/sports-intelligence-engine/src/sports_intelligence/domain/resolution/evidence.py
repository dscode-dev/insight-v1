"""A evidência de uma decisão — estruturada, e nunca texto livre.

O QUE PRECISAMOS PODER RECONSTRUIR, seis meses depois, olhando só o banco:

    + id do provedor bateu           (peso 1,00)
    + data de nascimento bateu       (peso 0,80)
    + clube na data bateu            (peso 0,60)
    - posição divergiu               (peso 0,20)

Um campo `explanation: str` com esse texto pareceria resolver e não resolve.
Ele vira a autoridade sobre o que aconteceu — e diverge do que de fato
aconteceu no primeiro refactor, porque ninguém atualiza uma string. Pior:
não é agregável. «Quantas resoluções de jogador dependeram de data de
nascimento?» exige varrer texto.

Então: cada evidência é uma linha com tipo, peso, resultado e um código de
explicação de um catálogo fechado. O texto legível é DERIVADO disso.

O PESO VEM DA POLÍTICA, não da evidência. A evidência diz o que foi
observado; quanto isso vale é decisão versionada, e mudá-la é mudar
`PolicyVersion` — não reescrever a evidência gravada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.resolution.confidence_scale import EvidenceOutcome
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import EntityId

MAX_EVIDENCE_VALUE_LENGTH: Final[int] = 200


class EvidenceKind(StrEnum):
    """O TIPO de evidência consultada. Fechado.

    Fechado porque a agregação depende disso: um catálogo aberto faria
    `provider_id`, `providerId` e `provider id` coexistirem, e a consulta que
    procura um deles encontraria um terço.
    """

    #: O provedor forneceu um id próprio e existe mapeamento persistido.
    PROVIDER_MAPPING = "PROVIDER_MAPPING"
    #: Casamento contra a chave canônica da entidade.
    CANONICAL_KEY = "CANONICAL_KEY"
    #: Casamento contra um alias registrado.
    ALIAS = "ALIAS"
    #: Similaridade textual entre nomes normalizados.
    NAME_SIMILARITY = "NAME_SIMILARITY"
    COUNTRY = "COUNTRY"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    NATIONALITY = "NATIONALITY"
    POSITION = "POSITION"
    #: O clube do jogador NA DATA do registro — não o clube atual.
    TEAM_AT_DATE = "TEAM_AT_DATE"
    COMPETITION = "COMPETITION"
    SEASON = "SEASON"
    HOME_TEAM = "HOME_TEAM"
    AWAY_TEAM = "AWAY_TEAM"
    KICKOFF = "KICKOFF"
    STAGE = "STAGE"
    ROUND = "ROUND"
    #: Estádio. Apoio, nunca autoridade: campo neutro, punição e mudança
    #: logística fazem uma partida legítima acontecer em outro lugar.
    VENUE = "VENUE"
    #: Participação histórica: o clube de fato jogou aquela competição
    #: naquela temporada.
    HISTORICAL_PARTICIPATION = "HISTORICAL_PARTICIPATION"
    #: Placar observado. Apoio fraco — dois jogos podem terminar 1-1.
    SCORE_OBSERVATION = "SCORE_OBSERVATION"

    @property
    def is_hard(self) -> bool:
        """Se sozinha ela decide.

        SÓ AS TRÊS EXATAS. Uma evidência forte que não é exata — data de
        nascimento, por exemplo — reduz o espaço de candidatos e não o fecha:
        dois jogadores podem nascer no mesmo dia.
        """
        return self in (
            EvidenceKind.PROVIDER_MAPPING,
            EvidenceKind.CANONICAL_KEY,
            EvidenceKind.ALIAS,
        )


class ExplanationCode(StrEnum):
    """POR QUE esta evidência resultou no que resultou. Fechado.

    É o vocabulário que a fila de revisão mostra ao humano e que os painéis
    agregam. Um código novo aqui é uma decisão de produto; um texto livre
    seria um código novo por execução.
    """

    PROVIDER_ID_MATCHED = "PROVIDER_ID_MATCHED"
    PROVIDER_ID_ABSENT = "PROVIDER_ID_ABSENT"
    PROVIDER_ID_UNKNOWN = "PROVIDER_ID_UNKNOWN"
    EXACT_NAME_MATCH = "EXACT_NAME_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    SIMILAR_NAME = "SIMILAR_NAME"
    NAME_TOO_DIFFERENT = "NAME_TOO_DIFFERENT"
    VALUE_MATCHED = "VALUE_MATCHED"
    VALUE_MISMATCH = "VALUE_MISMATCH"
    VALUE_ABSENT_IN_SOURCE = "VALUE_ABSENT_IN_SOURCE"
    VALUE_ABSENT_IN_CANONICAL = "VALUE_ABSENT_IN_CANONICAL"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OUTSIDE_TOLERANCE = "OUTSIDE_TOLERANCE"
    #: Fuso não declarado pela fonte. A ambiguidade vira evidência FRACA, e
    #: nunca correção silenciosa (§25).
    TIMEZONE_UNDECLARED = "TIMEZONE_UNDECLARED"
    #: Mandante e visitante trocados em relação ao candidato. Nunca corrigido
    #: automaticamente — ver `MatchResolutionPolicy` (§24).
    SIDES_REVERSED = "SIDES_REVERSED"
    OUT_OF_CATALOG = "OUT_OF_CATALOG"
    NOT_PARTICIPANT = "NOT_PARTICIPANT"
    NO_CANDIDATES = "NO_CANDIDATES"
    MULTIPLE_EQUAL_CANDIDATES = "MULTIPLE_EQUAL_CANDIDATES"
    HUMAN_DECISION = "HUMAN_DECISION"

    @property
    def is_positive(self) -> bool:
        return self in _POSITIVOS


_POSITIVOS: Final[frozenset[ExplanationCode]] = frozenset(
    {
        ExplanationCode.PROVIDER_ID_MATCHED,
        ExplanationCode.EXACT_NAME_MATCH,
        ExplanationCode.ALIAS_MATCH,
        ExplanationCode.SIMILAR_NAME,
        ExplanationCode.VALUE_MATCHED,
        ExplanationCode.WITHIN_TOLERANCE,
        ExplanationCode.HUMAN_DECISION,
    }
)


@final
@dataclass(frozen=True, slots=True)
class ResolutionEvidence:
    """Uma evidência consultada, com o que ela produziu."""

    kind: EvidenceKind
    outcome: EvidenceOutcome
    explanation: ExplanationCode
    #: O peso que a política deu a esta evidência nesta decisão. Gravado
    #: junto porque a política muda: sem ele, reler uma decisão antiga
    #: aplicaria os pesos de hoje ao raciocínio de ontem.
    weight: float
    #: O valor comparado, truncado. Para a fila de revisão — quem decide
    #: precisa ver `1994-07-12` e não só «data de nascimento divergiu».
    source_value: str | None = None
    canonical_value: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValidationError(f"peso de evidência {self.weight!r} fora de [0,1]")
        for nome in ("source_value", "canonical_value"):
            valor = getattr(self, nome)
            if valor is not None and len(valor) > MAX_EVIDENCE_VALUE_LENGTH:
                object.__setattr__(self, nome, valor[:MAX_EVIDENCE_VALUE_LENGTH] + "…")

    @classmethod
    def matched(
        cls,
        kind: EvidenceKind,
        *,
        weight: float,
        explanation: ExplanationCode = ExplanationCode.VALUE_MATCHED,
        source_value: str | None = None,
        canonical_value: str | None = None,
    ) -> Self:
        return cls(
            kind=kind,
            outcome=EvidenceOutcome.MATCHED,
            explanation=explanation,
            weight=weight,
            source_value=source_value,
            canonical_value=canonical_value,
        )

    @classmethod
    def mismatched(
        cls,
        kind: EvidenceKind,
        *,
        weight: float,
        explanation: ExplanationCode = ExplanationCode.VALUE_MISMATCH,
        source_value: str | None = None,
        canonical_value: str | None = None,
    ) -> Self:
        return cls(
            kind=kind,
            outcome=EvidenceOutcome.MISMATCHED,
            explanation=explanation,
            weight=weight,
            source_value=source_value,
            canonical_value=canonical_value,
        )

    @classmethod
    def unavailable(
        cls,
        kind: EvidenceKind,
        *,
        explanation: ExplanationCode,
        source_value: str | None = None,
    ) -> Self:
        """A evidência não pôde ser consultada.

        PESO ZERO E NÃO «NÃO BATEU». A distinção é a mesma do PR-00 entre
        ausente e zero: uma fonte que não traz data de nascimento não está
        discordando da data canônica — ela não disse nada. Tratá-la como
        divergência puniria fontes incompletas por serem incompletas.
        """
        return cls(
            kind=kind,
            outcome=EvidenceOutcome.UNAVAILABLE,
            explanation=explanation,
            weight=0.0,
            source_value=source_value,
        )

    @property
    def contributes(self) -> bool:
        return self.outcome is EvidenceOutcome.MATCHED and self.weight > 0.0

    @property
    def contradicts(self) -> bool:
        return self.outcome is EvidenceOutcome.MISMATCHED and self.weight > 0.0

    def __str__(self) -> str:
        marca = {
            EvidenceOutcome.MATCHED: "+",
            EvidenceOutcome.MISMATCHED: "-",
            EvidenceOutcome.UNAVAILABLE: "?",
        }[self.outcome]
        valores = ""
        if self.source_value is not None:
            valores = f" ({self.source_value}"
            valores += (
                f" contra {self.canonical_value})" if self.canonical_value is not None else ")"
            )
        return f"{marca} {self.kind}{valores} [{self.explanation}, peso {self.weight:.2f}]"


@final
@dataclass(frozen=True, slots=True)
class ResolutionAlternative:
    """Um candidato que não foi escolhido — e o quanto faltou.

    GUARDAR OS DESCARTADOS É O PONTO. Sem eles, uma decisão `AMBIGUOUS` diz
    «não sei» e não diz entre o quê, e o humano na fila de revisão precisa
    refazer a busca à mão. Com eles, a fila mostra os dois candidatos lado a
    lado com a evidência de cada um.

    O TOP-N É LIMITADO por configuração: guardar mil candidatos de um nome
    genérico enche o banco sem acrescentar nada depois do décimo.
    """

    canonical_entity_id: EntityId
    score: float
    evidence_summary: str
    label: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValidationError(f"score de alternativa {self.score!r} fora de [0,1]")

    def __str__(self) -> str:
        nome = f" {self.label!r}" if self.label else ""
        return f"{self.canonical_entity_id}{nome} @ {self.score:.3f} — {self.evidence_summary}"


def rank_alternatives(
    candidatos: tuple[ResolutionAlternative, ...], *, limit: int
) -> tuple[ResolutionAlternative, ...]:
    """Ordena por score decrescente, com desempate DETERMINÍSTICO.

    O DESEMPATE PELO ID É O QUE TORNA O REPROCESSAMENTO REPRODUZÍVEL. Dois
    candidatos com o mesmo score saem do banco em ordem arbitrária, e uma
    ordenação instável faria a mesma entrada produzir decisões diferentes em
    execuções diferentes — que é exatamente o que o ADR-0019 promete que não
    acontece.
    """
    if limit < 1:
        raise ValidationError(f"limite de alternativas {limit!r} inválido")
    return tuple(sorted(candidatos, key=lambda a: (-a.score, str(a.canonical_entity_id))))[:limit]
