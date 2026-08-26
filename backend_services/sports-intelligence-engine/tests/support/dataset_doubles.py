"""Os duplos em memória do PR-05.5.1 — com as MESMAS restrições dos reais.

A ARMADILHA É SEMPRE A MESMA: um duplo mais permissivo que o real deixa passar
exatamente a classe de erro que o real bloquearia em produção. Então aqui:

    `transition`            é condicional ao estado anterior, como o
                            `UPDATE ... WHERE status = $n`
    `create_version`        recusa `(dataset_id, version)` repetido
    `record_objects`        é idempotente por chave, como o `ON CONFLICT`
    `save` do manifesto     recusa o segundo manifesto da mesma versão
    `materialize_partition` recusa reescrever a mesma chave
    `verify_object`         devolve as linhas NA ORDEM em que foram gravadas —
                            e um teste consegue mandá-lo embaralhar

O MATERIALIZADOR FALSO GUARDA AS LINHAS INTEIRAS, e não só as contagens: a
validação semântica precisa comparar digestos, e um duplo que só contasse
linhas faria o teste mais importante do PR passar sem exercitar nada.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import final

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.manifest import (
    FeatureObjectRef,
    HistoricalFeatureDatasetManifest,
)
from sports_intelligence.domain.features.dataset.rows import (
    MaterializedFeatureRow,
    MaterializedObjectContent,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.dataset.versions import (
    FeatureDatasetBuildRun,
    FeatureDatasetSpec,
    HistoricalFeatureDataset,
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.features.prematch.models import (
    ContextCoverage,
    MatchContextInput,
)
from sports_intelligence.domain.features.prematch.policy import HistoricalContextPolicy
from sports_intelligence.domain.features.state.builder import CanonicalMatchStateInput
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@final
class FakeFeatureDatasetRepository:
    def __init__(self) -> None:
        self.datasets: dict[str, HistoricalFeatureDataset] = {}
        self.versions: dict[str, HistoricalFeatureDatasetVersion] = {}
        #: Quantas transições foram RECUSADAS por estado. É o número que prova
        #: que a concorrência é resolvida sem sobrescrita silenciosa.
        self.recusas = 0

    async def create_dataset(
        self,
        *,
        name: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> HistoricalFeatureDataset:
        if any(d.name == name for d in self.datasets.values()):
            raise ConflictError(f"já existe um dataset de features chamado {name!r}")
        dataset = HistoricalFeatureDataset.create(
            name=name, at=at, created_by=created_by, description=description
        )
        self.datasets[dataset.id] = dataset
        return dataset

    async def dataset_by_name(self, name: str) -> HistoricalFeatureDataset | None:
        return next((d for d in self.datasets.values() if d.name == name), None)

    async def dataset_by_id(self, dataset_id: str) -> HistoricalFeatureDataset | None:
        return self.datasets.get(dataset_id)

    async def create_version(
        self,
        *,
        dataset_id: str,
        version: DatasetVersion,
        source_version_id: str,
        source_version: DatasetVersion,
        source_corpus_fingerprint: ContentHash,
        spec: FeatureDatasetSpec,
        at: Instant,
        created_by: Actor,
    ) -> HistoricalFeatureDatasetVersion:
        if await self.version_of(dataset_id, version) is not None:
            raise ConflictError(f"a versão {version} já existe")
        criada = HistoricalFeatureDatasetVersion.draft(
            dataset_id=dataset_id,
            version=version,
            source_version_id=source_version_id,
            source_version=source_version,
            source_corpus_fingerprint=source_corpus_fingerprint,
            spec=spec,
            at=at,
            created_by=created_by,
        )
        self.versions[criada.id] = criada
        return criada

    async def version_by_id(self, version_id: str) -> HistoricalFeatureDatasetVersion | None:
        return self.versions.get(version_id)

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalFeatureDatasetVersion | None:
        return next(
            (
                v
                for v in self.versions.values()
                if v.dataset_id == dataset_id and v.version == version
            ),
            None,
        )

    async def transition(
        self,
        version_id: str,
        *,
        target: DatasetVersionStatus,
        at: Instant,
        raw_content_fingerprint: ContentHash | None = None,
        manifest_id: str | None = None,
        match_count: int | None = None,
        row_count: int | None = None,
        counts: SplitCounts | None = None,
        failure_reason: str | None = None,
        superseded_by: str | None = None,
    ) -> HistoricalFeatureDatasetVersion:
        from dataclasses import replace

        atual = self.versions.get(version_id)
        if atual is None:
            raise NotFoundError(f"versão {version_id} inexistente")
        if not atual.can_move_to(target):
            self.recusas += 1
            atual.require_transition(target)
        movida = replace(
            atual,
            status=target,
            raw_content_fingerprint=(
                atual.raw_content_fingerprint
                if raw_content_fingerprint is None
                else raw_content_fingerprint
            ),
            manifest_id=atual.manifest_id if manifest_id is None else manifest_id,
            match_count=atual.match_count if match_count is None else match_count,
            row_count=atual.row_count if row_count is None else row_count,
            counts=atual.counts if counts is None else counts,
            completed_at=at if target.is_terminal else atual.completed_at,
            failure_reason=(atual.failure_reason if failure_reason is None else failure_reason),
            superseded_by=(atual.superseded_by if superseded_by is None else superseded_by),
        )
        self.versions[version_id] = movida
        return movida

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        limit: int = 50,
    ) -> Sequence[HistoricalFeatureDatasetVersion]:
        return [
            v
            for v in self.versions.values()
            if v.dataset_id == dataset_id and (status is None or v.status is status)
        ][:limit]

    async def latest_ready(self, dataset_id: str) -> HistoricalFeatureDatasetVersion | None:
        prontas = [
            v
            for v in self.versions.values()
            if v.dataset_id == dataset_id and v.status is DatasetVersionStatus.READY
        ]
        if not prontas:
            return None
        return max(prontas, key=lambda v: (v.version.major, v.version.minor))

    async def versions_from_corpus(
        self, source_version_id: str, *, limit: int = 50
    ) -> Sequence[HistoricalFeatureDatasetVersion]:
        return [v for v in self.versions.values() if v.source_version_id == source_version_id][
            :limit
        ]


@final
class FakeFeatureDatasetBuildRepository:
    def __init__(self) -> None:
        self.runs: dict[str, FeatureDatasetBuildRun] = {}
        self.objects: dict[str, dict[str, FeatureObjectRef]] = {}

    async def start_run(
        self, *, version_id: str, at: Instant, started_by: Actor
    ) -> FeatureDatasetBuildRun:
        execucao = FeatureDatasetBuildRun.start(version_id=version_id, at=at, started_by=started_by)
        self.runs[execucao.id] = execucao
        return execucao

    async def finish_run(
        self,
        run_id: str,
        *,
        status: DatasetVersionStatus,
        at: Instant,
        matches_processed: int = 0,
        rows_written: int = 0,
        objects_written: int = 0,
        bytes_written: int = 0,
        failure_reason: str | None = None,
    ) -> FeatureDatasetBuildRun:
        from dataclasses import replace

        atual = self.runs.get(run_id)
        if atual is None:
            raise NotFoundError(f"execução {run_id} inexistente")
        terminada = replace(
            atual,
            status=status,
            finished_at=at,
            matches_processed=matches_processed,
            rows_written=rows_written,
            objects_written=objects_written,
            bytes_written=bytes_written,
            failure_reason=failure_reason,
        )
        self.runs[run_id] = terminada
        return terminada

    async def runs_of(
        self, version_id: str, *, limit: int = 20
    ) -> Sequence[FeatureDatasetBuildRun]:
        return [r for r in self.runs.values() if r.version_id == version_id][:limit]

    async def record_objects(self, version_id: str, objects: Sequence[FeatureObjectRef]) -> int:
        registro = self.objects.setdefault(version_id, {})
        for objeto in objects:
            registro[objeto.object_key] = objeto
        return len(objects)

    async def objects_of(self, version_id: str) -> Sequence[FeatureObjectRef]:
        return sorted(self.objects.get(version_id, {}).values(), key=lambda o: o.object_key)


@final
class FakeFeatureDatasetManifestRepository:
    def __init__(self) -> None:
        self.manifests: dict[str, HistoricalFeatureDatasetManifest] = {}
        self.keys: dict[str, str] = {}

    async def save(
        self,
        manifest: HistoricalFeatureDatasetManifest,
        *,
        manifest_key: str,
        manifest_sha256: str,
    ) -> HistoricalFeatureDatasetManifest:
        if manifest.dataset_version_id in self.manifests:
            raise ConflictError(f"a versão {manifest.dataset_version_id} já tem manifesto")
        self.manifests[manifest.dataset_version_id] = manifest
        self.keys[manifest.dataset_version_id] = manifest_key
        return manifest

    async def by_version(self, version_id: str) -> HistoricalFeatureDatasetManifest | None:
        return self.manifests.get(version_id)

    async def by_fingerprint(
        self, fingerprint: ContentHash, *, limit: int = 20
    ) -> Sequence[HistoricalFeatureDatasetManifest]:
        return [m for m in self.manifests.values() if m.raw_content_fingerprint == fingerprint][
            :limit
        ]


@final
class FakeFeatureMaterializer:
    """Guarda as linhas inteiras, e devolve digestos como o Parquet devolveria.

    `embaralhar` EXISTE PARA UM TESTE SÓ: ele faz a leitura devolver as linhas
    fora de ordem, e a validação tem de acusar. Sem ele, a conferência de ordem
    nunca seria exercitada — e uma conferência que nenhum teste quebra é uma
    conferência que ninguém sabe se funciona.
    """

    def __init__(self) -> None:
        self.objects: dict[str, list[MaterializedFeatureRow]] = {}
        self.manifests: dict[str, bytes] = {}
        self.falhar_na_particao: int | None = None
        self.embaralhar: str | None = None
        self.escritas = 0

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit,
        competition: str,
        season: str,
        part_index: int,
        rows: Sequence[MaterializedFeatureRow],
    ) -> FeatureObjectRef | None:
        if self.falhar_na_particao is not None and self.escritas == self.falhar_na_particao:
            raise RuntimeError("object store indisponível ao escrever a partição")
        if not rows:
            return None
        chave = (
            f"features/{dataset_name}/{version}/split={split.value}/"
            f"competition={competition}/season={season}/part-{part_index:05d}.parquet"
        )
        if chave in self.objects:
            raise ConflictError(f"reescrita da chave {chave}")
        self.objects[chave] = list(rows)
        self.escritas += 1
        conteudo = "".join(linha.digest for linha in rows).encode()
        return FeatureObjectRef(
            object_key=chave,
            split=split,
            competition=competition,
            season=season,
            sha256=ContentHash(hashlib.sha256(conteudo).hexdigest()),
            size_bytes=len(conteudo),
            row_count=len(rows),
            match_count=len({linha.key.match_key for linha in rows}),
        )

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> FeatureObjectRef:
        chave = self.manifest_key(dataset_name=dataset_name, version=version)
        self.manifests[chave] = document
        return FeatureObjectRef(
            object_key=chave,
            split=DatasetSplit.REFERENCE,
            competition="*",
            season="*",
            sha256=ContentHash(hashlib.sha256(document).hexdigest()),
            size_bytes=len(document),
            row_count=0,
            content_type="application/json",
        )

    async def verify_object(self, *, object_key: str) -> MaterializedObjectContent:
        linhas = self.objects.get(object_key)
        if linhas is None:
            raise NotFoundError(f"objeto {object_key} inexistente")
        ordenadas = list(linhas)
        if self.embaralhar == object_key and len(ordenadas) > 1:
            ordenadas[0], ordenadas[-1] = ordenadas[-1], ordenadas[0]
        conteudo = "".join(linha.digest for linha in linhas).encode()
        return MaterializedObjectContent(
            object_key=object_key,
            sha256=hashlib.sha256(conteudo).hexdigest(),
            size_bytes=len(conteudo),
            rows=tuple((linha.key, linha.digest) for linha in ordenadas),
        )

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        return f"features/{dataset_name}/{version}/manifest.json"

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        return f"features/{dataset_name}/{version}/"

    # ------------------------------------------------------------ leitura --

    @property
    def linhas(self) -> list[MaterializedFeatureRow]:
        return [linha for objeto in self.objects.values() for linha in objeto]


@final
class FakeStateSource:
    """Os insumos de estado, em memória, com paginação POR CHAVE.

    A PAGINAÇÃO É A DO REAL — `match_id > after`, ordenado —, e não uma fatia:
    a ordem da varredura é o que a impressão de conteúdo encadeia, e um duplo
    que devolvesse na ordem de inserção esconderia uma dependência de ordem.
    """

    def __init__(self, entradas: Mapping[MatchId, CanonicalMatchStateInput]) -> None:
        self.entradas = dict(entradas)
        self.consultas = 0
        #: Quantas vezes `load` foi chamado, e quantas partidas ele devolveu.
        #: São OS DOIS NÚMEROS que provam o reúso: noventa e um cortes de uma
        #: partida não podem custar noventa e uma cargas dela.
        self.cargas = 0
        self.partidas_carregadas = 0
        #: Quantas páginas de varredura foram pedidas.
        self.varreduras = 0

    async def load(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, CanonicalMatchStateInput]:
        self.consultas += 1
        self.cargas += 1
        encontradas = {m: self.entradas[m] for m in match_ids if m in self.entradas}
        self.partidas_carregadas += len(encontradas)
        return encontradas

    async def match_ids(
        self, version_id: str, *, limit: int = 500, after: str | None = None
    ) -> Sequence[MatchId]:
        self.consultas += 1
        self.varreduras += 1
        # A ORDEM É A DA CHAVE, como no `ORDER BY match_id` do adaptador — e
        # NÃO a de inserção. É isso que faz a impressão de conteúdo não depender
        # de em que ordem os fatos entraram no cenário.
        ordenadas = sorted(self.entradas, key=str)
        if after is not None:
            ordenadas = [m for m in ordenadas if str(m) > after]
        return ordenadas[:limit]


@final
class FakeContextSource:
    def __init__(
        self,
        contextos: Mapping[MatchId, MatchContextInput] | None = None,
    ) -> None:
        self.contextos = dict(contextos or {})
        self.consultas = 0

    async def coverage(self, version_id: str) -> Mapping[CompetitionId, ContextCoverage]:
        """Vazio: o cenário deste PR não exercita cobertura de contexto.

        O TIPO É O REAL mesmo assim. Um duplo que devolvesse `object` aqui
        satisfaria o teste e não satisfaria o protocolo — e a divergência só
        apareceria no dia em que alguém trocasse o duplo pelo adaptador.
        """
        return {}

    async def load(
        self,
        version_id: str,
        match_ids: Sequence[MatchId],
        *,
        policy: HistoricalContextPolicy,
    ) -> Mapping[MatchId, MatchContextInput]:
        self.consultas += 1
        return {m: self.contextos[m] for m in match_ids if m in self.contextos}
