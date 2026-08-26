"""A ida e a volta pelo Parquet — o que sobrevive ao arquivo, e com qual tipo.

POR QUE ESTE ARQUIVO EXISTE SEPARADO DO E2E. O corpus do E2E não publica `ODDS`
nem `LINEUP`, então nele as vinte e uma dimensões de mercado saem indisponíveis
— e é justamente o mercado que carrega os números com casas decimais que este
PR precisa provar que atravessam o arquivo intactos. O cenário da V2 tem
cotações com mediana e IQR CONFERIDOS À MÃO, e é sobre ele que a prova vale.

O QUE ELE PROVA:

    o VALOR volta EXATAMENTE igual        bit a bit, e não «aproximadamente»
    a mediana de mercado volta 1,95       o número do `v2_fixtures`, conferido
                                          à mão pelo método declarado
    o IQR volta 0,15                      idem — e não 0,20, que é o que a
                                          convenção exclusiva daria
    as DISPONIBILIDADES voltam distintas  e não como um `NULL` indistinto
    o SCHEMA é o declarado                233 colunas, tipadas pelo catálogo

SOBRE `Decimal`, E A RESPOSTA HONESTA. O motor calcula quantis, consenso e
intervalo de calendário em `Decimal` EXATO (PR-05.4, ADR-0034). Na fronteira do
`FeatureValue` — que é anterior a este PR e guarda `float` — o valor vira
`float`. O Parquet grava `float64`, que é o MESMO tipo: a materialização não
acrescenta coerção nem perda, e a leitura devolve o mesmo número. O que este
arquivo confere é exatamente isso, e não uma coluna `decimal128` que não existe.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    canonical_kickoff,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.historical.features.materializer import (
    AVAILABILITY_PREFIX,
    COLUNAS_ESPERADAS_NOTA,
    VALUE_PREFIX,
    ParquetFeatureDatasetMaterializer,
)
from tests.support.dataset_fixtures import apito_de, corpus_do_cenario
from tests.support.v2_fixtures import (
    IQR_ESPERADO,
    MEDIANA_ESPERADA,
    extrair_v2,
)

CATALOGO = extended_feature_catalog()
DEFINICOES = CATALOGO.definitions

#: As chaves das três dimensões do 1X2 mandante — as que o cenário confere.
CHAVE_MEDIANA = "market_1x2_home_median"
CHAVE_IQR = "market_1x2_home_iqr"
CHAVE_SUPORTE = "market_1x2_home_support"


def _linhas_do_cenario() -> list[MaterializedFeatureRow]:
    """A partida do cenário V2 na grade inteira, pronta para virar arquivo."""
    corpus = corpus_do_cenario(partidas=1)
    identificador, entrada = next(iter(corpus.items()))
    apito = canonical_kickoff(entrada.match)
    linhas: list[MaterializedFeatureRow] = []
    for ponto in DEFAULT_SNAPSHOT_GRID.points_for(identificador, kickoff=apito):
        # SEM CONTEXTO: o contexto do `v2_fixtures` está preso à partida de
        # referência dele, e o que este arquivo mede é a ida e a volta pelo
        # Parquet — não a leitura de calendário.
        snapshot = extrair_v2(entrada, as_of=ponto.as_of, sem_contexto=True)
        linhas.append(
            MaterializedFeatureRow(
                key=HistoricalFeatureSnapshotKey.of(identificador, grid_index=ponto.index),
                snapshot=snapshot,
                split=DatasetSplit.REFERENCE,
                competition_code=entrada.competition_code,
                season_label=entrada.season_label,
                kickoff=apito,
                grid_label=ponto.label,
            )
        )
    return linhas


async def _ida_e_volta(tmp_path: Path) -> tuple[Any, list[MaterializedFeatureRow]]:
    """Escreve as linhas num Parquet de verdade e lê a tabela de volta."""
    import pyarrow.parquet as pq

    store = FilesystemObjectStore(tmp_path / "features")
    materializador = ParquetFeatureDatasetMaterializer(store, definitions=DEFINICOES)
    linhas = _linhas_do_cenario()
    objeto = await materializador.materialize_partition(
        dataset_name="teste",
        version="v1.0",
        split=DatasetSplit.REFERENCE,
        competition="PREMIER_LEAGUE",
        season="2025/26",
        part_index=0,
        rows=linhas,
    )
    assert objeto is not None
    bruto = bytearray()
    async for bloco in store.open_stream(objeto.object_key):
        bruto.extend(bloco)
    return pq.read_table(io.BytesIO(bytes(bruto))), linhas


@pytest.fixture
async def arquivo(tmp_path: Path) -> tuple[Any, list[MaterializedFeatureRow]]:
    return await _ida_e_volta(tmp_path)


class TestOsValoresAtravessamOArquivo:
    async def test_todo_valor_volta_EXATAMENTE_igual(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """Bit a bit, e não «aproximadamente»: o domínio guarda `float` e o
        arquivo grava `float64`, então não há conversão no meio."""
        tabela, linhas = arquivo
        conferidos = 0
        for indice, linha in enumerate(linhas):
            calculados = {f.definition_key: f.numeric for f in linha.snapshot.features}
            for definicao in DEFINICOES:
                lido = tabela.column(f"{VALUE_PREFIX}{definicao.key}")[indice].as_py()
                esperado = calculados[definicao.key]
                assert lido == esperado, (definicao.key, lido, esperado)
                conferidos += 1
        assert conferidos == len(linhas) * len(DEFINICOES)

    async def test_a_mediana_de_mercado_volta_com_as_casas_decimais(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§50. `1.95` é o número conferido à mão em `v2_fixtures` pelo método
        `LINEAR_INTERPOLATED_QUANTILE_V1`, calculado em `Decimal` exato."""
        tabela, _ = arquivo
        valores = [
            v for v in tabela.column(f"{VALUE_PREFIX}{CHAVE_MEDIANA}").to_pylist() if v is not None
        ]
        assert valores, "o cenário precisa ter mercado disponível em algum corte"
        for lido in valores:
            assert Decimal(str(lido)) == MEDIANA_ESPERADA

    async def test_o_iqr_de_mercado_volta_com_as_casas_decimais(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§50. `0.15` — e NÃO `0.20`, que é o que a convenção exclusiva daria.
        A diferença é o §61 do PR-05.4, e ela sobrevive ao arquivo."""
        tabela, _ = arquivo
        valores = [
            v for v in tabela.column(f"{VALUE_PREFIX}{CHAVE_IQR}").to_pylist() if v is not None
        ]
        assert valores
        for lido in valores:
            assert Decimal(str(lido)) == IQR_ESPERADO

    async def test_o_suporte_volta_como_INTEIRO(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """Quatro casas de aposta são quatro, e não `4.0`: a coluna é `int64`
        porque a definição declara `INTEGER`."""
        import pyarrow as pa

        tabela, _ = arquivo
        campo = tabela.schema.field(f"{VALUE_PREFIX}{CHAVE_SUPORTE}")
        assert campo.type == pa.int64()
        valores = [
            v for v in tabela.column(f"{VALUE_PREFIX}{CHAVE_SUPORTE}").to_pylist() if v is not None
        ]
        assert valores
        assert all(isinstance(v, int) for v in valores)
        assert set(valores) == {4}

    async def test_o_xg_volta_com_as_seis_casas(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§50. O xG é quantizado em `Decimal` a seis casas (PR-05.3) antes de
        virar `float`; a ida e a volta não mexem no número."""
        tabela, linhas = arquivo
        chaves = [d.key for d in DEFINICOES if d.key.startswith("xg_")]
        assert chaves
        achou = False
        for indice, linha in enumerate(linhas):
            calculados = {f.definition_key: f.numeric for f in linha.snapshot.features}
            for chave in chaves:
                lido = tabela.column(f"{VALUE_PREFIX}{chave}")[indice].as_py()
                if lido is None:
                    continue
                achou = True
                assert Decimal(str(lido)) == Decimal(str(calculados[chave]))
        assert achou, "o cenário precisa ter xG disponível em algum corte"

    async def test_o_digesto_gravado_e_o_digesto_da_linha(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        tabela, linhas = arquivo
        gravados = tabela.column("row_digest").to_pylist()
        assert gravados == [linha.digest for linha in linhas]


class TestAsDisponibilidadesAtravessamOArquivo:
    async def test_os_estados_voltam_DISTINTOS_e_nunca_nulos(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§52, §58. «A fonte não declara» e «o corte proibiu» exigem ações
        diferentes; um `NULL` indistinto apagaria a diferença.

        O CONJUNTO É AFIRMADO POR EXTENSO, e não por um «pelo menos três».
        Estes são os quatro estados que ESTE cenário produz, e o teste quebra
        se um deles sumir — que é o alarme que se quer quando um refactor
        colapsa duas causas numa.

            AVAILABLE               o número existe
            SOURCE_UNAVAILABLE      a família veio e o fato não
            TEMPORALLY_UNAVAILABLE  o corte proibiu — com motivo no mapa
            INSUFFICIENT_COVERAGE   o corpus não alcança a janela

        OS OUTROS QUATRO NÃO APARECEM AQUI, e cada ausência tem causa:
        `NOT_DECLARED` exige um corpus sem a família (é o do E2E, e lá ele
        aparece); `PARTIAL_INPUT` exige finalização sem xG publicado;
        `NOT_APPLICABLE` e `BLOCKED_BY_POLICY` não têm produtor no
        `MATCH_STATE_RAW_V2`. Fingir que este cenário os cobre seria pior que
        dizer que não cobre.
        """
        tabela, _ = arquivo
        estados: set[str] = set()
        for definicao in DEFINICOES:
            coluna = tabela.column(f"{AVAILABILITY_PREFIX}{definicao.key}").to_pylist()
            assert None not in coluna, definicao.key
            estados.update(coluna)
        assert estados == {
            "AVAILABLE",
            "SOURCE_UNAVAILABLE",
            "TEMPORALLY_UNAVAILABLE",
            "INSUFFICIENT_COVERAGE",
        }, estados

    async def test_o_motivo_da_recusa_temporal_e_nomeado(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§59. `NULL` com `TEMPORALLY_UNAVAILABLE` ainda não basta: qual
        guarda recusou é a diferença entre revisar o corte e revisar a fonte."""
        tabela, _ = arquivo
        motivos: set[str] = set()
        for mapa in tabela.column("unavailable_reasons").to_pylist():
            motivos.update(dict(mapa or []).values())
        assert motivos == {"MISSING_KNOWLEDGE_CUTOFF"}, motivos

    async def test_cada_estado_lido_e_o_estado_calculado(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        tabela, linhas = arquivo
        for indice, linha in enumerate(linhas):
            calculados = {f.definition_key: f.availability.value for f in linha.snapshot.features}
            for definicao in DEFINICOES:
                lido = tabela.column(f"{AVAILABILITY_PREFIX}{definicao.key}")[indice].as_py()
                assert lido == calculados[definicao.key], definicao.key

    async def test_os_motivos_de_recusa_temporal_voltam_no_mapa(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        tabela, linhas = arquivo
        lidos = tabela.column("unavailable_reasons").to_pylist()
        for indice, linha in enumerate(linhas):
            assert dict(lidos[indice] or []) == linha.unavailable_reasons()

    async def test_indisponivel_e_sempre_nulo(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§51 — e o contrário também: disponível NUNCA é nulo."""
        tabela, _linhas = arquivo
        for definicao in DEFINICOES:
            estados = tabela.column(f"{AVAILABILITY_PREFIX}{definicao.key}").to_pylist()
            valores = tabela.column(f"{VALUE_PREFIX}{definicao.key}").to_pylist()
            for estado, valor in zip(estados, valores, strict=True):
                if estado == "AVAILABLE":
                    assert valor is not None, definicao.key
                else:
                    assert valor is None, (definicao.key, estado, valor)


class TestOSchemaDeclarado:
    async def test_o_numero_de_colunas_e_o_declarado(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        tabela, _ = arquivo
        assert tabela.num_columns == COLUNAS_ESPERADAS_NOTA
        assert len(set(tabela.column_names)) == tabela.num_columns

    async def test_cada_definicao_tem_UMA_coluna_de_valor_e_UMA_de_estado(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        tabela, _ = arquivo
        nomes = set(tabela.column_names)
        for definicao in DEFINICOES:
            assert f"{VALUE_PREFIX}{definicao.key}" in nomes
            assert f"{AVAILABILITY_PREFIX}{definicao.key}" in nomes
        assert len([n for n in nomes if n.startswith(VALUE_PREFIX)]) == 105
        assert len([n for n in nomes if n.startswith(AVAILABILITY_PREFIX)]) == 105

    async def test_o_tipo_de_cada_coluna_vem_da_DEFINICAO(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """O schema é derivado do catálogo, e nunca inferido do primeiro lote."""
        import pyarrow as pa

        from sports_intelligence.domain.features.definitions import FeatureOutputType

        tabela, _ = arquivo
        esperado = {
            FeatureOutputType.INTEGER: pa.int64(),
            FeatureOutputType.FLOAT: pa.float64(),
            FeatureOutputType.BOOLEAN: pa.bool_(),
        }
        for definicao in DEFINICOES:
            campo = tabela.schema.field(f"{VALUE_PREFIX}{definicao.key}")
            assert campo.type == esperado[definicao.output_type], definicao.key

    async def test_o_corte_pre_jogo_tem_instante_e_o_intra_jogo_nao(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§38 — nada de `kickoff + minuto` fabricado."""
        tabela, _ = arquivo
        fases = tabela.column("period").to_pylist()
        cortes = tabela.column("knowledge_cutoff").to_pylist()
        assert fases[0] == "PRE_MATCH"
        assert cortes[0] == apito_de(0)
        for fase, corte in zip(fases[1:], cortes[1:], strict=True):
            assert fase != "PRE_MATCH"
            assert corte is None

    async def test_nenhum_corte_tem_acrescimo_no_arquivo(
        self, arquivo: tuple[Any, list[MaterializedFeatureRow]]
    ) -> None:
        """§37 — o acréscimo fica fora da materialização sistemática."""
        tabela, _ = arquivo
        minutos = tabela.column("minute").to_pylist()
        fases = tabela.column("period").to_pylist()
        assert minutos == [0, *range(1, 91)]
        assert fases.count("FIRST_HALF") == 45
        assert fases.count("SECOND_HALF") == 45
