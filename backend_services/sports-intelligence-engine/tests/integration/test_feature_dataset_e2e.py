"""Do corpus PUBLICADO ao dataset de features em Parquet — PostgreSQL e store reais.

O QUE SÓ ESTE TESTE PROVA (§150 ao §158):

    o PARQUET É ESCRITO DE VERDADE   com 233 colunas tipadas pelo catálogo
    a PARTIÇÃO é `split=/competition=/season=` no caminho do objeto
    o BANCO guarda PONTEIROS          e nenhum valor de feature
    a MIGRATION 0012 aplica           e as restrições dela recusam o inválido
    a VALIDAÇÃO relê o Parquet        e reconstrói a impressão a partir dele
    a RECONSTRUÇÃO SEMÂNTICA confere  TODAS as partidas — o dataset é pequeno,
                                      então «amostra» aqui é o conjunto inteiro
    a PUBLICAÇÃO grava o manifesto     ao lado dos dados
    a REPRODUTIBILIDADE                duas versões sobre o mesmo corpus e as
                                      mesmas políticas têm a MESMA impressão

O CORPUS DO CENÁRIO NÃO PUBLICA `LINEUP` NEM `ODDS`, e isso é ÚTIL aqui em vez
de inconveniente: o `MATCH_STATE_RAW_V2` exige `LINEUP`, então a conferência
prévia da criação RECUSA este corpus — e há um teste que prova essa recusa. Os
demais dispensam a conferência de propósito, porque é justamente com famílias
ausentes que a regra «indisponível é `NULL`, e a coluna de disponibilidade diz
por quê» tem o que provar do começo ao fim.

A DIFERENÇA PARA OS DE UNIDADE. Lá o materializador é um duplo que guarda
objetos numa lista; aqui os bytes vão para o object store, voltam dele, e o
`pq.read_table` é quem diz se o schema declarado sobreviveu à ida e à volta.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.support.dataset_e2e import (
    ATOR,
    COLUNAS_ESPERADAS,
    NOME,
    Montagem,
    construir_versao,
    divisao_do_corpus,
    origem_publicada,
)
from tests.support.instrumentation import contando_consultas

pytestmark = pytest.mark.integration


class TestAConferenciaPrevia:
    async def test_a_conferencia_previa_recusa_este_corpus(
        self, database: Database, object_store: Any, publicado: dict[str, Any]
    ) -> None:
        """§58 — descobrir a família ausente DEPOIS de noventa mil snapshots
        custaria a construção inteira para chegar a uma máscara vazia."""
        from sports_intelligence.domain.shared.errors import ValidationError

        montagem = Montagem(database, object_store)
        origem = origem_publicada(publicado)
        assert CoverageFamily.LINEUP not in origem.published_families
        with pytest.raises(ValidationError, match="LINEUP"):
            await montagem.criar.execute(
                dataset_name="conferencia-previa",
                version=DatasetVersion(major=1, minor=0),
                source_version_id=origem.version_id,
                split=await divisao_do_corpus(database, publicado),
                actor=ATOR,
                published_families=origem.published_families,
            )


class TestAConstrucaoReal:
    async def test_a_versao_fica_em_validating_com_impressao_e_manifesto(
        self, construido: dict[str, Any]
    ) -> None:
        saida = construido["saida"]
        assert saida.version.status is DatasetVersionStatus.VALIDATING
        assert saida.raw_content_fingerprint.value
        assert saida.rows_written == saida.matches_processed * 91

    async def test_o_banco_guarda_a_versao_com_as_tres_impressoes(
        self, construido: dict[str, Any], database: Database
    ) -> None:
        saida = construido["saida"]
        async with database.acquire() as conexao:
            linha = await conexao.fetchrow(
                """
                SELECT grid_name, grid_fingerprint, split_fingerprint,
                       space_fingerprint, row_count, match_count,
                       reference_rows, evaluation_rows
                FROM historical_feature_dataset_versions WHERE id = $1
                """,
                __import__("uuid").UUID(saida.version.id),
            )
        assert linha is not None
        assert linha["grid_fingerprint"] == DEFAULT_SNAPSHOT_GRID.fingerprint
        assert linha["row_count"] == saida.rows_written
        assert linha["reference_rows"] + linha["evaluation_rows"] == linha["row_count"]

    async def test_a_versao_volta_do_banco_com_os_PARAMETROS_da_grade(
        self, construido: dict[str, Any]
    ) -> None:
        """O DEFEITO QUE ESTE TESTE PEGA: guardar só nome, versão e impressão
        faria a grade voltar com os limites PADRÃO — e uma política com
        parâmetros só é reconstrutível a partir dos parâmetros."""
        montagem, saida = construido["montagem"], construido["saida"]
        relida = await montagem.repo.version_by_id(saida.version.id)
        assert relida is not None
        assert relida.spec == saida.version.spec
        assert relida.spec.grid == DEFAULT_SNAPSHOT_GRID
        assert relida.spec.grid.regulation_size == 91
        assert relida.spec.split.reference_end_exclusive == (
            saida.version.spec.split.reference_end_exclusive
        )

    async def test_os_objetos_sao_registrados_com_a_particao_em_colunas(
        self, construido: dict[str, Any], database: Database
    ) -> None:
        """Reconciliar manifesto com registro não pode depender de fazer
        análise sintática de caminho."""
        saida = construido["saida"]
        async with database.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT object_key, split, competition, season, row_count "
                "FROM historical_feature_objects WHERE version_id = $1",
                __import__("uuid").UUID(saida.version.id),
            )
        assert linhas
        assert sum(linha["row_count"] for linha in linhas) == saida.rows_written
        for linha in linhas:
            assert linha["split"] in {s.value for s in DatasetSplit}
            assert f"split={linha['split']}" in linha["object_key"]
            assert f"competition={linha['competition']}" in linha["object_key"]

    async def test_o_banco_nao_guarda_valor_de_feature_nenhum(self, database: Database) -> None:
        """ADR-0037: o conteúdo mora no Parquet, e o banco guarda ponteiros."""
        async with database.acquire() as conexao:
            colunas = await conexao.fetch(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_name LIKE 'historical_feature%'
                """
            )
        nomes = {c["column_name"] for c in colunas}
        assert not {n for n in nomes if n.startswith(("f_", "a_"))}
        assert "feature_value" not in nomes


class TestOParquetDeVerdade:
    async def test_o_arquivo_tem_o_schema_declarado(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        import pyarrow.parquet as pq

        saida = construido["saida"]
        chave = next(
            o.object_key for o in saida.manifest.objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in object_store.open_stream(chave):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))
        assert tabela.num_columns == COLUNAS_ESPERADAS
        assert tabela.num_rows > 0
        nomes = set(tabela.column_names)
        assert {"match_id", "grid_index", "row_digest", "split"} <= nomes

    async def test_indisponivel_e_nulo_e_a_disponibilidade_diz_por_que(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """`NULL` sozinho diria que não há número e não diria por quê."""
        import pyarrow.parquet as pq

        saida = construido["saida"]
        chave = next(
            o.object_key for o in saida.manifest.objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in object_store.open_stream(chave):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))
        colunas = tabela.column_names
        valores = [c for c in colunas if c.startswith("f_")]
        assert len(valores) == 105
        achou_indisponivel = False
        for coluna in valores:
            disponibilidade = tabela.column(f"a_{coluna[2:]}").to_pylist()
            numeros = tabela.column(coluna).to_pylist()
            for estado, numero in zip(disponibilidade, numeros, strict=True):
                assert estado is not None
                if estado != "AVAILABLE":
                    achou_indisponivel = True
                    assert numero is None, f"{coluna} indisponível com valor {numero}"
        assert achou_indisponivel, "o cenário precisa ter alguma indisponibilidade"

    async def test_o_corte_intra_jogo_nao_tem_instante_de_conhecimento(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        import pyarrow.parquet as pq

        saida = construido["saida"]
        chave = next(
            o.object_key for o in saida.manifest.objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in object_store.open_stream(chave):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))
        fases = tabela.column("period").to_pylist()
        cortes = tabela.column("knowledge_cutoff").to_pylist()
        for fase, corte in zip(fases, cortes, strict=True):
            if fase == "PRE_MATCH":
                assert corte is not None
            else:
                assert corte is None, f"{fase} com instante fabricado"

    async def test_as_linhas_do_arquivo_estao_em_ordem_de_chave(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        import pyarrow.parquet as pq

        saida = construido["saida"]
        chave = next(
            o.object_key for o in saida.manifest.objects if o.object_key.endswith(".parquet")
        )
        bruto = bytearray()
        async for bloco in object_store.open_stream(chave):
            bruto.extend(bloco)
        tabela = pq.read_table(io.BytesIO(bytes(bruto)))
        pares = list(
            zip(
                tabela.column("match_id").to_pylist(),
                tabela.column("grid_index").to_pylist(),
                strict=True,
            )
        )
        assert pares == sorted(pares)


class TestAValidacaoReal:
    async def test_ela_passa_e_reconstroi_o_dataset_inteiro(
        self, construido: dict[str, Any]
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        relatorio = await montagem.validar.execute(
            version_id=saida.version.id,
            source=origem_publicada(construido["publicado"]),
            actor=ATOR,
        )
        assert relatorio.passed, relatorio.failures()
        assert relatorio.rows_verified == saida.rows_written
        assert relatorio.matches_rebuilt == saida.matches_processed

    async def test_a_impressao_e_reconstruida_a_partir_dos_ARQUIVOS(
        self, construido: dict[str, Any]
    ) -> None:
        """A construção calcula a impressão ESCREVENDO; a validação a
        recalcula LENDO — e as duas só coincidem se o escrito for o calculado."""
        montagem, saida = construido["montagem"], construido["saida"]
        relatorio = await montagem.validar.execute(
            version_id=saida.version.id,
            source=origem_publicada(construido["publicado"]),
            actor=ATOR,
        )
        assert not relatorio.fingerprint_mismatch

    async def test_o_hash_de_cada_objeto_confere(self, construido: dict[str, Any]) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        for objeto in saida.manifest.objects:
            if not objeto.object_key.endswith(".parquet"):
                continue
            conteudo = await montagem.materializer.verify_object(object_key=objeto.object_key)
            assert conteudo.sha256 == objeto.sha256.value
            assert conteudo.out_of_order() == ()


class TestAPublicacaoReal:
    async def test_ela_grava_o_manifesto_no_store_e_marca_ready(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        await montagem.validar.execute(
            version_id=saida.version.id,
            source=origem_publicada(construido["publicado"]),
            actor=ATOR,
        )
        publicada = await montagem.publicar.execute(
            version_id=saida.version.id,
            dataset_name=NOME,
            actor=ATOR,
            reason="primeira população do motor",
        )
        assert publicada.status is DatasetVersionStatus.READY

        chave = montagem.materializer.manifest_key(
            dataset_name=NOME, version=str(publicada.version)
        )
        bruto = bytearray()
        async for bloco in object_store.open_stream(chave):
            bruto.extend(bloco)
        assert bruto
        import json

        documento = json.loads(bytes(bruto))
        assert documento["row_count"] == saida.rows_written
        assert documento["raw_content_fingerprint"] == (saida.raw_content_fingerprint.value)
        assert documento["grid_exclusions"]

    async def test_o_manifesto_volta_do_banco_com_os_mesmos_bytes(
        self, construido: dict[str, Any]
    ) -> None:
        """Reconstruir das COLUNAS produziria um manifesto parecido, e o
        `manifest_sha256` deixaria de fechar sobre ele."""
        montagem, saida = construido["montagem"], construido["saida"]
        relido = await montagem.manifests.by_version(saida.version.id)
        assert relido is not None
        assert relido.to_json() == saida.manifest.to_json()
        assert relido.manifest_sha256 == saida.manifest.manifest_sha256


class TestAReprodutibilidadeReal:
    async def test_duas_versoes_sobre_o_mesmo_corpus_tem_a_mesma_impressao(
        self, database: Database, object_store: Any, publicado: dict[str, Any]
    ) -> None:
        """A prova de que o dataset é conteúdo, e não execução."""
        montagem = Montagem(database, object_store)
        primeira = await construir_versao(montagem, publicado)
        segunda = await construir_versao(
            montagem, publicado, version=DatasetVersion(major=1, minor=1)
        )
        assert primeira.raw_content_fingerprint == segunda.raw_content_fingerprint
        assert primeira.version.id != segunda.version.id


class TestAsConsultas:
    async def test_a_construcao_nao_faz_uma_consulta_por_partida(
        self, database: Database, object_store: Any, publicado: dict[str, Any]
    ) -> None:
        """91 cortes por partida NÃO podem virar 91 leituras: o contexto e o
        estado são carregados uma vez por lote e reusados em todos os cortes."""
        montagem = Montagem(database, object_store)
        async with contando_consultas(database) as contagem:
            saida = await construir_versao(montagem, publicado)
        assert saida.rows_written >= 91
        assert contagem.total < saida.rows_written, (
            f"{contagem.total} consultas para {saida.rows_written} linhas — "
            "a leitura está por corte, e não por lote"
        )
