"""O conjunto de artefatos persistido, em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

ESTE É O ÚNICO ADAPTADOR DO PR QUE GUARDA NÚMERO. As linhas normalizadas moram
no Parquet (ADR-0037); as medianas e os IQRs moram aqui, porque são poucos e
porque a leitura ao vivo vai pedi-los por competição, uma partida de cada vez.

`numeric`, E NÃO `double precision`. A conversão acontece nas duas pontas: o
`Decimal` do domínio vira `numeric` na escrita, e volta `Decimal` na leitura. O
asyncpg faz isso sem perder dígito — e é por isso que a coluna não pode ser de
ponto flutuante: `double` faria a escala de uma competição depender do
arredondamento do driver.

A ESCRITA DOS PACOTES É UMA TRANSAÇÃO SÓ. Um conjunto com metade das
competições gravadas não é um conjunto parcial: é um conjunto que normalizaria
metade das linhas e recusaria a outra metade, com a impressão dizendo que está
completo.

E ELA RECUSA UM CONJUNTO JÁ PUBLICADO. Um `READY` que aceitasse artefato novo
faria toda versão normalizada publicada sobre ele passar a apontar para números
diferentes dos que gravou — e a impressão na linha deixaria de descrever a
linha.

A TRANSIÇÃO É `UPDATE ... WHERE status = $esperado`, como no dataset cru: é essa
cláusula que serializa dois ajustes simultâneos sem lock distribuído.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    NormalizerArtifactSet,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Instant

_COLUNAS_CONJUNTO: Final[str] = """
    id, status, plan_fingerprint, split_fingerprint, reference_end_exclusive,
    reference_fingerprint, fingerprint, source_version_id,
    source_raw_content_fingerprint, reference_rows,
    created_at, created_by, created_by_kind, completed_at, failure_reason
"""

_COLUNAS_PACOTE: Final[str] = """
    set_id, competition, competition_id, reference_fingerprint,
    plan_fingerprint, fingerprint, artifact_count, fitted_count,
    insufficient_count, degenerate_count
"""

_COLUNAS_ARTEFATO: Final[str] = """
    set_id, competition, feature_key, feature_version, feature_fingerprint,
    competition_id, normalizer_key, normalizer_fingerprint, fit_cutoff,
    status, median, q1, q3, iqr, population_count, available_count,
    population_digest, source_corpus_fingerprint, source_space_fingerprint,
    fingerprint, detail
"""


@final
class PostgresNormalizerArtifactSetRepository:
    """O ajuste persistido — conjunto, pacotes e artefatos."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_set(
        self,
        *,
        plan_fingerprint: str,
        split_fingerprint: str,
        reference_end_exclusive: Instant,
        reference_fingerprint: str,
        source_version_id: str,
        source_raw_content_fingerprint: str,
        reference_rows: int,
        at: Instant,
        created_by: Actor,
    ) -> NormalizerArtifactSet:
        conjunto = NormalizerArtifactSet.draft(
            plan_fingerprint=plan_fingerprint,
            split_fingerprint=split_fingerprint,
            reference_end_exclusive=reference_end_exclusive,
            reference_fingerprint=reference_fingerprint,
            at=at,
            created_by=created_by,
            source_version_id=source_version_id,
            source_raw_content_fingerprint=source_raw_content_fingerprint,
        )
        conjunto = replace(conjunto, reference_rows=reference_rows)
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO normalizer_artifact_sets (
                    id, status, plan_fingerprint, split_fingerprint,
                    reference_end_exclusive, reference_fingerprint, fingerprint,
                    source_version_id, source_raw_content_fingerprint,
                    reference_rows, created_at, created_by, created_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                uuid.UUID(conjunto.id),
                conjunto.status.value,
                plan_fingerprint,
                split_fingerprint,
                reference_end_exclusive,
                reference_fingerprint,
                # A IMPRESSÃO DE UM CONJUNTO SEM PACOTE ainda assim identifica o
                # ajuste que ele PRETENDE ser: plano, divisão, fronteira e
                # referência já estão decididos. Ela é reescrita quando os
                # pacotes chegam, e as duas escritas são a mesma transição.
                conjunto.fingerprint,
                uuid.UUID(source_version_id) if source_version_id else None,
                source_raw_content_fingerprint or None,
                reference_rows,
                at,
                created_by.id,
                created_by.kind.value,
            )
        return conjunto

    async def save_bundles(
        self,
        set_id: str,
        bundles: Sequence[CompetitionNormalizerArtifactBundle],
    ) -> int:
        """Grava os pacotes e os artefatos, numa transação só."""
        atual = await self.by_id(set_id)
        if atual is None:
            raise NotFoundError(
                f"o conjunto de artefatos {set_id} não existe",
                context={"set_id": set_id},
            )
        if atual.status.is_readable_corpus:
            raise ConflictError(
                f"o conjunto {set_id} está em {atual.status} e não aceita artefato "
                "novo: toda versão normalizada publicada sobre ele passaria a apontar "
                "para números diferentes dos que gravou",
                context={"set_id": set_id, "status": atual.status.value},
            )
        if not bundles:
            return 0
        completo = replace(atual, bundles=tuple(sorted(bundles, key=lambda b: b.competition)))
        async with self._db.acquire() as conexao, conexao.transaction():
            # APAGAR ANTES DE GRAVAR. Reajustar depois de uma falha parcial é o
            # caminho normal, e um `ON CONFLICT` deixaria para trás o artefato
            # de uma competição que sumiu do escopo — um artefato órfão que
            # normalizaria linhas que o ajuste novo não cobre.
            await conexao.execute(
                "DELETE FROM normalizer_artifact_bundles WHERE set_id = $1",
                uuid.UUID(set_id),
            )
            await conexao.executemany(
                f"""
                INSERT INTO normalizer_artifact_bundles ({_COLUNAS_PACOTE})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                [
                    (
                        uuid.UUID(set_id),
                        pacote.competition,
                        pacote.competition_id.value,
                        pacote.reference_fingerprint,
                        pacote.plan_fingerprint,
                        pacote.fingerprint,
                        len(pacote.artifacts),
                        pacote.counts()[FitStatus.FITTED.value],
                        pacote.counts()[FitStatus.INSUFFICIENT_SAMPLE.value],
                        pacote.counts()[FitStatus.DEGENERATE_SCALE.value],
                    )
                    for pacote in completo.bundles
                ],
            )
            await conexao.executemany(
                f"""
                INSERT INTO normalizer_fit_artifacts ({_COLUNAS_ARTEFATO})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, $18, $19, $20, $21)
                """,
                [
                    (
                        uuid.UUID(set_id),
                        pacote.competition,
                        artefato.feature_key,
                        artefato.feature_version,
                        artefato.feature_fingerprint,
                        artefato.competition_id.value,
                        artefato.normalizer_key,
                        artefato.normalizer_fingerprint,
                        json.dumps(artefato.fit_cutoff, sort_keys=True, default=str),
                        artefato.status.value,
                        artefato.median,
                        artefato.q1,
                        artefato.q3,
                        artefato.iqr,
                        artefato.population_count,
                        artefato.available_count,
                        artefato.population_digest,
                        artefato.source_corpus_fingerprint,
                        artefato.source_space_fingerprint,
                        artefato.fingerprint,
                        artefato.detail,
                    )
                    for pacote in completo.bundles
                    for artefato in pacote.artifacts
                ],
            )
            # A IMPRESSÃO DO CONJUNTO MUDA QUANDO OS PACOTES CHEGAM, porque é
            # deles que ela é feita. Gravá-la aqui é o que torna «este ajuste já
            # existe?» uma consulta indexada.
            await conexao.execute(
                """
                UPDATE normalizer_artifact_sets SET fingerprint = $2 WHERE id = $1
                """,
                uuid.UUID(set_id),
                completo.fingerprint,
            )
        return sum(len(pacote.artifacts) for pacote in completo.bundles)

    async def by_id(self, set_id: str) -> NormalizerArtifactSet | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_CONJUNTO} FROM normalizer_artifact_sets WHERE id = $1",
                uuid.UUID(set_id),
            )
            if linha is None:
                return None
            pacotes = await self._pacotes(conexao, set_id)
        return _para_conjunto(linha, pacotes)

    async def by_fingerprint(self, fingerprint: str) -> NormalizerArtifactSet | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                SELECT {_COLUNAS_CONJUNTO} FROM normalizer_artifact_sets
                WHERE fingerprint = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                fingerprint,
            )
            if linha is None:
                return None
            pacotes = await self._pacotes(conexao, str(linha["id"]))
        return _para_conjunto(linha, pacotes)

    async def transition(
        self,
        set_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        failure_reason: str | None = None,
    ) -> NormalizerArtifactSet:
        atual = await self.by_id(set_id)
        if atual is None:
            raise NotFoundError(
                f"o conjunto de artefatos {set_id} não existe",
                context={"set_id": set_id},
            )
        atual.require_transition(target)
        movido = replace(
            atual,
            status=target,
            completed_at=at if target.is_terminal else atual.completed_at,
            failure_reason=(atual.failure_reason if failure_reason is None else failure_reason),
        )
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE normalizer_artifact_sets
                SET status = $2, completed_at = $3, failure_reason = $4
                WHERE id = $1 AND status = $5
                """,
                uuid.UUID(set_id),
                movido.status.value,
                movido.completed_at,
                movido.failure_reason,
                atual.status.value,
            )
        if _linhas_afetadas(resultado) != 1:
            raise ConflictError(
                f"o conjunto {set_id} não estava mais em {atual.status} quando a "
                "transição foi aplicada: outra execução o moveu",
                context={"expected": atual.status.value, "target": target.value},
            )
        return movido

    async def list_sets(
        self,
        *,
        status: DatasetVersionStatus | None = None,
        source_version_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[NormalizerArtifactSet]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_CONJUNTO} FROM normalizer_artifact_sets
                WHERE ($1::text IS NULL OR status = $1)
                  AND ($2::uuid IS NULL OR source_version_id = $2)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                None if status is None else status.value,
                None if source_version_id is None else uuid.UUID(source_version_id),
                limit,
            )
            # SEM OS PACOTES. Listar cinquenta conjuntos com todos os artefatos
            # de cada um traria dezenas de milhares de linhas para responder
            # «quais ajustes existem» — a lista é administrativa, e o corpo vem
            # em `by_id`.
            return [_para_conjunto(linha, ()) for linha in linhas]

    async def bundle_of(
        self, set_id: str, *, competition: str
    ) -> CompetitionNormalizerArtifactBundle | None:
        async with self._db.acquire() as conexao:
            pacote = await conexao.fetchrow(
                f"""
                SELECT {_COLUNAS_PACOTE} FROM normalizer_artifact_bundles
                WHERE set_id = $1 AND competition = $2
                """,
                uuid.UUID(set_id),
                competition,
            )
            if pacote is None:
                return None
            artefatos = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_ARTEFATO} FROM normalizer_fit_artifacts
                WHERE set_id = $1 AND competition = $2
                ORDER BY feature_key
                """,
                uuid.UUID(set_id),
                competition,
            )
        return _para_pacote(pacote, artefatos)

    # ------------------------------------------------------------ interno --

    async def _pacotes(
        self, conexao: Any, set_id: str
    ) -> tuple[CompetitionNormalizerArtifactBundle, ...]:
        """Todos os pacotes em DUAS consultas, e não em uma por competição.

        UM `SELECT` POR COMPETIÇÃO SERIA N+1 sobre um conjunto que pode ter
        dezenas de ligas, e a leitura do conjunto acontece em toda construção.
        """
        pacotes = await conexao.fetch(
            f"""
            SELECT {_COLUNAS_PACOTE} FROM normalizer_artifact_bundles
            WHERE set_id = $1
            ORDER BY competition
            """,
            uuid.UUID(set_id),
        )
        if not pacotes:
            return ()
        artefatos = await conexao.fetch(
            f"""
            SELECT {_COLUNAS_ARTEFATO} FROM normalizer_fit_artifacts
            WHERE set_id = $1
            ORDER BY competition, feature_key
            """,
            uuid.UUID(set_id),
        )
        por_competicao: dict[str, list[Any]] = {}
        for linha in artefatos:
            por_competicao.setdefault(linha["competition"], []).append(linha)
        return tuple(
            _para_pacote(pacote, por_competicao.get(pacote["competition"], []))
            for pacote in pacotes
        )


# =============================================================== mapeamento ==


def _para_conjunto(
    linha: Any, pacotes: Sequence[CompetitionNormalizerArtifactBundle]
) -> NormalizerArtifactSet:
    conjunto = NormalizerArtifactSet(
        id=str(linha["id"]),
        plan_fingerprint=linha["plan_fingerprint"],
        split_fingerprint=linha["split_fingerprint"],
        reference_end_exclusive=linha["reference_end_exclusive"],
        reference_fingerprint=linha["reference_fingerprint"],
        status=DatasetVersionStatus(linha["status"]),
        created_at=linha["created_at"],
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
        bundles=tuple(pacotes),
        source_version_id=(
            "" if linha["source_version_id"] is None else str(linha["source_version_id"])
        ),
        source_raw_content_fingerprint=linha["source_raw_content_fingerprint"] or "",
        reference_rows=linha["reference_rows"],
        completed_at=linha["completed_at"],
        failure_reason=linha["failure_reason"],
    )
    # A IMPRESSÃO GRAVADA É CONFERIDA CONTRA A RECALCULADA — e só quando os
    # pacotes vieram junto. Uma listagem administrativa não os carrega, e
    # conferir ali acusaria uma divergência que não existe.
    if pacotes and conjunto.fingerprint != linha["fingerprint"]:
        raise ConflictError(
            "a impressão gravada do conjunto de artefatos discorda da recalculada: "
            "os números no banco não são os que produziram aquela impressão",
            context={"stored": linha["fingerprint"], "rebuilt": conjunto.fingerprint},
        )
    return conjunto


def _para_pacote(linha: Any, artefatos: Sequence[Any]) -> CompetitionNormalizerArtifactBundle:
    pacote = CompetitionNormalizerArtifactBundle.of(
        competition=linha["competition"],
        competition_id=CompetitionId(linha["competition_id"]),
        reference_fingerprint=linha["reference_fingerprint"],
        plan_fingerprint=linha["plan_fingerprint"],
        artifacts=[_para_artefato(a) for a in artefatos],
    )
    if len(pacote.artifacts) != linha["artifact_count"]:
        raise ConflictError(
            f"o pacote de {pacote.competition} declara {linha['artifact_count']} "
            f"artefatos e trouxe {len(pacote.artifacts)}: a leitura está incompleta, "
            "e normalizar com ela deixaria eixos sem escala sem dizer por quê",
            context={
                "competition": pacote.competition,
                "declared": str(linha["artifact_count"]),
            },
        )
    return pacote


def _para_artefato(linha: Any) -> NormalizerFitArtifact:
    corte = linha["fit_cutoff"]
    if isinstance(corte, str):
        corte = json.loads(corte)
    return NormalizerFitArtifact(
        feature_key=linha["feature_key"],
        feature_version=linha["feature_version"],
        feature_fingerprint=linha["feature_fingerprint"],
        normalizer_key=linha["normalizer_key"],
        normalizer_fingerprint=linha["normalizer_fingerprint"],
        competition_id=CompetitionId(linha["competition_id"]),
        source_corpus_fingerprint=linha["source_corpus_fingerprint"],
        source_space_fingerprint=linha["source_space_fingerprint"],
        population_count=linha["population_count"],
        available_count=linha["available_count"],
        population_digest=linha["population_digest"],
        fit_cutoff=dict(corte),
        status=FitStatus(linha["status"]),
        median=_decimal(linha["median"]),
        q1=_decimal(linha["q1"]),
        q3=_decimal(linha["q3"]),
        iqr=_decimal(linha["iqr"]),
        detail=linha["detail"],
    )


def _decimal(valor: Any) -> Decimal | None:
    """O `numeric` de volta em `Decimal` — e um `float` é RECUSADO.

    ELE NÃO CONVERTE POR CONVENIÊNCIA. Se um driver devolvesse `float`, aceitar
    e converter esconderia que a escala passou por ponto flutuante em algum
    lugar do caminho — e o número resultante seria plausível.
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    raise ValidationError(
        f"a escala voltou do banco como {type(valor).__name__} e não Decimal: a "
        "coluna precisa ser `numeric`, e converter aqui esconderia a perda",
        context={"type": type(valor).__name__},
    )


def _linhas_afetadas(resultado: str) -> int:
    partes = resultado.split()
    return int(partes[-1]) if partes and partes[-1].isdigit() else 0
