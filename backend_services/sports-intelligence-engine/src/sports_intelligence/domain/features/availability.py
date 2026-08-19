"""Quando cada tipo de fato PODE ser conhecido — e o que fazer quando não se
sabe.

O PROBLEMA CONCRETO (§11). O corpus histórico guarda quando um fato ACONTECEU
com precisão de minuto de jogo, e quase nunca guarda quando ele FICOU
CONHECIDO. A tentação é assumir `knowledge_time = effective_time` e seguir em
frente. Essa suposição é falsa de um jeito específico e caro: ela transforma
toda correção tardia — a que o VAR confirmou dois minutos depois — em
informação que o replay «já tinha» no instante do lance.

A ALTERNATIVA NÃO É INVENTAR CARIMBO. É CLASSIFICAR: cada família de fato
declara COMO ela pode ser usada temporalmente, e a classificação é uma decisão
versionada — não um `if` espalhado pelo cálculo.

    PRE_MATCH_KNOWN         conhecido antes do apito. Escalação divulgada,
                            competição, mando de campo
    OCCURRENCE_OBSERVABLE   observável no instante em que acontece. É o gol
                            visto por quem assiste — a suposição declarada
                            para eventos originais
    OBSERVED_AT_TIMESTAMP   o corpus carrega o carimbo REAL de observação. É o
                            caso da cotação com `observed_at`
    POST_MATCH_ONLY         só existe depois do apito final. Resultado,
                            estatística final agregada
    RETROSPECTIVE_ONLY      existe no corpus e não há evidência de quando ficou
                            disponível. Correções sem carimbo caem aqui
    UNKNOWN                 nem sequer a classe é conhecida

FAIL-CLOSED É A REGRA (§27, §137). Quando a disponibilidade não pode ser
provada e a feature exige causalidade estrita, o resultado é `UNAVAILABLE` com
motivo — nunca o fato «porque provavelmente já era conhecido».
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import Version


@final
class TemporalAvailability(StrEnum):
    """Como um fato pode ser usado temporalmente (§11)."""

    PRE_MATCH_KNOWN = "PRE_MATCH_KNOWN"
    OCCURRENCE_OBSERVABLE = "OCCURRENCE_OBSERVABLE"
    OBSERVED_AT_TIMESTAMP = "OBSERVED_AT_TIMESTAMP"
    POST_MATCH_ONLY = "POST_MATCH_ONLY"
    RETROSPECTIVE_ONLY = "RETROSPECTIVE_ONLY"
    UNKNOWN = "UNKNOWN"

    @property
    def needs_wall_clock_proof(self) -> bool:
        """Se a elegibilidade EXIGE um carimbo de parede para ser provada.

        Só `OBSERVED_AT_TIMESTAMP`. As outras se resolvem pela posição na
        partida ou pela classe — e exigir carimbo delas recusaria todo o
        corpus histórico, que não os tem.
        """
        return self is TemporalAvailability.OBSERVED_AT_TIMESTAMP

    @property
    def is_provable_causally(self) -> bool:
        """Se um fato desta classe pode, em princípio, entrar num estado
        causal.

        `RETROSPECTIVE_ONLY` e `UNKNOWN` não podem: o primeiro porque se sabe
        que a informação é retrospectiva, o segundo porque não se sabe nada. A
        diferença entre os dois importa no diagnóstico, e nenhum dos dois vira
        dado num replay `AS_KNOWN`.
        """
        return self in (
            TemporalAvailability.PRE_MATCH_KNOWN,
            TemporalAvailability.OCCURRENCE_OBSERVABLE,
            TemporalAvailability.OBSERVED_AT_TIMESTAMP,
            TemporalAvailability.POST_MATCH_ONLY,
        )


@final
class FactKind(StrEnum):
    """As famílias de fato que o corpus publica, do ponto de vista TEMPORAL.

    ELAS NÃO SÃO AS `CoverageFamily` (§12). A cobertura agrupa por «o que o
    dado descreve»; aqui o agrupamento é por «quando ele pode ser conhecido», e
    a diferença aparece dentro da mesma família: a escalação inicial é
    pré-jogo, e a substituição — que também é `LINEUP` no sentido esportivo —
    é um evento que acontece no minuto 70.
    """

    #: Identidade e contexto da partida: competição, temporada, mando.
    MATCH_IDENTITY = "MATCH_IDENTITY"
    #: O placar final, o vencedor, a classificação.
    MATCH_RESULT = "MATCH_RESULT"
    #: Estatística agregada do jogo inteiro — `HOME_SHOTS = 14` (§15).
    FINAL_AGGREGATE = "FINAL_AGGREGATE"
    #: A escalação divulgada antes do apito.
    LINEUP_INITIAL = "LINEUP_INITIAL"
    #: Um evento canônico original.
    EVENT_ORIGINAL = "EVENT_ORIGINAL"
    #: Uma correção ou cancelamento de evento (§22).
    EVENT_REVISION = "EVENT_REVISION"
    #: Uma cotação com instante de observação declarado.
    ODDS_OBSERVATION = "ODDS_OBSERVATION"
    #: Uma cotação de fechamento sem prova de quando existiu (§18).
    ODDS_CLOSING = "ODDS_CLOSING"


@final
class FeatureAvailability(StrEnum):
    """Por que uma feature tem — ou não tem — valor (§45).

    UM BOOLEANO NÃO BASTA porque as causas pedem ações diferentes: «a fonte
    não declara isso» manda procurar outra fonte, «o fato existe e é do
    futuro» manda revisar o corte, e «a política proíbe» manda revisar a
    política. Achatá-las em `False` transforma três investigações numa.
    """

    AVAILABLE = "AVAILABLE"
    #: A fonte não declara esta dimensão para este corpus.
    NOT_DECLARED = "NOT_DECLARED"
    #: A pergunta não se aplica — cobertura espacial num evento estrutural.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    #: Declarada, e o dado não veio.
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    #: O fato existe, e não podia ser conhecido no corte (§67).
    TEMPORALLY_UNAVAILABLE = "TEMPORALLY_UNAVAILABLE"
    #: Licença, escopo ou modo temporal proíbem usar (§59, §79).
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    #: A cobertura declarada é insuficiente para o que a feature exige (§100).
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"

    @property
    def is_available(self) -> bool:
        return self is FeatureAvailability.AVAILABLE


#: A CLASSIFICAÇÃO PADRÃO, e cada linha dela é uma decisão declarada.
#:
#: `EVENT_ORIGINAL = OCCURRENCE_OBSERVABLE` é a suposição mais forte deste
#: mapa, e ela está aqui à vista: o corpus histórico não guarda quando o
#: provedor publicou cada evento — o PR-04.4.1 grava `ObservationTimes.at_once`
#: com o instante de INGESTÃO, que não é o de observação. Assumir que um gol é
#: observável quando acontece é uma aproximação defensável (quem assiste vê),
#: e ela IGNORA a latência real do provedor. Uma política mais estrita pode
#: exigir `OBSERVED_AT_TIMESTAMP` e recusar todo evento sem carimbo — é para
#: isso que a política tem versão.
#:
#: `EVENT_REVISION = RETROSPECTIVE_ONLY` é a outra ponta, e é conservadora de
#: propósito (§26, §78): a correção existe no corpus, não há evidência de
#: quando ficou disponível, e aplicá-la retroativamente é exatamente o
#: vazamento do §25.
_CLASSIFICACAO_PADRAO: Final[dict[FactKind, TemporalAvailability]] = {
    FactKind.MATCH_IDENTITY: TemporalAvailability.PRE_MATCH_KNOWN,
    FactKind.MATCH_RESULT: TemporalAvailability.POST_MATCH_ONLY,
    FactKind.FINAL_AGGREGATE: TemporalAvailability.POST_MATCH_ONLY,
    FactKind.LINEUP_INITIAL: TemporalAvailability.PRE_MATCH_KNOWN,
    FactKind.EVENT_ORIGINAL: TemporalAvailability.OCCURRENCE_OBSERVABLE,
    FactKind.EVENT_REVISION: TemporalAvailability.RETROSPECTIVE_ONLY,
    FactKind.ODDS_OBSERVATION: TemporalAvailability.OBSERVED_AT_TIMESTAMP,
    FactKind.ODDS_CLOSING: TemporalAvailability.UNKNOWN,
}


@final
@dataclass(frozen=True, slots=True)
class TemporalAvailabilityPolicy:
    """Como cada família de fato pode ser usada temporalmente. VERSIONADA (§12).

    POR QUE ELA É UM OBJETO E NÃO UM `if`. A classificação é uma decisão
    editorial sobre o dado — «assumimos que um gol é observável quando
    acontece» é uma afirmação que alguém precisa poder revisar, datar e
    comparar. Espalhada pelo cálculo, ela vira quinze suposições implícitas
    que ninguém consegue enumerar.

    A IMPRESSÃO É O QUE TORNA DUAS EXECUÇÕES COMPARÁVEIS (§134). Dois
    snapshots calculados sob políticas de conteúdos diferentes descrevem
    causalidades diferentes, e a impressão é o que impede alguém de compará-los
    achando que descrevem a mesma coisa.
    """

    version: Version
    #: A classificação por família. Ela é COMPLETA por construção: o
    #: `__post_init__` recusa uma política que esqueça uma família, porque a
    #: família esquecida cairia num default silencioso.
    classification: dict[FactKind, TemporalAvailability] = field(
        default_factory=lambda: dict(_CLASSIFICACAO_PADRAO)
    )
    #: Se um fato de classe desconhecida pode entrar quando a posição dele é
    #: provadamente anterior ao corte. `False` é o fail-closed do §137.
    allow_unknown_when_effective_precedes: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        faltando = [k for k in FactKind if k not in self.classification]
        if faltando:
            nomes = ", ".join(sorted(k.value for k in faltando))
            raise ValidationError(
                f"política temporal sem classificação para {nomes}. Uma família "
                "esquecida cairia num default silencioso, e o default silencioso "
                "é exatamente o vazamento que esta política existe para impedir",
                context={"missing": nomes},
            )

    @classmethod
    def default(cls) -> Self:
        """A política padrão da V1, com as suposições declaradas acima."""
        return cls(
            version=Version(major=1, minor=0),
            description=(
                "eventos originais observáveis na ocorrência; revisões "
                "retrospectivas; resultado e agregado final só pós-jogo"
            ),
        )

    @classmethod
    def strict_observed(cls) -> Self:
        """A política ESTRITA: nada entra sem carimbo de observação.

        Ela existe para que a suposição do padrão seja visivelmente uma
        escolha, e não a única possibilidade. Sob ela, um corpus sem carimbo
        de observação simplesmente não produz feature intra-jogo — o que é
        honesto e pouco útil, e é por isso que não é o padrão.
        """
        classificacao = dict(_CLASSIFICACAO_PADRAO)
        classificacao[FactKind.EVENT_ORIGINAL] = TemporalAvailability.OBSERVED_AT_TIMESTAMP
        classificacao[FactKind.EVENT_REVISION] = TemporalAvailability.OBSERVED_AT_TIMESTAMP
        return cls(
            version=Version(major=1, minor=0),
            classification=classificacao,
            description="exige carimbo de observação para todo fato intra-jogo",
        )

    def availability_of(self, kind: FactKind) -> TemporalAvailability:
        return self.classification[kind]

    def as_canonical(self) -> dict[str, object]:
        """O que entra na impressão — conteúdo, e nunca carimbo de execução."""
        return {
            "allow_unknown_when_effective_precedes": (
                self.allow_unknown_when_effective_precedes
            ),
            "classification": {
                k.value: self.classification[k].value for k in sorted(FactKind, key=str)
            },
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 da forma canônica (§134).

        A DESCRIÇÃO NÃO ENTRA. Ela é para quem lê, e mudar a redação de um
        comentário não muda a causalidade que a política declara.
        """
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"política temporal {self.version} [{self.fingerprint[:12]}]"
