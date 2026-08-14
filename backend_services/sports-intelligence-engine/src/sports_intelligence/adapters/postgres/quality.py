"""Os repositórios de qualidade em SQL escrito à mão.

TODA LEITURA É EM MASSA, e a reconstrução de um veredito toca cinco tabelas —
avaliação, cobertura, licenças, identidade e problemas. Fazê-lo por partida
custaria cinco consultas por linha; aqui são cinco por LOTE, com
`= ANY($1::uuid[])` em cada uma e a junção feita em memória sobre o que voltou.

NENHUM `UPDATE` SOBRE AVALIAÇÃO. A única exceção é fechar uma execução em
curso, e ela é condicional a `status = 'RUNNING'` — como toda transição desta
base desde o PR-02. Um teste de arquitetura lê este arquivo e falha se
aparecer outro.

`expected_count` VAI E VOLTA COMO `None` (§58, §83). O `NOT_DECLARED` que
virasse `0` no banco seria a perda mais silenciosa deste PR: o relatório
passaria a dizer «0% de cobertura de escalação» sobre uma fonte que nunca
prometeu escalação nenhuma.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.assessment import (
    BuildEligibility,
    IdentityConfidences,
    MatchQualityAssessment,
)
from sports_intelligence.domain.quality.coverage import (
    CoverageFamily,
    CoverageReport,
    CoverageState,
    FamilyCoverage,
)
from sports_intelligence.domain.quality.dimensions import QualityVector
from sports_intelligence.domain.quality.issues import IssueCode, QualityIssue
from sports_intelligence.domain.quality.licensing import (
    LicenseFootprint,
    UsageEligibility,
    UsageVerdict,
)
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.quality.runs import (
    MatchQualityRecord,
    QualityCounts,
    QualityRun,
    QualityRunInput,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import instant

#: Quantas avaliações vão ao banco por rodada de `unnest`. Troca idas ao banco
#: por tamanho de array; o valor acompanha o dos candidatos de fusão, que o
#: benchmark do PR-03.1 calibrou em quinhentos sem pico de memória visível.
_AVALIACOES_POR_RODADA: Final[int] = 500


@final
class PostgresQualityRunRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create(self, run: QualityRun) -> QualityRun:
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                """
                INSERT INTO quality_runs (
                    id, policy_major, policy_minor, policy_fingerprint,
                    policy_snapshot, status, started_at, triggered_by,
                    triggered_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                uuid.UUID(run.id),
                run.policy_version.major,
                run.policy_version.minor,
                run.policy_fingerprint.value,
                json.dumps({}),
                run.status.value,
                run.started_at,
                run.triggered_by.id,
                run.triggered_by.kind.value,
            )
            await conexao.executemany(
                """
                INSERT INTO quality_run_inputs (
                    quality_run_id, fusion_run_id, fusion_output_fingerprint
                )
                VALUES ($1, $2, $3)
                """,
                [
                    (
                        uuid.UUID(run.id),
                        uuid.UUID(entrada.fusion_run_id),
                        entrada.fusion_output_fingerprint.value
                        if entrada.fusion_output_fingerprint
                        else None,
                    )
                    for entrada in run.inputs
                ],
            )
        return run

    async def save_policy_snapshot(
        self, run_id: str, policy: HistoricalQualityPolicy
    ) -> None:
        """Grava a forma canônica da política DENTRO da execução (§9).

        SEPARADO DO `create` porque a política é um objeto de domínio e o
        repositório de execução não deveria conhecê-la para criar uma linha.
        Chamá-lo é responsabilidade do caso de uso, que já a tem em mãos.

        CONDICIONAL A `RUNNING`: uma execução concluída não ganha snapshot
        novo, senão a política de uma avaliação de seis meses atrás poderia
        ser reescrita — que é exatamente o que a imutabilidade impede.
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                "UPDATE quality_runs SET policy_snapshot = $2 "
                "WHERE id = $1 AND status = 'RUNNING'",
                uuid.UUID(run_id),
                json.dumps(policy.as_canonical()),
            )

    async def finish(self, run: QualityRun) -> bool:
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE quality_runs
                SET status = $2, completed_at = $3, failure_reason = $4,
                    records_examined = $5, eligible_count = $6,
                    review_required_count = $7, ineligible_count = $8,
                    output_fingerprint = $9
                WHERE id = $1 AND status = 'RUNNING'
                """,
                uuid.UUID(run.id),
                run.status.value,
                run.completed_at,
                run.failure_reason,
                run.counts.records_examined,
                run.counts.eligible,
                run.counts.review_required,
                run.counts.ineligible,
                run.output_fingerprint.value if run.output_fingerprint else None,
            )
        return _linhas(resultado) > 0

    async def by_id(self, run_id: str) -> QualityRun | None:
        try:
            identificador = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM quality_runs WHERE id = $1", identificador
            )
            if linha is None:
                return None
            entradas = await conexao.fetch(
                "SELECT fusion_run_id, fusion_output_fingerprint FROM quality_run_inputs "
                "WHERE quality_run_id = $1 ORDER BY fusion_run_id",
                identificador,
            )
        return _para_execucao(linha, entradas)

    async def recent(self, *, limit: int = 20) -> Sequence[QualityRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM quality_runs ORDER BY started_at DESC LIMIT $1",
                min(limit, 100),
            )
            if not linhas:
                return []
            # UMA CONSULTA PARA AS ENTRADAS DE TODAS AS EXECUÇÕES, e não uma
            # por execução: vinte execuções na tela não valem vinte idas ao
            # banco (§68).
            entradas = await conexao.fetch(
                "SELECT quality_run_id, fusion_run_id, fusion_output_fingerprint "
                "FROM quality_run_inputs WHERE quality_run_id = ANY($1::uuid[]) "
                "ORDER BY quality_run_id, fusion_run_id",
                [linha["id"] for linha in linhas],
            )
        por_execucao: dict[Any, list[Any]] = {}
        for entrada in entradas:
            por_execucao.setdefault(entrada["quality_run_id"], []).append(entrada)
        return [
            _para_execucao(linha, por_execucao.get(linha["id"], [])) for linha in linhas
        ]


@final
class PostgresQualityAssessmentRepository:
    """Vereditos por partida, gravados e relidos em massa."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def append_many(
        self,
        records: Sequence[MatchQualityRecord],
        *,
        policy: HistoricalQualityPolicy,
    ) -> int:
        """Grava um conjunto de vereditos, em blocos.

        A POLÍTICA VEM JUNTO, e não é acoplamento gratuito: a severidade de
        cada problema é DELA (§12), e o `QualityIssue` deliberadamente não a
        carrega. As duas alternativas eram piores — o adapter escolher a
        política sozinho (e poder discordar da que rodou) ou um estado de
        módulo entre o cálculo e a gravação, que duas execuções concorrentes
        corromperiam.
        """
        if not records:
            return 0
        gravados = 0
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(records), _AVALIACOES_POR_RODADA):
                gravados += await self._gravar_rodada(
                    conexao,
                    records[inicio : inicio + _AVALIACOES_POR_RODADA],
                    policy,
                )
        return gravados

    @staticmethod
    async def _gravar_rodada(
        conexao: Any,
        records: Sequence[MatchQualityRecord],
        policy: HistoricalQualityPolicy,
    ) -> int:
        """Grava um bloco em SEIS consultas — uma por tabela, não por linha.

        `executemany` E NÃO `unnest` NA PRIMEIRA, e o motivo é o tipo: duas
        colunas são `text[]`, e `unnest` sobre um array de arrays o ACHATA —
        as famílias das quinhentas avaliações do bloco virariam uma lista só.
        É o tipo de defeito que passa no teste de uma linha e corrompe o lote.

        `executemany` continua sendo UMA ida ao banco: o statement é preparado
        uma vez e os N conjuntos de argumentos vão juntos.

        A SEGUNDA CONSULTA DIZ QUAIS ENTRARAM. Como os ids são nossos e recém
        sorteados, `WHERE id = ANY(...)` devolve exatamente os que existem — e
        um veredito já gravado por uma tentativa anterior não ganha cobertura
        duplicada.
        """
        await conexao.executemany(
            """
            INSERT INTO match_quality_assessments (
                id, quality_run_id, match_id, fusion_group_id,
                integrity, consistency, completeness, identity_confidence,
                temporal_integrity, provenance_quality,
                eligibility, reason, usage_research, usage_commercial,
                requires_attribution, families_in_conflict,
                families_unresolved_identity
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17)
            ON CONFLICT (quality_run_id, match_id) DO NOTHING
            """,
            [
                (
                    uuid.UUID(r.id),
                    uuid.UUID(r.quality_run_id),
                    r.match_id.value,
                    uuid.UUID(r.fusion_group_id),
                    r.assessment.quality.integrity,
                    r.assessment.quality.consistency,
                    r.assessment.quality.completeness,
                    r.assessment.quality.identity_confidence,
                    r.assessment.quality.temporal_integrity,
                    r.assessment.quality.provenance_quality,
                    r.assessment.eligibility.value,
                    r.assessment.reason,
                    r.assessment.usage.research.value,
                    r.assessment.usage.commercial.value,
                    r.assessment.usage.footprint.requires_attribution,
                    [f.value for f in r.families_in_conflict],
                    [f.value for f in r.families_unresolved_identity],
                )
                for r in records
            ],
        )
        presentes = await conexao.fetch(
            "SELECT id FROM match_quality_assessments WHERE id = ANY($1::uuid[])",
            [uuid.UUID(r.id) for r in records],
        )
        aceitos = {linha["id"] for linha in presentes}
        gravaveis = [r for r in records if uuid.UUID(r.id) in aceitos]
        if not gravaveis:
            return 0

        await _gravar_cobertura(conexao, gravaveis)
        await _gravar_licencas(conexao, gravaveis)
        await _gravar_identidade(conexao, gravaveis)
        await _gravar_problemas(conexao, gravaveis, policy)
        return len(gravaveis)

    async def by_run(
        self,
        run_id: str,
        *,
        eligibility: BuildEligibility | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[Sequence[MatchQualityRecord], int]:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM match_quality_assessments "
                "WHERE quality_run_id = $1 AND ($2::text IS NULL OR eligibility = $2)",
                uuid.UUID(run_id),
                eligibility.value if eligibility else None,
            )
            linhas = await conexao.fetch(
                """
                SELECT * FROM match_quality_assessments
                WHERE quality_run_id = $1 AND ($2::text IS NULL OR eligibility = $2)
                ORDER BY match_id LIMIT $3 OFFSET $4
                """,
                uuid.UUID(run_id),
                eligibility.value if eligibility else None,
                min(limit, 500),
                offset,
            )
            registros = await self._hidratar(conexao, linhas)
        return registros, int(total or 0)

    async def page_after(
        self, run_id: str, *, limit: int = 500, after_match_id: str | None = None
    ) -> Sequence[MatchQualityRecord]:
        """A próxima página de vereditos, por chave e não por `OFFSET`.

        TODOS OS VEREDITOS, e não só os elegíveis. A construção precisa se
        pronunciar sobre os três desfechos (§85): o inelegível vira `SKIPPED`,
        o de revisão vira `REVIEW_REQUIRED`, e os dois deixam registro. Filtrar
        aqui faria as partidas recusadas sumirem do build sem linha nenhuma —
        e a ausência de linha é indistinguível de a partida nunca ter existido.

        `match_id > $2` USA O ÍNDICE ÚNICO `(quality_run_id, match_id)` e custa
        o mesmo na página 1 e na página 100. Com `OFFSET`, a centésima página
        faria o banco percorrer cinquenta mil linhas para descartá-las.
        """
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT * FROM match_quality_assessments
                WHERE quality_run_id = $1
                  AND ($2::uuid IS NULL OR match_id > $2::uuid)
                ORDER BY match_id LIMIT $3
                """,
                uuid.UUID(run_id),
                uuid.UUID(after_match_id) if after_match_id else None,
                min(limit, 2_000),
            )
            return await self._hidratar(conexao, linhas)

    async def by_matches(
        self, run_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[MatchQualityRecord]:
        if not match_ids:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM match_quality_assessments "
                "WHERE quality_run_id = $1 AND match_id = ANY($2::uuid[]) "
                "ORDER BY match_id",
                uuid.UUID(run_id),
                [m.value for m in match_ids],
            )
            return await self._hidratar(conexao, linhas)

    @staticmethod
    async def _hidratar(
        conexao: Any, linhas: Sequence[Any]
    ) -> Sequence[MatchQualityRecord]:
        """Reconstrói os vereditos em QUATRO consultas, não em quatro por linha.

        É o mesmo desenho do carregamento de evidências do PR-03: uma consulta
        por tabela-filha com `= ANY`, e a junção em memória sobre o que voltou.
        """
        if not linhas:
            return []
        ids = [linha["id"] for linha in linhas]
        coberturas = await conexao.fetch(
            "SELECT * FROM quality_assessment_coverage WHERE assessment_id = ANY($1::uuid[])",
            ids,
        )
        licencas = await conexao.fetch(
            "SELECT * FROM quality_assessment_licenses WHERE assessment_id = ANY($1::uuid[])",
            ids,
        )
        identidades = await conexao.fetch(
            "SELECT * FROM quality_assessment_identity WHERE assessment_id = ANY($1::uuid[])",
            ids,
        )
        problemas = await conexao.fetch(
            "SELECT * FROM quality_assessment_issues WHERE assessment_id = ANY($1::uuid[]) "
            "ORDER BY issue_code, subject",
            ids,
        )
        return [
            _para_registro(
                linha,
                _agrupar(coberturas, linha["id"]),
                _agrupar(licencas, linha["id"]),
                _agrupar(identidades, linha["id"]),
                _agrupar(problemas, linha["id"]),
            )
            for linha in linhas
        ]


# ------------------------------------------------------------- escrita ----


async def _gravar_cobertura(conexao: Any, records: Sequence[MatchQualityRecord]) -> None:
    linhas = [
        (uuid.UUID(r.id), c)
        for r in records
        for c in r.assessment.coverage.families
    ]
    if not linhas:
        return
    await conexao.execute(
        """
        INSERT INTO quality_assessment_coverage (
            assessment_id, family, state, available_count, expected_count
        )
        SELECT * FROM unnest($1::uuid[], $2::text[], $3::text[], $4::integer[], $5::integer[])
        ON CONFLICT (assessment_id, family) DO NOTHING
        """,
        [i for i, _ in linhas],
        [c.family.value for _, c in linhas],
        [c.state.value for _, c in linhas],
        [c.available_count for _, c in linhas],
        # `None` VAI COMO `NULL` E VOLTA COMO `None` (§83). É a linha que
        # impede `NOT_DECLARED` de virar `0%` na primeira ida ao banco.
        [c.expected_count for _, c in linhas],
    )


async def _gravar_licencas(conexao: Any, records: Sequence[MatchQualityRecord]) -> None:
    linhas = [
        (uuid.UUID(r.id), familia, licenca)
        for r in records
        for familia, licencas in r.assessment.usage.footprint.by_family.items()
        for licenca in sorted(licencas, key=lambda lic: lic.value)
    ]
    if not linhas:
        return
    await conexao.execute(
        """
        INSERT INTO quality_assessment_licenses (assessment_id, family, license_class)
        SELECT * FROM unnest($1::uuid[], $2::text[], $3::text[])
        ON CONFLICT DO NOTHING
        """,
        [i for i, _, _ in linhas],
        [f.value for _, f, _ in linhas],
        [lic.value for _, _, lic in linhas],
    )


async def _gravar_identidade(conexao: Any, records: Sequence[MatchQualityRecord]) -> None:
    linhas = [
        (uuid.UUID(r.id), sujeito, valor)
        for r in records
        for sujeito, valor in sorted(
            r.assessment.identity.by_subject.items(), key=lambda p: p[0].value
        )
    ]
    if not linhas:
        return
    await conexao.execute(
        """
        INSERT INTO quality_assessment_identity (assessment_id, subject_type, confidence)
        SELECT * FROM unnest($1::uuid[], $2::text[], $3::double precision[])
        ON CONFLICT DO NOTHING
        """,
        [i for i, _, _ in linhas],
        [s.value for _, s, _ in linhas],
        [v for _, _, v in linhas],
    )


async def _gravar_problemas(
    conexao: Any,
    records: Sequence[MatchQualityRecord],
    policy: HistoricalQualityPolicy,
) -> None:
    """Grava os problemas COM a severidade que a política atribuiu.

    A SEVERIDADE É GRAVADA, e é redundante com o snapshot da política de
    propósito (§12). O `QualityIssue` não a carrega — decisão do PR-04.1, para
    que o validador não a carimbe — e o banco precisa dela: sem a coluna,
    «quantos bloqueantes esta execução encontrou» exigiria reaplicar a política
    de seis meses atrás sobre cada linha. E essa política pode ter mudado
    desde então, que é justamente o motivo de ela ser versionada.
    """
    linhas = [(uuid.UUID(r.id), p) for r in records for p in r.assessment.issues]
    if not linhas:
        return
    await conexao.execute(
        """
        INSERT INTO quality_assessment_issues (
            assessment_id, issue_code, severity, dimension, subject, context
        )
        SELECT * FROM unnest($1::uuid[], $2::text[], $3::text[], $4::text[],
                             $5::text[], $6::jsonb[])
        ON CONFLICT (assessment_id, issue_code, subject) DO NOTHING
        """,
        [i for i, _ in linhas],
        [p.code.value for _, p in linhas],
        [policy.severity_of(p.code).name for _, p in linhas],
        [p.dimension.value if p.dimension else None for _, p in linhas],
        [p.subject[:512] for _, p in linhas],
        [json.dumps(dict(sorted(p.context.items()))) for _, p in linhas],
    )


# ------------------------------------------------------------- tradução ----


def _agrupar(linhas: Sequence[Any], assessment_id: Any) -> list[Any]:
    return [linha for linha in linhas if linha["assessment_id"] == assessment_id]


def _para_execucao(linha: Any, entradas: Sequence[Any]) -> QualityRun:
    return QualityRun(
        id=str(linha["id"]),
        inputs=tuple(
            QualityRunInput(
                fusion_run_id=str(e["fusion_run_id"]),
                fusion_output_fingerprint=(
                    ContentHash(e["fusion_output_fingerprint"])
                    if e["fusion_output_fingerprint"]
                    else None
                ),
            )
            for e in entradas
        ),
        policy_version=PolicyVersion(
            major=linha["policy_major"], minor=linha["policy_minor"]
        ),
        policy_fingerprint=ContentHash(linha["policy_fingerprint"]),
        status=RunStatus(linha["status"]),
        started_at=instant(linha["started_at"]),
        triggered_by=Actor(
            id=linha["triggered_by"], kind=ActorKind(linha["triggered_by_kind"])
        ),
        counts=QualityCounts(
            records_examined=linha["records_examined"],
            eligible=linha["eligible_count"],
            review_required=linha["review_required_count"],
            ineligible=linha["ineligible_count"],
        ),
        completed_at=(
            instant(linha["completed_at"]) if linha["completed_at"] else None
        ),
        failure_reason=linha["failure_reason"],
        output_fingerprint=(
            ContentHash(linha["output_fingerprint"])
            if linha["output_fingerprint"]
            else None
        ),
    )


def _para_registro(
    linha: Any,
    coberturas: Sequence[Any],
    licencas: Sequence[Any],
    identidades: Sequence[Any],
    problemas: Sequence[Any],
) -> MatchQualityRecord:
    avaliacao = MatchQualityAssessment(
        match_id=MatchId(linha["match_id"]),
        quality=QualityVector(
            integrity=linha["integrity"],
            consistency=linha["consistency"],
            completeness=linha["completeness"],
            identity_confidence=linha["identity_confidence"],
            temporal_integrity=linha["temporal_integrity"],
            provenance_quality=linha["provenance_quality"],
        ),
        coverage=CoverageReport.of(
            *(
                FamilyCoverage(
                    family=CoverageFamily(c["family"]),
                    state=CoverageState(c["state"]),
                    available_count=c["available_count"],
                    # `NULL` VOLTA COMO `None`, e é o §83 fechando o ciclo.
                    expected_count=c["expected_count"],
                )
                for c in coberturas
            )
        ),
        identity=IdentityConfidences(
            by_subject={
                SubjectType(i["subject_type"]): i["confidence"] for i in identidades
            }
        ),
        usage=UsageVerdict(
            research=UsageEligibility(linha["usage_research"]),
            commercial=UsageEligibility(linha["usage_commercial"]),
            footprint=_pegada(licencas),
        ),
        issues=tuple(
            QualityIssue(
                code=IssueCode(p["issue_code"]),
                subject=p["subject"],
                context=_contexto(p["context"]),
            )
            for p in problemas
        ),
        eligibility=BuildEligibility(linha["eligibility"]),
        reason=linha["reason"],
    )
    return MatchQualityRecord(
        id=str(linha["id"]),
        quality_run_id=str(linha["quality_run_id"]),
        fusion_group_id=str(linha["fusion_group_id"]),
        assessment=avaliacao,
        families_in_conflict=tuple(
            CoverageFamily(f) for f in linha["families_in_conflict"]
        ),
        families_unresolved_identity=tuple(
            CoverageFamily(f) for f in linha["families_unresolved_identity"]
        ),
    )


def _pegada(licencas: Sequence[Any]) -> LicenseFootprint:
    por_familia: dict[CoverageFamily, set[LicenseClass]] = {}
    for linha in licencas:
        familia = CoverageFamily(linha["family"])
        por_familia.setdefault(familia, set()).add(LicenseClass(linha["license_class"]))
    return LicenseFootprint(
        by_family={f: frozenset(ls) for f, ls in por_familia.items()}
    )


def _contexto(bruto: Any) -> dict[str, str]:
    carregado = json.loads(bruto) if isinstance(bruto, str) else dict(bruto or {})
    return {str(k): str(v) for k, v in carregado.items()}


def _linhas(resultado: str) -> int:
    try:
        return int(str(resultado).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0
