"""Os cinco resolvers. Puros sobre o contexto, determinísticos, sem I/O.

A FORMA É A MESMA NOS CINCO, e é deliberado:

    1. mapeamento de provedor?      decide sozinho, confiança 1,0
    2. casamento exato?             chave canônica ou alias
    3. candidatos por similaridade  cada um com suas evidências
    4. score e margem               a política classifica
    5. decisão                      com evidência, alternativas e versões

O passo 4 é o único que decide status, e ele está na política — nenhum
resolver escreve um limiar. É o que garante que os cinco sejam conservadores
da mesma forma, e que afrouxar um limiar seja uma mudança de política com
versão, não uma linha num arquivo.

SEM I/O NENHUM. Tudo que os resolvers leem veio do `ResolutionContext`,
carregado em massa antes do lote. É o que mata o N+1 e é também o que torna
cada resolver testável com uma entrada fixa e nenhuma infraestrutura.

DETERMINÍSTICOS. Nenhum `random`, nenhuma leitura de relógio interna, e todo
desempate explícito — por score, depois por id. Reprocessar o mesmo lote com
as mesmas versões produz exatamente as mesmas decisões, na mesma ordem (§33).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, final

from sports_intelligence.domain.competitions.catalog import (
    CATALOG,
    CompetitionCode,
    resolve_code,
)
from sports_intelligence.domain.resolution.decisions import (
    ResolutionConfidence,
    ResolutionMethod,
    ResolutionStatus,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import (
    EvidenceKind,
    ExplanationCode,
    ResolutionAlternative,
    ResolutionEvidence,
    rank_alternatives,
)
from sports_intelligence.domain.resolution.policy import (
    MatchResolutionPolicy,
    ResolutionPolicy,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    EntityId,
    PlayerId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.sources.mapping import SeasonConvention
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from sports_intelligence.ingestion.normalization.similarity import StringSimilarity
from sports_intelligence.ingestion.resolution.context import (
    NormalizedName,
    ResolutionContext,
)
from sports_intelligence.ingestion.resolution.seasons import (
    SeasonHint,
    parse_season_label,
)

#: CORTE DE CANDIDATO — não de decisão. Abaixo disto, a entidade nem vira
#: candidata: sem ele, cada nome de fonte produziria um candidato por entidade
#: do registro, e a fila de revisão receberia listas de centenas.
#:
#: NÃO É UM LIMIAR DE STATUS. Quem decide entre resolver, revisar e recusar é
#: a política, e nenhum resolver escreve esse número (§9).
_CORTE_DE_CANDIDATO_TIME: Final[float] = 0.55
_CORTE_DE_CANDIDATO_JOGADOR: Final[float] = 0.70

#: Acima disto a evidência de nome é rotulada `SIMILAR_NAME`; abaixo,
#: `NAME_TOO_DIFFERENT`. É um RÓTULO para a fila de revisão — o peso da
#: evidência é proporcional à similaridade e vem da política.
_ROTULO_DE_NOME_SIMILAR: Final[float] = 0.80


@final
@dataclass(frozen=True, slots=True)
class Outcome:
    """O que um resolver conclui, antes de virar `ResolutionDecision`.

    SEPARADO DA DECISÃO de propósito: a decisão precisa de relógio, ator,
    versões e referência de entrada — coisas da camada de aplicação. O
    resolver produz o raciocínio; o caso de uso o carimba. Assim os resolvers
    continuam puros e testáveis sem montar meia aplicação.
    """

    status: ResolutionStatus
    method: ResolutionMethod
    confidence: ResolutionConfidence
    evidence: tuple[ResolutionEvidence, ...]
    alternatives: tuple[ResolutionAlternative, ...] = ()
    entity_id: EntityId | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status.yields_canonical_reference and self.entity_id is None:
            raise ValidationError("resultado RESOLVED sem entidade")

    @classmethod
    def rejected(cls, evidence: tuple[ResolutionEvidence, ...], reason: str) -> Outcome:
        return cls(
            status=ResolutionStatus.REJECTED,
            method=ResolutionMethod.COMPOSITE_RULE,
            confidence=ResolutionConfidence.none(),
            evidence=evidence,
            reason=reason,
        )

    @classmethod
    def unresolved(cls, evidence: tuple[ResolutionEvidence, ...]) -> Outcome:
        return cls(
            status=ResolutionStatus.UNRESOLVED,
            method=ResolutionMethod.CONFIDENCE_MATCH,
            confidence=ResolutionConfidence.none(),
            evidence=evidence,
        )

    @classmethod
    def exact(
        cls,
        entity: EntityId,
        method: ResolutionMethod,
        evidence: tuple[ResolutionEvidence, ...],
    ) -> Outcome:
        """Casamento exato: confiança 1,0 e nenhuma alternativa.

        SEM ALTERNATIVAS DE PROPÓSITO. Um mapeamento de provedor não tem
        segundo colocado — ou existe, ou não existe. Listar candidatos
        próximos ao lado dele sugeriria uma dúvida que não há.
        """
        return cls(
            status=ResolutionStatus.RESOLVED,
            method=method,
            confidence=ResolutionConfidence.certain(),
            evidence=evidence,
            entity_id=entity,
        )


@final
@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """Um candidato pontuado, com o raciocínio que produziu o score."""

    entity_id: EntityId
    score: float
    evidence: tuple[ResolutionEvidence, ...]
    label: str | None = None

    @property
    def corroborating(self) -> int:
        return sum(1 for e in self.evidence if e.contributes)

    def summary(self) -> str:
        return " ".join(
            f"{'+' if e.contributes else '-'}{e.kind}"
            for e in self.evidence
            if e.contributes or e.contradicts
        )


def classify(
    candidates: tuple[ScoredCandidate, ...],
    *,
    policy: ResolutionPolicy,
    subject: SubjectType,
    required: frozenset[EvidenceKind] | None = None,
) -> Outcome:
    """Transforma candidatos pontuados numa decisão, PELA POLÍTICA.

    A ORDENAÇÃO É DETERMINÍSTICA — score decrescente, depois id — e é o que
    torna o reprocessamento reproduzível: dois candidatos com o mesmo score
    saem do banco em ordem arbitrária, e sem desempate explícito a mesma
    entrada produziria decisões diferentes em execuções diferentes.
    """
    regras = policy.for_subject(subject)
    if not candidates:
        return Outcome.unresolved(
            (
                ResolutionEvidence.unavailable(
                    EvidenceKind.NAME_SIMILARITY,
                    explanation=ExplanationCode.NO_CANDIDATES,
                ),
            )
        )

    ordenados = sorted(candidates, key=lambda c: (-c.score, str(c.entity_id)))
    melhor = ordenados[0]
    margem = melhor.score - (ordenados[1].score if len(ordenados) > 1 else 0.0)
    exigidas = required if required is not None else regras.required_evidence
    presentes = {e.kind for e in melhor.evidence if e.contributes}

    status = regras.classify(
        confidence=ResolutionConfidence(melhor.score),
        corroborating_evidence=melhor.corroborating,
        margin=margem if len(ordenados) > 1 else 1.0,
        has_required_evidence=exigidas <= presentes,
    )
    alternativas = rank_alternatives(
        tuple(
            ResolutionAlternative(
                canonical_entity_id=c.entity_id,
                score=c.score,
                evidence_summary=c.summary(),
                label=c.label,
            )
            for c in ordenados
        ),
        limit=regras.alternative_limit,
    )
    return Outcome(
        status=status,
        method=ResolutionMethod.CONFIDENCE_MATCH,
        confidence=ResolutionConfidence(melhor.score),
        evidence=melhor.evidence,
        alternatives=alternativas,
        entity_id=melhor.entity_id if status.yields_canonical_reference else None,
    )


# ============================================================ competição ====


@final
class CompetitionResolver:
    """Cinco competições, catálogo fechado, aliases explícitos.

    SEM FUZZY IRRESTRITO (§14). O catálogo tem cinco itens e nomes muito
    distintos; similaridade livre aqui só criaria o risco de `Premier League`
    casar com `Liga Premier` de outro país. Ou casa exato — código, nome
    canônico, alias registrado — ou é uma competição que não cobrimos.

    FORA DO CATÁLOGO É `REJECTED`, e não `UNRESOLVED`. A diferença importa:
    `UNRESOLVED` diz «não achei, talvez ache depois»; `REJECTED` diz «decidi
    que isto não é uma das cinco». A Bundesliga não vai aparecer no catálogo
    da V1 por mais que se espere, e mantê-la em `UNRESOLVED` faria a fila
    crescer com casos que nunca resolvem.
    """

    def resolve(
        self, name: NormalizedName, *, context: ResolutionContext, policy: ResolutionPolicy
    ) -> Outcome:
        _ = policy
        # 1. o código, escrito por extenso pela fonte
        codigo = _codigo_direto(name.raw)
        if codigo is not None:
            return self._por_codigo(codigo, name, ExplanationCode.EXACT_NAME_MATCH)

        # 2. alias registrado
        for alias in context.aliases_for(SubjectType.COMPETITION, name.normalized):
            return Outcome.exact(
                alias.entity_id,
                ResolutionMethod.EXACT_ALIAS,
                (
                    ResolutionEvidence.matched(
                        EvidenceKind.ALIAS,
                        weight=1.0,
                        explanation=ExplanationCode.ALIAS_MATCH,
                        source_value=name.raw,
                        canonical_value=alias.alias_original,
                    ),
                ),
            )

        # 3. nome canônico de uma das cinco, normalizado do mesmo jeito.
        # `CATALOG` é um mapa código → entrada; iterar os VALORES é o que dá
        # acesso ao nome de exibição.
        for entrada in CATALOG.values():
            if context.normalizer.normalize(entrada.name) == name.normalized:
                return self._por_codigo(entrada.code, name, ExplanationCode.EXACT_NAME_MATCH)

        return Outcome.rejected(
            (
                ResolutionEvidence.mismatched(
                    EvidenceKind.CANONICAL_KEY,
                    weight=1.0,
                    explanation=ExplanationCode.OUT_OF_CATALOG,
                    source_value=name.raw,
                ),
            ),
            reason=(
                f"{name.raw!r} não é uma das cinco competições da V1. Se for uma "
                "grafia nova de alguma delas, registre um alias."
            ),
        )

    def _por_codigo(
        self, codigo: CompetitionCode, name: NormalizedName, explicacao: ExplanationCode
    ) -> Outcome:
        from sports_intelligence.domain.competitions.catalog import entry_for

        return Outcome.exact(
            entry_for(codigo).id,
            ResolutionMethod.EXACT_CANONICAL_KEY,
            (
                ResolutionEvidence.matched(
                    EvidenceKind.CANONICAL_KEY,
                    weight=1.0,
                    explanation=explicacao,
                    source_value=name.raw,
                    canonical_value=codigo.value,
                ),
            ),
        )


def _codigo_direto(raw: str) -> CompetitionCode | None:
    try:
        return resolve_code(raw)
    except Exception:  # noqa: BLE001 — ausência no catálogo é resposta
        return None


# ============================================================== temporada ====


@final
class SeasonResolver:
    """Temporada é CONTEXTUAL, e `2024` não significa a mesma coisa em toda liga.

    O CASO QUE DEFINE ESTE RESOLVER (§15): `2024` no Brasileirão é a temporada
    de 2024, que começa e termina no mesmo ano. `2024` numa fonte de Premier
    League costuma ser 2023/24 — ou 2024/25, conforme o publicador. Resolver
    universalmente para um dos dois erra metade das vezes, em silêncio.

    Então a resolução exige a competição (evidência obrigatória na política) e
    consulta, em ordem:

        a convenção DECLARADA pela fonte no mapeamento;
        o rótulo canônico da temporada, normalizado;
        a data da partida, quando existe — ela desambigua sozinha.

    Sem nenhuma das três, vai para revisão. Não adivinha.
    """

    def resolve(
        self,
        label: NormalizedName,
        *,
        competition: CompetitionId,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        convention: SeasonConvention = SeasonConvention.UNDECLARED,
        match_date: date | None = None,
    ) -> Outcome:
        base = (
            ResolutionEvidence.matched(
                EvidenceKind.COMPETITION,
                weight=policy.weight_of(EvidenceKind.COMPETITION),
                source_value=str(competition),
            ),
        )

        # 1. o rótulo bate exatamente com o de uma temporada registrada
        exata = context.seasons_by_label.get((competition, label.normalized))
        if exata is not None:
            return Outcome.exact(
                exata,
                ResolutionMethod.EXACT_CANONICAL_KEY,
                (
                    *base,
                    ResolutionEvidence.matched(
                        EvidenceKind.SEASON,
                        weight=1.0,
                        explanation=ExplanationCode.EXACT_NAME_MATCH,
                        source_value=label.raw,
                    ),
                ),
            )

        pista = parse_season_label(label.raw, convention=convention)
        candidatos = self._candidatos(
            pista, competition=competition, context=context, policy=policy, base=base
        )
        if match_date is not None:
            candidatos = self._reforcar_com_data(candidatos, match_date, context, policy)
        return classify(
            candidatos,
            policy=policy,
            subject=SubjectType.SEASON,
            required=frozenset({EvidenceKind.COMPETITION}),
        )

    def _candidatos(
        self,
        pista: SeasonHint,
        *,
        competition: CompetitionId,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        base: tuple[ResolutionEvidence, ...],
    ) -> tuple[ScoredCandidate, ...]:
        saida: list[ScoredCandidate] = []
        for season_id, temporada in context.seasons.items():
            if temporada.competition_id != competition:
                continue
            candidata = parse_season_label(temporada.label, convention=SeasonConvention.UNDECLARED)
            if not pista.compatible_with(candidata):
                continue
            forca = pista.agreement_with(candidata)
            saida.append(
                ScoredCandidate(
                    entity_id=season_id,
                    score=min(1.0, 0.5 + 0.5 * forca),
                    evidence=(
                        *base,
                        ResolutionEvidence.matched(
                            EvidenceKind.SEASON,
                            weight=policy.weight_of(EvidenceKind.SEASON) * forca,
                            explanation=ExplanationCode.SIMILAR_NAME,
                            source_value=pista.raw,
                            canonical_value=temporada.label,
                        ),
                    ),
                    label=temporada.label,
                )
            )
        return tuple(saida)

    def _reforcar_com_data(
        self,
        candidatos: tuple[ScoredCandidate, ...],
        match_date: date,
        context: ResolutionContext,
        policy: ResolutionPolicy,
    ) -> tuple[ScoredCandidate, ...]:
        """A data da partida desambigua o que o rótulo não desambigua.

        É a evidência mais forte que existe para temporada: uma partida de
        setembro de 2023 está na 2023/24 da Premier League e na 2023 do
        Brasileirão, e a janela registrada de cada temporada responde isso sem
        precisar da convenção da fonte.
        """
        reforcados: list[ScoredCandidate] = []
        for candidato in candidatos:
            # Os candidatos de temporada vieram de `context.seasons`, então o
            # id É um `SeasonId`. A conferência de tipo existe porque
            # `ScoredCandidate` é genérico sobre `EntityId` — ele serve aos
            # cinco resolvers — e um `isinstance` aqui é mais barato que cinco
            # tipos de candidato.
            temporada = (
                context.seasons.get(candidato.entity_id)
                if isinstance(candidato.entity_id, SeasonId)
                else None
            )
            if temporada is None:
                reforcados.append(candidato)
                continue
            dentro = temporada.starts_at.date() <= match_date <= temporada.ends_at.date()
            evidencia = (
                ResolutionEvidence.matched(
                    EvidenceKind.KICKOFF,
                    weight=policy.weight_of(EvidenceKind.KICKOFF),
                    explanation=ExplanationCode.WITHIN_TOLERANCE,
                    source_value=match_date.isoformat(),
                    canonical_value=f"{temporada.starts_at.date()}..{temporada.ends_at.date()}",
                )
                if dentro
                else ResolutionEvidence.mismatched(
                    EvidenceKind.KICKOFF,
                    weight=policy.weight_of(EvidenceKind.KICKOFF),
                    explanation=ExplanationCode.OUTSIDE_TOLERANCE,
                    source_value=match_date.isoformat(),
                )
            )
            reforcados.append(
                ScoredCandidate(
                    entity_id=candidato.entity_id,
                    score=min(1.0, candidato.score + 0.35) if dentro else candidato.score * 0.4,
                    evidence=(*candidato.evidence, evidencia),
                    label=candidato.label,
                )
            )
        return tuple(reforcados)


# =================================================================== time ====


@final
class TeamResolver:
    """Clube: mapeamento, nome canônico, alias, e só então similaridade.

    A SIMILARIDADE NUNCA DECIDE SOZINHA. A política exige duas evidências
    corroborantes para time, então um nome parecido sem país, competição ou
    participação histórica que o apoie vai para revisão — que é o desfecho
    certo para `Sporting CP` contra `Sporting Gijón`.
    """

    def __init__(self, similarity: StringSimilarity | None = None) -> None:
        self._similarity = similarity or StringSimilarity()

    def resolve(
        self,
        name: NormalizedName,
        *,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        provider_ref: str | None = None,
        provider_id: object = None,
        country: str | None = None,
        competition: CompetitionId | None = None,
        season: SeasonId | None = None,
    ) -> Outcome:
        from sports_intelligence.domain.shared.identity import ProviderId

        # 1. mapeamento de provedor — a evidência mais forte que existe
        if provider_ref and isinstance(provider_id, ProviderId):
            mapeamento = context.mapping_for(provider_id, SubjectType.TEAM, provider_ref)
            if mapeamento is not None:
                return Outcome.exact(
                    mapeamento.canonical_entity_id,
                    ResolutionMethod.EXACT_PROVIDER_MAPPING,
                    (
                        ResolutionEvidence.matched(
                            EvidenceKind.PROVIDER_MAPPING,
                            weight=1.0,
                            explanation=ExplanationCode.PROVIDER_ID_MATCHED,
                            source_value=provider_ref,
                            canonical_value=str(mapeamento.canonical_entity_id),
                        ),
                    ),
                )

        # 2. alias registrado — casamento exato sobre a chave normalizada
        aliases = context.aliases_for(SubjectType.TEAM, name.normalized)
        if len(aliases) == 1:
            return Outcome.exact(
                aliases[0].entity_id,
                ResolutionMethod.EXACT_ALIAS,
                (
                    ResolutionEvidence.matched(
                        EvidenceKind.ALIAS,
                        weight=1.0,
                        explanation=ExplanationCode.ALIAS_MATCH,
                        source_value=name.raw,
                        canonical_value=aliases[0].alias_original,
                    ),
                ),
            )

        # 3. nome canônico exato, com UM dono
        exatos = context.teams_named(name.normalized)
        if len(exatos) == 1:
            return Outcome.exact(
                exatos[0],
                ResolutionMethod.EXACT_CANONICAL_KEY,
                (
                    ResolutionEvidence.matched(
                        EvidenceKind.CANONICAL_KEY,
                        weight=1.0,
                        explanation=ExplanationCode.EXACT_NAME_MATCH,
                        source_value=name.raw,
                    ),
                ),
            )

        # 4. similaridade, com evidência de apoio
        return classify(
            self._candidatos(
                name,
                context=context,
                policy=policy,
                country=country,
                competition=competition,
                season=season,
                aliases_ambiguos=tuple(a.entity_id for a in aliases) if len(aliases) > 1 else (),
            ),
            policy=policy,
            subject=SubjectType.TEAM,
        )

    def _candidatos(
        self,
        name: NormalizedName,
        *,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        country: str | None,
        competition: CompetitionId | None,
        season: SeasonId | None,
        aliases_ambiguos: tuple[EntityId, ...],
    ) -> tuple[ScoredCandidate, ...]:
        peso_nome = policy.weight_of(EvidenceKind.NAME_SIMILARITY)
        saida: list[ScoredCandidate] = []
        # O UNIVERSO DE CANDIDATOS É DO NOME, NÃO DO LOTE (§29 a §33). Varrer
        # `context.teams` fazia o resultado depender de quais outras linhas
        # foram processadas junto — e a medição do PR-03.1 pegou 2,7% das
        # listas de alternativas mudando com o tamanho do lote.
        universo: set[TeamId] = {
            *context.team_candidates_for(name.normalized),
            *(a for a in aliases_ambiguos if isinstance(a, TeamId)),
        }
        for team_id in sorted(universo, key=str):
            time = context.teams.get(team_id)
            if time is None:
                continue
            canonico = NormalizedName.of(time.canonical_name, context.normalizer)
            similaridade = self._similarity.score(
                name.normalized,
                canonico.normalized,
                tokens_a=name.tokens,
                tokens_b=canonico.tokens,
            )
            # CORTE ANTES DE PONTUAR. Sem ele, cada nome de fonte produziria
            # um candidato por clube do registro — e a fila de revisão
            # receberia listas de centenas.
            if similaridade < _CORTE_DE_CANDIDATO_TIME and team_id not in aliases_ambiguos:
                continue

            evidencias: list[ResolutionEvidence] = [
                ResolutionEvidence.matched(
                    EvidenceKind.NAME_SIMILARITY,
                    weight=peso_nome * similaridade,
                    explanation=(
                        ExplanationCode.SIMILAR_NAME
                        if similaridade >= _ROTULO_DE_NOME_SIMILAR
                        else ExplanationCode.NAME_TOO_DIFFERENT
                    ),
                    source_value=name.raw,
                    canonical_value=time.canonical_name,
                )
            ]
            score = similaridade * 0.7

            if country:
                bate = time.country.upper() == country.upper()
                evidencias.append(
                    ResolutionEvidence.matched(
                        EvidenceKind.COUNTRY,
                        weight=policy.weight_of(EvidenceKind.COUNTRY),
                        source_value=country,
                        canonical_value=time.country,
                    )
                    if bate
                    else ResolutionEvidence.mismatched(
                        EvidenceKind.COUNTRY,
                        weight=policy.weight_of(EvidenceKind.COUNTRY),
                        source_value=country,
                        canonical_value=time.country,
                    )
                )
                # PAÍS DIVERGENTE É PENALIDADE FORTE. É a evidência que separa
                # Sporting CP de Sporting Kansas City — e foi a ausência dela
                # que fundiu clubes entre continentes no motor anterior.
                score = score + 0.2 if bate else score * 0.35

            if competition is not None and season is not None:
                participou = context.participated(competition, season, team_id)
                if participou is True:
                    evidencias.append(
                        ResolutionEvidence.matched(
                            EvidenceKind.HISTORICAL_PARTICIPATION,
                            weight=policy.weight_of(EvidenceKind.HISTORICAL_PARTICIPATION),
                            source_value=str(competition),
                        )
                    )
                    score = min(1.0, score + 0.18)
                elif participou is False:
                    evidencias.append(
                        ResolutionEvidence.mismatched(
                            EvidenceKind.HISTORICAL_PARTICIPATION,
                            weight=policy.weight_of(EvidenceKind.HISTORICAL_PARTICIPATION),
                            explanation=ExplanationCode.NOT_PARTICIPANT,
                            source_value=str(competition),
                        )
                    )
                    score *= 0.5
                else:
                    # NÃO SE SABE ≠ NÃO PARTICIPOU. Um registro canônico ainda
                    # vazio não tem participantes, e penalizar por isso
                    # puniria todo candidato igualmente.
                    evidencias.append(
                        ResolutionEvidence.unavailable(
                            EvidenceKind.HISTORICAL_PARTICIPATION,
                            explanation=ExplanationCode.VALUE_ABSENT_IN_CANONICAL,
                        )
                    )

            saida.append(
                ScoredCandidate(
                    entity_id=team_id,
                    score=min(1.0, score),
                    evidence=tuple(evidencias),
                    label=time.canonical_name,
                )
            )
        return tuple(saida)


# =============================================================== jogador ====


@final
class PlayerResolver:
    """O mais conservador dos cinco. Homônimo NUNCA resolve por nome.

    O CASO QUE GOVERNA ESTE RESOLVER: dois `João Silva` com datas de
    nascimento diferentes, em clubes diferentes. O nome bate perfeitamente —
    e é justamente por isso que não se pode resolver. A política exige três
    evidências corroborantes para jogador; o nome é uma.

    A EVIDÊNCIA TEMPORAL É O QUE DESEMPATA (§20). «João Silva, Flamengo, 2023»
    e «João Silva, Palmeiras, 2026» são registros diferentes, e o vínculo do
    jogador NA DATA — não o clube atual — é o que os separa.
    """

    def __init__(self, similarity: StringSimilarity | None = None) -> None:
        self._similarity = similarity or StringSimilarity()

    def resolve(
        self,
        name: NormalizedName,
        *,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        provider_ref: str | None = None,
        provider_id: object = None,
        date_of_birth: date | None = None,
        nationality: str | None = None,
        team: TeamId | None = None,
        at: Instant | None = None,
    ) -> Outcome:
        from sports_intelligence.domain.shared.identity import ProviderId

        if provider_ref and isinstance(provider_id, ProviderId):
            mapeamento = context.mapping_for(provider_id, SubjectType.PLAYER, provider_ref)
            if mapeamento is not None:
                return Outcome.exact(
                    mapeamento.canonical_entity_id,
                    ResolutionMethod.EXACT_PROVIDER_MAPPING,
                    (
                        ResolutionEvidence.matched(
                            EvidenceKind.PROVIDER_MAPPING,
                            weight=1.0,
                            explanation=ExplanationCode.PROVIDER_ID_MATCHED,
                            source_value=provider_ref,
                        ),
                    ),
                )

        candidatos = self._candidatos(
            name,
            context=context,
            policy=policy,
            date_of_birth=date_of_birth,
            nationality=nationality,
            team=team,
            at=at,
        )
        resultado = classify(candidatos, policy=policy, subject=SubjectType.PLAYER)

        # HOMÔNIMOS EXATOS SÃO SEMPRE `AMBIGUOUS`, mesmo que uma evidência
        # empurre um deles para cima. Sem esta trava, um `João Silva` com
        # nacionalidade conhecida resolveria contra dois homônimos por causa
        # de um campo fraco — e a nacionalidade é o mesmo país para os dois.
        homonimos = context.players_named(name.normalized)
        if len(homonimos) > 1 and resultado.status is ResolutionStatus.RESOLVED:
            distinguiu = date_of_birth is not None or team is not None
            if not distinguiu:
                return Outcome(
                    status=ResolutionStatus.AMBIGUOUS,
                    method=ResolutionMethod.CONFIDENCE_MATCH,
                    confidence=resultado.confidence,
                    evidence=(
                        *resultado.evidence,
                        ResolutionEvidence.unavailable(
                            EvidenceKind.DATE_OF_BIRTH,
                            explanation=ExplanationCode.MULTIPLE_EQUAL_CANDIDATES,
                            source_value=name.raw,
                        ),
                    ),
                    alternatives=resultado.alternatives,
                )
        return resultado

    def _candidatos(
        self,
        name: NormalizedName,
        *,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        date_of_birth: date | None,
        nationality: str | None,
        team: TeamId | None,
        at: Instant | None,
    ) -> tuple[ScoredCandidate, ...]:
        saida: list[ScoredCandidate] = []
        # MESMO PRINCÍPIO DO TIME: os candidatos são os DAQUELE nome.
        for player_id in context.player_candidates_for(name.normalized):
            jogador = context.players.get(player_id)
            if jogador is None:
                continue
            canonico = NormalizedName.of(jogador.canonical_name, context.normalizer)
            similaridade = self._similarity.score(
                name.normalized,
                canonico.normalized,
                tokens_a=name.tokens,
                tokens_b=canonico.tokens,
            )
            if similaridade < _CORTE_DE_CANDIDATO_JOGADOR:
                continue

            evidencias: list[ResolutionEvidence] = [
                ResolutionEvidence.matched(
                    EvidenceKind.NAME_SIMILARITY,
                    weight=policy.weight_of(EvidenceKind.NAME_SIMILARITY) * similaridade,
                    explanation=ExplanationCode.SIMILAR_NAME,
                    source_value=name.raw,
                    canonical_value=jogador.canonical_name,
                )
            ]
            # O NOME SOZINHO NÃO CHEGA AO LIMIAR, e é por construção: 0,55 de
            # base contra um limiar de 0,96. Só as evidências de apoio levam
            # um jogador à resolução automática.
            score = similaridade * 0.55

            evidencia_dob, delta_dob = self._avaliar_dob(
                date_of_birth, jogador.date_of_birth, policy
            )
            evidencias.append(evidencia_dob)
            score = _aplicar(score, delta_dob)

            if nationality is not None:
                bate = (jogador.nationality or "").upper() == nationality.upper()
                evidencias.append(
                    (ResolutionEvidence.matched if bate else ResolutionEvidence.mismatched)(
                        EvidenceKind.NATIONALITY,
                        weight=policy.weight_of(EvidenceKind.NATIONALITY),
                        source_value=nationality,
                        canonical_value=jogador.nationality,
                    )
                    if jogador.nationality
                    else ResolutionEvidence.unavailable(
                        EvidenceKind.NATIONALITY,
                        explanation=ExplanationCode.VALUE_ABSENT_IN_CANONICAL,
                    )
                )
                if jogador.nationality:
                    score = _aplicar(score, 0.08 if bate else -0.25)

            evidencia_time, delta_time = self._avaliar_time(team, player_id, at, context, policy)
            evidencias.append(evidencia_time)
            score = _aplicar(score, delta_time)

            saida.append(
                ScoredCandidate(
                    entity_id=player_id,
                    score=min(1.0, max(0.0, score)),
                    evidence=tuple(evidencias),
                    label=jogador.canonical_name,
                )
            )
        return tuple(saida)

    @staticmethod
    def _avaliar_dob(
        origem: date | None, canonica: date | None, policy: ResolutionPolicy
    ) -> tuple[ResolutionEvidence, float]:
        """Data de nascimento: a evidência que separa homônimos.

        DIVERGÊNCIA É QUASE FATAL, e é o comportamento certo: duas pessoas com
        o mesmo nome e datas diferentes são duas pessoas. A penalidade derruba
        o candidato para muito abaixo do limiar de revisão.
        """
        peso = policy.weight_of(EvidenceKind.DATE_OF_BIRTH)
        if origem is None:
            return (
                ResolutionEvidence.unavailable(
                    EvidenceKind.DATE_OF_BIRTH,
                    explanation=ExplanationCode.VALUE_ABSENT_IN_SOURCE,
                ),
                0.0,
            )
        if canonica is None:
            return (
                ResolutionEvidence.unavailable(
                    EvidenceKind.DATE_OF_BIRTH,
                    explanation=ExplanationCode.VALUE_ABSENT_IN_CANONICAL,
                    source_value=origem.isoformat(),
                ),
                0.0,
            )
        if origem == canonica:
            return (
                ResolutionEvidence.matched(
                    EvidenceKind.DATE_OF_BIRTH,
                    weight=peso,
                    source_value=origem.isoformat(),
                    canonical_value=canonica.isoformat(),
                ),
                0.30,
            )
        return (
            ResolutionEvidence.mismatched(
                EvidenceKind.DATE_OF_BIRTH,
                weight=peso,
                source_value=origem.isoformat(),
                canonical_value=canonica.isoformat(),
            ),
            -0.60,
        )

    @staticmethod
    def _avaliar_time(
        team: TeamId | None,
        player: PlayerId,
        at: Instant | None,
        context: ResolutionContext,
        policy: ResolutionPolicy,
    ) -> tuple[ResolutionEvidence, float]:
        """O clube do jogador NA DATA — nunca o clube atual (§20)."""
        peso = policy.weight_of(EvidenceKind.TEAM_AT_DATE)
        if team is None or at is None:
            return (
                ResolutionEvidence.unavailable(
                    EvidenceKind.TEAM_AT_DATE,
                    explanation=ExplanationCode.VALUE_ABSENT_IN_SOURCE,
                ),
                0.0,
            )
        na_data = context.team_of_player_at(player, at)
        if na_data is None:
            return (
                ResolutionEvidence.unavailable(
                    EvidenceKind.TEAM_AT_DATE,
                    explanation=ExplanationCode.VALUE_ABSENT_IN_CANONICAL,
                    source_value=str(team),
                ),
                0.0,
            )
        if na_data == team:
            return (
                ResolutionEvidence.matched(
                    EvidenceKind.TEAM_AT_DATE,
                    weight=peso,
                    source_value=str(team),
                    canonical_value=str(na_data),
                ),
                0.25,
            )
        return (
            ResolutionEvidence.mismatched(
                EvidenceKind.TEAM_AT_DATE,
                weight=peso,
                source_value=str(team),
                canonical_value=str(na_data),
            ),
            -0.35,
        )


def _aplicar(score: float, delta: float) -> float:
    return max(0.0, min(1.0, score + delta))


# ============================================================== partida ====


@final
@dataclass(frozen=True, slots=True)
class MatchCandidateInput:
    """O que a fonte diz sobre uma partida, já com identidades resolvidas.

    OS TIMES CHEGAM COMO `TeamId`, e é a ordem obrigatória do ADR-0022: a
    partida só é resolvida depois de competição, temporada e os dois clubes.
    Aceitar nomes aqui faria a resolução de partida resolver clube por dentro,
    sem evidência nem decisão registrada.
    """

    competition: CompetitionId
    season: SeasonId
    home: TeamId
    away: TeamId
    kickoff: Instant
    #: `True` quando a fonte não declarou fuso. Vira evidência FRACA e nunca
    #: correção silenciosa (§25).
    kickoff_timezone_undeclared: bool = False
    stage: str | None = None
    round_number: int | None = None
    venue: str | None = None


@final
class MatchResolver:
    """Score composto de sete dimensões, com pesos versionados.

    COMPETIÇÃO E TEMPORADA SÃO EVIDÊNCIA DURA (§87). Dois jogos entre os
    mesmos times na mesma data em competições diferentes existem — copa e
    liga —, e sem essa trava eles seriam fundidos. A política as marca como
    obrigatórias, e o resolver nem gera candidato fora delas.

    INVERSÃO DE MANDO NUNCA É CORRIGIDA SOZINHA (§24). `Arsenal x Chelsea` e
    `Chelsea x Arsenal` produzem candidato com penalidade grande o bastante
    para cair na faixa de revisão. Trocar automaticamente resolveria o caso
    em que a fonte errou e destruiria o caso em que são os dois jogos do
    returno.
    """

    def resolve(
        self,
        entrada: MatchCandidateInput,
        *,
        context: ResolutionContext,
        policy: ResolutionPolicy,
        match_policy: MatchResolutionPolicy,
    ) -> Outcome:
        diretos = context.fixtures(entrada.season, entrada.home, entrada.away)
        invertidos = context.fixtures(entrada.season, entrada.away, entrada.home)

        candidatos = [
            self._pontuar(entrada, partida, match_policy, policy, invertido=False)
            for partida in diretos
        ] + [
            self._pontuar(entrada, partida, match_policy, policy, invertido=True)
            for partida in invertidos
        ]
        return classify(
            tuple(candidatos),
            policy=policy,
            subject=SubjectType.MATCH,
            required=frozenset({EvidenceKind.COMPETITION, EvidenceKind.SEASON}),
        )

    def _pontuar(
        self,
        entrada: MatchCandidateInput,
        partida: object,
        match_policy: MatchResolutionPolicy,
        policy: ResolutionPolicy,
        *,
        invertido: bool,
    ) -> ScoredCandidate:
        from sports_intelligence.domain.matches.models import Match

        assert isinstance(partida, Match)
        evidencias: list[ResolutionEvidence] = []
        score = 0.0

        mesma_competicao = partida.competition_id == entrada.competition
        evidencias.append(
            (ResolutionEvidence.matched if mesma_competicao else ResolutionEvidence.mismatched)(
                EvidenceKind.COMPETITION,
                weight=policy.weight_of(EvidenceKind.COMPETITION),
                source_value=str(entrada.competition),
                canonical_value=str(partida.competition_id),
            )
        )
        if mesma_competicao:
            score += match_policy.competition_weight
        elif match_policy.competition_must_match:
            # COMPETIÇÃO DIFERENTE ZERA. Não é penalidade: é outra partida.
            return ScoredCandidate(
                entity_id=partida.id, score=0.0, evidence=tuple(evidencias), label=None
            )

        evidencias.append(
            ResolutionEvidence.matched(
                EvidenceKind.SEASON,
                weight=policy.weight_of(EvidenceKind.SEASON),
                source_value=str(entrada.season),
            )
        )
        score += match_policy.season_weight

        lados = (
            (
                EvidenceKind.HOME_TEAM,
                match_policy.home_team_weight,
                entrada.home,
                partida.home_team_id,
            ),
            (
                EvidenceKind.AWAY_TEAM,
                match_policy.away_team_weight,
                entrada.away,
                partida.away_team_id,
            ),
        )
        for lado, peso, esperado, encontrado in lados:
            bate = esperado == encontrado
            evidencias.append(
                (ResolutionEvidence.matched if bate else ResolutionEvidence.mismatched)(
                    lado,
                    weight=policy.weight_of(lado),
                    explanation=(
                        ExplanationCode.VALUE_MATCHED if bate else ExplanationCode.SIDES_REVERSED
                    ),
                    source_value=str(esperado),
                    canonical_value=str(encontrado),
                )
            )
            if bate:
                score += peso

        delta = partida.kickoff - entrada.kickoff
        fator = match_policy.kickoff_score(delta)
        explicacao = (
            ExplanationCode.TIMEZONE_UNDECLARED
            if entrada.kickoff_timezone_undeclared and 0.0 < fator < 1.0
            else (
                ExplanationCode.WITHIN_TOLERANCE
                if fator >= 0.5
                else ExplanationCode.OUTSIDE_TOLERANCE
            )
        )
        evidencias.append(
            (ResolutionEvidence.matched if fator > 0 else ResolutionEvidence.mismatched)(
                EvidenceKind.KICKOFF,
                weight=policy.weight_of(EvidenceKind.KICKOFF) * fator,
                explanation=explicacao,
                source_value=entrada.kickoff.isoformat(),
                canonical_value=partida.kickoff.isoformat(),
            )
        )
        score += match_policy.kickoff_weight * fator

        if entrada.round_number is not None and partida.stage.round_number is not None:
            bate = entrada.round_number == partida.stage.round_number
            evidencias.append(
                (ResolutionEvidence.matched if bate else ResolutionEvidence.mismatched)(
                    EvidenceKind.ROUND,
                    weight=policy.weight_of(EvidenceKind.ROUND),
                    source_value=str(entrada.round_number),
                    canonical_value=str(partida.stage.round_number),
                )
            )
            if bate:
                score += match_policy.round_weight

        if invertido:
            evidencias.append(
                ResolutionEvidence.mismatched(
                    EvidenceKind.HOME_TEAM,
                    weight=policy.weight_of(EvidenceKind.HOME_TEAM),
                    explanation=ExplanationCode.SIDES_REVERSED,
                    source_value=f"{entrada.home} x {entrada.away}",
                    canonical_value=f"{partida.home_team_id} x {partida.away_team_id}",
                )
            )
            score = max(0.0, score - match_policy.reversed_sides_penalty)

        return ScoredCandidate(
            entity_id=partida.id,
            score=min(1.0, score),
            evidence=tuple(evidencias),
            label=f"{partida.home_team_id} x {partida.away_team_id} @ {partida.kickoff.date()}",
        )


@final
@dataclass(frozen=True, slots=True)
class ResolverBundle:
    """Os cinco, montados juntos com normalizador e similaridade comuns.

    COMUNS É REQUISITO: se o resolver de time normalizasse diferente do de
    jogador, um alias registrado por um não casaria pelo outro — e a
    divergência apareceria como «às vezes resolve».
    """

    normalizer: NameNormalizer
    similarity: StringSimilarity
    competition: CompetitionResolver
    season: SeasonResolver
    team: TeamResolver
    player: PlayerResolver
    match: MatchResolver

    @classmethod
    def build(cls, normalizer: NameNormalizer | None = None) -> ResolverBundle:
        n = normalizer or NameNormalizer()
        s = StringSimilarity()
        return cls(
            normalizer=n,
            similarity=s,
            competition=CompetitionResolver(),
            season=SeasonResolver(),
            team=TeamResolver(s),
            player=PlayerResolver(s),
            match=MatchResolver(),
        )

    def normalized(self, raw: str) -> NormalizedName:
        return NormalizedName.of(raw, self.normalizer)
