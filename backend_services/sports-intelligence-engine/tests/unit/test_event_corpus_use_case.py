"""A publicação de eventos no corpus, do caso de uso — PR-04.4.2.

O QUE ESTES TESTES PROVAM, e o duplo tem as MESMAS restrições do real:

    a versão DECLARA quais eventos publica        §5
    pesquisa e comércio publicam conteúdos        §71 ao §77
      diferentes das mesmas partidas
    o manifesto conta o que existe                §31, §111
    a exclusão por licença é EXPLICÁVEL           §37
    a reconciliação bloqueia publicação torta     §51, §121, §122
    a página é fatiada por volume de evento       §46, §90
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sports_intelligence.application.use_cases.corpus import (
    BuildCorpusVersion,
    CorpusBuildOutput,
    PublishCorpusVersion,
)
from sports_intelligence.domain.corpus.composition import (
    EventExclusionTally,
    PublishedEvent,
)
from sports_intelligence.domain.corpus.manifest import (
    CorpusObjectRef,
    HistoricalCanonicalManifest,
)
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus, VersionInputs
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ports.clock import FrozenClock
from tests.support.build_doubles import (
    FakeAudit,
    FakeQualityAssessmentRepository,
)
from tests.support.build_fixtures import AGORA
from tests.support.corpus_doubles import (
    FakeCompositionReader,
    FakeCorpusEventReader,
    FakeCorpusRepository,
    FakeManifestRepository,
    FakeMaterializer,
    FakeMembershipRepository,
)
from tests.support.corpus_fixtures import (
    BUILD_RUN,
    EVENT_RUN,
    OUTRA_EVENT_RUN,
    PUBLICADOR,
    dataset,
    escopo,
    evento_canonico,
    eventos_de,
    muitos_fatos,
    partida,
    publicado,
)


class Ambiente:
    """O grafo com duplos — o MESMO caso de uso da API e da CLI."""

    def __init__(
        self,
        *,
        matches: int = 2,
        eventos_por_partida: int = 3,
        build_scope: UsageScope = UsageScope.RESEARCH,
        events: dict[MatchId, tuple[PublishedEvent, ...]] | None = None,
        event_scopes: dict[str, UsageScope] | None = None,
        exclusions: EventExclusionTally | None = None,
        materializar: bool = False,
        batch_size: int = 500,
        event_rows_batch: int = 20_000,
    ) -> None:
        self.datasets = FakeCorpusRepository()
        self.membership = FakeMembershipRepository()
        self.manifests = FakeManifestRepository()
        # O ESCOPO DOS BUILDS DE PARTIDA ACOMPANHA O DA VERSÃO nos cenários
        # comerciais: o que este módulo testa é a fronteira de EVENTO, e um
        # build de partida fora de escopo faria a guarda do PR-04.3.1 §27
        # disparar antes — escondendo justamente o que se quer ver.
        self.composition = FakeCompositionReader(
            muitos_fatos(matches), (), default_scope=build_scope
        )
        self.assessments = FakeQualityAssessmentRepository()
        self.audit = FakeAudit()
        self.clock = FrozenClock(AGORA)
        self.materializer = FakeMaterializer() if materializar else None
        self.events = FakeCorpusEventReader(
            events=(
                events
                if events is not None
                else {
                    partida(n).id: eventos_de(n, quantos=eventos_por_partida)
                    for n in range(matches)
                }
            ),
            # `{}` É UMA DECLARAÇÃO — «nenhuma execução existe» —, e não
            # ausência de configuração: por isso `is None` e não `or`.
            scopes=(
                {EVENT_RUN: UsageScope.RESEARCH, OUTRA_EVENT_RUN: UsageScope.RESEARCH}
                if event_scopes is None
                else event_scopes
            ),
            exclusions=exclusions,
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
            events=self.events,
            event_rows_batch=event_rows_batch,
        )
        self.publish = PublishCorpusVersion(
            datasets=self.datasets,
            membership=self.membership,
            manifests=self.manifests,
            clock=self.clock,
            audit=self.audit,
            materializer=self.materializer,
        )

    async def compor(
        self,
        *,
        version: str = "1.0",
        usage: UsageScope = UsageScope.RESEARCH,
        event_runs: tuple[str, ...] = (EVENT_RUN,),
        dataset_id: str | None = None,
    ) -> CorpusBuildOutput:
        maior, _, menor = version.partition(".")
        criado = dataset_id or (await self.datasets.create_dataset(dataset())).id
        return await self.build.execute(
            actor=PUBLICADOR,
            dataset_id=criado,
            version=DatasetVersion(major=int(maior), minor=int(menor)),
            scope=escopo(usage),
            inputs=VersionInputs(
                build_run_ids=(BUILD_RUN,),
                quality_run_ids=(),
                event_build_run_ids=event_runs,
            ),
        )


class TestAVersaoDeclaraOsEventos:
    """§5. Pertinência é DECLARADA, nunca derivada da partida."""

    async def test_com_execucao_de_evento_a_versao_publica_eventos(self) -> None:
        ambiente = Ambiente(matches=2, eventos_por_partida=3)
        saida = await ambiente.compor()
        assert saida.event_members_written == 6
        assert await ambiente.membership.count_event_members(saida.version.id) == 6

    async def test_sem_execucao_de_evento_a_mesma_partida_entra_sem_eventos(self) -> None:
        """As MESMAS partidas, dois corpus: um com eventos e outro sem. É a
        diferença que derivar pertinência apagaria."""
        ambiente = Ambiente(matches=2)
        saida = await ambiente.compor(event_runs=())
        assert saida.event_members_written == 0
        assert saida.manifest.counts.events.total == 0
        # E o documento nem carrega a chave: ele é o de antes deste PR.
        assert "events" not in saida.manifest.counts.as_canonical()

    async def test_as_execucoes_de_evento_ficam_registradas(self) -> None:
        ambiente = Ambiente()
        saida = await ambiente.compor()
        gravadas = await ambiente.datasets.event_build_run_ids_of(saida.version.id)
        assert list(gravadas) == [EVENT_RUN]

    async def test_execucao_de_evento_inexistente_e_recusada(self) -> None:
        ambiente = Ambiente(event_scopes={})
        with pytest.raises(NotFoundError, match="não encontrada"):
            await ambiente.compor()

    async def test_a_procedencia_da_politica_de_evento_entra_no_manifesto(self) -> None:
        """«Produzido de que jeito» é pergunta do manifesto, e a resposta vem
        do banco — não do chamador."""
        ambiente = Ambiente()
        saida = await ambiente.compor()
        forma = saida.manifest.inputs.as_canonical()
        assert forma["event_build_run_ids"] == [EVENT_RUN]
        assert forma["event_policy_versions"] == [1]


class TestPesquisaContraComercio:
    """§71 ao §77. As mesmas partidas, conteúdos de evento diferentes."""

    def _cenario(self) -> dict[MatchId, tuple[PublishedEvent, ...]]:
        """Dois eventos públicos e dois restritos, na mesma partida.

        A EXECUÇÃO COMERCIAL SÓ PRODUZIU OS PÚBLICOS — é o que a elegibilidade
        do PR-04.4.1 faz com `LICENSE_POLICY`. Aqui isso aparece como os
        restritos existindo apenas sob a execução de pesquisa.
        """
        publicos = tuple(
            publicado(
                evento_canonico(n=i, minuto=10 + i, sequencia=i, source_key=f"pub-{i}"),
                runs=(EVENT_RUN, OUTRA_EVENT_RUN),
            )
            for i in range(2)
        )
        restritos = tuple(
            publicado(
                evento_canonico(
                    n=10 + i,
                    minuto=30 + i,
                    sequencia=10 + i,
                    source_key=f"res-{i}",
                    license_class=LicenseClass.RESEARCH_ONLY,
                ),
                runs=(EVENT_RUN,),
            )
            for i in range(2)
        )
        return {partida(0).id: publicos + restritos}

    async def test_pesquisa_inclui_os_quatro(self) -> None:
        ambiente = Ambiente(matches=1, events=self._cenario())
        saida = await ambiente.compor(version="1.0")
        assert saida.event_members_written == 4
        assert saida.manifest.counts.events.total == 4

    async def test_comercio_exclui_os_restritos(self) -> None:
        """§73. O mesmo `MatchId`, e dois eventos a menos."""
        ambiente = Ambiente(
            matches=1,
            events=self._cenario(),
            build_scope=UsageScope.COMMERCIAL,
            event_scopes={
                EVENT_RUN: UsageScope.RESEARCH,
                OUTRA_EVENT_RUN: UsageScope.COMMERCIAL,
            },
        )
        saida = await ambiente.compor(usage=UsageScope.COMMERCIAL, event_runs=(OUTRA_EVENT_RUN,))
        assert saida.event_members_written == 2
        assert saida.manifest.counts.events.total == 2

    async def test_as_impressoes_diferem_e_os_matchids_nao(self) -> None:
        """§74, §75. Mesma partida canônica, corpus diferentes."""
        pesquisa = Ambiente(matches=1, events=self._cenario())
        comercio = Ambiente(
            matches=1,
            events=self._cenario(),
            build_scope=UsageScope.COMMERCIAL,
            event_scopes={
                EVENT_RUN: UsageScope.RESEARCH,
                OUTRA_EVENT_RUN: UsageScope.COMMERCIAL,
            },
        )
        de_pesquisa = await pesquisa.compor()
        de_comercio = await comercio.compor(
            usage=UsageScope.COMMERCIAL, event_runs=(OUTRA_EVENT_RUN,)
        )
        assert de_pesquisa.manifest.corpus_fingerprint != de_comercio.manifest.corpus_fingerprint
        de_um = set(pesquisa.membership.members[de_pesquisa.version.id])
        de_outro = set(comercio.membership.members[de_comercio.version.id])
        assert de_um == de_outro

    async def test_o_match_core_sobrevive_a_exclusao_de_evento(self) -> None:
        """§36, §78. Excluir EVENT por licença NÃO remove a partida, e não
        degrada o núcleo dela."""
        ambiente = Ambiente(
            matches=1,
            events={},
            build_scope=UsageScope.COMMERCIAL,
            event_scopes={OUTRA_EVENT_RUN: UsageScope.COMMERCIAL},
        )
        saida = await ambiente.compor(usage=UsageScope.COMMERCIAL, event_runs=(OUTRA_EVENT_RUN,))
        assert saida.members_written == 1
        assert saida.event_members_written == 0
        familias = saida.manifest.license.families_included
        assert "MATCH" in familias
        assert "EVENT" not in familias


class TestAExclusaoExplicavel:
    """§37. `events=0` não explica nada; o motivo e a licença explicam."""

    async def test_a_exclusao_por_licenca_aparece_com_motivo(self) -> None:
        ambiente = Ambiente(
            matches=1,
            events={},
            exclusions=EventExclusionTally(
                by_reason={"LICENSE_POLICY": 120},
                licenses=("RESEARCH_ONLY",),
            ),
            build_scope=UsageScope.COMMERCIAL,
            event_scopes={OUTRA_EVENT_RUN: UsageScope.COMMERCIAL},
        )
        saida = await ambiente.compor(usage=UsageScope.COMMERCIAL, event_runs=(OUTRA_EVENT_RUN,))
        licenca = saida.manifest.license
        assert "EVENT" in licenca.families_excluded
        assert licenca.exclusion_reasons["EVENT"] == {"LICENSE_POLICY": 120}
        assert licenca.exclusion_licenses["EVENT"] == "RESEARCH_ONLY"

    async def test_sem_exclusao_a_familia_nao_aparece_como_excluida(self) -> None:
        ambiente = Ambiente(matches=1)
        saida = await ambiente.compor()
        assert "EVENT" not in saida.manifest.license.families_excluded


class TestOManifestoComEventos:
    """§31, §32, §111, §112. Contagens e cobertura do que foi publicado."""

    async def test_conta_eventos_por_tipo_e_estado(self) -> None:
        ambiente = Ambiente(matches=2, eventos_por_partida=5)
        saida = await ambiente.compor()
        contagem = saida.manifest.counts.events
        assert contagem.total == 10
        assert contagem.by_type["SHOT"] == 2
        assert contagem.by_status["ACTIVE"] == 10

    async def test_a_cobertura_de_evento_e_disponibilidade_e_nao_medicao(self) -> None:
        """§30. Não há denominador honesto para «quantos eventos esta partida
        DEVERIA ter» — e inventar um produziria porcentagem que parece medida."""
        ambiente = Ambiente(matches=2, eventos_por_partida=5)
        saida = await ambiente.compor()
        de_evento = next(c for c in saida.manifest.coverage if c.family == "EVENT")
        assert de_evento.state == CoverageState.AVAILABILITY_ONLY.value
        assert de_evento.expected_total is None
        assert de_evento.available_total == 10
        assert de_evento.matches_with_data == 2

    async def test_a_cobertura_espacial_e_medida_sobre_o_denominador_honesto(self) -> None:
        """§28. Numerador: eventos com coordenada. Denominador: os que
        ACONTECEM num ponto do campo."""
        ambiente = Ambiente(matches=2, eventos_por_partida=5)
        saida = await ambiente.compor()
        espacial = next(c for c in saida.manifest.coverage if c.family == "SPATIAL")
        assert espacial.state == CoverageState.MEASURED.value
        assert espacial.available_total == 6
        assert espacial.expected_total == 6

    async def test_sem_evento_a_cobertura_continua_nao_declarada(self) -> None:
        """O comportamento anterior sobrevive: sem evento publicado, o que a
        avaliação disser vale — inclusive `NOT_DECLARED`."""
        ambiente = Ambiente(matches=2)
        saida = await ambiente.compor(event_runs=())
        de_evento = next(c for c in saida.manifest.coverage if c.family == "EVENT")
        assert de_evento.state == CoverageState.NOT_DECLARED.value

    async def test_a_licenca_dos_eventos_publicados_entra_no_resumo(self) -> None:
        ambiente = Ambiente(matches=1)
        saida = await ambiente.compor()
        assert "PUBLIC_DOMAIN" in saida.manifest.license.licenses_present


class TestAMaterializacaoDeEventos:
    """§18, §44, §45, §48. Os arquivos de evento e o metadado deles."""

    async def test_escreve_events_parquet_por_particao(self) -> None:
        ambiente = Ambiente(matches=2, eventos_por_partida=4, materializar=True)
        await ambiente.compor()
        assert ambiente.materializer is not None
        de_evento = {
            chave: linhas
            for chave, linhas in ambiente.materializer.objects.items()
            if "family=EVENT/" in chave
        }
        assert de_evento
        assert sum(de_evento.values()) == 8

    async def test_sem_evento_nenhum_arquivo_de_evento_e_escrito(self) -> None:
        """§52. Um Parquet de zero linha é indistinguível, na leitura, de uma
        partição que ninguém escreveu."""
        ambiente = Ambiente(matches=2, materializar=True)
        saida = await ambiente.compor(event_runs=())
        assert saida.objects_written
        assert ambiente.materializer is not None
        assert not [c for c in ambiente.materializer.objects if "family=EVENT/" in c]


class TestAReconciliacao:
    """§51, §121, §122. Três números que precisam bater, ou nada é publicado."""

    async def test_publica_quando_os_numeros_batem(self) -> None:
        ambiente = Ambiente(matches=2, eventos_por_partida=3, materializar=True)
        saida = await ambiente.compor()
        publicada = await ambiente.publish.execute(
            actor=PUBLICADOR, version_id=saida.version.id, reason="teste"
        )
        assert publicada.status.is_frozen

    async def test_recusa_quando_a_pertinencia_nao_bate_com_o_manifesto(self) -> None:
        """Um lote perdido ou em dobro — e a versão é imutável depois."""
        ambiente = Ambiente(matches=2, eventos_por_partida=3)
        saida = await ambiente.compor()
        del ambiente.membership.event_members[saida.version.id][
            next(iter(ambiente.membership.event_members[saida.version.id]))
        ]
        with pytest.raises(ValidationError, match="evento"):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="teste"
            )

    async def test_recusa_quando_o_arquivo_nao_tem_as_linhas_declaradas(self) -> None:
        ambiente = Ambiente(matches=2, eventos_por_partida=3, materializar=True)
        saida = await ambiente.compor()
        manifesto = ambiente.manifests.manifests[saida.version.id]
        objetos = tuple(
            o if o.family != CoverageFamily.EVENT.value else _com_linhas(o, 1)
            for o in manifesto.objects
        )
        ambiente.manifests.manifests[saida.version.id] = _com_objetos(manifesto, objetos)
        with pytest.raises(ValidationError, match="linha"):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id=saida.version.id, reason="teste"
            )


class TestAFalhaNaoViraReady:
    """§119, §120. Publicação falha vira `FAILED`, e nunca `READY` com ressalva."""

    async def test_falha_ao_escrever_o_arquivo_de_evento_derruba_a_versao(self) -> None:
        """Uma versão que falhou no meio deixou pertinência parcial gravada — e
        é exatamente por isso que ela precisa de um estado próprio: `READY`
        significaria «este é o corpus», e ele estaria pela metade."""
        ambiente = Ambiente(matches=2, eventos_por_partida=3, materializar=True)
        assert ambiente.materializer is not None
        ambiente.materializer.falhar_em = CoverageFamily.EVENT
        with pytest.raises(RuntimeError, match="object store indisponível"):
            await ambiente.compor()
        versoes = list(ambiente.datasets.versions.values())
        assert versoes
        assert all(v.status is DatasetVersionStatus.FAILED for v in versoes)
        assert all(v.failure_reason for v in versoes)

    async def test_a_versao_que_falhou_nao_e_publicavel(self) -> None:
        ambiente = Ambiente(matches=1, eventos_por_partida=2, materializar=True)
        assert ambiente.materializer is not None
        ambiente.materializer.falhar_em = CoverageFamily.EVENT
        with pytest.raises(RuntimeError):
            await ambiente.compor()
        versao = next(iter(ambiente.datasets.versions.values()))
        with pytest.raises(ConflictError, match="VALIDATING"):
            await ambiente.publish.execute(
                actor=PUBLICADOR, version_id=versao.id, reason="não deveria publicar"
            )


class TestOFatiamentoPorEvento:
    """§46, §90, §91. A página é cortada por VOLUME de evento."""

    async def test_a_pagina_e_fatiada_quando_o_teto_e_baixo(self) -> None:
        ambiente = Ambiente(matches=4, eventos_por_partida=3, event_rows_batch=4)
        await ambiente.compor()
        # Quatro partidas com três eventos: 3+3 estoura o teto de 4, então
        # cada pedaço leva uma partida. Quatro leituras, e não uma.
        assert ambiente.events.leituras == 4

    async def test_o_teto_alto_traz_a_pagina_inteira(self) -> None:
        ambiente = Ambiente(matches=4, eventos_por_partida=3, event_rows_batch=100)
        await ambiente.compor()
        assert ambiente.events.leituras == 1

    async def test_o_fatiamento_nao_muda_a_impressao(self) -> None:
        """§16. O tamanho do pedaço é detalhe de execução."""
        estreito = Ambiente(matches=4, eventos_por_partida=3, event_rows_batch=4)
        largo = Ambiente(matches=4, eventos_por_partida=3, event_rows_batch=100)
        um = await estreito.compor()
        outro = await largo.compor()
        assert um.manifest.corpus_fingerprint == outro.manifest.corpus_fingerprint

    async def test_a_contagem_vem_antes_da_leitura(self) -> None:
        """§46. Ler primeiro e medir depois seria descobrir o pico de memória
        tendo já pagado por ele."""
        ambiente = Ambiente(matches=4, eventos_por_partida=3, event_rows_batch=4)
        await ambiente.compor()
        assert ambiente.events.contagens == 1


def _com_linhas(objeto: CorpusObjectRef, linhas: int) -> CorpusObjectRef:
    """O mesmo objeto declarando OUTRO número de linhas — a discordância que a
    reconciliação do §51 existe para pegar."""
    return replace(objeto, row_count=linhas)


def _com_objetos(
    manifesto: HistoricalCanonicalManifest, objetos: tuple[CorpusObjectRef, ...]
) -> HistoricalCanonicalManifest:
    return replace(manifesto, objects=objetos)
