"""Do dataset cru PUBLICADO à representação normalizada — infraestrutura real.

O QUE SÓ ESTE TESTE PROVA:

    o PARQUET NORMALIZADO é escrito    com 330 colunas derivadas do PLANO
    o PREFIXO é `normalized/`          e não o do cru — duas representações do
                                       mesmo conteúdo não podem colidir
    as TRÊS MÁSCARAS chegam ao arquivo  valor, motivo da normalização, motivo
                                       da origem
    a MIGRATION 0013 aplica            e as restrições dela recusam o inválido
    a ESCALA volta do banco em `Decimal` e não em ponto flutuante
    o CONTRATO 1:1 fecha                contra o RODAPÉ do Parquet cru, e não
                                       contra a coluna do banco
    a VALIDAÇÃO relê o Parquet          e reconstrói as três impressões
    a PUBLICAÇÃO grava o manifesto       ao lado dos dados, com o plano inteiro
    a INVARIANTE central vale            no caminho completo, e não só no
                                       domínio: reajustar sobre a mesma
                                       referência dá a MESMA impressão

O CORPUS DO CENÁRIO É PEQUENO, e isso muda o que se pode afirmar: com poucas
partidas, os artefatos saem `INSUFFICIENT_SAMPLE` — o mínimo declarado é trinta
observações disponíveis. ISSO NÃO É UMA LIMITAÇÃO DO TESTE, é o caminho que
mais importa provar de ponta a ponta: um eixo sem amostra produz célula VAZIA
com o motivo certo, e NUNCA o valor cru disfarçado de normalizado.

A DIFERENÇA PARA OS DE PROPRIEDADE. Lá tudo é em memória e a invariante é
provada sobre cenários sintéticos; aqui os bytes vão para o object store,
voltam dele, e o `pq.read_table` é quem diz se o schema derivado do plano
sobreviveu à ida e à volta.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.fitting.artifact import FitStatus
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
)
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.support.dataset_e2e import NOME as NOME_CRU
from tests.support.normalized_e2e import (
    ATOR,
    COLUNAS_ESPERADAS,
    NOME,
    MontagemNormalizada,
)

pytestmark = pytest.mark.integration


async def _ate_validating(dados: dict[str, Any]) -> dict[str, Any]:
    """Ajuste conferido, versão criada e construída. Para em `VALIDATING`."""
    montagem: MontagemNormalizada = dados["montagem_n"]
    crua = dados["versao_crua"]
    relatorio = await montagem.conferir_ajuste.execute(
        artifact_set_id=dados["ajuste"].artifact_set.id,
        actor=ATOR,
        reason="E2E: o ajuste conferido é o que autoriza normalizar",
    )
    assert relatorio.passed, relatorio.divergences
    versao = await montagem.criar.execute(
        version=DatasetVersion(major=1, minor=0),
        source_version_id=crua.id,
        artifact_set_id=dados["ajuste"].artifact_set.id,
        dataset_name=NOME,
        actor=ATOR,
    )
    saida = await montagem.construir.execute(
        version_id=versao.id,
        dataset_name=NOME,
        raw_dataset_name=NOME_CRU,
        actor=ATOR,
    )
    return {**dados, "versao_n": versao, "saida_n": saida, "relatorio_ajuste": relatorio}


@pytest.fixture
async def construido_n(normalizado: dict[str, Any]) -> dict[str, Any]:
    return await _ate_validating(normalizado)


class TestOAjusteReal:
    """O ajuste sobre o Parquet cru, lido do object store de verdade."""

    def test_ele_le_a_referencia_e_produz_artefatos(self, normalizado: dict[str, Any]) -> None:
        ajuste = normalizado["ajuste"]
        assert ajuste.reference_rows > 0
        assert ajuste.competitions >= 1
        # VINTE E NOVE EIXOS POR COMPETIÇÃO — os `ROBUST` do plano, e só eles.
        # Os `PASS_THROUGH` não têm escala para guardar.
        assert ajuste.artifacts == 29 * ajuste.competitions
        assert ajuste.artifacts == ajuste.fitted + ajuste.insufficient + ajuste.degenerate

    async def test_o_conjunto_fica_em_building_e_nao_em_ready(
        self, normalizado: dict[str, Any]
    ) -> None:
        """§ O grafo é explícito: publicar sem conferir não é alcançável.

        `BUILDING` E NÃO `DRAFT`: o ajuste lê, calcula e grava numa chamada só,
        e marcar o fim dela é o que permite à conferência seguir por
        `VALIDATING` sem abrir o salto `DRAFT → READY`.
        """
        montagem: MontagemNormalizada = normalizado["montagem_n"]
        conjunto = await montagem.artifacts.by_id(normalizado["ajuste"].artifact_set.id)
        assert conjunto is not None
        assert conjunto.status is DatasetVersionStatus.BUILDING

    async def test_a_escala_volta_do_banco_em_decimal(self, normalizado: dict[str, Any]) -> None:
        """A coluna é `numeric`, e o adaptador RECUSA um `float`.

        UM `double precision` FARIA A ESCALA DE UMA COMPETIÇÃO depender do
        arredondamento do driver — e o número resultante seria plausível.
        """
        from decimal import Decimal

        montagem: MontagemNormalizada = normalizado["montagem_n"]
        conjunto = await montagem.artifacts.by_id(normalizado["ajuste"].artifact_set.id)
        assert conjunto is not None
        for pacote in conjunto.bundles:
            for artefato in pacote.artifacts:
                for numero in (artefato.median, artefato.q1, artefato.q3, artefato.iqr):
                    assert numero is None or isinstance(numero, Decimal)

    async def test_a_impressao_gravada_fecha_com_a_recalculada(
        self, normalizado: dict[str, Any]
    ) -> None:
        montagem: MontagemNormalizada = normalizado["montagem_n"]
        # A LEITURA JÁ CONFERE — `_para_conjunto` levanta se divergir. Este
        # teste existe para que a conferência seja EXERCITADA no E2E, e não só
        # exista no código.
        conjunto = await montagem.artifacts.by_id(normalizado["ajuste"].artifact_set.id)
        assert conjunto is not None
        assert conjunto.fingerprint == normalizado["ajuste"].fingerprint

    async def test_o_pacote_de_uma_competicao_vem_sozinho(
        self, normalizado: dict[str, Any]
    ) -> None:
        """O acesso que a leitura ao vivo do PR-06 vai usar."""
        montagem: MontagemNormalizada = normalizado["montagem_n"]
        conjunto = normalizado["ajuste"].artifact_set
        competicao = conjunto.competitions[0]
        pacote = await montagem.artifacts.bundle_of(conjunto.id, competition=competicao)
        assert pacote is not None
        assert pacote.competition == competicao
        assert len(pacote.artifacts) == 29


class TestAConferenciaDoAjuste:
    async def test_ela_aprova_e_publica_o_conjunto(self, construido_n: dict[str, Any]) -> None:
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        conjunto = await montagem.artifacts.by_id(construido_n["ajuste"].artifact_set.id)
        assert conjunto is not None
        assert conjunto.status is DatasetVersionStatus.READY

    async def test_um_conjunto_publicado_nao_aceita_artefato_novo(
        self, construido_n: dict[str, Any]
    ) -> None:
        """§ A imutabilidade é do REPOSITÓRIO, e não da disciplina."""
        from sports_intelligence.domain.shared.errors import ConflictError

        montagem: MontagemNormalizada = construido_n["montagem_n"]
        conjunto = construido_n["ajuste"].artifact_set
        with pytest.raises(ConflictError, match="não aceita artefato"):
            await montagem.artifacts.save_bundles(conjunto.id, conjunto.bundles)


class TestAConstrucaoReal:
    def test_a_versao_fica_em_validating_com_as_tres_impressoes(
        self, construido_n: dict[str, Any]
    ) -> None:
        saida = construido_n["saida_n"]
        assert saida.version.status is DatasetVersionStatus.VALIDATING
        assert saida.fingerprint
        assert saida.reference_fingerprint
        assert saida.evaluation_fingerprint
        assert saida.version.manifest_id is not None

    def test_o_contrato_1_para_1_fecha(self, construido_n: dict[str, Any]) -> None:
        saida = construido_n["saida_n"]
        crua = construido_n["versao_crua"]
        assert saida.rows_read == saida.rows_written
        assert saida.rows_written == crua.row_count

    async def test_o_parquet_tem_as_colunas_do_plano(self, construido_n: dict[str, Any]) -> None:
        import pyarrow.parquet as pq

        montagem: MontagemNormalizada = construido_n["montagem_n"]
        objeto = next(
            o for o in construido_n["saida_n"].objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in montagem.materializer._store.open_stream(objeto.object_key):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))
        assert len(tabela.schema) == COLUNAS_ESPERADAS
        for prefixo in ("n_", "m_", "s_"):
            assert any(nome.startswith(prefixo) for nome in tabela.schema.names)
        # AS TRÊS FAMÍLIAS DO MESMO EIXO existem juntas, e é o que permite
        # distinguir «não havia valor» de «não havia escala».
        assert "n_xg_home_5m" in tabela.schema.names
        assert "m_xg_home_5m" in tabela.schema.names
        assert "s_xg_home_5m" in tabela.schema.names

    def test_o_prefixo_do_objeto_e_normalized(self, construido_n: dict[str, Any]) -> None:
        """Escrever sob o prefixo do cru faria duas representações colidirem."""
        for objeto in construido_n["saida_n"].objects:
            assert objeto.object_key.startswith("normalized/")
            assert "split=" in objeto.object_key
            assert "competition=" in objeto.object_key

    async def test_sem_escala_a_celula_fica_vazia_no_ARQUIVO(
        self, construido_n: dict[str, Any]
    ) -> None:
        """O caminho que mais importa provar de ponta a ponta (ADR-0035).

        O QUE O CENÁRIO PRODUZ, medido: alguns eixos `ROBUST` chegam a trinta
        observações e ajustam; outros têm valor cru e IQR nulo — a competição
        não tem dispersão naquele eixo. Os SEGUNDOS são o caso deste teste.

        A CÉLULA FICA VAZIA E A MÁSCARA DE ORIGEM DIZ `AVAILABLE`. As duas
        colunas juntas são o que distingue «não havia valor» de «havia valor e
        não havia escala» — e a segunda NÃO pode trazer o número cru
        disfarçado, sob pena de misturar unidades na mesma coluna.
        """
        import pyarrow.parquet as pq

        montagem: MontagemNormalizada = construido_n["montagem_n"]
        contagem = construido_n["saida_n"].availability.by_state
        degenerados = contagem.get(NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE.value, 0)
        assert degenerados > 0, "o cenário precisa exercitar o caminho sem dispersão"

        objeto = next(
            o for o in construido_n["saida_n"].objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in montagem.materializer._store.open_stream(objeto.object_key):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))

        vistos = 0
        for eixo in montagem.plan.robust_keys:
            mascara = tabela.column(f"m_{eixo}").to_pylist()
            valores = tabela.column(f"n_{eixo}").to_pylist()
            origens = tabela.column(f"s_{eixo}").to_pylist()
            for estado, valor, origem in zip(mascara, valores, origens, strict=True):
                if estado != NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE.value:
                    continue
                vistos += 1
                assert valor is None, (
                    f"{eixo}: célula sem escala carregando {valor} — a coluna teria "
                    "unidades misturadas entre competições"
                )
                assert origem == "AVAILABLE", (
                    f"{eixo}: sem escala e sem valor cru é SOURCE_VALUE_UNAVAILABLE; "
                    "atribuir o caso à origem faria alguém procurar um provedor de "
                    "dados para resolver um problema de distribuição"
                )
        assert vistos == degenerados

    def test_a_contagem_por_estado_soma_a_grade_inteira(self, construido_n: dict[str, Any]) -> None:
        """Nenhuma célula some: 105 eixos por linha, sempre."""
        saida = construido_n["saida_n"]
        assert saida.availability.total_cells == saida.rows_written * 105

    def test_as_duas_familias_de_disponibilidade_sao_contadas_separadas(
        self, construido_n: dict[str, Any]
    ) -> None:
        """§62 — um contador só apagaria a diferença onde ela decide o que fazer."""
        disponibilidade = construido_n["saida_n"].availability
        assert disponibilidade.by_state
        assert disponibilidade.by_source_state
        assert disponibilidade.total_cells == sum(disponibilidade.by_state.values())


class TestOBancoGuardaPonteirosEEscala:
    async def test_os_objetos_estao_registrados(self, construido_n: dict[str, Any]) -> None:
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        registrados = await montagem.builds.objects_of(construido_n["versao_n"].id)
        chaves = {o.object_key for o in registrados}
        assert chaves == {o.object_key for o in construido_n["saida_n"].objects}

    async def test_nenhuma_linha_normalizada_no_banco(
        self, database: Database, construido_n: dict[str, Any]
    ) -> None:
        """ADR-0037 — as linhas moram no Parquet, e só nele."""
        async with database.acquire() as conexao:
            tabelas = await conexao.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name LIKE 'normalized%'
                """
            )
        nomes = {linha["table_name"] for linha in tabelas}
        assert "normalized_feature_rows" not in nomes
        assert "normalized_feature_objects" in nomes

    async def test_a_execucao_registra_as_celulas_sem_escala(
        self, construido_n: dict[str, Any]
    ) -> None:
        """A métrica de saúde do AJUSTE, e não da coleta."""
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        execucoes = await montagem.builds.runs_of(construido_n["versao_n"].id)
        assert execucoes
        assert execucoes[0].rows_written == construido_n["saida_n"].rows_written
        assert (
            execucoes[0].artifact_unavailable_cells
            == construido_n["saida_n"].availability.artifact_unavailable
        )


class TestAValidacaoRele:
    async def test_ela_aprova_e_as_tres_impressoes_fecham(
        self, construido_n: dict[str, Any]
    ) -> None:
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        relatorio = await montagem.validar.execute(
            version_id=construido_n["versao_n"].id,
            raw_dataset_name=NOME_CRU,
            actor=ATOR,
        )
        assert relatorio.passed, relatorio.failures
        saida = construido_n["saida_n"]
        assert relatorio.fingerprint == saida.fingerprint
        assert relatorio.reference_fingerprint == saida.reference_fingerprint
        assert relatorio.evaluation_fingerprint == saida.evaluation_fingerprint

    async def test_o_leitor_enumera_as_particoes_do_BUCKET(
        self, construido_n: dict[str, Any]
    ) -> None:
        """Elas vêm do object store, e não do banco.

        O QUE IMPORTA PARA A RECONCILIAÇÃO é o que EXISTE no bucket: um objeto
        órfão que o registro não conhece tem de aparecer aqui para que alguém o
        veja. Deduzi-las do banco responderia só o que o banco já sabe.
        """
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        crua = construido_n["versao_crua"]
        todas = await montagem.reader.partitions(dataset_name=NOME_CRU, version=str(crua.version))
        so_referencia = await montagem.reader.partitions(
            dataset_name=NOME_CRU,
            version=str(crua.version),
            split=DatasetSplit.REFERENCE,
        )
        assert todas
        assert list(todas) == sorted(todas, key=lambda p: (p[0].value, p[1], p[2]))
        assert all(p[0] is DatasetSplit.REFERENCE for p in so_referencia)
        assert set(so_referencia) <= set(todas)

    async def test_ela_confere_a_cardinalidade_contra_o_rodape_do_parquet(
        self, construido_n: dict[str, Any]
    ) -> None:
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        no_arquivo = await montagem.reader.row_count(
            dataset_name=NOME_CRU, version=str(construido_n["versao_crua"].version)
        )
        assert no_arquivo == construido_n["saida_n"].rows_written


class TestAPublicacao:
    async def test_ela_grava_o_manifesto_com_o_plano_inteiro(
        self, construido_n: dict[str, Any]
    ) -> None:
        montagem: MontagemNormalizada = construido_n["montagem_n"]
        version_id = construido_n["versao_n"].id
        relatorio = await montagem.validar.execute(
            version_id=version_id, raw_dataset_name=NOME_CRU, actor=ATOR
        )
        assert relatorio.passed
        publicada = await montagem.publicar.execute(
            version_id=version_id,
            dataset_name=NOME,
            actor=ATOR,
            reason="E2E: esta é a base de comparação a partir de agora",
        )
        assert publicada.status is DatasetVersionStatus.READY

        manifesto = await montagem.builds.manifest_by_version(version_id)
        assert manifesto is not None
        assert manifesto.plan.size == 105
        assert manifesto.plan.fingerprint == montagem.plan.fingerprint
        # O MAPA `(competição, eixo) → artefato` cobre os eixos ROBUST, e só.
        assert len(manifesto.artifact_map) == 29 * len(manifesto.competitions)
        estados = {e.status for e in manifesto.artifact_map}
        assert estados <= {e.value for e in FitStatus}


class TestAInvarianteNoCaminhoCompleto:
    """§152 — reajustar sobre a MESMA referência dá a MESMA impressão."""

    async def test_reajustar_produz_o_mesmo_conjunto(self, normalizado: dict[str, Any]) -> None:
        montagem: MontagemNormalizada = normalizado["montagem_n"]
        crua = normalizado["versao_crua"]
        segundo = await montagem.ajustar.execute(
            source_version_id=crua.id,
            raw_dataset_name=NOME_CRU,
            actor=ATOR,
            # SEM REUSO, para que o segundo ajuste seja de fato calculado de
            # novo — reusar o primeiro provaria só que a busca por impressão
            # funciona.
            reuse_existing=False,
        )
        primeiro = normalizado["ajuste"]
        assert segundo.artifact_set.id != primeiro.artifact_set.id
        assert segundo.fingerprint == primeiro.fingerprint
        assert segundo.reference_rows == primeiro.reference_rows
        for esquerda, direita in zip(
            primeiro.artifact_set.bundles,
            segundo.artifact_set.bundles,
            strict=True,
        ):
            assert esquerda.fingerprint == direita.fingerprint
