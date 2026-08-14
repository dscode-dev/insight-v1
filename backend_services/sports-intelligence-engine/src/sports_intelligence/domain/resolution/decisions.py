"""A decisão de resolução: o que foi decidido, com que evidência, e por quem.

O QUE ESTE MÓDULO EXISTE PARA IMPEDIR. A frase mais cara que um motor destes
pode dizer é «parece ser o mesmo, então é o mesmo». Ela não falha: o merge
acontece, a tabela soma, e três grafias de um clube viram um clube com o
histórico de três — ou, pior, dois jogadores homônimos viram um com as
carreiras somadas.

Por isso nenhuma resolução aqui é um booleano. Toda decisão carrega:

    o que foi decidido        status + entidade canônica
    com base em quê           evidências, uma a uma, com peso e resultado
    quão forte                confiança explícita, em [0,1]
    por qual regra            método, de um catálogo fechado
    sob qual versão           resolver, normalizador e política
    quem decidiu              ator humano ou de serviço
    de qual entrada           dataset, versão e impressão do manifesto

Sem os sete, a decisão não é auditável — e uma decisão de identidade que não
se audita é indistinguível de um palpite que deu certo.

A DECISÃO É IMUTÁVEL. Reprocessar não corrige uma decisão: emite outra, numa
execução nova. As duas coexistem, e a diferença entre elas é o que mostra o
que o resolver novo passou a enxergar (ADR-0019).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.resolution.evidence import (
    ResolutionAlternative,
    ResolutionEvidence,
)
from sports_intelligence.domain.resolution.versions import (
    NormalizerVersion,
    PolicyVersion,
    ResolverVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    EntityId,
    ProviderId,
    ProviderRef,
)
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


class SubjectType(StrEnum):
    """O que está sendo resolvido. Fechado, e na ordem de dependência.

    A ORDEM IMPORTA E NÃO É ALFABÉTICA: competição resolve sozinha; temporada
    precisa da competição; time precisa das duas; jogador precisa do time;
    partida precisa de todos. Resolver fora de ordem é resolver com menos
    evidência do que existia.
    """

    COMPETITION = "COMPETITION"
    SEASON = "SEASON"
    TEAM = "TEAM"
    PLAYER = "PLAYER"
    MATCH = "MATCH"

    @property
    def resolution_order(self) -> int:
        return _ORDEM[self]

    @property
    def false_merge_is_catastrophic(self) -> bool:
        """Onde um merge errado contamina o histórico de forma irreversível.

        Um `TeamId` ou `PlayerId` errado se propaga para influência de
        jogador, força de elenco, estados históricos e grafo tático — e a
        contaminação não é detectável depois, porque tudo continua somando.
        Competição e temporada erradas são caras e recuperáveis; estas três
        não são (ADR-0018).
        """
        return self in (SubjectType.TEAM, SubjectType.PLAYER, SubjectType.MATCH)


_ORDEM: Final[dict[SubjectType, int]] = {
    SubjectType.COMPETITION: 0,
    SubjectType.SEASON: 1,
    SubjectType.TEAM: 2,
    SubjectType.PLAYER: 3,
    SubjectType.MATCH: 4,
}


class ResolutionStatus(StrEnum):
    """O resultado da tentativa. Cinco estados, e nenhum deles é booleano.

    `resolved = True/False` apagaria a distinção que mais importa
    operacionalmente: entre «não achei nada» e «achei dois e não sei qual».
    A primeira se conserta com mais dados; a segunda, com uma decisão humana.
    """

    #: Uma entidade canônica foi identificada com evidência suficiente.
    RESOLVED = "RESOLVED"
    #: Nenhum candidato plausível. Não é erro: é o estado honesto de um
    #: registro cuja entidade ainda não existe no registro canônico.
    UNRESOLVED = "UNRESOLVED"
    #: Dois ou mais candidatos empatados ou próximos demais. O motor SABE que
    #: não sabe, e isso é informação — não falha.
    AMBIGUOUS = "AMBIGUOUS"
    #: Há um candidato provável, e não o bastante para decidir sozinho.
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    #: Decidido que este registro NÃO corresponde a nenhuma entidade —
    #: competição fora do catálogo, linha de cabeçalho repetida, lixo.
    #: Distinto de `UNRESOLVED`: aqui alguém (ou uma regra) decidiu.
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in (ResolutionStatus.RESOLVED, ResolutionStatus.REJECTED)

    @property
    def needs_human(self) -> bool:
        """Se este registro entra na fila de revisão."""
        return self in (ResolutionStatus.AMBIGUOUS, ResolutionStatus.REVIEW_REQUIRED)

    @property
    def yields_canonical_reference(self) -> bool:
        """Se desta decisão sai uma referência canônica utilizável.

        SÓ `RESOLVED`. É a guarda que a fusão consulta: nada que não tenha
        passado por aqui pode entrar num grupo de fusão (ADR-0022).
        """
        return self is ResolutionStatus.RESOLVED


class ResolutionMethod(StrEnum):
    """COMO a decisão aconteceu. Fechado, e nunca `AUTO`.

    `AUTO` responde «não foi humano» e não responde nada sobre a força da
    conclusão. Um mapeamento de provedor conhecido e um casamento por
    similaridade de nome são as duas coisas mais distantes possíveis em
    confiabilidade, e ambos seriam `AUTO`.
    """

    #: O provedor já tem mapeamento persistido para esta referência. É a
    #: evidência mais forte que existe: alguém já decidiu isto antes, e a
    #: decisão ficou registrada.
    EXACT_PROVIDER_MAPPING = "EXACT_PROVIDER_MAPPING"
    #: Casamento exato contra a chave canônica — o código de uma competição,
    #: o nome canônico de um clube.
    EXACT_CANONICAL_KEY = "EXACT_CANONICAL_KEY"
    #: Casamento exato contra um alias registrado.
    EXACT_ALIAS = "EXACT_ALIAS"
    #: Regra composta e determinística: (competição, temporada, mandante,
    #: visitante, data) casando dentro de tolerância declarada.
    COMPOSITE_RULE = "COMPOSITE_RULE"
    #: Similaridade acima do limiar da política, com evidência de apoio.
    #: NUNCA é autoridade sozinha (ADR-0018).
    CONFIDENCE_MATCH = "CONFIDENCE_MATCH"
    #: Um humano decidiu, na fila de revisão.
    MANUAL_REVIEW = "MANUAL_REVIEW"

    @property
    def is_exact(self) -> bool:
        return self in (
            ResolutionMethod.EXACT_PROVIDER_MAPPING,
            ResolutionMethod.EXACT_CANONICAL_KEY,
            ResolutionMethod.EXACT_ALIAS,
        )

    @property
    def is_human(self) -> bool:
        return self is ResolutionMethod.MANUAL_REVIEW


@final
@dataclass(frozen=True, slots=True, order=True)
class ResolutionConfidence:
    """Força da evidência, em [0,1]. NÃO é probabilidade.

    A DISTINÇÃO NÃO É ACADÊMICA. Uma probabilidade calibrada afirma que, de
    cem casos com confiança 0,9, noventa estarão certos — e essa afirmação
    exige um conjunto rotulado que não existe e que ninguém mediu. Publicar
    um número como se fosse probabilidade, sem calibração, é a forma mais
    fácil de o operador confiar num limiar que nunca foi verificado.

    O que este número significa, e só:

        a força da evidência usada nesta decisão, segundo a versão ATUAL do
        resolver e da política.

    Duas consequências disso, ambas deliberadas:

    - comparar confianças entre versões de resolver é comparar réguas
      diferentes, e `assert_comparable` na decisão recusa fazê-lo;
    - o limiar de auto-resolução é configuração versionada, não constante —
      porque ele é uma escolha de risco, não uma verdade medida.

    Quando houver corpus rotulado para calibrar de verdade, isto vira uma
    probabilidade com `CalibrationVersion` própria, e esta classe sai.
    """

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValidationError(
                f"confiança {self.value!r} fora de [0,1]"
            )
        object.__setattr__(self, "value", float(self.value))

    @classmethod
    def certain(cls) -> Self:
        """1,0 — reservada a casamento exato contra mapeamento ou chave.

        Nunca produzida por similaridade: um nome idêntico continua podendo
        ser de duas entidades diferentes.
        """
        return cls(1.0)

    @classmethod
    def none(cls) -> Self:
        return cls(0.0)

    def combined_with(self, other: ResolutionConfidence, *, weight: float) -> Self:
        """Combinação linear ponderada, determinística e sem surpresa.

        SEM PRODUTO DE PROBABILIDADES, que é a tentação: multiplicar
        confianças pressupõe independência entre evidências, e nome, país e
        competição não são independentes — clubes do mesmo país têm nomes
        parecidos. Multiplicar puniria evidências corroborantes.
        """
        if not 0.0 <= weight <= 1.0:
            raise ValidationError(f"peso {weight!r} fora de [0,1]")
        return type(self)(self.value * (1.0 - weight) + other.value * weight)

    def __str__(self) -> str:
        return f"{self.value:.3f}"


@final
@dataclass(frozen=True, slots=True)
class SourceValue:
    """O texto cru que a fonte trouxe, e onde ele estava.

    GUARDA O ORIGINAL E O NORMALIZADO. O normalizado é o que casou; o
    original é o que o operador reconhece ao abrir a fila de revisão. Guardar
    só o normalizado faria a fila mostrar `manchester city` para um humano
    que precisa reconhecer `Manchester City FC`.
    """

    raw: str
    normalized: str
    normalizer_version: NormalizerVersion

    def __post_init__(self) -> None:
        if not self.raw.strip():
            raise ValidationError("valor de fonte vazio")

    def __str__(self) -> str:
        return f"{self.raw!r} → {self.normalized!r}"


@final
@dataclass(frozen=True, slots=True)
class DecisionVersions:
    """As três versões que governam uma decisão automática.

    JUNTAS NUM OBJETO porque elas viajam juntas e são conferidas juntas:
    comparar duas decisões exige que as três batam. Espalhadas em três campos,
    a conferência vira três `if` que alguém esquece de escrever.
    """

    resolver: ResolverVersion
    normalizer: NormalizerVersion
    policy: PolicyVersion

    def assert_comparable(self, other: DecisionVersions) -> None:
        """Recusa comparar decisões produzidas por versões diferentes.

        Duas confianças de resolvers diferentes são réguas diferentes. Um
        diff entre elas descreve a mudança do código, não a mudança dos dados
        — a mesma armadilha que o ADR-0008 trata para features.
        """
        if self != other:
            raise ValidationError(
                f"decisões de versões diferentes não se comparam: {self} contra {other}"
            )

    def __str__(self) -> str:
        return f"{self.resolver}/{self.normalizer}/{self.policy}"


@final
@dataclass(frozen=True, slots=True)
class ResolutionInput:
    """De qual entrada exata esta decisão foi derivada.

    A IMPRESSÃO DO MANIFESTO É O QUE FECHA A LINHAGEM. Sem ela, «esta decisão
    veio do dataset X» é uma afirmação sobre um dataset que pode ter mudado
    desde então. Com ela, a pergunta «quais bytes produziram esta conclusão»
    é uma consulta (PR-02, ADR-0015).
    """

    dataset_id: DatasetId
    dataset_version: DatasetVersion
    manifest_fingerprint: ContentHash

    def __str__(self) -> str:
        return f"{self.dataset_id}@{self.dataset_version}#{self.manifest_fingerprint.short}"


@final
@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    """Uma decisão de identidade. Imutável, versionada e auditável."""

    id: str
    subject_type: SubjectType
    provider_id: ProviderId
    source_value: SourceValue
    status: ResolutionStatus
    method: ResolutionMethod
    confidence: ResolutionConfidence
    versions: DecisionVersions
    decided_at: Instant
    decided_by: Actor
    input_ref: ResolutionInput
    #: A referência do provedor, quando ele fornece um id próprio. É a
    #: evidência mais forte disponível — e continua sendo `ProviderRef`, não
    #: `EntityId`: a passagem entre os dois é ESTA decisão (ADR-0011).
    provider_ref: ProviderRef | None = None
    #: De QUAL LINHA esta decisão saiu — `dataset:arquivo:linha`.
    #:
    #: SEM ELE, A DECISÃO NÃO SE LIGA AO REGISTRO. `input_ref` diz de qual
    #: dataset e sob qual manifesto, o que responde «de quais bytes» e não
    #: responde «de qual linha». É por esta referência que a fusão descobre
    #: quais registros já têm identidade provada (ADR-0022) e é por ela que a
    #: procedência de um campo fundido volta ao arquivo bruto.
    #:
    #: `None` é legítimo para a decisão MANUAL: ela nasce de um item de fila,
    #: e o item guarda a referência do registro dele.
    record_ref: str | None = None
    #: A entidade canônica escolhida. `None` em tudo que não seja `RESOLVED`.
    canonical_entity_id: EntityId | None = None
    evidence: tuple[ResolutionEvidence, ...] = ()
    alternatives: tuple[ResolutionAlternative, ...] = ()
    #: Preenchido em `MANUAL_REVIEW` e em `REJECTED` por decisão humana.
    reason: str | None = None

    def __post_init__(self) -> None:
        # A REGRA CENTRAL: só `RESOLVED` produz referência canônica, e
        # `RESOLVED` sem referência é uma decisão que afirma ter resolvido
        # sem dizer para quê.
        if self.status.yields_canonical_reference and self.canonical_entity_id is None:
            raise ValidationError(
                "decisão RESOLVED sem entidade canônica: ela afirmaria ter resolvido "
                "sem dizer para o quê"
            )
        if not self.status.yields_canonical_reference and self.canonical_entity_id is not None:
            raise ValidationError(
                f"decisão {self.status} com entidade canônica — só RESOLVED produz "
                "referência utilizável, e uma referência aqui seria usada por engano"
            )
        if self.method.is_human and not (self.reason or "").strip():
            raise ValidationError(
                "decisão manual sem motivo: a fila de revisão existe para registrar "
                "por que um humano decidiu o que o motor não conseguiu"
            )
        if self.method.is_human and self.decided_by.is_automated:
            raise ValidationError(
                "decisão MANUAL_REVIEW atribuída a um ator de serviço — "
                "o método diz que um humano decidiu, e o ator diz que não"
            )
        if not self.method.is_human and not self.decided_by.is_automated:
            raise ValidationError(
                f"decisão {self.method} atribuída a um humano: métodos automáticos "
                "são executados por um ator de serviço, e a distinção é o que "
                "permite medir quanto do trabalho é automático"
            )
        # Uma decisão exata com confiança baixa é contradição interna: o
        # método afirma casamento exato, e o número diz que não confia nele.
        if self.method.is_exact and self.confidence.value < 1.0:
            raise ValidationError(
                f"método {self.method} com confiança {self.confidence} — "
                "casamento exato ou é exato ou não é"
            )

    @classmethod
    def resolved(
        cls,
        *,
        subject_type: SubjectType,
        provider_id: ProviderId,
        source_value: SourceValue,
        canonical_entity_id: EntityId,
        method: ResolutionMethod,
        confidence: ResolutionConfidence,
        versions: DecisionVersions,
        decided_at: Instant,
        decided_by: Actor,
        input_ref: ResolutionInput,
        provider_ref: ProviderRef | None = None,
        record_ref: str | None = None,
        evidence: tuple[ResolutionEvidence, ...] = (),
        alternatives: tuple[ResolutionAlternative, ...] = (),
        reason: str | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            subject_type=subject_type,
            provider_id=provider_id,
            source_value=source_value,
            status=ResolutionStatus.RESOLVED,
            method=method,
            confidence=confidence,
            versions=versions,
            decided_at=decided_at,
            decided_by=decided_by,
            input_ref=input_ref,
            provider_ref=provider_ref,
            record_ref=record_ref,
            canonical_entity_id=canonical_entity_id,
            evidence=evidence,
            alternatives=alternatives,
            reason=reason,
        )

    @classmethod
    def undecided(
        cls,
        *,
        subject_type: SubjectType,
        provider_id: ProviderId,
        source_value: SourceValue,
        status: ResolutionStatus,
        confidence: ResolutionConfidence,
        versions: DecisionVersions,
        decided_at: Instant,
        decided_by: Actor,
        input_ref: ResolutionInput,
        method: ResolutionMethod = ResolutionMethod.CONFIDENCE_MATCH,
        provider_ref: ProviderRef | None = None,
        record_ref: str | None = None,
        evidence: tuple[ResolutionEvidence, ...] = (),
        alternatives: tuple[ResolutionAlternative, ...] = (),
        reason: str | None = None,
    ) -> Self:
        """Uma decisão de NÃO resolver — que também é uma decisão.

        `UNRESOLVED`, `AMBIGUOUS` e `REVIEW_REQUIRED` são registrados com a
        mesma cerimônia de um `RESOLVED`: com evidência, alternativas e
        versão. Sem isso, a pergunta «por que este registro não resolveu»
        exigiria reexecutar o resolver — e o resolver já mudou.
        """
        if status.yields_canonical_reference:
            raise ValidationError(
                f"{status} não é um estado indeciso — use `resolved`"
            )
        return cls(
            id=str(uuid.uuid4()),
            subject_type=subject_type,
            provider_id=provider_id,
            source_value=source_value,
            status=status,
            method=method,
            confidence=confidence,
            versions=versions,
            decided_at=decided_at,
            decided_by=decided_by,
            input_ref=input_ref,
            provider_ref=provider_ref,
            record_ref=record_ref,
            evidence=evidence,
            alternatives=alternatives,
            reason=reason,
        )

    @property
    def is_automatic(self) -> bool:
        return not self.method.is_human

    @property
    def best_alternative(self) -> ResolutionAlternative | None:
        return self.alternatives[0] if self.alternatives else None

    def evidence_summary(self) -> str:
        """A reconstrução legível do raciocínio.

            + exact provider id
            + DOB matched
            - position mismatch

        É o que a fila de revisão mostra ao humano, e é montado a partir das
        evidências estruturadas — nunca de um texto livre gravado junto. Um
        texto livre vira a autoridade sobre o que aconteceu, e diverge do que
        de fato aconteceu no primeiro refactor.
        """
        if not self.evidence:
            return "(nenhuma evidência registrada)"
        return "\n".join(str(e) for e in self.evidence)

    def __str__(self) -> str:
        alvo = f" → {self.canonical_entity_id}" if self.canonical_entity_id else ""
        return (
            f"[{self.status}] {self.subject_type} {self.source_value.raw!r}{alvo} "
            f"· {self.method} · {self.confidence}"
        )


@final
@dataclass(frozen=True, slots=True)
class DecisionCounts:
    """O resumo de uma execução, por status.

    UM OBJETO E NÃO UM DICIONÁRIO: uma contagem que falta num dicionário é
    `KeyError` em produção; aqui é um campo com default zero, e a soma é
    conferida contra o total.
    """

    total: int = 0
    resolved: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    review_required: int = 0
    rejected: int = 0

    def with_status(self, status: ResolutionStatus) -> Self:
        campo = {
            ResolutionStatus.RESOLVED: "resolved",
            ResolutionStatus.UNRESOLVED: "unresolved",
            ResolutionStatus.AMBIGUOUS: "ambiguous",
            ResolutionStatus.REVIEW_REQUIRED: "review_required",
            ResolutionStatus.REJECTED: "rejected",
        }[status]
        valores = {
            "total": self.total + 1,
            "resolved": self.resolved,
            "unresolved": self.unresolved,
            "ambiguous": self.ambiguous,
            "review_required": self.review_required,
            "rejected": self.rejected,
        }
        valores[campo] += 1
        return type(self)(**valores)

    @property
    def needs_human(self) -> int:
        return self.ambiguous + self.review_required

    @property
    def automatic_rate(self) -> float | None:
        """Fração resolvida sem humano. `None` quando não houve registro.

        `None` E NÃO 0.0: uma execução sem registros não tem taxa, e informar
        zero faria um painel mostrar «0% automático» para um dataset vazio.
        """
        return self.resolved / self.total if self.total else None

    def assert_consistent(self) -> None:
        soma = (
            self.resolved
            + self.unresolved
            + self.ambiguous
            + self.review_required
            + self.rejected
        )
        if soma != self.total:
            raise ValidationError(
                f"contagens não fecham: {soma} por status contra {self.total} no total"
            )


#: Campos que a fila de revisão precisa ver e que não cabem numa linha.
MAX_ALTERNATIVES_STORED: Final[int] = 10

