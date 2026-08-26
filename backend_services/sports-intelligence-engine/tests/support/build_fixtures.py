"""O cenário do PR-04.2 — montado uma vez, usado pela unidade e pela integração.

POR QUE COMPARTILHADO. Os testes de unidade e os de integração precisam do
MESMO cenário: uma fonte de domínio público com o núcleo da partida e uma
fonte `RESEARCH_ONLY` que só trouxe odds. Dois cenários parecidos escritos em
dois arquivos divergem no primeiro ajuste — e a divergência apareceria como um
teste de unidade verde sobre um caso que a integração não exercita.

O CENÁRIO É O DO §19 E DO §103, e ele existe porque é o caso que separa um
build de pesquisa de um comercial: mesma partida, mesma identidade, famílias
diferentes materializadas.

TAMBÉM MORAM AQUI OS DUPLOS EM MEMÓRIA dos repositórios de qualidade e de
construção. Eles têm as MESMAS restrições dos reais — `append_many` é
idempotente por chave, a escrita canônica compara equivalência antes de
reaproveitar, e nenhum deles faz `UPDATE` sobre fato. Um duplo mais permissivo
que o real deixa passar exatamente a classe de erro que o real bloquearia.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, final

from sports_intelligence.domain.build.facts import LineupDraft, MatchIdentityFacts
from sports_intelligence.domain.competitions.models import (
    CompetitionRegime,
    RegimeCode,
    Stage,
    StageType,
)
from sports_intelligence.domain.fusion.models import (
    FusionGroup,
    ResolvedSourceRecord,
)
from sports_intelligence.domain.fusion.policy import DEFAULT_FUSION_POLICY
from sports_intelligence.domain.fusion.runs import (
    FusedMatchCandidate,
    FusionCounts,
    FusionRun,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.versions import (
    CURRENT_FUSION_POLICY_VERSION,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    DatasetId,
    MatchId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.sources.records import DatasetRecordRef
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.historical.quality.assessor import CandidateEvidence
from sports_intelligence.ingestion.fusion.engine import FusionEngine, group_by_identity

AGORA: Final[Instant] = instant(datetime(2026, 8, 17, 12, 0, tzinfo=UTC))
#: A execução de resolução declarada como entrada da fusão do cenário.
RESOLUTION_RUN_ID: Final[str] = "11111111-1111-4111-8111-111111111111"

KICKOFF: Final[Instant] = instant(datetime(2026, 3, 14, 19, 30, tzinfo=UTC))

#: A fonte de DOMÍNIO PÚBLICO, com o núcleo da partida.
PUBLICA: Final[ProviderId] = ProviderId("fonte_publica")
#: A fonte `RESEARCH_ONLY`, que só trouxe cotações. É ela que separa o build de
#: pesquisa do comercial (§19).
RESTRITA: Final[ProviderId] = ProviderId("fonte_restrita")

DATASET_PUBLICO: Final[DatasetId] = DatasetId.derive("pr042", "publico")
DATASET_RESTRITO: Final[DatasetId] = DatasetId.derive("pr042", "restrito")

#: Todo id é DERIVADO e não sorteado: o cenário precisa ser o mesmo em duas
#: execuções para que a impressão determinística possa ser comparada (§53).
COMPETICAO: Final[CompetitionId] = CompetitionId.derive("pr042", "competicao")
TEMPORADA: Final[SeasonId] = SeasonId.derive("pr042", "temporada")
CASA: Final[TeamId] = TeamId.derive("pr042", "mandante")
FORA: Final[TeamId] = TeamId.derive("pr042", "visitante")

REGIME: Final[CompetitionRegime] = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(1990, 1, 1, tzinfo=UTC)),
    regulation_version="pr042-v1",
)

#: As confianças que um cenário saudável tem. Acima de todos os pisos da
#: política padrão — o cenário base PASSA, e cada teste degrada UM eixo.
CONFIANCAS_BOAS: Final[dict[SubjectType, float]] = {
    SubjectType.COMPETITION: 1.0,
    SubjectType.SEASON: 1.0,
    SubjectType.TEAM: 0.99,
    SubjectType.MATCH: 0.98,
}


def match_id(n: int = 0) -> MatchId:
    return MatchId.derive("pr042", f"partida-{n}")


def ref(dataset: DatasetId, linha: int) -> DatasetRecordRef:
    return DatasetRecordRef(
        dataset_id=dataset,
        file_id=str(DatasetId.derive("arquivo", str(dataset))),
        record_number=linha,
    )


def identity_facts(n: int = 0) -> MatchIdentityFacts:
    """A identidade canônica da partida do cenário — JÁ resolvida."""
    return MatchIdentityFacts(
        match_id=match_id(n),
        competition_id=COMPETICAO,
        season_id=TEMPORADA,
        regime=REGIME,
        stage=Stage(type=StageType.LEAGUE, round_number=1 + n % 38),
        home_team_id=CASA,
        away_team_id=FORA,
        scheduled_kickoff=KICKOFF,
    )


# ============================================================= candidatos ==


def registro_publico(
    n: int = 0,
    *,
    home_score: str | None = "2",
    away_score: str | None = "1",
    formation: str | None = None,
) -> ResolvedSourceRecord:
    """A linha da fonte de domínio público: núcleo da partida."""
    valores: dict[SemanticRole, str] = {
        SemanticRole.HOME_TEAM_NAME: "Mandante FC",
        SemanticRole.AWAY_TEAM_NAME: "Visitante FC",
        SemanticRole.SEASON_LABEL: "2026",
        # `KICKOFF` É FATO, e não rótulo (PR-04.2.1 §12): ele é procedência
        # factual do núcleo, e toda fonte real o traz.
        SemanticRole.KICKOFF: KICKOFF.isoformat(),
    }
    if home_score is not None:
        valores[SemanticRole.HOME_SCORE] = home_score
    if away_score is not None:
        valores[SemanticRole.AWAY_SCORE] = away_score
    if formation is not None:
        valores[SemanticRole.HOME_FORMATION] = formation
    return ResolvedSourceRecord(
        record_ref=ref(DATASET_PUBLICO, n + 1),
        provider_id=PUBLICA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.PUBLIC_DOMAIN,
        canonical_entity_id=match_id(n),
        resolution_decision_id=str(DatasetId.derive("decisao-publica", str(n))),
        values=valores,
    )


def registro_de_odds(
    n: int = 0,
    *,
    casa: str = "bet365",
    cotacao: str = "2.00",
    provider: ProviderId = RESTRITA,
    license_class: LicenseClass = LicenseClass.RESEARCH_ONLY,
    linha: int = 1,
) -> ResolvedSourceRecord:
    """Uma linha da fonte restrita: uma casa de apostas, uma cotação."""
    return ResolvedSourceRecord(
        record_ref=ref(DATASET_RESTRITO, linha),
        provider_id=provider,
        source_type=SourceType.OPEN_DATA,
        license_class=license_class,
        canonical_entity_id=match_id(n),
        resolution_decision_id=str(DatasetId.derive("decisao-odds", f"{n}-{linha}")),
        values={
            SemanticRole.BOOKMAKER_NAME: casa,
            SemanticRole.ODDS_HOME: cotacao,
            SemanticRole.ODDS_DRAW: "3.40",
            SemanticRole.ODDS_AWAY: "3.90",
        },
    )


@final
@dataclass(frozen=True, slots=True)
class Cenario:
    """Um grupo de fusão e o candidato que ele produziu."""

    group: FusionGroup
    candidate: FusedMatchCandidate

    def evidence(
        self,
        *,
        confidences: Mapping[SubjectType, float] | None = None,
        lineup_drafts: tuple[LineupDraft, ...] = (),
    ) -> CandidateEvidence:
        return CandidateEvidence(
            candidate=self.candidate,
            group=self.group,
            identity_confidences=dict(confidences if confidences is not None else CONFIANCAS_BOAS),
            lineup_drafts=lineup_drafts,
        )


def cenario(
    *registros: ResolvedSourceRecord, extras: Sequence[ResolvedSourceRecord] = ()
) -> Cenario:
    """Funde os registros pelo MESMO caminho que a produção usa.

    NÃO MONTA `FusedMatchCandidate` À MÃO. Um candidato escrito no teste seria
    um candidato que a fusão nunca produziria, e o teste passaria a cobrir uma
    forma que não existe.
    """
    alvo = registros[0].canonical_entity_id
    assert isinstance(alvo, MatchId)
    grupo = FusionGroup.of(alvo, tuple(registros), tuple(extras))
    return Cenario(group=grupo, candidate=FusionEngine(DEFAULT_FUSION_POLICY).fuse(grupo))


def cenario_publico_com_odds(n: int = 0) -> Cenario:
    """O CENÁRIO CENTRAL DO PR (§19, §103).

        MATCH_CORE   fonte pública, PUBLIC_DOMAIN
        ODDS         fonte restrita, RESEARCH_ONLY, duas casas

    Ele é o que faz o build de pesquisa e o comercial divergirem — e a
    identidade da partida é a MESMA nos dois.
    """
    principais = (
        registro_publico(n),
        registro_de_odds(n, casa="bet365", cotacao="2.00", linha=1),
    )
    extras = (registro_de_odds(n, casa="pinnacle", cotacao="2.05", linha=2),)
    return cenario(*principais, extras=extras)


def cenarios(quantos: int) -> tuple[Cenario, ...]:
    """Vários cenários independentes, para o lote e para o benchmark."""
    return tuple(cenario_publico_com_odds(n) for n in range(quantos))


def grupos_e_candidatos(
    cenarios_: Sequence[Cenario],
) -> tuple[tuple[FusionGroup, ...], tuple[FusedMatchCandidate, ...]]:
    return tuple(c.group for c in cenarios_), tuple(c.candidate for c in cenarios_)


def registros_de(cenarios_: Sequence[Cenario]) -> tuple[ResolvedSourceRecord, ...]:
    """Todos os registros dos cenários, para reexecutar o agrupamento real."""
    return tuple(
        registro for c in cenarios_ for registro in (*c.group.records, *c.group.extra_observations)
    )


def reagrupar(
    registros: Sequence[ResolvedSourceRecord],
) -> tuple[tuple[FusionGroup, ...], tuple[FusedMatchCandidate, ...]]:
    grupos, _ = group_by_identity(tuple(registros))
    motor = FusionEngine(DEFAULT_FUSION_POLICY)
    return grupos, tuple(motor.fuse(g) for g in grupos)


def fusion_run_concluida(run_id: str | None = None) -> FusionRun:
    """Uma execução de fusão CONCLUÍDA — a única que a avaliação aceita (§8)."""
    execucao = FusionRun.start(
        input_resolution_run_ids=(RESOLUTION_RUN_ID,),
        policy_version=CURRENT_FUSION_POLICY_VERSION,
        at=AGORA,
        triggered_by=Actor.service("historical-fusion-worker"),
    )
    if run_id is not None:
        execucao = replace(execucao, id=run_id)
    return execucao.complete(counts=FusionCounts(groups=1), at=AGORA)


# =================================================== variações do cenário ==


def sem_odds(n: int = 0) -> Cenario:
    """A mesma partida SEM a fonte restrita — o corpus só com o núcleo."""
    return cenario(registro_publico(n))


def sem_placar(n: int = 0) -> Cenario:
    """A partida sem placar. O §44 em ação: ausência NÃO vira `0-0`."""
    return cenario(registro_publico(n, home_score=None, away_score=None))


def placar_em_conflito(n: int = 0) -> Cenario:
    """Duas fontes discordando do PLACAR — conflito de NÚCLEO (§45).

    As duas são de domínio público de propósito: o que reprova aqui é o
    desacordo sobre um fato verificável, e não a licença.
    """
    outra = replace(
        registro_publico(n),
        record_ref=ref(DATASET_RESTRITO, 9),
        provider_id=RESTRITA,
        resolution_decision_id=str(DatasetId.derive("decisao-b", str(n))),
        values={
            SemanticRole.HOME_TEAM_NAME: "Mandante FC",
            SemanticRole.AWAY_TEAM_NAME: "Visitante FC",
            SemanticRole.SEASON_LABEL: "2026",
            SemanticRole.HOME_SCORE: "3",
            SemanticRole.AWAY_SCORE: "1",
        },
    )
    return cenario(registro_publico(n), outra)


def formacao_em_conflito(n: int = 0) -> Cenario:
    """Duas fontes discordando da FORMAÇÃO — conflito OPCIONAL (§46).

    O placar continua concordando: é o que separa «a escalação ficou
    indecidível» de «a partida ficou indecidível».
    """
    outra = replace(
        registro_publico(n, formation="4-3-3"),
        record_ref=ref(DATASET_RESTRITO, 8),
        provider_id=RESTRITA,
        resolution_decision_id=str(DatasetId.derive("decisao-c", str(n))),
        values={
            SemanticRole.HOME_TEAM_NAME: "Mandante FC",
            SemanticRole.AWAY_TEAM_NAME: "Visitante FC",
            SemanticRole.SEASON_LABEL: "2026",
            SemanticRole.HOME_SCORE: "2",
            SemanticRole.AWAY_SCORE: "1",
            SemanticRole.HOME_FORMATION: "4-2-3-1",
        },
    )
    return cenario(registro_publico(n, formation="4-3-3"), outra)


async def um_lote[T](itens: Sequence[T]) -> AsyncIterator[Sequence[T]]:
    """Um iterador assíncrono de UM lote. O caminho mais curto até o caso de uso."""
    yield itens


async def lotes[T](*grupos: Sequence[T]) -> AsyncIterator[Sequence[T]]:
    """Vários lotes, para provar que a execução acumula sem materializar tudo."""
    for grupo in grupos:
        yield grupo


# ============================ cenários da fronteira de licença (PR-04.2.1) ==


def registro_so_com_grafia(n: int = 0) -> ResolvedSourceRecord:
    """Uma fonte `RESEARCH_ONLY` que só empresta o NOME dos times (§7).

    ELA NÃO AFIRMA FATO NENHUM: sem placar, sem horário. O que ela traz são
    rótulos — e rótulos, depois de a resolução provar que apontam para o mesmo
    `TeamId`, não são procedência factual do núcleo.

    É o cenário A da lavagem de licença: a grafia restrita NÃO pode deixar a
    partida comercialmente inelegível.
    """
    return ResolvedSourceRecord(
        record_ref=ref(DATASET_RESTRITO, 40 + n),
        provider_id=RESTRITA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.RESEARCH_ONLY,
        canonical_entity_id=match_id(n),
        resolution_decision_id=str(DatasetId.derive("decisao-grafia", str(n))),
        values={
            SemanticRole.HOME_TEAM_NAME: "Man City",
            SemanticRole.AWAY_TEAM_NAME: "Visitante",
            SemanticRole.SEASON_LABEL: "2026",
        },
    )


def registro_restrito_do_nucleo(n: int = 0) -> ResolvedSourceRecord:
    """Uma fonte `RESEARCH_ONLY` que AFIRMA o núcleo da partida (§8).

    Ela traz placar e horário — os fatos —, com os MESMOS valores da fonte
    pública. Sozinha, ela é a única procedência factual do núcleo; ao lado da
    pública, ela apenas CONFIRMA, e a confirmação não contamina (§42).
    """
    return ResolvedSourceRecord(
        record_ref=ref(DATASET_RESTRITO, 50 + n),
        provider_id=RESTRITA,
        source_type=SourceType.OPEN_DATA,
        license_class=LicenseClass.RESEARCH_ONLY,
        canonical_entity_id=match_id(n),
        resolution_decision_id=str(DatasetId.derive("decisao-nucleo", str(n))),
        values={
            SemanticRole.HOME_TEAM_NAME: "Man City",
            SemanticRole.AWAY_TEAM_NAME: "Visitante",
            SemanticRole.SEASON_LABEL: "2026",
            SemanticRole.KICKOFF: KICKOFF.isoformat(),
            SemanticRole.HOME_SCORE: "2",
            SemanticRole.AWAY_SCORE: "1",
        },
    )


def kickoff_em_conflito(n: int = 0) -> Cenario:
    """Duas fontes discordando do HORÁRIO — conflito de NÚCLEO (§12, §13).

    A identidade da partida é a mesma nas duas: elas resolveram para o mesmo
    `MatchId`. O que diverge é um FATO, e por isso o desfecho é outro do que
    para uma grafia diferente.
    """
    outra = replace(
        registro_publico(n),
        record_ref=ref(DATASET_RESTRITO, 60 + n),
        provider_id=RESTRITA,
        resolution_decision_id=str(DatasetId.derive("decisao-horario", str(n))),
        values={
            SemanticRole.HOME_TEAM_NAME: "Mandante FC",
            SemanticRole.AWAY_TEAM_NAME: "Visitante FC",
            SemanticRole.SEASON_LABEL: "2026",
            # TRÊS HORAS DE DIFERENÇA: não é arredondamento nem fuso mal lido
            # dentro da tolerância — é desacordo sobre quando o jogo foi.
            SemanticRole.KICKOFF: instant(datetime(2026, 3, 14, 22, 30, tzinfo=UTC)).isoformat(),
            SemanticRole.HOME_SCORE: "2",
            SemanticRole.AWAY_SCORE: "1",
        },
    )
    return cenario(registro_publico(n), outra)
