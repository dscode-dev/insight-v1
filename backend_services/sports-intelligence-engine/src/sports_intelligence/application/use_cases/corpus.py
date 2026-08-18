"""Os casos de uso do corpus histórico: criar, compor, publicar.

TRÊS CASOS DE USO E NÃO UM «publicar corpus», e a divisão é a do ciclo de vida
(§11, §12):

    CreateHistoricalDataset     declara a identidade lógica. Barato, idempotente
    BuildCorpusVersion          compõe e materializa. Caro, retomável
    PublishCorpusVersion        confere e congela. O GATE

O GATE É O TERCEIRO E ELE NÃO SE FUNDE AOS OUTROS (§12, §67). `DRAFT → READY`
não existe no grafo, e a razão é operacional: uma publicação que compõe e
declara pronto na mesma chamada não tem onde CONFERIR — e conferir é a única
coisa que separa «publicado» de «gravado».

O CAMINHO É O MESMO PARA API E CLI (§78). Os dois entram por aqui; se cada um
tivesse a sua orquestração, uma delas ganharia uma verificação que a outra não
tem, e a diferença apareceria em produção como «pela CLI funciona».

NADA AQUI RECALCULA QUALIDADE OU IDENTIDADE (§133, §134). Publicar é uma
operação de LEITURA sobre fatos já construídos, mais escrita de pertinência e
manifesto. Uma reavaliação escondida dentro da publicação faria o corpus mudar
de conteúdo por ter sido publicado.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.domain.corpus.composition import (
    ComposedMatchCorpusFacts,
    compose,
)
from sports_intelligence.domain.corpus.facts import (
    MATERIALIZABLE_FAMILIES,
    MatchCorpusFacts,
)
from sports_intelligence.domain.corpus.manifest import (
    MANIFEST_SCHEMA_VERSION,
    HistoricalCanonicalManifest,
)
from sports_intelligence.domain.corpus.membership import CorpusMember
from sports_intelligence.domain.corpus.scope import CorpusScope
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
    VersionInputs,
)
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.historical.corpus.aggregation import CorpusAccumulator
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.object_store.corpus import CanonicalCorpusMaterializerPort
from sports_intelligence.ports.repositories.corpus import (
    CanonicalManifestRepositoryPort,
    CorpusCompositionReaderPort,
    CorpusMembershipRepositoryPort,
    HistoricalCanonicalDatasetRepositoryPort,
)
from sports_intelligence.ports.repositories.quality import (
    QualityAssessmentRepositoryPort,
)

#: O tamanho do lote da composição. Nomeado porque ele é o parâmetro que o
#: §88 varia para provar que a impressão NÃO depende dele.
DEFAULT_COMPOSITION_BATCH: int = 500


@final
@dataclass(frozen=True, slots=True)
class CreateHistoricalDataset:
    """Declara a identidade lógica do corpus. Não cria conteúdo nenhum."""

    datasets: HistoricalCanonicalDatasetRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        actor: Actor,
        name: str,
        description: str | None = None,
        correlation_id: str | None = None,
    ) -> HistoricalCanonicalDataset:
        """Cria, ou devolve o existente se o nome já for daquele dataset.

        IDEMPOTENTE POR NOME (§83). Um retry de rede não pode produzir dois
        datasets com o mesmo nome nem estourar um erro que faria o operador
        achar que a primeira chamada falhou. O que NÃO é idempotente é a
        VERSÃO — ali a repetição é um erro, porque «1.0» precisa significar um
        conteúdo só (§64).
        """
        existente = await self.datasets.dataset_by_name(name.strip())
        if existente is not None:
            return existente

        criado = await self.datasets.create_dataset(
            HistoricalCanonicalDataset.create(
                name=name,
                at=self.clock.now(),
                created_by=actor,
                description=description,
            )
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.CORPUS_DATASET_CREATED,
            actor=actor,
            correlation_id=correlation_id,
            dataset=criado.name,
            corpus_dataset_id=criado.id,
        )
        return criado


@final
@dataclass(frozen=True, slots=True)
class CorpusBuildOutput:
    version: HistoricalCanonicalDatasetVersion
    members_written: int
    objects_written: int
    materialized: bool
    #: O manifesto MONTADO e ainda NÃO publicado. Ele viaja daqui para o gate
    #: por um motivo: só a composição viu o fluxo inteiro e pôde agregar
    #: qualidade, cobertura e licença sem uma segunda varredura (§133). O que
    #: o gate faz com ele é CONFERIR contra o banco, não confiar (§67).
    manifest: HistoricalCanonicalManifest


@final
@dataclass(frozen=True, slots=True)
class BuildCorpusVersion:
    """Compõe uma versão: pertinência, materialização, impressão.

    ELA NÃO PUBLICA (§12). Ao final a versão está em `VALIDATING`, com
    conteúdo gravado e impressão calculada — e nada disso é legível como
    corpus até alguém publicar.
    """

    datasets: HistoricalCanonicalDatasetRepositoryPort
    membership: CorpusMembershipRepositoryPort
    composition: CorpusCompositionReaderPort
    assessments: QualityAssessmentRepositoryPort
    manifests: CanonicalManifestRepositoryPort
    clock: ClockPort
    audit: AuditPort
    #: `None` publica sem Parquet, e a versão fica `READY` do mesmo jeito
    #: (ADR-0027). O arquivo é representação; a verdade está no PostgreSQL.
    materializer: CanonicalCorpusMaterializerPort | None = None
    quality_policy: HistoricalQualityPolicy | None = None
    batch_size: int = DEFAULT_COMPOSITION_BATCH

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: str,
        version: DatasetVersion,
        scope: CorpusScope,
        inputs: VersionInputs,
        quality_run_id: str | None = None,
        correlation_id: str | None = None,
    ) -> CorpusBuildOutput:
        dataset = await self.datasets.dataset_by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset histórico {dataset_id} não encontrado")

        # A COMPATIBILIDADE DE ESCOPO É CONFERIDA ANTES DE QUALQUER
        # ESCRITA (§27). Descobri-la no meio da composição deixaria uma versão
        # em `BUILDING` com pertinência parcial gravada, e o motivo da recusa
        # não depende de nada que a varredura descubra.
        await self._assert_escopos_compativeis(inputs, scope.usage)

        rascunho = await self._abrir(
            dataset_id=dataset_id,
            version=version,
            scope=scope,
            inputs=inputs,
            actor=actor,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.CORPUS_VERSION_CREATED,
            actor=actor,
            correlation_id=correlation_id,
            dataset=dataset.name,
            version=str(version),
            usage=scope.usage.value,
            build_runs=str(len(inputs.build_run_ids)),
        )

        construindo = rascunho.start_building()
        if not await self.datasets.transition(construindo, expected=DatasetVersionStatus.DRAFT):
            raise ConflictError(
                f"a versão {version} saiu de DRAFT antes desta composição começar — "
                "outra execução chegou primeiro, e sobrescrever faria duas "
                "composições disputarem a mesma versão",
                context={"version_id": rascunho.id},
            )

        try:
            resultado = await self._compor(
                version=construindo,
                dataset=dataset,
                inputs=inputs,
                quality_run_id=quality_run_id,
            )
        except Exception as erro:
            await self._falhar(
                construindo,
                reason=f"{type(erro).__name__}: {erro}",
                actor=actor,
                correlation_id=correlation_id,
            )
            raise

        validando = construindo.start_validating(
            match_count=resultado.members_written,
            corpus_fingerprint=resultado.fingerprint,
        )
        if not await self.datasets.transition(validando, expected=DatasetVersionStatus.BUILDING):
            raise ConflictError(
                "a versão mudou de estado durante a composição",
                context={"version_id": construindo.id},
            )
        await self.datasets.register_builds(validando.id, inputs.build_run_ids)
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.CORPUS_VERSION_BUILT,
            actor=actor,
            correlation_id=correlation_id,
            version_id=validando.id,
            matches=str(resultado.members_written),
            objects=str(len(resultado.objects)),
            fingerprint=resultado.fingerprint.value,
        )
        manifesto = _montar_manifesto(
            dataset=dataset,
            version=validando,
            inputs=inputs,
            resultado=resultado,
            at=self.clock.now(),
        )
        # O MANIFESTO É GRAVADO AQUI, e não no gate. Quem o monta é a
        # composição — a única que viu o fluxo inteiro e pôde agregar sem uma
        # segunda varredura (§133). Se o gate o recebesse de fora, a
        # conferência do §67 estaria conferindo o que o CHAMADOR afirmou, e
        # não o que foi composto.
        await self.manifests.save(
            manifesto,
            object_key=(
                None
                if self.materializer is None
                else self.materializer.manifest_key(
                    dataset_name=dataset.name, version=str(validando.version)
                )
            ),
        )
        # E OS OBJETOS VÃO PARA A TABELA, e não só para dentro do documento. O
        # manifesto DESCREVE os arquivos; a tabela os torna consultáveis — «que
        # objetos esta versão escreveu» e «o que ficou órfão daquela que
        # falhou» são consultas com índice aqui, e varredura de bucket lá.
        await self.manifests.record_objects(validando.id, resultado.objects)
        return CorpusBuildOutput(
            version=validando,
            members_written=resultado.members_written,
            objects_written=len(resultado.objects),
            materialized=self.materializer is not None,
            manifest=manifesto,
        )

    # ----------------------------------------------------------- interno --

    async def _assert_escopos_compativeis(self, inputs: VersionInputs, usage: UsageScope) -> None:
        """Recusa compor builds de escopos de uso diferentes (§27).

        A UNIÃO DE UM CORPUS COMERCIAL COM UM DE PESQUISA é um corpus de
        pesquisa com rótulo comercial: a composição une famílias, então as
        odds restritas que a política comercial acabou de excluir voltariam
        pela porta do build de pesquisa. Nenhum dos dois builds está errado — o
        que está errado é pedir que os dois formem UMA versão.
        """
        escopos = await self.composition.usage_scopes_of(inputs.build_run_ids)
        ausentes = [b for b in inputs.build_run_ids if b not in escopos]
        if ausentes:
            raise NotFoundError(
                f"execução(ões) de construção não encontrada(s): {sorted(ausentes)}"
            )
        divergentes = {b: e for b, e in escopos.items() if e is not usage}
        if divergentes:
            detalhe = ", ".join(f"{b[:8]}={e.value}" for b, e in sorted(divergentes.items()))
            raise ValidationError(
                f"a versão declara escopo {usage.value} e recebeu build(s) de outro "
                f"escopo: {detalhe}. Compor os dois produziria a UNIÃO das famílias "
                "— e a união de um corpus comercial com um de pesquisa é um corpus "
                "de pesquisa com rótulo comercial (PR-04.3.1 §27)",
                context={"usage": usage.value, "divergent": detalhe},
            )

    async def _abrir(
        self,
        *,
        dataset_id: str,
        version: DatasetVersion,
        scope: CorpusScope,
        inputs: VersionInputs,
        actor: Actor,
    ) -> HistoricalCanonicalDatasetVersion:
        """Cria a versão em `DRAFT`, ou retoma a que ficou pelo caminho.

        RETOMAR SÓ VALE PARA `DRAFT` (§83). Uma versão em `BUILDING` pode ter
        outra execução escrevendo nela agora; uma em `READY` é imutável. Nos
        dois casos a resposta certa é recusar, e não continuar por cima.
        """
        existente = await self.datasets.version_of(dataset_id, version)
        if existente is None:
            return await self.datasets.create_version(
                HistoricalCanonicalDatasetVersion.draft(
                    dataset_id=dataset_id,
                    version=version,
                    scope=scope,
                    inputs=inputs,
                    at=self.clock.now(),
                    created_by=actor,
                )
            )
        if existente.status is not DatasetVersionStatus.DRAFT:
            raise ConflictError(
                f"a versão {version} já existe em {existente.status}. Uma versão "
                "publicada é imutável e uma em curso pertence a outra execução — "
                "mudança de conteúdo produz versão NOVA (ADR-0026)",
                context={"version_id": existente.id, "status": existente.status.value},
            )
        return existente

    async def _compor(
        self,
        *,
        version: HistoricalCanonicalDatasetVersion,
        dataset: HistoricalCanonicalDataset,
        inputs: VersionInputs,
        quality_run_id: str | None,
    ) -> _ResultadoDaComposicao:
        """Varre os fatos em lotes e grava pertinência, objetos e impressão.

        MEMÓRIA CONSTANTE (§86). O que sobrevive entre lotes é o acumulador —
        contadores e uma impressão de 32 bytes. Os fatos do lote anterior já
        foram gravados e descartados.
        """
        acumulador = CorpusAccumulator(
            usage=version.scope.usage, scope=version.scope, policy=self.quality_policy
        )
        objetos: list[Any] = []
        gravados = 0
        cursor: str | None = None
        # O ÍNDICE DE PEDAÇO POR PARTIÇÃO. Ele existe para que a
        # materialização aconteça LOTE A LOTE: acumular uma partição inteira
        # até o fim da varredura seria o corpus todo em memória quando ele cabe
        # numa competição só (§86).
        pedacos: dict[tuple[str, str, str], int] = {}

        while True:
            pagina = await self.composition.page_facts(
                inputs.build_run_ids, limit=self.batch_size, after_match_id=cursor
            )
            if not pagina:
                break
            lote, cursor = _ate_a_ultima_partida_completa(pagina, self.batch_size)

            fora_do_escopo = [
                f
                for f in lote
                if not version.scope.covers(f.match.competition_id, f.match.season_id)
            ]
            if fora_do_escopo:
                # O ESCOPO É DECLARADO E NÃO DESCOBERTO. Uma partida que o
                # build produziu e o escopo não menciona não é «bônus»: ou o
                # escopo está errado, ou os builds são os errados — e as duas
                # exigem que alguém decida, e não que a publicação escolha.
                raise ValidationError(
                    f"{len(fora_do_escopo)} partida(s) fora do escopo declarado, a "
                    f"começar por {fora_do_escopo[0].match.id} em "
                    f"{fora_do_escopo[0].competition.value}/"
                    f"{fora_do_escopo[0].season_label}"
                )

            # A COMPOSIÇÃO ACONTECE AQUI, e não no SQL (PR-04.3.1 §29). A
            # leitura devolve UMA linha por (partida, build); juntá-las é
            # decisão de domínio — união de famílias quando os fatos
            # concordam, recusa quando divergem —, e nenhuma cláusula
            # `DISTINCT ON` sabe tomá-la.
            compostas = _compor_por_partida(lote)
            vereditos = await self._vereditos(compostas, quality_run_id)
            membros: list[CorpusMember] = [
                acumulador.absorb(fatos, assessment=vereditos.get(fatos.match_id))
                for fatos in compostas
            ]
            gravados += await self.membership.append_members(version.id, membros)
            await self._absorver_exclusoes(acumulador, inputs, compostas)
            if self.materializer is not None:
                objetos.extend(await self._materializar_lote(dataset, version, compostas, pedacos))

        return _ResultadoDaComposicao(
            members_written=gravados,
            fingerprint=acumulador.fingerprint(),
            objects=tuple(objetos),
            accumulator=acumulador,
        )

    async def _vereditos(
        self, lote: Sequence[ComposedMatchCorpusFacts], quality_run_id: str | None
    ) -> dict[MatchId, Any]:
        """Os vereditos do lote — UMA consulta, nunca uma por partida (§86)."""
        if quality_run_id is None:
            return {}
        ids = [f.match_id for f in lote]
        return {r.match_id: r for r in await self.assessments.by_matches(quality_run_id, ids)}

    async def _absorver_exclusoes(
        self,
        acumulador: CorpusAccumulator,
        inputs: VersionInputs,
        lote: Sequence[ComposedMatchCorpusFacts],
    ) -> None:
        decisoes = await self.composition.decisions_of(
            inputs.build_run_ids, [f.match_id for f in lote]
        )
        for decisao in decisoes:
            acumulador.absorb_exclusions(decisao)

    async def _materializar_lote(
        self,
        dataset: HistoricalCanonicalDataset,
        version: HistoricalCanonicalDatasetVersion,
        lote: Sequence[ComposedMatchCorpusFacts],
        pedacos: dict[tuple[str, str, str], int],
    ) -> list[Any]:
        """Escreve os pedaços deste lote, uma partição e uma família por vez.

        O LAÇO É POR PARTIÇÃO E POR FAMÍLIA porque é assim que a leitura
        analítica poda: `competition=EPL/season=2024-25` é o predicado que
        evita ler o corpus inteiro para responder sobre uma temporada (§43).
        """
        assert self.materializer is not None
        por_particao: dict[tuple[str, str], list[ComposedMatchCorpusFacts]] = {}
        for fatos in lote:
            por_particao.setdefault(fatos.partition_key, []).append(fatos)

        objetos: list[Any] = []
        for (competicao, temporada), fatos_da_particao in sorted(por_particao.items()):
            for familia in sorted(MATERIALIZABLE_FAMILIES, key=lambda f: f.value):
                presentes = [f for f in fatos_da_particao if f.includes(familia)]
                if not presentes:
                    continue
                chave = (familia.value, competicao, temporada)
                indice = pedacos.get(chave, 0)
                objeto = await self.materializer.materialize_partition(
                    dataset_name=dataset.name,
                    version=str(version.version),
                    family=familia,
                    competition=competicao,
                    season=temporada,
                    part_index=indice,
                    facts=presentes,
                )
                if objeto is not None:
                    pedacos[chave] = indice + 1
                    objetos.append(objeto)
        return objetos

    async def _falhar(
        self,
        version: HistoricalCanonicalDatasetVersion,
        *,
        reason: str,
        actor: Actor,
        correlation_id: str | None,
    ) -> None:
        """`FAILED` e não `READY` com ressalva (§53).

        Uma versão que falhou no meio deixou membership parcial gravada, e é
        exatamente por isso que ela precisa de um estado próprio: `READY`
        significaria «este é o corpus», e ele estaria pela metade.
        """
        falha = version.fail(reason=reason, at=self.clock.now())
        await self.datasets.transition(falha, expected=version.status)
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.CORPUS_VERSION_FAILED,
            actor=actor,
            correlation_id=correlation_id,
            version_id=version.id,
            failure=reason[:200],
        )


@final
@dataclass(frozen=True, slots=True)
class _ResultadoDaComposicao:
    members_written: int
    fingerprint: Any
    objects: tuple[Any, ...]
    accumulator: CorpusAccumulator


@final
@dataclass(frozen=True, slots=True)
class PublishCorpusVersion:
    """O GATE. Confere o que foi composto e congela a versão (§67, §68).

    O QUE ELE CONFERE, e por que cada item está aqui:

        contagem gravada = contagem do manifesto   uma discordância aqui
                                                   significa lote perdido
        impressão recalculada = a da composição    o conteúdo não mudou entre
                                                   compor e publicar
        manifesto existe e é completo              um corpus sem descrição não
                                                   é publicável

    ELE NÃO CONSERTA NADA. Discordância vira `FAILED` e uma versão nova, nunca
    um ajuste na publicada — que é o ADR-0026 inteiro.
    """

    datasets: HistoricalCanonicalDatasetRepositoryPort
    membership: CorpusMembershipRepositoryPort
    manifests: CanonicalManifestRepositoryPort
    clock: ClockPort
    audit: AuditPort
    materializer: CanonicalCorpusMaterializerPort | None = None

    async def execute(
        self,
        *,
        actor: Actor,
        version_id: str,
        reason: str = "publicação do corpus histórico",
        correlation_id: str | None = None,
        supersede_previous: bool = True,
    ) -> HistoricalCanonicalDatasetVersion:
        versao = await self.datasets.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(f"versão de corpus {version_id} não encontrada")
        if versao.status is not DatasetVersionStatus.VALIDATING:
            raise ConflictError(
                f"a versão está em {versao.status} e a publicação só aceita "
                "VALIDATING — o gate existe para que ninguém publique o que não "
                "foi conferido (§12)",
                context={"version_id": version_id, "status": versao.status.value},
            )

        # O MANIFESTO VEM DO BANCO E NÃO DO CHAMADOR. Aceitá-lo por parâmetro
        # permitiria publicar uma descrição que não corresponde ao conteúdo, e
        # a conferência do §67 passaria a conferir uma afirmação do cliente.
        manifest = await self.manifests.by_version(version_id)
        if manifest is None:
            raise ValidationError(
                f"a versão {version_id} não tem manifesto: ela não passou pela "
                "composição, e um corpus sem descrição do que contém não é "
                "publicável (§12)"
            )

        await self._conferir(versao, manifest)
        if self.materializer is not None:
            await self.materializer.write_manifest(
                dataset_name=manifest.dataset_name,
                version=str(manifest.dataset_version),
                document=manifest.to_json(),
            )

        publicada = versao.publish(manifest_id=manifest.id, at=self.clock.now())
        if not await self.datasets.transition(publicada, expected=DatasetVersionStatus.VALIDATING):
            raise ConflictError(
                "outra publicação chegou primeiro a esta versão",
                context={"version_id": version_id},
            )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.CORPUS_VERSION_PUBLISHED,
            actor=actor,
            correlation_id=correlation_id,
            reason=reason,
            version_id=publicada.id,
            version=str(publicada.version),
            usage=publicada.usage.value,
            matches=str(publicada.match_count),
            fingerprint=manifest.corpus_fingerprint.value,
        )
        if supersede_previous:
            await self._superar_anterior(publicada, actor=actor, correlation_id=correlation_id)
        return publicada

    async def _conferir(
        self,
        version: HistoricalCanonicalDatasetVersion,
        manifest: HistoricalCanonicalManifest,
    ) -> None:
        """A conferência do §67. Ela lê o BANCO, e não o que lhe contaram."""
        if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValidationError(f"manifesto com schema {manifest.schema_version!r}")
        if manifest.dataset_version_id != version.id:
            raise ValidationError(
                "o manifesto descreve outra versão — publicá-lo faria o corpus "
                "carregar a descrição de um conteúdo que não é o dele"
            )
        gravados = await self.membership.count_members(version.id)
        if gravados != manifest.counts.matches:
            raise ValidationError(
                f"o manifesto declara {manifest.counts.matches} partida(s) e o banco "
                f"tem {gravados}. A diferença é um lote perdido ou um lote em dobro, "
                "e publicar assim faria a descrição mentir sobre o conteúdo (§67)"
            )
        if version.match_count != gravados:
            raise ValidationError(
                f"a versão diz ter {version.match_count} partida(s) e o banco tem {gravados}"
            )
        if version.corpus_fingerprint is None:
            raise ValidationError("versão em VALIDATING sem impressão do corpus")
        if version.corpus_fingerprint != manifest.corpus_fingerprint:
            raise ValidationError(
                "a impressão do manifesto difere da que a composição calculou: o "
                "conteúdo mudou entre compor e publicar, e o que seria publicado "
                "não é o que foi conferido (§68)"
            )

    async def _superar_anterior(
        self,
        published: HistoricalCanonicalDatasetVersion,
        *,
        actor: Actor,
        correlation_id: str | None,
    ) -> None:
        """Marca a versão publicada anterior como superada (§79).

        NÃO APAGA NADA. Ela continua legível: um resultado calculado sobre a
        1.0 continua explicável pela 1.0, e seria irreproduzível se ela
        sumisse — que é o oposto do motivo de as versões existirem.
        """
        anteriores = [
            v
            for v in (
                await self.datasets.list_versions(
                    published.dataset_id,
                    status=DatasetVersionStatus.READY,
                    usage=published.usage,
                    limit=50,
                )
            )[0]
            if v.id != published.id
        ]
        for anterior in anteriores:
            superada = anterior.supersede(by_version_id=published.id, at=self.clock.now())
            if await self.datasets.transition(superada, expected=DatasetVersionStatus.READY):
                await _auditar(
                    self.audit,
                    self.clock,
                    AuditAction.CORPUS_VERSION_SUPERSEDED,
                    actor=actor,
                    correlation_id=correlation_id,
                    reason=f"substituída pela versão {published.version}",
                    version_id=anterior.id,
                    superseded_by=published.id,
                )


def _montar_manifesto(
    *,
    dataset: HistoricalCanonicalDataset,
    version: HistoricalCanonicalDatasetVersion,
    inputs: VersionInputs,
    resultado: _ResultadoDaComposicao,
    at: Instant,
) -> HistoricalCanonicalManifest:
    """Monta o manifesto a partir do que a composição acumulou.

    NADA AQUI É RECALCULADO (§133, §134, §135). Os resumos vêm do acumulador,
    que os recebeu das avaliações e das decisões já persistidas. Recalcular
    produziria uma segunda opinião sobre perguntas já respondidas, e as duas
    divergiriam no primeiro ajuste de política.
    """
    acumulador = resultado.accumulator
    return HistoricalCanonicalManifest(
        id=str(uuid.uuid4()),
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        dataset_version=version.version,
        dataset_version_id=version.id,
        scope=version.scope,
        inputs=inputs,
        counts=acumulador.counts,
        coverage=acumulador.coverage_summary(),
        quality=acumulador.quality_summary(),
        license=acumulador.license_summary(),
        issues=acumulador.issue_summary(),
        corpus_fingerprint=resultado.fingerprint,
        created_at=at,
        objects=tuple(resultado.objects),
        coverage_by_partition=acumulador.coverage_by_partition(),
    )


async def _auditar(
    audit: AuditPort,
    clock: ClockPort,
    action: AuditAction,
    *,
    actor: Actor,
    correlation_id: str | None,
    reason: str | None = None,
    **detalhe: Any,
) -> None:
    await audit.record(
        AuditEntry.of(
            action,
            actor=actor,
            at=clock.now(),
            correlation_id=correlation_id,
            reason=reason,
            **detalhe,
        )
    )


def _ate_a_ultima_partida_completa(
    pagina: Sequence[MatchCorpusFacts], limite: int
) -> tuple[tuple[MatchCorpusFacts, ...], str | None]:
    """Corta a página no fim da última partida COMPLETA, e devolve o cursor.

    O PROBLEMA QUE ISTO RESOLVE, e ele não existia antes da composição
    multi-build: a leitura devolve uma linha por (partida, build), e uma
    partida com duas contribuições ocupa duas linhas. Se a fronteira da página
    cair no meio delas, a partida seria composta duas vezes — uma por página —,
    e o corpus teria a mesma partida com metade da linhagem em cada metade.

    O acumulador PEGARIA isso (a impressão recusa membro repetido), mas pegar
    tarde é diferente de não acontecer: a segunda composição já teria escrito
    pertinência. Então a página é cortada antes.

    PÁGINA PARCIAL É PÁGINA FINAL: quando ela vem menor que o limite, não há
    continuação e nada precisa ser cortado. E se a página INTEIRA for de uma
    partida só, nada é cortado tampouco — cortar tudo faria o laço não avançar.
    """
    if not pagina:
        return (), None
    if len(pagina) < limite:
        return tuple(pagina), str(pagina[-1].match.id)

    ultima = pagina[-1].match.id
    completas = [f for f in pagina if f.match.id != ultima]
    if not completas:
        # Uma partida sozinha maior que o lote inteiro. Ela é processada
        # inteira nesta página — o limite é de linhas, não de partidas.
        return tuple(pagina), str(ultima)
    return tuple(completas), str(completas[-1].match.id)


def _compor_por_partida(
    lote: Sequence[MatchCorpusFacts],
) -> tuple[ComposedMatchCorpusFacts, ...]:
    """Agrupa por partida e compõe. Preserva a ordem de `match_id`.

    A ORDEM IMPORTA porque a impressão do corpus a exige estritamente
    crescente — e ela vem do `ORDER BY` da leitura, não de uma ordenação
    aqui: reordenar em Python esconderia uma leitura desordenada em vez de
    denunciá-la.
    """
    por_partida: dict[MatchId, list[MatchCorpusFacts]] = {}
    for fatos in lote:
        por_partida.setdefault(fatos.match.id, []).append(fatos)
    return tuple(compose(tuple(grupo)) for grupo in por_partida.values())
