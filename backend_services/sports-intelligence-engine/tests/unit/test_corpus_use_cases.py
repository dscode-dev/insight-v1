"""Compor e publicar: o gate, a idempotência, a concorrência, a agregação.

O QUE ESTES TESTES PROTEGEM:

    o GATE                  publicar sem conferir é recusado (§12, §67)
    a CONFERÊNCIA           contagem e impressão têm de bater com o BANCO
    a IDEMPOTÊNCIA          um retry não duplica partida (§83)
    a CONCORRÊNCIA          a segunda publicação vê o estado mudado (§84)
    a AGREGAÇÃO             pior caso, nunca média; `NOT_DECLARED` sobrevive
    a LICENÇA               o manifesto comercial não declara o que excluiu
"""

from __future__ import annotations

import pytest

from sports_intelligence.application.use_cases.corpus import (
    BuildCorpusVersion,
    CorpusBuildOutput,
    CreateHistoricalDataset,
    PublishCorpusVersion,
)
from sports_intelligence.domain.build.decisions import (
    BuildDecision,
    BuildOutcome,
    FamilyDecision,
    FamilyExclusionReason,
    FamilyOutcome,
)
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDatasetVersion,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.audit import AuditAction
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ports.clock import FrozenClock
from tests.support.build_doubles import FakeAudit, FakeQualityAssessmentRepository
from tests.support.build_fixtures import AGORA
from tests.support.corpus_doubles import (
    FakeCompositionReader,
    FakeCorpusRepository,
    FakeManifestRepository,
    FakeMaterializer,
    FakeMembershipRepository,
)
from tests.support.corpus_fixtures import (
    BUILD_RUN,
    PUBLICADOR,
    dataset,
    entradas,
    escopo,
    fatos,
    muitos_fatos,
)


class Ambiente:
    """O grafo montado com duplos. Os mesmos casos de uso da API e da CLI."""

    def __init__(
        self,
        *,
        facts: tuple[MatchCorpusFacts, ...] = (),
        decisions: tuple[BuildDecision, ...] = (),
        materializar: bool = False,
        batch_size: int = 500,
        build_scope: UsageScope = UsageScope.RESEARCH,
        scopes: dict[str, UsageScope] | None = None,
    ) -> None:
        self.datasets = FakeCorpusRepository()
        self.membership = FakeMembershipRepository()
        self.manifests = FakeManifestRepository()
        # O ESCOPO DOS BUILDS É DECLARADO, e não deduzido do escopo da versão:
        # é justamente a divergência entre os dois que o §27 recusa, e um duplo
        # que os igualasse por construção tornaria a guarda inverificável.
        self.composition = FakeCompositionReader(
            facts, decisions, scopes=scopes, default_scope=build_scope
        )
        self.assessments = FakeQualityAssessmentRepository()
        self.audit = FakeAudit()
        self.clock = FrozenClock(AGORA)
        self.materializer = FakeMaterializer() if materializar else None
        self.create = CreateHistoricalDataset(
            datasets=self.datasets, clock=self.clock, audit=self.audit
        )
        self.build = BuildCorpusVersion(
            datasets=self.datasets,
            membership=self.membership,
            composition=self.composition,
            assessments=self.assessments,
            manifests=self.manifests,
            clock=self.clock,
            audit=self.audit,
            materializer=self.materializer,
            batch_size=batch_size,
        )
        self.publish = PublishCorpusVersion(
            datasets=self.datasets,
            membership=self.membership,
            manifests=self.manifests,
            clock=self.clock,
            audit=self.audit,
            materializer=self.materializer,
        )

    async def com_dataset(self) -> str:
        criado = await self.datasets.create_dataset(dataset())
        return criado.id

    async def compor(
        self,
        *,
        version: str = "1.0",
        usage: UsageScope = UsageScope.RESEARCH,
        dataset_id: str | None = None,
    ) -> CorpusBuildOutput:
        maior, _, menor = version.partition(".")
        return await self.build.execute(
            actor=PUBLICADOR,
            dataset_id=dataset_id or await self.com_dataset(),
            version=DatasetVersion(major=int(maior), minor=int(menor)),
            scope=escopo(usage),
            inputs=entradas(),
        )


class TestCriarDataset:
    async def test_e_idempotente_por_nome(self) -> None:
        """§83. Um retry de rede não pode produzir dois datasets com o mesmo
        nome nem estourar erro que faça o operador achar que a primeira
        chamada falhou."""
        ambiente = Ambiente()
        primeiro = await ambiente.create.execute(actor=PUBLICADOR, name="historical-core")
        segundo = await ambiente.create.execute(actor=PUBLICADOR, name="historical-core")
        assert primeiro.id == segundo.id
        assert len(ambiente.datasets.datasets) == 1
        # A trilha registra a criação UMA vez — o retry não é um evento.
        assert ambiente.audit.actions().count(AuditAction.CORPUS_DATASET_CREATED.value) == 1

    async def test_o_nome_vira_caminho_e_recusa_barra(self) -> None:
        ambiente = Ambiente()
        with pytest.raises(ValidationError, match="barra e espaço"):
            await ambiente.create.execute(actor=PUBLICADOR, name="core/2024")


class TestCompor:
    async def test_termina_em_validating_e_nao_publicada(self) -> None:
        """§12. A composição NÃO publica: o gate é um passo separado, e é
        onde a conferência acontece."""
        ambiente = Ambiente(facts=muitos_fatos(3))
        saida = await ambiente.compor()
        assert saida.version.status is DatasetVersionStatus.VALIDATING
        assert saida.members_written == 3
        assert saida.version.corpus_fingerprint is not None

    async def test_pagina_em_lotes(self) -> None:
        """§86. Dez mil partidas não entram em memória de uma vez, e o teste
        conta as páginas em vez de supor que elas aconteceram."""
        ambiente = Ambiente(facts=muitos_fatos(10), batch_size=3)
        await ambiente.compor()
        # SEIS PÁGINAS E NÃO QUATRO, e a diferença é o preço da composição
        # multi-build: uma página CHEIA é cortada no fim da última partida
        # completa, porque as contribuições restantes daquela partida podem
        # estar na página seguinte. As linhas cortadas voltam na próxima
        # leitura — no pior caso, uma partida por página.
        assert ambiente.composition.paginas == 6

    async def test_o_lote_nao_muda_a_impressao(self) -> None:
        """§88. Publicar com lote pequeno ou grande produz o MESMO corpus."""
        pequeno = Ambiente(facts=muitos_fatos(9), batch_size=2)
        grande = Ambiente(facts=muitos_fatos(9), batch_size=50)
        a = await pequeno.compor()
        b = await grande.compor()
        assert a.manifest.corpus_fingerprint == b.manifest.corpus_fingerprint

    async def test_partida_fora_do_escopo_e_recusada(self) -> None:
        """§65. O escopo é DECLARADO e não descoberto: uma partida que o
        build produziu e o escopo não menciona exige que alguém decida."""
        from sports_intelligence.domain.competitions.catalog import CompetitionCode
        from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
        from sports_intelligence.domain.shared.identity import CompetitionId, SeasonId

        ambiente = Ambiente(facts=muitos_fatos(2))
        dataset_id = await ambiente.com_dataset()
        outro = CorpusScope.of(
            ScopeEntry(
                competition=CompetitionCode.LA_LIGA,
                season_label="2025/26",
                competition_id=CompetitionId.derive("outro", "competicao"),
                season_id=SeasonId.derive("outro", "temporada"),
            ),
            usage=UsageScope.RESEARCH,
        )
        with pytest.raises(ValidationError, match="fora do escopo"):
            await ambiente.build.execute(
                actor=PUBLICADOR,
                dataset_id=dataset_id,
                version=DatasetVersion(major=1, minor=0),
                scope=outro,
                inputs=entradas(),
            )
        # E A VERSÃO FICA `FAILED`, não `READY` com ressalva (§53).
        versoes, _ = await ambiente.datasets.list_versions(dataset_id)
        assert versoes[0].status is DatasetVersionStatus.FAILED

    async def test_builds_de_escopos_diferentes_sao_recusados(self) -> None:
        """§27, Caso D. A união de um corpus comercial com um de pesquisa é um
        corpus de pesquisa com rótulo comercial — as odds restritas voltariam
        pela porta do outro build."""
        de_pesquisa = "77777777-7777-4777-8777-777777777777"
        ambiente = Ambiente(
            facts=(
                *muitos_fatos(2),
                *(fatos(n, build_run_id=de_pesquisa) for n in range(2)),
            ),
            build_scope=UsageScope.COMMERCIAL,
            scopes={de_pesquisa: UsageScope.RESEARCH},
        )
        with pytest.raises(ValidationError, match="rótulo comercial"):
            await ambiente.build.execute(
                actor=PUBLICADOR,
                dataset_id=await ambiente.com_dataset(),
                version=DatasetVersion(major=1, minor=0),
                scope=escopo(UsageScope.COMMERCIAL),
                inputs=entradas(build_runs=(BUILD_RUN, de_pesquisa)),
            )

    async def test_a_recusa_de_escopo_acontece_antes_de_qualquer_escrita(
        self,
    ) -> None:
        """Descobrir a incompatibilidade no meio da varredura deixaria uma
        versão em BUILDING com pertinência parcial gravada."""
        de_pesquisa = "77777777-7777-4777-8777-777777777777"
        ambiente = Ambiente(
            facts=muitos_fatos(2),
            build_scope=UsageScope.COMMERCIAL,
            scopes={de_pesquisa: UsageScope.RESEARCH},
        )
        dataset_id = await ambiente.com_dataset()
        with pytest.raises(ValidationError):
            await ambiente.build.execute(
                actor=PUBLICADOR,
                dataset_id=dataset_id,
                version=DatasetVersion(major=1, minor=0),
                scope=escopo(UsageScope.COMMERCIAL),
                inputs=entradas(build_runs=(BUILD_RUN, de_pesquisa)),
            )
        versoes, total = await ambiente.datasets.list_versions(dataset_id)
        assert total == 0, "nenhuma versão deveria ter sido criada"
        assert not versoes

    async def test_a_mesma_versao_duas_vezes_e_conflito(self) -> None:
        """§64. «1.0» precisa significar um conteúdo só, para sempre."""
        ambiente = Ambiente(facts=muitos_fatos(2))
        dataset_id = await ambiente.com_dataset()
        await ambiente.compor(dataset_id=dataset_id)
        with pytest.raises(ConflictError, match="já existe"):
            await ambiente.compor(dataset_id=dataset_id)

    async def test_materializa_uma_particao_por_familia(self) -> None:
        ambiente = Ambiente(
            facts=muitos_fatos(4, families=(CoverageFamily.MATCH, CoverageFamily.ODDS)),
            materializar=True,
            batch_size=2,
        )
        saida = await ambiente.compor()
        assert ambiente.materializer is not None
        # QUATRO LOTES vezes DUAS FAMÍLIAS: oito pedaços, cada um com chave
        # própria — o duplo recusaria reescrita da mesma chave. São quatro
        # lotes e não dois porque a página cheia é cortada no fim da última
        # partida completa (§22): o corte custa fragmentação, e a fragmentação
        # é o que `part-NNNNN` existe para absorver.
        assert len(ambiente.materializer.objects) == 8
        assert saida.objects_written == 8
        assert saida.materialized is True

    async def test_os_objetos_sao_gravados_e_nao_so_descritos(self) -> None:
        """§55, §118. O manifesto DESCREVE os arquivos; a tabela os torna
        consultáveis — «que objetos esta versão escreveu» e «o que ficou órfão
        daquela que falhou» são consultas com índice, e não varredura de
        bucket."""
        ambiente = Ambiente(
            facts=muitos_fatos(4, families=(CoverageFamily.MATCH, CoverageFamily.ODDS)),
            materializar=True,
            batch_size=2,
        )
        saida = await ambiente.compor()
        gravados = await ambiente.manifests.objects_of(saida.version.id)
        assert len(gravados) == saida.objects_written
        assert {o.object_key for o in gravados} == {o.object_key for o in saida.manifest.objects}

    async def test_a_chave_do_manifesto_e_gravada_com_ele(self) -> None:
        """Uma coluna que nunca é preenchida é pior que uma ausente: ela
        promete um ponteiro e devolve `NULL`."""
        com_parquet = Ambiente(facts=muitos_fatos(2), materializar=True)
        saida = await com_parquet.compor()
        chave = com_parquet.manifests.object_keys[saida.version.id]
        assert chave is not None
        assert chave.endswith("/manifest.json")

        # E SEM MATERIALIZADOR ELA É `None`, que é a verdade: não há arquivo.
        sem_parquet = Ambiente(facts=muitos_fatos(2), materializar=False)
        outra = await sem_parquet.compor()
        assert sem_parquet.manifests.object_keys[outra.version.id] is None

    async def test_publica_sem_parquet_quando_nao_ha_materializador(self) -> None:
        """ADR-0027. O arquivo é representação; a verdade está no PostgreSQL."""
        ambiente = Ambiente(facts=muitos_fatos(2), materializar=False)
        saida = await ambiente.compor()
        assert saida.materialized is False
        assert saida.members_written == 2


class TestOGate:
    async def _composta(
        self, *, facts: tuple[MatchCorpusFacts, ...]
    ) -> tuple[Ambiente, CorpusBuildOutput]:
        ambiente = Ambiente(facts=facts)
        saida = await ambiente.compor()
        return ambiente, saida

    async def test_publica_e_congela(self) -> None:
        ambiente, saida = await self._composta(facts=muitos_fatos(3))
        publicada = await ambiente.publish.execute(
            actor=PUBLICADOR,
            version_id=saida.version.id,
            reason="corpus histórico 1.0",
        )
        assert publicada.status is DatasetVersionStatus.READY
        assert publicada.is_frozen
        assert publicada.manifest_id is not None

    async def test_recusa_versao_que_nao_passou_pela_composicao(self) -> None:
        """§12. Publicar o que não foi conferido é o que o gate existe para
        impedir."""
        ambiente = Ambiente(facts=muitos_fatos(1))
        dataset_id = await ambiente.com_dataset()
        rascunho = await ambiente.datasets.create_version(
            HistoricalCanonicalDatasetVersion.draft(
                dataset_id=dataset_id,
                version=DatasetVersion(major=2, minor=0),
                scope=escopo(),
                inputs=entradas(),
                at=AGORA,
                created_by=PUBLICADOR,
            )
        )
        with pytest.raises(ConflictError, match="só aceita"):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id=rascunho.id, reason="tentativa"
            )

    async def test_recusa_versao_inexistente(self) -> None:
        ambiente = Ambiente()
        with pytest.raises(NotFoundError):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id="nao-existe", reason="tentativa"
            )

    async def test_recusa_quando_a_contagem_do_manifesto_nao_bate(self) -> None:
        """§67. A diferença é um lote perdido ou um lote em dobro, e publicar
        assim faria a descrição mentir sobre o conteúdo."""
        ambiente, saida = await self._composta(facts=muitos_fatos(3))
        # Alguém apaga uma linha de pertinência por fora — é o defeito que a
        # conferência existe para pegar.
        versao_id = saida.version.id
        membros = ambiente.membership.members[versao_id]
        membros.pop(next(iter(membros)))
        with pytest.raises(ValidationError, match="partida"):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id=versao_id, reason="tentativa"
            )

    async def test_a_publicacao_supera_a_anterior(self) -> None:
        """§79. A anterior NÃO some — ela fica marcada como substituída."""
        ambiente = Ambiente(facts=muitos_fatos(2))
        dataset_id = await ambiente.com_dataset()
        primeira = await ambiente.compor(version="1.0", dataset_id=dataset_id)
        publicada = await ambiente.publish.execute(
            actor=PUBLICADOR,
            version_id=primeira.version.id,
            reason="1.0",
        )
        segunda = await ambiente.compor(version="1.1", dataset_id=dataset_id)
        await ambiente.publish.execute(
            actor=PUBLICADOR,
            version_id=segunda.version.id,
            reason="1.1",
        )
        anterior = await ambiente.datasets.version_by_id(publicada.id)
        assert anterior is not None
        assert anterior.status is DatasetVersionStatus.SUPERSEDED
        assert anterior.status.is_readable_corpus
        atual = await ambiente.datasets.latest_ready(dataset_id, usage=UsageScope.RESEARCH)
        assert atual is not None
        assert str(atual.version) == "v1.1"

    async def test_a_trilha_registra_a_decisao_com_motivo(self) -> None:
        """Publicar é decisão administrativa, e `is_decision` exige motivo."""
        ambiente, saida = await self._composta(facts=muitos_fatos(1))
        await ambiente.publish.execute(
            actor=PUBLICADOR,
            version_id=saida.version.id,
            reason="publicação inicial do corpus",
        )
        publicacao = next(
            e for e in ambiente.audit.entries if e.action is AuditAction.CORPUS_VERSION_PUBLISHED
        )
        assert publicacao.action.is_decision
        assert publicacao.reason == "publicação inicial do corpus"

    async def test_a_segunda_publicacao_da_mesma_versao_e_recusada(self) -> None:
        """§84. A concorrência é resolvida pelo estado gravado, e não por um
        lock distribuído que este PR não tem."""
        ambiente, saida = await self._composta(facts=muitos_fatos(1))
        versao_id = saida.version.id
        await ambiente.publish.execute(actor=PUBLICADOR, version_id=versao_id, reason="primeira")
        with pytest.raises(ConflictError, match="só aceita"):
            await ambiente.publish.execute(actor=PUBLICADOR, version_id=versao_id, reason="segunda")


class TestAAgregacaoDoManifesto:
    async def test_a_licenca_do_manifesto_descreve_o_que_foi_excluido(self) -> None:
        """§26 e ADR-0025. «ODDS excluída» não responde nada; «excluída por
        LICENSE_POLICY, RESEARCH_ONLY, num build COMMERCIAL» responde tudo."""
        excluidas = tuple(
            BuildDecision(
                match_id=f.match.id,
                outcome=BuildOutcome.BUILD,
                scope=UsageScope.COMMERCIAL,
                build_policy_version=PolicyVersion(major=1, minor=0),
                families=(
                    FamilyDecision(family=CoverageFamily.MATCH, outcome=FamilyOutcome.INCLUDED),
                    FamilyDecision(
                        family=CoverageFamily.ODDS,
                        outcome=FamilyOutcome.EXCLUDED,
                        reason=FamilyExclusionReason.LICENSE_POLICY,
                        license_class=LicenseClass.RESEARCH_ONLY,
                    ),
                ),
            )
            for f in muitos_fatos(2)
        )
        ambiente = Ambiente(
            facts=muitos_fatos(2),
            decisions=excluidas,
            build_scope=UsageScope.COMMERCIAL,
        )
        saida = await ambiente.compor(usage=UsageScope.COMMERCIAL)
        licenca = saida.manifest.license
        assert licenca.usage_scope == UsageScope.COMMERCIAL.value
        assert "ODDS" in licenca.families_excluded
        assert licenca.exclusion_licenses["ODDS"] == LicenseClass.RESEARCH_ONLY.value
        assert licenca.exclusion_reasons["ODDS"]["LICENSE_POLICY"] == 2
        # E O CORPUS COMERCIAL NÃO DECLARA A LICENÇA QUE ELE EXCLUIU: seria o
        # manifesto de um corpus sem nenhum dado restrito dizendo o contrário.
        assert LicenseClass.RESEARCH_ONLY.value not in licenca.licenses_present

    async def test_a_cobertura_lista_todas_as_familias_inclusive_as_ausentes(
        self,
    ) -> None:
        """§20 do PR-04.1: `TRACKING` aparece como `NOT_DECLARED` em vez de
        sumir — sumir é indistinguível de «ninguém pensou nisso»."""
        ambiente = Ambiente(facts=muitos_fatos(2))
        saida = await ambiente.compor()
        familias = {c.family for c in saida.manifest.coverage}
        assert {"MATCH", "LINEUP", "EVENT", "PLAYER", "ODDS", "SPATIAL", "TRACKING"} <= familias
        tracking = next(c for c in saida.manifest.coverage if c.family == "TRACKING")
        assert tracking.state == "NOT_DECLARED"
        assert tracking.ratio is None

    async def test_o_manifesto_e_gravado_pela_composicao(self) -> None:
        """§133. Quem monta é quem viu o fluxo inteiro. Se o gate o recebesse
        de fora, a conferência estaria conferindo o que o chamador afirmou."""
        ambiente = Ambiente(facts=muitos_fatos(2))
        saida = await ambiente.compor()
        gravado = await ambiente.manifests.by_version(saida.version.id)
        assert gravado is not None
        assert gravado.corpus_fingerprint == saida.manifest.corpus_fingerprint

    async def test_dois_corpus_dos_mesmos_fatos_tem_a_mesma_impressao(self) -> None:
        """§89. Duas publicações INDEPENDENTES dos mesmos fatos são o mesmo
        corpus — e é para responder isso que a impressão exclui carimbo de
        tempo e id de execução (§31)."""
        primeiro = Ambiente(facts=muitos_fatos(4))
        segundo = Ambiente(facts=muitos_fatos(4))
        a = await primeiro.compor()
        b = await segundo.compor()
        assert a.version.id != b.version.id
        assert a.manifest.corpus_fingerprint == b.manifest.corpus_fingerprint

    async def test_pesquisa_e_comercio_produzem_impressoes_diferentes(self) -> None:
        """ADR-0025. A mesma avaliação produz corpus diferentes por escopo, e
        os dois coexistem — com identidades de partida IGUAIS."""
        pesquisa = Ambiente(
            facts=muitos_fatos(3, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        )
        comercial = Ambiente(
            facts=muitos_fatos(3, families=(CoverageFamily.MATCH,)),
            build_scope=UsageScope.COMMERCIAL,
        )
        a = await pesquisa.compor(usage=UsageScope.RESEARCH)
        b = await comercial.compor(usage=UsageScope.COMMERCIAL)
        assert a.manifest.corpus_fingerprint != b.manifest.corpus_fingerprint
        assert a.manifest.counts.matches == b.manifest.counts.matches


class TestAIdempotencia:
    async def test_regravar_o_mesmo_lote_nao_duplica(self) -> None:
        """§83. Um retry depois de um timeout parcial não pode duplicar a
        partida — a contagem passaria a discordar do conteúdo."""
        ambiente = Ambiente(facts=muitos_fatos(3))
        saida = await ambiente.compor()
        versao_id = saida.version.id
        membros = list(ambiente.membership.members[versao_id].values())
        regravados = await ambiente.membership.append_members(versao_id, membros)
        assert regravados == 0
        assert ambiente.membership.ignorados == 3
        assert await ambiente.membership.count_members(versao_id) == 3

    async def test_a_mesma_partida_em_dois_builds_entra_uma_vez(self) -> None:
        """§24. Um membro, DUAS linhagens — e nenhum build vence.

        O PR-04.3 chegava ao mesmo «2» por um caminho errado: `DISTINCT ON`
        escolhia a linha mais recente e descartava a outra, com as famílias e a
        linhagem dela junto. Aqui as duas contribuições sobrevivem.
        """
        outro_build = "77777777-7777-4777-8777-777777777777"
        ambiente = Ambiente(
            facts=(
                *muitos_fatos(2),
                fatos(0, build_run_id=outro_build),
            )
        )
        saida = await ambiente.build.execute(
            actor=PUBLICADOR,
            dataset_id=await ambiente.com_dataset(),
            version=DatasetVersion(major=1, minor=0),
            scope=escopo(),
            inputs=entradas(build_runs=(BUILD_RUN, outro_build)),
        )
        assert saida.members_written == 2

        gravados = await ambiente.membership.page_members(saida.version.id)
        compartilhada = next(m for m in gravados if str(m.match_id) == str(fatos(0).match.id))
        assert set(compartilhada.build_run_ids) == {BUILD_RUN, outro_build}
        sozinha = next(m for m in gravados if str(m.match_id) != str(fatos(0).match.id))
        assert sozinha.build_run_ids == (BUILD_RUN,)

    async def test_familias_complementares_de_dois_builds_se_somam(self) -> None:
        """§25, §35. Nenhuma família se perde na composição."""
        outro_build = "77777777-7777-4777-8777-777777777777"
        ambiente = Ambiente(
            facts=(
                fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS)),
                fatos(0, build_run_id=outro_build),
            )
        )
        saida = await ambiente.build.execute(
            actor=PUBLICADOR,
            dataset_id=await ambiente.com_dataset(),
            version=DatasetVersion(major=1, minor=0),
            scope=escopo(),
            inputs=entradas(build_runs=(BUILD_RUN, outro_build)),
        )
        assert saida.members_written == 1
        membro = (await ambiente.membership.page_members(saida.version.id))[0]
        assert set(membro.included_families) == {
            CoverageFamily.MATCH,
            CoverageFamily.ODDS,
        }
        assert set(membro.build_run_ids) == {BUILD_RUN, outro_build}

    async def test_fato_conflitante_entre_builds_bloqueia_a_publicacao(self) -> None:
        """§26, §36. A versão termina em FAILED — nada é publicado."""
        from dataclasses import replace as _replace
        from datetime import timedelta

        from sports_intelligence.domain.shared.temporal import instant

        outro_build = "77777777-7777-4777-8777-777777777777"
        base = fatos(0)
        divergente = _replace(
            base,
            build_run_id=outro_build,
            match=_replace(
                base.match,
                scheduled_kickoff=instant(base.match.scheduled_kickoff + timedelta(hours=3)),
            ),
        )
        ambiente = Ambiente(facts=(base, divergente))
        dataset_id = await ambiente.com_dataset()
        with pytest.raises(ConflictError, match="Nenhum build vence"):
            await ambiente.build.execute(
                actor=PUBLICADOR,
                dataset_id=dataset_id,
                version=DatasetVersion(major=1, minor=0),
                scope=escopo(),
                inputs=entradas(build_runs=(BUILD_RUN, outro_build)),
            )
        versoes, _ = await ambiente.datasets.list_versions(dataset_id)
        assert versoes[0].status is DatasetVersionStatus.FAILED

    async def test_a_ordem_dos_builds_nao_muda_a_impressao(self) -> None:
        """§37. `[A, B]` e `[B, A]` produzem o mesmo corpus."""
        outro_build = "77777777-7777-4777-8777-777777777777"
        a = fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        b = fatos(0, build_run_id=outro_build)
        direta = Ambiente(facts=(a, b))
        invertida = Ambiente(facts=(b, a))
        entrada = entradas(build_runs=(BUILD_RUN, outro_build))
        saidas = []
        for ambiente in (direta, invertida):
            saidas.append(
                await ambiente.build.execute(
                    actor=PUBLICADOR,
                    dataset_id=await ambiente.com_dataset(),
                    version=DatasetVersion(major=1, minor=0),
                    scope=escopo(),
                    inputs=entrada,
                )
            )
        assert saidas[0].manifest.corpus_fingerprint == saidas[1].manifest.corpus_fingerprint

    async def test_a_composicao_atravessa_a_fronteira_da_pagina(self) -> None:
        """As duas contribuições de uma partida podem cair em páginas
        diferentes. Se isso compusesse a partida duas vezes, o corpus teria
        metade da linhagem em cada metade — e a impressão recusaria o membro
        repetido. A página é cortada no fim da última partida completa."""
        outro_build = "77777777-7777-4777-8777-777777777777"
        ambiente = Ambiente(
            facts=(
                *muitos_fatos(3),
                *(fatos(n, build_run_id=outro_build) for n in range(3)),
            ),
            batch_size=3,
        )
        saida = await ambiente.build.execute(
            actor=PUBLICADOR,
            dataset_id=await ambiente.com_dataset(),
            version=DatasetVersion(major=1, minor=0),
            scope=escopo(),
            inputs=entradas(build_runs=(BUILD_RUN, outro_build)),
        )
        assert saida.members_written == 3
        for membro in await ambiente.membership.page_members(saida.version.id):
            assert set(membro.build_run_ids) == {BUILD_RUN, outro_build}


class TestOLimiteDoPR05:
    async def test_nada_aqui_ativa_vetor(self) -> None:
        """§4. Um corpus pronto é um corpus que pode ser LIDO."""
        from sports_intelligence.domain.corpus.versions import assert_not_vector_active
        from sports_intelligence.domain.shared.errors import InvariantViolationError

        ambiente = Ambiente(facts=muitos_fatos(1))
        saida = await ambiente.compor()
        publicada = await ambiente.publish.execute(
            actor=PUBLICADOR,
            version_id=saida.version.id,
            reason="pronto para leitura",
        )
        with pytest.raises(InvariantViolationError, match="PR-05"):
            assert_not_vector_active(publicada)


def test_o_build_run_do_fixture_e_o_esperado() -> None:
    """Guarda de sanidade: o cenário compõe o build do PR-04.2."""
    assert fatos().build_run_id == BUILD_RUN
