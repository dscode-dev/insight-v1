"""As políticas de resolução — onde os limiares moram, e por que não no código.

`if score > 0.8:` ESPALHADO É O DEFEITO QUE ESTE MÓDULO EXISTE PARA IMPEDIR.
Ele tem três custos, e os três só aparecem tarde:

    o mesmo limiar escrito em cinco lugares vira cinco políticas que divergem
    na primeira vez que alguém ajusta uma;

    ajustar exige deploy, então na prática ninguém ajusta e alguém contorna;

    e — o pior — uma decisão gravada em janeiro não tem como dizer sob qual
    limiar foi tomada, porque o limiar não estava em lugar nenhum além do
    código de janeiro.

Então: limiares e pesos são CONFIGURAÇÃO VERSIONADA. Toda decisão grava a
`PolicyVersion` que a produziu, e mudar um número é publicar uma política
nova — não editar a antiga (ADR-0019).

O PRINCÍPIO QUE GOVERNA OS VALORES ESCOLHIDOS:

    Custo(falso merge) > Custo(não resolvido)

Um `PlayerId` errado contamina influência de jogador, força de elenco,
estados históricos e grafo tático — e a contaminação não é detectável depois,
porque tudo continua somando. Um registro não resolvido é visível, contável e
consertável. Por isso, na dúvida: `REVIEW_REQUIRED` (ADR-0018).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Self, final

from sports_intelligence.domain.resolution.decisions import (
    ResolutionConfidence,
    ResolutionStatus,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import EvidenceKind
from sports_intelligence.domain.resolution.versions import (
    CURRENT_MATCH_POLICY_VERSION,
    CURRENT_RESOLUTION_POLICY_VERSION,
    PolicyVersion,
)
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class SubjectPolicy:
    """Os limiares de UM tipo de sujeito.

    POR SUJEITO, e não um limiar global, porque o custo de errar é diferente
    por tipo. Competição tem catálogo fechado de cinco itens e casamento
    exato quase sempre; jogador tem homônimos e precisa de muito mais.
    """

    auto_resolve_threshold: float
    review_threshold: float
    #: Quantas evidências CORROBORANTES são necessárias para resolver
    #: sozinho. Uma só — o nome — nunca basta para jogador: é exatamente
    #: assim que dois homônimos viram um.
    minimum_evidence: int
    #: Evidências sem as quais não se resolve automaticamente, por mais alto
    #: que o score fique. Para jogador é o caso do nome sozinho.
    required_evidence: frozenset[EvidenceKind] = frozenset()
    #: Quantos candidatos descartados são guardados.
    alternative_limit: int = 5
    #: Distância mínima entre o primeiro e o segundo colocado. Sem ela, dois
    #: candidatos com 0,91 e 0,90 resolveriam para o primeiro — e a diferença
    #: de 0,01 não é informação, é ruído da régua.
    minimum_margin: float = 0.05

    def __post_init__(self) -> None:
        for nome in ("auto_resolve_threshold", "review_threshold", "minimum_margin"):
            valor = getattr(self, nome)
            if not 0.0 <= valor <= 1.0:
                raise ValidationError(f"{nome}={valor!r} fora de [0,1]")
        if self.review_threshold > self.auto_resolve_threshold:
            raise ValidationError(
                f"review_threshold ({self.review_threshold}) acima de "
                f"auto_resolve_threshold ({self.auto_resolve_threshold}): a faixa de "
                "revisão ficaria vazia e tudo resolveria ou nada resolveria"
            )
        if self.minimum_evidence < 1:
            raise ValidationError(
                "minimum_evidence menor que 1: uma decisão sem nenhuma evidência "
                "corroborante é um palpite"
            )
        if self.alternative_limit < 1:
            raise ValidationError(f"alternative_limit={self.alternative_limit} inválido")

    def classify(
        self,
        *,
        confidence: ResolutionConfidence,
        corroborating_evidence: int,
        margin: float,
        has_required_evidence: bool,
    ) -> ResolutionStatus:
        """A ÚNICA porta entre um score e um status.

        Ela é chamada por todos os resolvers, e é por isso que os limiares
        não precisam aparecer em nenhum deles. Um resolver que classificasse
        por conta própria criaria uma segunda política, invisível.

        A ORDEM DAS RECUSAS É DELIBERADA. As guardas duras vêm primeiro —
        evidência obrigatória e margem — e só depois o limiar. Assim um score
        alto obtido por uma evidência só nunca ultrapassa a exigência de
        corroboração: é o caso do homônimo, em que o nome bate perfeitamente
        e é justamente por isso que não se pode resolver.
        """
        if confidence.value < self.review_threshold:
            return ResolutionStatus.UNRESOLVED
        if not has_required_evidence:
            return ResolutionStatus.REVIEW_REQUIRED
        if corroborating_evidence < self.minimum_evidence:
            return ResolutionStatus.REVIEW_REQUIRED
        if margin < self.minimum_margin:
            # DOIS CANDIDATOS PRÓXIMOS DEMAIS. Escolher o primeiro seria
            # decidir por ruído da régua, e é assim que um merge errado
            # entra sem ninguém perceber.
            return ResolutionStatus.AMBIGUOUS
        if confidence.value < self.auto_resolve_threshold:
            return ResolutionStatus.REVIEW_REQUIRED
        return ResolutionStatus.RESOLVED


@final
@dataclass(frozen=True, slots=True)
class ResolutionPolicy:
    """A política de resolução inteira, versionada.

    OS PESOS TAMBÉM MORAM AQUI. `evidence_weights` diz quanto cada tipo de
    evidência vale; a evidência gravada carrega o peso que recebeu, para que
    reler uma decisão antiga não aplique os pesos de hoje ao raciocínio de
    ontem.
    """

    version: PolicyVersion
    subjects: dict[SubjectType, SubjectPolicy]
    evidence_weights: dict[EvidenceKind, float]

    def __post_init__(self) -> None:
        faltando = [s for s in SubjectType if s not in self.subjects]
        if faltando:
            raise ValidationError(
                f"política sem limiares para {sorted(s.value for s in faltando)}: "
                "um sujeito sem política resolveria sob regra nenhuma"
            )
        for tipo, peso in self.evidence_weights.items():
            if not 0.0 <= peso <= 1.0:
                raise ValidationError(f"peso de {tipo} fora de [0,1]: {peso!r}")

    def for_subject(self, subject: SubjectType) -> SubjectPolicy:
        return self.subjects[subject]

    def weight_of(self, kind: EvidenceKind) -> float:
        """O peso de uma evidência. Zero quando a política não a conhece.

        ZERO E NÃO ERRO: um resolver novo pode consultar uma evidência que a
        política antiga não previa, e derrubar a execução por isso impediria
        exatamente o reprocessamento que o PR existe para permitir. Peso zero
        significa «esta política não dá valor a isso», que é a resposta certa.
        """
        return self.evidence_weights.get(kind, 0.0)


@final
@dataclass(frozen=True, slots=True)
class MatchResolutionPolicy:
    """Os pesos e tolerâncias da resolução de partida.

    SEPARADA DA POLÍTICA GERAL porque a resolução de partida é a única que
    compõe um score a partir de sete dimensões, com tolerância temporal e uma
    regra própria sobre inversão de mando. Enfiá-la na política geral faria a
    política de competição carregar campos que não usa.
    """

    version: PolicyVersion
    #: Pesos das dimensões. Precisam somar 1,0 — verificado, porque um
    #: conjunto que soma 0,8 produz um score que nunca alcança o limiar, e o
    #: sintoma é «nada resolve» sem nenhuma pista de por quê.
    competition_weight: float = 0.22
    season_weight: float = 0.14
    home_team_weight: float = 0.20
    away_team_weight: float = 0.20
    kickoff_weight: float = 0.16
    stage_weight: float = 0.04
    round_weight: float = 0.02
    venue_weight: float = 0.02

    #: Tolerância de horário. Fontes divergem em minutos por arredondamento e
    #: por hora cheia; divergem em horas por fuso não declarado.
    kickoff_exact_tolerance: timedelta = timedelta(minutes=15)
    kickoff_loose_tolerance: timedelta = timedelta(hours=3)
    #: Além disto, o horário é evidência CONTRÁRIA, não fraca.
    kickoff_max_tolerance: timedelta = timedelta(hours=26)

    #: COMPETIÇÃO É EVIDÊNCIA DURA. Dois jogos entre os mesmos times na mesma
    #: data em competições diferentes existem — copa e liga, mata-mata e
    #: torneio amistoso. Sem esta trava, eles seriam fundidos.
    competition_must_match: bool = True
    #: Temporada idem: o mesmo confronto acontece todo ano.
    season_must_match: bool = True

    #: Inversão de mando NUNCA é corrigida automaticamente (§24). Ela produz
    #: candidato com penalidade, e a penalidade é grande o bastante para
    #: derrubar o score para a faixa de revisão.
    reversed_sides_penalty: float = 0.35
    allow_reversed_sides_auto_resolve: bool = False

    def __post_init__(self) -> None:
        soma = (
            self.competition_weight
            + self.season_weight
            + self.home_team_weight
            + self.away_team_weight
            + self.kickoff_weight
            + self.stage_weight
            + self.round_weight
            + self.venue_weight
        )
        if abs(soma - 1.0) > 1e-9:
            raise ValidationError(
                f"os pesos de partida somam {soma:.4f} e precisam somar 1,0 — "
                "um conjunto que não soma produz score que nunca alcança o limiar, "
                "e o sintoma é 'nada resolve' sem pista nenhuma"
            )
        if self.kickoff_exact_tolerance > self.kickoff_loose_tolerance:
            raise ValidationError("tolerância exata maior que a frouxa")
        if self.kickoff_loose_tolerance > self.kickoff_max_tolerance:
            raise ValidationError("tolerância frouxa maior que o teto")
        if not 0.0 <= self.reversed_sides_penalty <= 1.0:
            raise ValidationError("penalidade de inversão fora de [0,1]")

    def kickoff_score(self, delta: timedelta) -> float:
        """Quanto o horário contribui, dado o afastamento.

        TRÊS FAIXAS E NÃO UMA FUNÇÃO CONTÍNUA. Uma curva suave daria a
        impressão de precisão que não existe: a diferença entre 14 e 16
        minutos não é informação, e entre 15 minutos e 3 horas é.

            ≤ exata     1,00   arredondamento, hora cheia
            ≤ frouxa    0,50   fuso provavelmente não declarado
            ≤ teto      0,15   mesmo dia, horário muito diferente
            acima       0,00   outra partida
        """
        absoluto = abs(delta)
        if absoluto <= self.kickoff_exact_tolerance:
            return 1.0
        if absoluto <= self.kickoff_loose_tolerance:
            return 0.5
        if absoluto <= self.kickoff_max_tolerance:
            return 0.15
        return 0.0


#: A política que este PR entrega. Os números abaixo são escolhas de RISCO,
#: não verdades medidas — e cada um tem o motivo escrito.
DEFAULT_RESOLUTION_POLICY: Final[ResolutionPolicy] = ResolutionPolicy(
    version=CURRENT_RESOLUTION_POLICY_VERSION,
    subjects={
        # Catálogo fechado de cinco, com aliases explícitos. Ou casa exato,
        # ou é uma competição que não cobrimos.
        SubjectType.COMPETITION: SubjectPolicy(
            auto_resolve_threshold=0.95,
            review_threshold=0.75,
            minimum_evidence=1,
            alternative_limit=3,
            minimum_margin=0.10,
        ),
        # Temporada depende da competição, e o rótulo `2024` significa coisas
        # diferentes em ligas de ano civil e de ano cruzado.
        SubjectType.SEASON: SubjectPolicy(
            auto_resolve_threshold=0.90,
            review_threshold=0.60,
            minimum_evidence=2,
            required_evidence=frozenset({EvidenceKind.COMPETITION}),
            alternative_limit=3,
        ),
        SubjectType.TEAM: SubjectPolicy(
            auto_resolve_threshold=0.92,
            review_threshold=0.65,
            minimum_evidence=2,
            alternative_limit=5,
            minimum_margin=0.08,
        ),
        # O MAIS CONSERVADOR DOS CINCO, de longe. Homônimo é comum no
        # futebol, e um `PlayerId` errado contamina de forma irreversível.
        # `minimum_evidence=3` significa: nome mais duas outras coisas.
        SubjectType.PLAYER: SubjectPolicy(
            auto_resolve_threshold=0.96,
            review_threshold=0.55,
            minimum_evidence=3,
            alternative_limit=8,
            minimum_margin=0.12,
        ),
        SubjectType.MATCH: SubjectPolicy(
            auto_resolve_threshold=0.90,
            review_threshold=0.60,
            minimum_evidence=3,
            required_evidence=frozenset({EvidenceKind.COMPETITION, EvidenceKind.SEASON}),
            alternative_limit=5,
            minimum_margin=0.10,
        ),
    },
    evidence_weights={
        # Mapeamento de provedor é a única evidência que decide sozinha:
        # alguém já tomou esta decisão antes e ela ficou registrada.
        EvidenceKind.PROVIDER_MAPPING: 1.00,
        EvidenceKind.CANONICAL_KEY: 0.95,
        EvidenceKind.ALIAS: 0.90,
        # Similaridade NUNCA é autoridade sozinha. O peso é alto o bastante
        # para levar à revisão e baixo o bastante para não resolver.
        EvidenceKind.NAME_SIMILARITY: 0.55,
        EvidenceKind.DATE_OF_BIRTH: 0.80,
        EvidenceKind.TEAM_AT_DATE: 0.65,
        EvidenceKind.NATIONALITY: 0.35,
        EvidenceKind.COUNTRY: 0.40,
        EvidenceKind.POSITION: 0.20,
        EvidenceKind.COMPETITION: 0.70,
        EvidenceKind.SEASON: 0.60,
        EvidenceKind.HOME_TEAM: 0.75,
        EvidenceKind.AWAY_TEAM: 0.75,
        EvidenceKind.KICKOFF: 0.65,
        EvidenceKind.STAGE: 0.25,
        EvidenceKind.ROUND: 0.20,
        EvidenceKind.HISTORICAL_PARTICIPATION: 0.45,
        # Estádio e placar são APOIO. Campo neutro, punição e mudança
        # logística fazem uma partida legítima acontecer em outro lugar; e
        # dois jogos podem terminar 1-1.
        EvidenceKind.VENUE: 0.15,
        EvidenceKind.SCORE_OBSERVATION: 0.10,
    },
)

DEFAULT_MATCH_POLICY: Final[MatchResolutionPolicy] = MatchResolutionPolicy(
    version=CURRENT_MATCH_POLICY_VERSION
)


def stricter_for_reprocessing(base: ResolutionPolicy, version: PolicyVersion) -> ResolutionPolicy:
    """Uma política mais conservadora, derivada da atual.

    EXISTE PARA O CASO REAL: alguém descobre um merge errado em produção e
    precisa reprocessar com o limiar mais alto, sem reescrever a política que
    já governou decisões gravadas. Isto produz uma política NOVA, com versão
    nova — e as decisões antigas continuam explicáveis pela antiga.
    """
    return ResolutionPolicy(
        version=version,
        subjects={
            tipo: SubjectPolicy(
                auto_resolve_threshold=min(1.0, p.auto_resolve_threshold + 0.03),
                review_threshold=p.review_threshold,
                minimum_evidence=p.minimum_evidence + 1,
                required_evidence=p.required_evidence,
                alternative_limit=p.alternative_limit,
                minimum_margin=min(1.0, p.minimum_margin + 0.05),
            )
            for tipo, p in base.subjects.items()
        },
        evidence_weights=dict(base.evidence_weights),
    )



@final
@dataclass(frozen=True, slots=True)
class ResolutionThresholds:
    """A visão resumida de uma política, para relatório e API.

    Sem ela, expor a política significaria serializar dicionários aninhados
    de enums — e a API do Control Plane passaria a depender da forma interna
    da política.
    """

    version: PolicyVersion
    per_subject: dict[str, tuple[float, float, int]]

    @classmethod
    def of(cls, policy: ResolutionPolicy) -> Self:
        return cls(
            version=policy.version,
            per_subject={
                tipo.value: (
                    p.auto_resolve_threshold,
                    p.review_threshold,
                    p.minimum_evidence,
                )
                for tipo, p in sorted(policy.subjects.items(), key=lambda kv: kv[0].value)
            },
        )
