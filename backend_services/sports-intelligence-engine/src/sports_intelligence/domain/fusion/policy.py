"""A política de fusão — por campo, e não uma precedência global.

POR QUE A PRECEDÊNCIA DO ADR-0009 NÃO BASTA SOZINHA. Ela ordena FONTES:
nativo, comercial, aberto, manual. É a resposta certa para «quem ganha quando
não há nada mais a dizer» e é a resposta errada para quase todo campo
específico, porque a qualidade de uma fonte não é uniforme:

    uma fonte pode ser a melhor em xG e não publicar escalação;
    outra tem escalação confiável e placar copiado de terceiros;
    uma terceira é a única com odds.

Uma precedência global faria a primeira vencer em escalação por ser
comercial — e a escalação dela é a pior das três.

Então: `FusionPolicy` declara preferência POR CAMPO, e a precedência global é
o que sobra quando o campo não tem política própria.

`INSIGHT_NATIVE` NÃO GANHA AUTOMATICAMENTE (§47). Ele vence por padrão porque
foi observado pelo próprio motor — mas um campo que o motor não observa
diretamente não deveria ganhar só pelo tipo da fonte. A política por campo
pode inverter isso, e a inversão é declarada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.fusion.models import FusionRule
from sports_intelligence.domain.resolution.versions import (
    CURRENT_FUSION_POLICY_VERSION,
    PolicyVersion,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import SourceType, precedence_rank
from sports_intelligence.domain.sources.semantics import SemanticRole


class ConflictResolution(StrEnum):
    """O que fazer quando as fontes divergem num campo.

    O DEFAULT É NÃO RESOLVER, e é a decisão mais importante deste módulo. Um
    default que escolhe alguma coisa faria todo campo sem política declarada
    produzir um valor de aparência decidida — e ninguém revisaria, porque
    nada apareceria como conflito.
    """

    #: Preserva as duas e não escolhe. O campo sai `CONFLICT_UNRESOLVED`.
    KEEP_UNRESOLVED = "KEEP_UNRESOLVED"
    #: A ordem de `preferred_sources` decide.
    PREFER_SOURCE = "PREFER_SOURCE"
    #: A qualidade declarada da fonte decide.
    PREFER_QUALITY = "PREFER_QUALITY"
    #: O valor com mais casas decimais vence. Para o caso em que a divergência
    #: é de arredondamento — `59.8` contra `60` —, não de fato.
    PREFER_PRECISION = "PREFER_PRECISION"
    #: A precedência global do ADR-0009 decide. Último recurso declarado.
    GLOBAL_PRECEDENCE = "GLOBAL_PRECEDENCE"


@final
@dataclass(frozen=True, slots=True)
class FieldPolicy:
    """A política de UM campo."""

    role: SemanticRole
    on_conflict: ConflictResolution = ConflictResolution.KEEP_UNRESOLVED
    #: Ordem de preferência entre provedores, quando `PREFER_SOURCE`.
    preferred_sources: tuple[ProviderId, ...] = ()
    #: Abaixo disto a contribuição é ignorada, mesmo sendo a única.
    minimum_quality: float | None = None
    #: Tolerância para considerar dois números o MESMO valor. `possession`
    #: 59.8 e 59.9 são a mesma observação com arredondamento diferente;
    #: `home_score` 2 e 3 nunca são.
    numeric_tolerance: float | None = None
    #: MÉDIA SÓ ONDE FOR SEMANTICAMENTE VÁLIDO, e por declaração explícita
    #: (§50). Nunca é o default: a média de dois placares é um placar que
    #: nenhuma fonte observou.
    allow_averaging: bool = False

    def __post_init__(self) -> None:
        if self.on_conflict is ConflictResolution.PREFER_SOURCE and not self.preferred_sources:
            raise ValidationError(
                f"{self.role}: PREFER_SOURCE sem lista de preferência — a política "
                "diz para preferir uma fonte e não diz qual"
            )
        if self.minimum_quality is not None and not 0.0 <= self.minimum_quality <= 1.0:
            raise ValidationError(f"{self.role}: qualidade mínima fora de [0,1]")
        if self.numeric_tolerance is not None and self.numeric_tolerance < 0:
            raise ValidationError(f"{self.role}: tolerância negativa")
        if self.allow_averaging and self.numeric_tolerance is None:
            raise ValidationError(
                f"{self.role}: média permitida sem tolerância declarada. Se dois "
                "valores podem ser promediados, precisa estar dito a que distância "
                "eles ainda descrevem a mesma coisa."
            )

    def rule_for_conflict(self) -> FusionRule:
        return {
            ConflictResolution.KEEP_UNRESOLVED: FusionRule.CONFLICT_UNRESOLVED,
            ConflictResolution.PREFER_SOURCE: FusionRule.PREFERRED_SOURCE,
            ConflictResolution.PREFER_QUALITY: FusionRule.HIGHEST_QUALITY,
            ConflictResolution.PREFER_PRECISION: FusionRule.MOST_PRECISE,
            ConflictResolution.GLOBAL_PRECEDENCE: FusionRule.PREFERRED_SOURCE,
        }[self.on_conflict]


@final
@dataclass(frozen=True, slots=True)
class FusionPolicy:
    """A política de fusão inteira, versionada e imutável.

    MUDAR UM CAMPO PUBLICA UMA POLÍTICA NOVA (ADR-0020). A execução que rodou
    sob a v1 continua explicável pela v1, e a diferença entre as saídas das
    duas é o que mostra o efeito da mudança — que é exatamente o que se quer
    poder medir antes de confiar nela.
    """

    version: PolicyVersion
    fields: dict[SemanticRole, FieldPolicy]
    #: Aplicada a campos sem política própria.
    default_conflict: ConflictResolution = ConflictResolution.KEEP_UNRESOLVED
    #: Papéis tratados como CONJUNTO DE OBSERVAÇÕES, nunca como escalar.
    observation_roles: frozenset[SemanticRole] = frozenset()

    def __post_init__(self) -> None:
        for papel, politica in self.fields.items():
            if politica.role is not papel:
                raise ValidationError(
                    f"política indexada como {papel} descreve {politica.role}"
                )
        sobrepostos = set(self.fields) & self.observation_roles
        if sobrepostos:
            raise ValidationError(
                f"papéis declarados como escalar E como observação: "
                f"{sorted(p.value for p in sobrepostos)}. As duas fusões são "
                "diferentes e um papel não pode passar pelas duas."
            )

    def for_field(self, role: SemanticRole) -> FieldPolicy:
        """A política de um campo, ou o default declarado.

        DEFAULT E NÃO ERRO: um mapeamento pode trazer um campo que a política
        não previa, e derrubar a fusão por isso impediria justamente o
        reprocessamento com fontes novas. O default preserva o conflito, que
        é a escolha segura.
        """
        return self.fields.get(role, FieldPolicy(role=role, on_conflict=self.default_conflict))

    def is_observation_set(self, role: SemanticRole) -> bool:
        return role in self.observation_roles or role.is_odds


def source_precedence_key(source_type: SourceType) -> int:
    """A precedência global do ADR-0009, como chave de ordenação.

    Reexportada aqui para que a política de fusão a use sem importar o módulo
    de procedência inteiro — e para que o ponto em que ela é aplicada seja
    um só, visível.
    """
    return precedence_rank(source_type)


#: A política que este PR entrega.
#:
#: O DEFAULT É `KEEP_UNRESOLVED` para tudo que não está listado, e as poucas
#: exceções abaixo têm o motivo escrito. É deliberadamente pouco: uma
#: política que resolve tudo automaticamente na primeira versão é uma
#: política que ninguém calibrou.
DEFAULT_FUSION_POLICY: Final[FusionPolicy] = FusionPolicy(
    version=CURRENT_FUSION_POLICY_VERSION,
    fields={
        # PLACAR NÃO SE RESOLVE POR PREFERÊNCIA. Duas fontes discordando do
        # placar significa que uma delas está errada sobre um fato público e
        # verificável — e escolher uma esconde um problema de fonte que
        # alguém precisa ver.
        SemanticRole.HOME_SCORE: FieldPolicy(
            role=SemanticRole.HOME_SCORE, on_conflict=ConflictResolution.KEEP_UNRESOLVED
        ),
        SemanticRole.AWAY_SCORE: FieldPolicy(
            role=SemanticRole.AWAY_SCORE, on_conflict=ConflictResolution.KEEP_UNRESOLVED
        ),
        # POSSE DE BOLA diverge por arredondamento: 59.8 e 60 descrevem a
        # mesma observação. Tolerância declarada e a mais precisa vence.
        SemanticRole.HOME_POSSESSION: FieldPolicy(
            role=SemanticRole.HOME_POSSESSION,
            on_conflict=ConflictResolution.PREFER_PRECISION,
            numeric_tolerance=1.5,
        ),
        SemanticRole.AWAY_POSSESSION: FieldPolicy(
            role=SemanticRole.AWAY_POSSESSION,
            on_conflict=ConflictResolution.PREFER_PRECISION,
            numeric_tolerance=1.5,
        ),
        # xG É MODELO, NÃO OBSERVAÇÃO. Duas fontes com xG diferente estão
        # rodando modelos diferentes, e escolher uma seria escolher um modelo
        # sem dizer qual. Fica em conflito até alguém declarar preferência.
        SemanticRole.HOME_XG: FieldPolicy(
            role=SemanticRole.HOME_XG, on_conflict=ConflictResolution.KEEP_UNRESOLVED
        ),
        SemanticRole.AWAY_XG: FieldPolicy(
            role=SemanticRole.AWAY_XG, on_conflict=ConflictResolution.KEEP_UNRESOLVED
        ),
        # FORMAÇÃO é rótulo declarado pela fonte, e `4-2-3-1` contra `4-3-3`
        # é desacordo de interpretação — não de fato (PR-01).
        SemanticRole.HOME_FORMATION: FieldPolicy(
            role=SemanticRole.HOME_FORMATION,
            on_conflict=ConflictResolution.KEEP_UNRESOLVED,
        ),
        SemanticRole.AWAY_FORMATION: FieldPolicy(
            role=SemanticRole.AWAY_FORMATION,
            on_conflict=ConflictResolution.KEEP_UNRESOLVED,
        ),
        # CHUTES divergem por critério de contagem. A precedência global
        # decide, porque aqui a fonte melhor tende a ser melhor no geral.
        SemanticRole.HOME_SHOTS: FieldPolicy(
            role=SemanticRole.HOME_SHOTS, on_conflict=ConflictResolution.GLOBAL_PRECEDENCE
        ),
        SemanticRole.AWAY_SHOTS: FieldPolicy(
            role=SemanticRole.AWAY_SHOTS, on_conflict=ConflictResolution.GLOBAL_PRECEDENCE
        ),
    },
    observation_roles=frozenset(
        {
            SemanticRole.ODDS_HOME,
            SemanticRole.ODDS_DRAW,
            SemanticRole.ODDS_AWAY,
            SemanticRole.BOOKMAKER_NAME,
        }
    ),
)
