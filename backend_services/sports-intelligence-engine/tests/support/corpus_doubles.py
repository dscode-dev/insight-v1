"""Os duplos em memória do PR-04.3 — com as MESMAS restrições dos reais.

A ARMADILHA CONTINUA SENDO A MESMA (ver `build_doubles`): um duplo mais
permissivo que o real deixa passar exatamente a classe de erro que o real
bloquearia em produção. Então aqui:

    `transition`         é condicional ao estado anterior, como o
                         `UPDATE ... WHERE status = $n`
    `append_members`     é idempotente por `(version_id, match_id)`, como o
                         `ON CONFLICT DO NOTHING`
    `create_version`     recusa `(dataset_id, version)` repetido, como o índice
    `save` do manifesto  recusa o segundo manifesto da mesma versão
    `page_facts`         pagina por CHAVE e devolve a partida UMA vez, mesmo
                         quando dois builds a produziram

São duplos, não mocks: têm comportamento e são verificados pelo estado final.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import final

from sports_intelligence.domain.build.decisions import BuildDecision
from sports_intelligence.domain.corpus.composition import (
    ComposedMatchCorpusFacts,
    EventExclusionTally,
    PublishedEvent,
)
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.manifest import (
    CorpusObjectRef,
    HistoricalCanonicalManifest,
)
from sports_intelligence.domain.corpus.membership import CorpusEventMember, CorpusMember
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import ConflictError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.versioning import DatasetVersion


@final
class FakeCorpusRepository:
    def __init__(self) -> None:
        self.datasets: dict[str, HistoricalCanonicalDataset] = {}
        self.versions: dict[str, HistoricalCanonicalDatasetVersion] = {}
        self.event_builds: dict[str, list[str]] = {}
        self.builds: dict[str, list[str]] = {}
        #: Quantas transições foram RECUSADAS por estado. É o número que prova
        #: que a concorrência é resolvida sem sobrescrita silenciosa.
        self.recusas = 0

    async def create_dataset(
        self, dataset: HistoricalCanonicalDataset
    ) -> HistoricalCanonicalDataset:
        if any(d.name == dataset.name for d in self.datasets.values()):
            raise ConflictError(f"dataset {dataset.name!r} já existe")
        self.datasets[dataset.id] = dataset
        return dataset

    async def dataset_by_name(self, name: str) -> HistoricalCanonicalDataset | None:
        return next((d for d in self.datasets.values() if d.name == name), None)

    async def dataset_by_id(self, dataset_id: str) -> HistoricalCanonicalDataset | None:
        return self.datasets.get(dataset_id)

    async def list_datasets(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[HistoricalCanonicalDataset], int]:
        todos = list(self.datasets.values())
        return todos[offset : offset + limit], len(todos)

    async def create_version(
        self, version: HistoricalCanonicalDatasetVersion
    ) -> HistoricalCanonicalDatasetVersion:
        if any(
            v.dataset_id == version.dataset_id and v.version == version.version
            for v in self.versions.values()
        ):
            raise ConflictError(f"a versão {version.version} já existe")
        self.versions[version.id] = version
        return version

    async def version_by_id(self, version_id: str) -> HistoricalCanonicalDatasetVersion | None:
        return self.versions.get(version_id)

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalCanonicalDatasetVersion | None:
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
        version: HistoricalCanonicalDatasetVersion,
        *,
        expected: DatasetVersionStatus,
    ) -> bool:
        atual = self.versions.get(version.id)
        if atual is None or atual.status is not expected:
            self.recusas += 1
            return False
        self.versions[version.id] = version
        return True

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        usage: UsageScope | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[HistoricalCanonicalDatasetVersion], int]:
        encontradas = [
            v
            for v in self.versions.values()
            if v.dataset_id == dataset_id
            and (status is None or v.status is status)
            and (usage is None or v.usage is usage)
        ]
        return encontradas[offset : offset + limit], len(encontradas)

    async def latest_ready(
        self, dataset_id: str, *, usage: UsageScope
    ) -> HistoricalCanonicalDatasetVersion | None:
        candidatas = [
            v
            for v in self.versions.values()
            if v.dataset_id == dataset_id
            and v.usage is usage
            and v.status is DatasetVersionStatus.READY
        ]
        return max(candidatas, key=lambda v: v.version, default=None)

    async def register_builds(self, version_id: str, build_run_ids: Sequence[str]) -> int:
        self.builds.setdefault(version_id, []).extend(build_run_ids)
        return len(build_run_ids)

    async def build_run_ids_of(self, version_id: str) -> Sequence[str]:
        return self.builds.get(version_id, [])

    async def register_event_builds(
        self, version_id: str, event_build_run_ids: Sequence[str]
    ) -> int:
        self.event_builds.setdefault(version_id, []).extend(event_build_run_ids)
        return len(event_build_run_ids)

    async def event_build_run_ids_of(self, version_id: str) -> Sequence[str]:
        return self.event_builds.get(version_id, [])

    async def versions_using_build(
        self, build_run_id: str, *, limit: int = 20
    ) -> Sequence[HistoricalCanonicalDatasetVersion]:
        return [
            self.versions[v]
            for v, builds in self.builds.items()
            if build_run_id in builds and v in self.versions
        ][:limit]


@final
class FakeMembershipRepository:
    def __init__(self) -> None:
        self.members: dict[str, dict[MatchId, CorpusMember]] = {}
        #: Quantos INSERTs foram ignorados por já existirem. É o número que
        #: prova a idempotência do §83 em vez de supô-la.
        self.ignorados = 0
        #: A pertinência de EVENTO, por versão. Ela tem a MESMA restrição do
        #: real: uma linha por `(versão, evento)`, com as contribuições
        #: acumuladas — um duplo mais permissivo deixaria passar exatamente o
        #: defeito que o §68 existe para impedir.
        self.event_members: dict[str, dict[uuid.UUID, CorpusEventMember]] = {}
        self.eventos_ignorados = 0

    async def append_members(self, version_id: str, members: Sequence[CorpusMember]) -> int:
        da_versao = self.members.setdefault(version_id, {})
        gravados = 0
        for membro in members:
            if membro.match_id in da_versao:
                self.ignorados += 1
                continue
            da_versao[membro.match_id] = membro
            gravados += 1
        return gravados

    async def page_members(
        self,
        version_id: str,
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[CorpusMember]:
        ordenados = sorted(self.members.get(version_id, {}).values(), key=lambda m: str(m.match_id))
        if after_match_id is not None:
            ordenados = [m for m in ordenados if str(m.match_id) > after_match_id]
        return ordenados[:limit]

    async def members_by_match(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[CorpusMember]:
        da_versao = self.members.get(version_id, {})
        return [da_versao[m] for m in match_ids if m in da_versao]

    async def count_members(self, version_id: str) -> int:
        return len(self.members.get(version_id, {}))

    async def versions_containing(self, match_id: MatchId, *, limit: int = 20) -> Sequence[str]:
        return [v for v, membros in self.members.items() if match_id in membros][:limit]

    # ------------------------------------------------ pertinência de evento --

    async def append_event_members(
        self, version_id: str, members: Sequence[CorpusEventMember]
    ) -> int:
        da_versao = self.event_members.setdefault(version_id, {})
        gravados = 0
        for membro in members:
            existente = da_versao.get(membro.event_id)
            if existente is not None:
                # O MESMO EVENTO DE OUTRA EXECUÇÃO ACRESCENTA LINHAGEM, e não
                # uma pertinência a mais — como o `ON CONFLICT` do real mais a
                # tabela-filha (§68).
                da_versao[membro.event_id] = CorpusEventMember.of(
                    event_id=existente.event_id,
                    match_id=existente.match_id,
                    competition=existente.competition,
                    season_label=existente.season_label,
                    event_build_run_ids=(
                        *existente.event_build_run_ids,
                        *membro.event_build_run_ids,
                    ),
                    content_digest=existente.content_digest,
                )
                self.eventos_ignorados += 1
                continue
            da_versao[membro.event_id] = membro
            gravados += 1
        return gravados

    async def count_event_members(self, version_id: str) -> int:
        return len(self.event_members.get(version_id, {}))

    async def event_members_of_match(
        self, version_id: str, match_id: MatchId
    ) -> Sequence[CorpusEventMember]:
        return sorted(
            (m for m in self.event_members.get(version_id, {}).values() if m.match_id == match_id),
            key=lambda m: str(m.event_id),
        )

    async def versions_containing_event(
        self, event_id: uuid.UUID, *, limit: int = 20
    ) -> Sequence[str]:
        return [v for v, eventos in self.event_members.items() if event_id in eventos][:limit]


@final
class FakeManifestRepository:
    def __init__(self) -> None:
        self.manifests: dict[str, HistoricalCanonicalManifest] = {}
        self.object_keys: dict[str, str | None] = {}
        self.objects: dict[str, dict[str, CorpusObjectRef]] = {}

    async def save(
        self,
        manifest: HistoricalCanonicalManifest,
        *,
        object_key: str | None = None,
    ) -> HistoricalCanonicalManifest:
        if manifest.dataset_version_id in self.manifests:
            raise ConflictError("esta versão já tem manifesto")
        self.manifests[manifest.dataset_version_id] = manifest
        self.object_keys[manifest.dataset_version_id] = object_key
        return manifest

    async def record_objects(self, version_id: str, objects: Sequence[CorpusObjectRef]) -> int:
        # IDEMPOTENTE PELA CHAVE, como o `ON CONFLICT` do real: reexecutar a
        # composição de uma versão que falhou reescreve as mesmas linhas.
        da_versao = self.objects.setdefault(version_id, {})
        for objeto in objects:
            da_versao[objeto.object_key] = objeto
        return len(objects)

    async def objects_of(self, version_id: str) -> Sequence[CorpusObjectRef]:
        return sorted(self.objects.get(version_id, {}).values(), key=lambda o: o.object_key)

    async def by_version(self, version_id: str) -> HistoricalCanonicalManifest | None:
        return self.manifests.get(version_id)

    async def by_fingerprint(
        self, corpus_fingerprint: str, *, limit: int = 10
    ) -> Sequence[HistoricalCanonicalManifest]:
        return [
            m for m in self.manifests.values() if m.corpus_fingerprint.value == corpus_fingerprint
        ][:limit]


@final
class FakeCompositionReader:
    """A leitura da composição. PAGINA POR CHAVE e não repete partida."""

    def __init__(
        self,
        facts: Sequence[MatchCorpusFacts],
        decisions: Sequence[BuildDecision] = (),
        *,
        scopes: Mapping[str, UsageScope] | None = None,
        default_scope: UsageScope = UsageScope.RESEARCH,
    ) -> None:
        self.scopes = dict(scopes or {})
        self.default_scope = default_scope
        self.facts = sorted(facts, key=lambda f: str(f.match.id))
        self.decisions = list(decisions)
        #: Quantas páginas foram pedidas. É o que prova o processamento em
        #: lotes em vez de supô-lo.
        self.paginas = 0

    async def page_facts(
        self,
        build_run_ids: Sequence[str],
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[MatchCorpusFacts]:
        self.paginas += 1
        # UMA LINHA POR (PARTIDA, BUILD), como o real depois do PR-04.3.1: a
        # deduplicação saiu do SQL e virou composição no domínio, porque
        # deduplicar aqui responderia «qual build vence?» e apagaria as
        # famílias e a linhagem do perdedor (§22, §29).
        #
        # A ORDEM SECUNDÁRIA POR BUILD mantém as linhas de uma partida
        # adjacentes e reproduzíveis, que é o que permite a quem consome
        # cortar a página no fim da última partida completa.
        candidatos = sorted(
            (
                f
                for f in self.facts
                if f.build_run_id in build_run_ids
                and (after_match_id is None or str(f.match.id) > after_match_id)
            ),
            key=lambda f: (str(f.match.id), f.build_run_id),
        )
        return candidatos[:limit]

    async def usage_scopes_of(self, build_run_ids: Sequence[str]) -> Mapping[str, UsageScope]:
        """O escopo de cada build. O duplo assume o do cenário para todos —
        os testes que exercitam divergência passam `scopes` explicitamente."""
        return {b: self.scopes.get(b, self.default_scope) for b in build_run_ids}

    async def decisions_of(
        self, build_run_ids: Sequence[str], match_ids: Sequence[MatchId]
    ) -> Sequence[BuildDecision]:
        alvo = set(match_ids)
        return [d for d in self.decisions if d.match_id in alvo]


@final
class FakeMaterializer:
    """O materializador. Grava chaves, e recusa reescrever a mesma."""

    def __init__(self) -> None:
        self.objects: dict[str, int] = {}
        self.manifests: list[str] = []
        #: A família em que ele DEVE falhar, quando o teste quer provar que uma
        #: falha de escrita derruba a versão em vez de virar `READY` com
        #: ressalva (PR-04.4.2 §119).
        self.falhar_em: CoverageFamily | None = None

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        family: CoverageFamily,
        competition: str,
        season: str,
        part_index: int,
        facts: Sequence[ComposedMatchCorpusFacts],
    ) -> CorpusObjectRef | None:
        if self.falhar_em is not None and family is self.falhar_em:
            raise RuntimeError(f"object store indisponível ao escrever {family.value}")
        linhas = [linha for f in facts for linha in f.rows_for(family)]
        if not linhas:
            return None
        chave = (
            f"corpus/{dataset_name}/{version}/family={family.value}/"
            f"competition={competition}/season={season}/part-{part_index:05d}.parquet"
        )
        if chave in self.objects:
            raise ConflictError(f"reescrita da chave {chave}")
        self.objects[chave] = len(linhas)
        return CorpusObjectRef(
            object_key=chave,
            family=family.value,
            competition=competition,
            season=season,
            sha256=ContentHash("0" * 64),
            size_bytes=len(linhas) * 100,
            row_count=len(linhas),
        )

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> CorpusObjectRef:
        chave = f"corpus/{dataset_name}/{version}/manifest.json"
        self.manifests.append(chave)
        return CorpusObjectRef(
            object_key=chave,
            family="MANIFEST",
            competition="*",
            season="*",
            sha256=ContentHash("1" * 64),
            size_bytes=len(document),
            row_count=1,
            content_type="application/json",
        )

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        return f"corpus/{dataset_name}/{version}/manifest.json"

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        return f"corpus/{dataset_name}/{version}/"


@final
class FakeCorpusEventReader:
    """Os eventos que uma versão publica, em memória.

    ELE TEM AS MESMAS RESTRIÇÕES DO REAL: só devolve eventos das execuções
    DECLARADAS, conta antes de ler (para que o fatiamento do §46 seja
    exercitado de verdade) e devolve a linhagem plural de cada evento.
    """

    def __init__(
        self,
        *,
        events: Mapping[MatchId, Sequence[PublishedEvent]] | None = None,
        scopes: Mapping[str, UsageScope] | None = None,
        exclusions: EventExclusionTally | None = None,
        policy_versions: tuple[int, ...] = (1,),
        type_mapping_versions: tuple[int, ...] = (1,),
    ) -> None:
        self.events = {k: tuple(v) for k, v in (events or {}).items()}
        self.scopes = dict(scopes or {})
        self.exclusions = exclusions or EventExclusionTally()
        self.policy_versions = policy_versions
        self.type_mapping_versions = type_mapping_versions
        #: Quantas consultas de cada tipo. São os números que provam o §46 e o
        #: §91 em vez de supô-los.
        self.contagens = 0
        self.leituras = 0

    async def usage_scopes_of(self, event_build_run_ids: Sequence[str]) -> Mapping[str, UsageScope]:
        return {b: e for b, e in self.scopes.items() if b in set(event_build_run_ids)}

    async def policy_versions_of(
        self, event_build_run_ids: Sequence[str]
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        if not event_build_run_ids:
            return (), ()
        return self.policy_versions, self.type_mapping_versions

    async def count_events(
        self, event_build_run_ids: Sequence[str], match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, int]:
        self.contagens += 1
        if not event_build_run_ids:
            return {}
        alvo = set(match_ids)
        return {m: len(e) for m, e in self.events.items() if m in alvo and e}

    async def events_of(
        self, event_build_run_ids: Sequence[str], match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, tuple[PublishedEvent, ...]]:
        self.leituras += 1
        if not event_build_run_ids:
            return {}
        declaradas = set(event_build_run_ids)
        alvo = set(match_ids)
        publicados: dict[MatchId, tuple[PublishedEvent, ...]] = {}
        for partida, eventos in self.events.items():
            if partida not in alvo:
                continue
            # SÓ AS EXECUÇÕES DECLARADAS. Um duplo que devolvesse tudo faria o
            # teste de pesquisa contra comércio passar sem que a filtragem
            # existisse (§5, §35).
            do_escopo = tuple(
                PublishedEvent(
                    event=p.event,
                    build_run_ids=tuple(b for b in p.build_run_ids if b in declaradas),
                )
                for p in eventos
                if declaradas & set(p.build_run_ids)
            )
            if do_escopo:
                publicados[partida] = do_escopo
        return publicados

    async def exclusions_of(self, event_build_run_ids: Sequence[str]) -> EventExclusionTally:
        if not event_build_run_ids:
            return EventExclusionTally()
        return self.exclusions
