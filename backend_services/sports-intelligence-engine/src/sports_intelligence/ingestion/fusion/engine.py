"""O motor de fusão: agrupa por identidade provada, funde campo a campo.

A ORDEM É OBRIGATÓRIA E O TIPO A IMPÕE (ADR-0022):

    identidade resolvida  →  agrupamento  →  fusão

`group` aceita `ResolvedSourceRecord`, que não se constrói sem
`resolution_decision_id`. Não há caminho de código que funda registros cuja
identidade não foi provada — a regra deixou de ser convenção e virou
assinatura.

O QUE O MOTOR NÃO FAZ:

    não escolhe quando a política não diz como     `CONFLICT_UNRESOLVED`
    não tira média                                  salvo declaração explícita
    não funde odds de casas diferentes              são observações distintas
    não descarta o valor perdedor                   alternativas ficam sempre

CADA CAMPO SAI COM PROCEDÊNCIA. `home_score = 2` vem com dataset, arquivo e
linha de cada fonte que o disse — e de cada uma que disse outra coisa.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Final, final

from sports_intelligence.domain.fusion.models import (
    ODDS_OBSERVATION_KIND,
    CanonicalFieldCandidate,
    FieldContribution,
    FusionGroup,
    FusionRule,
    Observation,
    ObservationSet,
    ResolvedSourceRecord,
)
from sports_intelligence.domain.fusion.policy import (
    ConflictResolution,
    FieldPolicy,
    FusionPolicy,
    source_precedence_key,
)
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate, FusionCounts
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.sources.semantics import SemanticRole

#: O tipo do conjunto de observações de odds. Reexportado do domínio, onde ele
#: passou a morar no PR-04.2: quem LÊ um candidato fundido — a avaliação de
#: qualidade, a construção canônica — precisa reconhecer o conjunto sem
#: importar este motor para isso.
ODDS_SET_KIND: Final[str] = ODDS_OBSERVATION_KIND


def group_by_identity(
    records: tuple[ResolvedSourceRecord, ...],
) -> tuple[tuple[FusionGroup, ...], tuple[ResolvedSourceRecord, ...]]:
    """Agrupa registros resolvidos pela entidade canônica.

    DEVOLVE OS DESCARTADOS JUNTO, e é a metade que costuma faltar. Duas
    linhas da MESMA fonte dizendo o placar da mesma partida são duplicata
    interna — não duas confirmações — e contá-las inflaria a concordância.

    MAS «MESMA FONTE» NÃO IMPLICA «MESMA OBSERVAÇÃO» (§5). Uma fonte que
    publica uma linha por casa de apostas manda `Bet365 @ 2.00` e
    `Pinnacle @ 2.05` como duas linhas, e as duas são verdade ao mesmo tempo.
    Descartar a segunda — que era o comportamento até o PR-03.1 — apaga
    justamente a dispersão entre casas, que é o sinal.

    Então a segunda linha de uma fonte tem três destinos possíveis, e a
    `observation_identity` decide qual:

        identidade NOVA          contribui como observação extra
        identidade REPETIDA      duplicata verdadeira — descartada (§11)
        SEM identidade           não é observação: duplicata escalar
    """
    por_entidade: dict[str, list[ResolvedSourceRecord]] = defaultdict(list)
    for registro in records:
        por_entidade[str(registro.canonical_entity_id)].append(registro)

    grupos: list[FusionGroup] = []
    descartados: list[ResolvedSourceRecord] = []
    for chave in sorted(por_entidade):
        do_grupo = sorted(
            por_entidade[chave], key=lambda r: (str(r.provider_id), str(r.record_ref))
        )
        principais: dict[str, ResolvedSourceRecord] = {}
        extras: list[ResolvedSourceRecord] = []
        identidades: set[str] = set()
        for registro in do_grupo:
            provedor = str(registro.provider_id)
            identidade = registro.observation_identity
            if provedor not in principais:
                principais[provedor] = registro
                if identidade is not None:
                    identidades.add(identidade)
                continue
            if identidade is None or identidade in identidades:
                descartados.append(registro)
                continue
            identidades.add(identidade)
            extras.append(registro)

        entidade = next(iter(principais.values())).canonical_entity_id
        if not isinstance(entidade, MatchId):
            raise ValidationError(
                f"agrupamento de fusão recebeu {type(entidade).__name__}; a V1 funde partidas"
            )
        grupos.append(FusionGroup.of(entidade, tuple(principais.values()), tuple(extras)))
    return tuple(grupos), tuple(descartados)


@final
class FusionEngine:
    """Funde um grupo em um candidato canônico, sob política versionada."""

    def __init__(self, policy: FusionPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> FusionPolicy:
        return self._policy

    def fuse(self, group: FusionGroup) -> FusedMatchCandidate:
        """O candidato de um grupo. Determinístico sobre o grupo e a política."""
        from sports_intelligence.domain.fusion.runs import assert_group_is_fully_resolved

        assert_group_is_fully_resolved(group)

        papeis = sorted(
            {papel for registro in group.records for papel in registro.values},
            key=lambda p: p.value,
        )
        campos: list[CanonicalFieldCandidate] = []
        observacoes: list[Observation] = []

        for papel in papeis:
            if self._policy.is_observation_set(papel):
                continue
            contribuicoes = group.contributions_for(papel)
            if not contribuicoes:
                continue
            campos.append(self._fundir_campo(papel, contribuicoes))

        observacoes.extend(self._observacoes_de_odds(group))
        conjuntos = (
            (ObservationSet.deduplicated(ODDS_SET_KIND, tuple(observacoes)),) if observacoes else ()
        )
        return FusedMatchCandidate(
            canonical_match_id=group.canonical_match_id,
            group_id=group.id,
            fields=tuple(campos),
            observation_sets=conjuntos,
        )

    # ------------------------------------------------------ fusão escalar --

    def _fundir_campo(
        self, papel: SemanticRole, contribuicoes: tuple[FieldContribution, ...]
    ) -> CanonicalFieldCandidate:
        politica = self._policy.for_field(papel)
        aceitas = self._filtrar_por_qualidade(contribuicoes, politica)
        if not aceitas:
            # TODAS ABAIXO DA QUALIDADE MÍNIMA. O campo fica em conflito não
            # resolvido com as contribuições originais — descartá-lo apagaria
            # o fato de que as fontes disseram algo e foi rejeitado.
            return CanonicalFieldCandidate(
                field_name=papel,
                rule=FusionRule.CONFLICT_UNRESOLVED,
                contributions=contribuicoes,
            )

        distintos = self._valores_distintos(aceitas, politica)
        if len(distintos) == 1:
            valor = aceitas[0].value
            concordantes = [c for c in aceitas if self._equivalentes(c.value, valor, politica)]
            regra = (
                FusionRule.EXACT_AGREEMENT if len(concordantes) > 1 else FusionRule.MOST_COMPLETE
            )
            escolhida = max(concordantes, key=lambda c: (c.precision or 0, str(c.provider_id)))
            return CanonicalFieldCandidate(
                field_name=papel,
                rule=regra,
                contributions=contribuicoes,
                selected_value=escolhida.value,
                selected_from=escolhida.provider_id,
                # CONCORDÂNCIA ENTRE FONTES AUMENTA A CONFIANÇA, e é o motivo
                # de `EXACT_AGREEMENT` existir como regra própria: três fontes
                # dizendo 2 não é o mesmo que uma dizendo 2.
                confidence=min(1.0, 0.6 + 0.2 * len(concordantes)),
            )

        return self._resolver_conflito(papel, contribuicoes, aceitas, politica)

    def _resolver_conflito(
        self,
        papel: SemanticRole,
        todas: tuple[FieldContribution, ...],
        aceitas: tuple[FieldContribution, ...],
        politica: FieldPolicy,
    ) -> CanonicalFieldCandidate:
        escolhida = self._escolher(aceitas, politica)
        if escolhida is None:
            return CanonicalFieldCandidate(
                field_name=papel, rule=FusionRule.CONFLICT_UNRESOLVED, contributions=todas
            )
        return CanonicalFieldCandidate(
            field_name=papel,
            rule=politica.rule_for_conflict(),
            contributions=todas,
            selected_value=escolhida.value,
            selected_from=escolhida.provider_id,
            # CONFIANÇA BAIXA NUM CAMPO EM CONFLITO, mesmo quando a política
            # sabe escolher: a escolha resolveu quem vence, e não a
            # discordância entre as fontes.
            confidence=0.5,
        )

    def _escolher(
        self, contribuicoes: tuple[FieldContribution, ...], politica: FieldPolicy
    ) -> FieldContribution | None:
        """Aplica a estratégia de conflito. `None` = não resolver.

        TODO DESEMPATE TERMINA NO ID DO PROVEDOR, e é o que torna a fusão
        reproduzível: duas contribuições com a mesma precisão e a mesma
        qualidade sairiam do banco em ordem arbitrária, e sem desempate
        explícito a mesma entrada produziria saídas diferentes (§92).
        """
        if politica.on_conflict is ConflictResolution.KEEP_UNRESOLVED:
            return None
        if politica.on_conflict is ConflictResolution.PREFER_SOURCE:
            for preferida in politica.preferred_sources:
                achada = next((c for c in contribuicoes if c.provider_id == preferida), None)
                if achada is not None:
                    return achada
            # NENHUMA PREFERIDA CONTRIBUIU. Cair para outra estratégia seria
            # aplicar uma regra que a política não declarou.
            return None
        if politica.on_conflict is ConflictResolution.PREFER_QUALITY:
            com_qualidade = [c for c in contribuicoes if c.quality is not None]
            if not com_qualidade:
                return None
            return max(com_qualidade, key=lambda c: (c.quality or 0.0, str(c.provider_id)))
        if politica.on_conflict is ConflictResolution.PREFER_PRECISION:
            com_precisao = [c for c in contribuicoes if c.precision is not None]
            if not com_precisao:
                return None
            return max(com_precisao, key=lambda c: (c.precision or 0, str(c.provider_id)))
        return min(
            contribuicoes,
            key=lambda c: (source_precedence_key(c.source_type), str(c.provider_id)),
        )

    @staticmethod
    def _filtrar_por_qualidade(
        contribuicoes: tuple[FieldContribution, ...], politica: FieldPolicy
    ) -> tuple[FieldContribution, ...]:
        if politica.minimum_quality is None:
            return contribuicoes
        return tuple(
            c
            for c in contribuicoes
            # QUALIDADE AUSENTE NÃO É QUALIDADE ZERO. Uma fonte que não
            # declara qualidade não está declarando qualidade ruim, e
            # descartá-la aqui puniria a ausência de metadado.
            if c.quality is None or c.quality >= politica.minimum_quality
        )

    def _valores_distintos(
        self, contribuicoes: tuple[FieldContribution, ...], politica: FieldPolicy
    ) -> tuple[str, ...]:
        """Os valores que a política considera DIFERENTES entre si.

        `59.8` e `60` são o mesmo valor quando a tolerância é 1,5 e são dois
        valores quando não há tolerância. É a política que decide, porque a
        resposta depende do campo: posse de bola tolera arredondamento,
        placar não.
        """
        distintos: list[str] = []
        for contribuicao in contribuicoes:
            if not any(self._equivalentes(contribuicao.value, v, politica) for v in distintos):
                distintos.append(contribuicao.value)
        return tuple(distintos)

    @staticmethod
    def _equivalentes(a: str, b: str, politica: FieldPolicy) -> bool:
        if a == b:
            return True
        if politica.numeric_tolerance is None:
            return False
        try:
            return abs(Decimal(a) - Decimal(b)) <= Decimal(str(politica.numeric_tolerance))
        except (InvalidOperation, ValueError):
            return False

    # -------------------------------------------- fusão de observações --

    def _observacoes_de_odds(self, group: FusionGroup) -> list[Observation]:
        """Odds viram observações, uma por (fonte, casa, mercado).

        NUNCA UM VALOR ESCOLHIDO. Duas casas cotando 2,00 e 2,05 não estão em
        conflito — estão dizendo coisas diferentes sobre o mesmo jogo, e as
        duas são verdade. A dispersão entre elas é o sinal que o Odds
        Intelligence vai ler, e uma média a apagaria (§54, §90).
        """
        saida: list[Observation] = []
        for registro in group.observation_records:
            cotacoes = {
                papel: valor
                for papel in (
                    SemanticRole.ODDS_HOME,
                    SemanticRole.ODDS_DRAW,
                    SemanticRole.ODDS_AWAY,
                )
                if (valor := registro.values.get(papel)) is not None and valor.strip()
            }
            if not cotacoes:
                continue
            casa = registro.values.get(SemanticRole.BOOKMAKER_NAME) or str(registro.provider_id)
            valores = "|".join(
                f"{papel.value}={valor}" for papel, valor in sorted(cotacoes.items())
            )
            saida.append(
                Observation(
                    # O DISCRIMINANTE INCLUI A CASA **E OS VALORES**.
                    #
                    # A casa impede que a segunda cotação seja descartada como
                    # repetição da primeira. Os valores impedem o oposto: duas
                    # cotações DIFERENTES da mesma casa — o tick seguinte —
                    # colapsariam numa só se a chave fosse só a casa.
                    #
                    # O que continua colapsando, e deve: a MESMA cotação da
                    # MESMA casa trazida por duas fontes distintas. É uma
                    # observação só, e as duas fontes a confirmam.
                    discriminator=f"1X2|{casa}|{valores}",
                    values={papel.value: valor for papel, valor in sorted(cotacoes.items())},
                    record_ref=registro.record_ref,
                    provider_id=registro.provider_id,
                    license_class=registro.license_class,
                )
            )
        return saida


def count_fusion(
    candidatos: tuple[FusedMatchCandidate, ...], grupos: tuple[FusionGroup, ...]
) -> FusionCounts:
    """As contagens de uma execução de fusão."""
    campos = sum(len(c.fields) for c in candidatos)
    conflitos = sum(1 for c in candidatos for f in c.fields if f.rule.had_conflict)
    nao_resolvidos = sum(len(c.unresolved_conflicts) for c in candidatos)
    return FusionCounts(
        groups=len(grupos),
        multi_source_groups=sum(1 for g in grupos if g.is_multi_source),
        fields_selected=campos,
        conflicts=conflitos,
        unresolved_conflicts=nao_resolvidos,
        observation_sets=sum(len(c.observation_sets) for c in candidatos),
    )
