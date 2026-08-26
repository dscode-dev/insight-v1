"""A CADEIA DE INTEGRIDADE do PR-05.5.1, conferida ponta a ponta.

    FeatureSnapshot → MaterializedRow → Parquet → ObjectMetadata → Manifest

O QUE ESTE ARQUIVO PROVA, e nenhum outro prova: que a cadeia é **reversível
semanticamente**. Cada elo é reconstruído a partir do elo seguinte e comparado
com o que foi gravado:

    o DIGESTO DE CADA LINHA         recomputado LENDO O PARQUET, e mais nada
    a IMPRESSÃO DE CONTEÚDO         recomposta dos objetos, comparada ao banco
                                    E ao manifesto
    os VALORES                      lidos de volta e comparados aos calculados
    as DISPONIBILIDADES             sete estados distintos que sobrevivem ao
                                    arquivo, e não viram um `NULL` indistinto
    os OBJETOS                      SHA-256 dos bytes REAIS do object store
    as CONTAGENS                    manifesto = banco = linhas de Parquet

A RECONSTRUÇÃO DO DIGESTO É FEITA AQUI, e não chamando o domínio. É de
propósito: o que se afirma é «esta linha é reconstrutível a partir do arquivo»,
e chamar `MaterializedFeatureRow.digest` provaria apenas que o domínio concorda
consigo mesmo. O leitor deste arquivo é uma segunda implementação da mesma
forma canônica — se as duas divergirem, o teste quebra, que é o objetivo.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid as _uuid
from decimal import Decimal
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID
from sports_intelligence.domain.features.dataset.rows import (
    ROW_DIGEST_ALGORITHM,
    HistoricalFeatureSnapshotKey,
    rebuild_content_fingerprint,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.domain.shared.canonical import (
    canonical_json,
    decimal_text,
    instant_text,
)
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    EngineError,
    ValidationError,
)
from sports_intelligence.historical.features.materializer import (
    AVAILABILITY_PREFIX,
    VALUE_PREFIX,
)
from tests.support.dataset_e2e import (
    ATOR,
    COLUNAS_ESPERADAS,
    NOME,
    construir_versao,
    origem_publicada,
)

pytestmark = pytest.mark.integration

#: As 105 definições da V2. O schema do arquivo é derivado delas.
DEFINICOES = extended_feature_catalog().definitions


async def _tabela(object_store: Any, chave: str) -> Any:
    import pyarrow.parquet as pq

    bruto = bytearray()
    async for bloco in object_store.open_stream(chave):
        bruto.extend(bloco)
    return pq.read_table(io.BytesIO(bytes(bruto)))


async def _bytes_do_objeto(object_store: Any, chave: str) -> bytes:
    bruto = bytearray()
    async for bloco in object_store.open_stream(chave):
        bruto.extend(bloco)
    return bytes(bruto)


def _parquets(saida: Any) -> list[Any]:
    return [o for o in saida.manifest.objects if o.object_key.endswith(".parquet")]


def _linhas_do_arquivo(tabela: Any) -> list[dict[str, Any]]:
    """As linhas do Parquet como dicionários, coluna a coluna."""
    colunas = {nome: tabela.column(nome).to_pylist() for nome in tabela.column_names}
    return [{nome: valores[i] for nome, valores in colunas.items()} for i in range(tabela.num_rows)]


def _digesto_reconstruido(linha: dict[str, Any]) -> str:
    """O digesto da linha, recomposto SÓ com o que está no arquivo.

    ESTA É UMA SEGUNDA IMPLEMENTAÇÃO da forma canônica de
    `MaterializedFeatureRow`, e é o que dá valor ao teste: se o domínio mudar a
    forma sem que este leitor mude junto, a divergência aparece aqui — que é
    exatamente o alarme que se quer quando o formato de um arquivo publicado
    muda de significado.
    """
    valores: dict[str, str | None] = {}
    disponibilidades: dict[str, str] = {}
    for definicao in DEFINICOES:
        numero = linha[f"{VALUE_PREFIX}{definicao.key}"]
        valores[definicao.key] = None if numero is None else decimal_text(Decimal(str(numero)))
        disponibilidades[definicao.key] = linha[f"{AVAILABILITY_PREFIX}{definicao.key}"]

    corte = linha["knowledge_cutoff"]
    forma = {
        "algorithm": ROW_DIGEST_ALGORITHM,
        "as_of": {
            "knowledge_cutoff": None if corte is None else instant_text(corte),
            "match_id": linha["match_id"],
            "mode": linha["temporal_mode"],
            "position": {
                "minute": linha["minute"],
                "period": linha["period"],
                # A GRADE NUNCA DECLARA DESEMPATE, e por isso `sequence` é
                # sempre nulo na forma canônica de um corte materializado.
                "sequence": None,
                # E NUNCA TEM ACRÉSCIMO: o corpus não publica a duração dele.
                "stoppage": 0,
            },
        },
        "availability": disponibilidades,
        "competition_code": linha["competition"],
        "feature_space": {
            "fingerprint": linha["space_fingerprint"],
            "name": linha["space_name"],
            "version": linha["space_version"],
        },
        "grid_index": linha["grid_index"],
        "grid_label": linha["grid_label"],
        "kickoff": instant_text(linha["kickoff"]),
        "match_id": linha["match_id"],
        "season_label": linha["season"],
        "snapshot_fingerprint": linha["snapshot_fingerprint"],
        "split": linha["split"],
        "state_issue_count": linha["state_issue_count"],
        "temporal_policy": {
            "fingerprint": linha["policy_fingerprint"],
            "version": linha["policy_version"],
        },
        "unavailable_reasons": dict(linha["unavailable_reasons"] or []),
        "values": valores,
    }
    return hashlib.sha256(canonical_json(forma)).hexdigest()


# ==================================================== digesto e impressão ==


class TestOsDigestosDeLinha:
    """§44, §63, §64. TODAS as linhas do E2E pequeno, e não uma amostra."""

    async def test_todo_digesto_e_reconstrutivel_do_arquivo(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        conferidas = 0
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                assert _digesto_reconstruido(linha) == linha["row_digest"], (
                    f"{linha['match_id']}#{linha['grid_index']}"
                )
                conferidas += 1
        assert conferidas == saida.rows_written
        assert conferidas > 0

    async def test_o_digesto_muda_se_um_valor_do_arquivo_mudar(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """A prova de que o digesto cobre os VALORES, e não só as coordenadas."""
        saida = construido["saida"]
        tabela = await _tabela(object_store, _parquets(saida)[0].object_key)
        linha = _linhas_do_arquivo(tabela)[0]
        coluna = next(
            f"{VALUE_PREFIX}{d.key}"
            for d in DEFINICOES
            if linha[f"{VALUE_PREFIX}{d.key}"] is not None
        )
        adulterada = {**linha, coluna: (linha[coluna] or 0) + 7}
        assert _digesto_reconstruido(adulterada) != linha["row_digest"]

    async def test_o_digesto_muda_se_uma_disponibilidade_mudar(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        tabela = await _tabela(object_store, _parquets(saida)[0].object_key)
        linha = _linhas_do_arquivo(tabela)[0]
        chave = f"{AVAILABILITY_PREFIX}{DEFINICOES[0].key}"
        outro = "SOURCE_UNAVAILABLE" if linha[chave] != "SOURCE_UNAVAILABLE" else "AVAILABLE"
        assert _digesto_reconstruido({**linha, chave: outro}) != linha["row_digest"]


class TestAImpressaoDeConteudo:
    """§43, §81. Recomposta dos ARQUIVOS, comparada ao banco e ao manifesto."""

    async def test_a_impressao_recomposta_bate_com_o_banco_e_com_o_manifesto(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        pares: list[tuple[HistoricalFeatureSnapshotKey, str]] = []
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                pares.append(
                    (
                        HistoricalFeatureSnapshotKey(
                            match_key=linha["match_id"],
                            grid_index=int(linha["grid_index"]),
                        ),
                        linha["row_digest"],
                    )
                )
        pares.sort(key=lambda par: par[0])
        spec = saida.version.spec
        recomposta = rebuild_content_fingerprint(
            pares,
            space_name=spec.space_name,
            space_version=spec.space_version,
            grid_fingerprint=spec.grid_fingerprint,
            split_fingerprint=spec.split_fingerprint,
        )
        no_banco = await montagem.repo.version_by_id(saida.version.id)
        assert no_banco is not None
        assert no_banco.raw_content_fingerprint is not None
        assert recomposta == no_banco.raw_content_fingerprint.value
        assert recomposta == saida.manifest.raw_content_fingerprint.value

    async def test_as_chaves_de_snapshot_sao_unicas_na_versao(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§46 — `(metade, partida, corte)` uma vez só."""
        saida = construido["saida"]
        chaves: list[tuple[str, str, int]] = []
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                chaves.append((linha["split"], linha["match_id"], int(linha["grid_index"])))
        assert len(set(chaves)) == len(chaves) == saida.rows_written


# ================================================== valores e semântica ==


class TestOsValoresSobrevivemAoArquivo:
    """§50, §51, §52."""

    async def test_o_valor_lido_e_exatamente_o_valor_calculado(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """A ida e a volta não podem mexer no número.

        SOBRE `Decimal`: o domínio guarda todo valor de feature como `float`
        (`FeatureValue._value`), inclusive xG, mediana e IQR de mercado. O
        Parquet grava `float64` — o MESMO tipo —, então a leitura devolve
        bit a bit o que foi gravado. Não há coerção nem perda; o que NÃO existe
        é um `Decimal` no meio do caminho, e este teste confere a igualdade
        exata em vez de fingir que existe.
        """
        saida = construido["saida"]
        # A CONFERÊNCIA É CONTRA O DIGESTO, que já cobre os valores: se um
        # número tivesse mudado na ida e na volta, a reconstrução do digesto
        # feita a partir do arquivo não fecharia com a coluna gravada.
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                assert _digesto_reconstruido(linha) == linha["row_digest"]

    async def test_indisponivel_e_sempre_nulo_e_disponivel_nunca_e(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§51 — o contrato, conferido linha a linha e coluna a coluna."""
        saida = construido["saida"]
        disponiveis = indisponiveis = 0
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                for definicao in DEFINICOES:
                    estado = linha[f"{AVAILABILITY_PREFIX}{definicao.key}"]
                    numero = linha[f"{VALUE_PREFIX}{definicao.key}"]
                    if estado == "AVAILABLE":
                        assert numero is not None, definicao.key
                        disponiveis += 1
                    else:
                        assert numero is None, f"{definicao.key}={numero} sob {estado}"
                        indisponiveis += 1
        assert disponiveis > 0
        assert indisponiveis > 0

    async def test_os_estados_de_indisponibilidade_sobrevivem_distintos(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§52 — «a fonte não publica» e «o corte proibiu» exigem ações
        diferentes, e um `NULL` indistinto apagaria a diferença."""
        saida = construido["saida"]
        estados: set[str] = set()
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for definicao in DEFINICOES:
                estados.update(tabela.column(f"{AVAILABILITY_PREFIX}{definicao.key}").to_pylist())
        assert None not in estados
        # O CONJUNTO É AFIRMADO POR EXTENSO, e ele é DIFERENTE do cenário em
        # memória — de propósito, porque os dois corpus são diferentes:
        #
        #     NOT_DECLARED           este corpus não publica `LINEUP` nem
        #                            `ODDS`; o cenário em memória publica
        #     INSUFFICIENT_COVERAGE  o contexto não alcança a janela
        #     SOURCE_UNAVAILABLE     a família veio e o fato não
        #
        # `TEMPORALLY_UNAVAILABLE` NÃO APARECE AQUI, e a ausência tem causa: a
        # recusa temporal do cenário em memória é sobre COTAÇÕES, e este corpus
        # não tem nenhuma para recusar. Um estado que sumisse por refactor —
        # em vez de por ausência de fato — quebra este teste.
        assert estados == {
            "AVAILABLE",
            "NOT_DECLARED",
            "SOURCE_UNAVAILABLE",
            "INSUFFICIENT_COVERAGE",
        }, estados

    async def test_o_motivo_de_recusa_temporal_viaja_no_mapa(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for linha in _linhas_do_arquivo(tabela):
                motivos = dict(linha["unavailable_reasons"] or [])
                for chave, motivo in motivos.items():
                    estado = linha[f"{AVAILABILITY_PREFIX}{chave}"]
                    assert estado == "TEMPORALLY_UNAVAILABLE", (chave, estado)
                    assert motivo


# ============================================================== o schema ==


class TestOSchemaDoArquivo:
    """§47, §48, §49."""

    async def test_todo_objeto_tem_o_MESMO_schema(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        schemas = set()
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            schemas.add(str(tabela.schema))
        assert len(schemas) == 1

    async def test_as_105_features_aparecem_exatamente_uma_vez(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        tabela = await _tabela(object_store, _parquets(saida)[0].object_key)
        nomes = list(tabela.column_names)
        assert len(nomes) == len(set(nomes)) == COLUNAS_ESPERADAS
        valores = [n for n in nomes if n.startswith(VALUE_PREFIX)]
        estados = [n for n in nomes if n.startswith(AVAILABILITY_PREFIX)]
        assert len(valores) == len(estados) == len(DEFINICOES) == 105
        assert {n[len(VALUE_PREFIX) :] for n in valores} == {d.key for d in DEFINICOES}
        assert {n[len(AVAILABILITY_PREFIX) :] for n in estados} == {d.key for d in DEFINICOES}

    async def test_a_disponibilidade_nunca_e_nula_no_schema(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        tabela = await _tabela(object_store, _parquets(saida)[0].object_key)
        for definicao in DEFINICOES:
            campo = tabela.schema.field(f"{AVAILABILITY_PREFIX}{definicao.key}")
            assert not campo.nullable, definicao.key


# ================================================= objetos e manifesto ==


class TestAIntegridadeDosObjetos:
    """§53, §55, §56, §57, §58."""

    async def test_o_sha_do_banco_bate_com_os_BYTES_REAIS_do_store(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        registrados = await montagem.builds.objects_of(saida.version.id)
        assert registrados
        for objeto in registrados:
            bruto = await _bytes_do_objeto(object_store, objeto.object_key)
            assert hashlib.sha256(bruto).hexdigest() == objeto.sha256.value
            assert len(bruto) == objeto.size_bytes

    async def test_manifesto_e_banco_declaram_os_MESMOS_objetos(
        self, construido: dict[str, Any]
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        no_banco = {o.object_key: o for o in await montagem.builds.objects_of(saida.version.id)}
        no_manifesto = {o.object_key: o for o in _parquets(saida)}
        assert set(no_banco) == set(no_manifesto)
        for chave, objeto in no_manifesto.items():
            assert no_banco[chave].sha256 == objeto.sha256
            assert no_banco[chave].row_count == objeto.row_count
            assert no_banco[chave].split == objeto.split

    async def test_todo_objeto_do_manifesto_EXISTE_no_store(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        saida = construido["saida"]
        for objeto in _parquets(saida):
            bruto = await _bytes_do_objeto(object_store, objeto.object_key)
            assert bruto

    async def test_as_contagens_de_linha_fecham_nos_TRES_lugares(
        self, construido: dict[str, Any], object_store: Any, database: Database
    ) -> None:
        """§57 — manifesto = objetos do banco = linhas REAIS do Parquet."""
        montagem, saida = construido["montagem"], construido["saida"]
        no_manifesto = saida.manifest.row_count
        no_banco = sum(o.row_count for o in await montagem.builds.objects_of(saida.version.id))
        nos_arquivos = 0
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            nos_arquivos += tabela.num_rows
        async with database.acquire() as conexao:
            na_versao = await conexao.fetchval(
                "SELECT row_count FROM historical_feature_dataset_versions WHERE id = $1",
                _uuid.UUID(saida.version.id),
            )
        assert no_manifesto == no_banco == nos_arquivos == na_versao

    async def test_as_contagens_por_METADE_fecham(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§58."""
        saida = construido["saida"]
        por_metade: dict[str, int] = {}
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for metade in tabela.column("split").to_pylist():
                por_metade[metade] = por_metade.get(metade, 0) + 1
        contagens = saida.manifest.counts
        assert por_metade.get("REFERENCE", 0) == contagens.reference_rows
        assert por_metade.get("EVALUATION", 0) == contagens.evaluation_rows
        assert sum(por_metade.values()) == saida.manifest.row_count

    async def test_as_linhas_por_PARTICAO_fecham_com_o_manifesto(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§59, §60."""
        saida = construido["saida"]
        por_particao: dict[str, int] = {}
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            rotulo = f"{objeto.split.value}/{objeto.competition}/{objeto.season}"
            por_particao[rotulo] = por_particao.get(rotulo, 0) + tabela.num_rows
        assert por_particao == saida.manifest.rows_by_partition

    async def test_o_resumo_de_disponibilidade_fecha_com_as_linhas(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§62 — recalculado das rows, comparado ao manifesto."""
        saida = construido["saida"]
        contagem: dict[str, int] = {}
        total = 0
        for objeto in _parquets(saida):
            tabela = await _tabela(object_store, objeto.object_key)
            for definicao in DEFINICOES:
                for estado in tabela.column(f"{AVAILABILITY_PREFIX}{definicao.key}").to_pylist():
                    contagem[estado] = contagem.get(estado, 0) + 1
                    total += 1
        assert total == saida.manifest.availability.total_values
        assert contagem == saida.manifest.availability.by_state


class TestAsEstatisticasDosObjetos:
    """§83, §84, §87. O tamanho dos arquivos é risco operacional."""

    async def test_a_distribuicao_e_reportada_e_nao_e_um_arquivo_por_partida(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§86 — «uma partida, um objeto» é o problema do arquivo miúdo."""
        saida = construido["saida"]
        objetos = _parquets(saida)
        tamanhos = sorted(o.size_bytes for o in objetos)
        linhas = sorted(o.row_count for o in objetos)
        assert objetos
        assert min(linhas) >= 91, linhas
        print(
            f"\nobjetos={len(objetos)} "
            f"linhas(min/mediana/max)={linhas[0]}/{linhas[len(linhas) // 2]}/{linhas[-1]} "
            f"bytes(min/mediana/max)={tamanhos[0]}/{tamanhos[len(tamanhos) // 2]}/"
            f"{tamanhos[-1]} total={sum(tamanhos)}"
        )

    async def test_a_compressao_e_medida_contra_o_tamanho_LOGICO(
        self, construido: dict[str, Any], object_store: Any
    ) -> None:
        """§87. O tamanho lógico é `linhas x colunas x 8 bytes` — uma
        estimativa DECLARADA, e não uma medida: o Arrow não descomprime para
        um formato de largura fixa, então «descomprimido» é uma convenção."""
        saida = construido["saida"]
        comprimido = sum(o.size_bytes for o in _parquets(saida))
        logico = saida.rows_written * COLUNAS_ESPERADAS * 8
        assert comprimido > 0
        print(
            f"\nlogico~{logico / 1_048_576:.2f} MB | "
            f"Parquet={comprimido / 1_048_576:.2f} MB | "
            f"razao={logico / comprimido:.1f}x | "
            f"bytes/linha={comprimido / saida.rows_written:.0f}"
        )


# ============================================ imutabilidade e corrida ==


class TestAImutabilidadeDaVersaoPublicada:
    """§76, §77."""

    async def _publicar(self, construido: dict[str, Any]) -> Any:
        montagem, saida = construido["montagem"], construido["saida"]
        await montagem.validar.execute(
            version_id=saida.version.id,
            source=origem_publicada(construido["publicado"]),
            actor=ATOR,
        )
        return await montagem.publicar.execute(
            version_id=saida.version.id,
            dataset_name=NOME,
            actor=ATOR,
            reason="gate do PR-05.5.1",
        )

    async def test_uma_versao_READY_nao_aceita_voltar(self, construido: dict[str, Any]) -> None:
        montagem = construido["montagem"]
        publicada = await self._publicar(construido)
        assert publicada.status is DatasetVersionStatus.READY
        for alvo in (
            DatasetVersionStatus.BUILDING,
            DatasetVersionStatus.VALIDATING,
            DatasetVersionStatus.DRAFT,
            DatasetVersionStatus.FAILED,
        ):
            with pytest.raises(ValidationError, match=r"não pode ir para"):
                await montagem.repo.transition(publicada.id, target=alvo, at=montagem.clock.now())

    async def test_publicar_uma_versao_NOVA_nao_toca_a_anterior(
        self, construido: dict[str, Any], database: Database
    ) -> None:
        """§77 — os bytes do manifesto, a impressão e os objetos da 1.0
        continuam sendo os mesmos depois da 1.1."""
        from sports_intelligence.domain.shared.versioning import DatasetVersion

        montagem, publicado_ = construido["montagem"], construido["publicado"]
        primeira = await self._publicar(construido)
        antes = await montagem.manifests.by_version(primeira.id)
        assert antes is not None
        bytes_antes = antes.to_json()
        objetos_antes = [
            (o.object_key, o.sha256.value) for o in await montagem.builds.objects_of(primeira.id)
        ]

        segunda = await construir_versao(
            montagem, publicado_, version=DatasetVersion(major=1, minor=1)
        )
        await montagem.validar.execute(
            version_id=segunda.version.id, source=origem_publicada(publicado_), actor=ATOR
        )
        await montagem.publicar.execute(
            version_id=segunda.version.id,
            dataset_name=NOME,
            actor=ATOR,
            reason="a segunda",
        )

        depois = await montagem.manifests.by_version(primeira.id)
        assert depois is not None
        assert depois.to_json() == bytes_antes
        assert [
            (o.object_key, o.sha256.value) for o in await montagem.builds.objects_of(primeira.id)
        ] == objetos_antes
        relida = await montagem.repo.version_by_id(primeira.id)
        assert relida is not None
        assert relida.raw_content_fingerprint == primeira.raw_content_fingerprint
        assert relida.status is DatasetVersionStatus.SUPERSEDED
        assert relida.superseded_by == segunda.version.id


class TestAConcorrencia:
    """§78. Duas execuções sobre a mesma versão — o PostgreSQL decide."""

    async def test_oito_transicoes_simultaneas_e_uma_so_vence(
        self, construido: dict[str, Any]
    ) -> None:
        """A INVARIANTE É «UMA VENCE», e não «a segunda recebe tal exceção».

        O motor recusa de DOIS jeitos, e os dois são do PostgreSQL:

            a leitura já vê o estado novo   o domínio recusa a transição
            a leitura viu o estado velho    o `UPDATE ... WHERE status = $n`
                                            pega zero linhas e levanta

        Qual dos dois acontece depende do entrelaçamento, e fixar um deles no
        teste o tornaria dependente de escalonamento. O que NÃO pode acontecer,
        e é o que se afirma aqui, é duas vencerem — ou uma sobrescrever a outra
        em silêncio.
        """
        import asyncio

        montagem, saida = construido["montagem"], construido["saida"]
        agora = montagem.clock.now()
        resultados = await asyncio.gather(
            *(
                montagem.repo.transition(
                    saida.version.id,
                    target=DatasetVersionStatus.FAILED,
                    at=agora,
                    failure_reason=f"corredora {n}",
                )
                for n in range(8)
            ),
            return_exceptions=True,
        )
        vencedoras = [r for r in resultados if not isinstance(r, BaseException)]
        recusadas = [r for r in resultados if isinstance(r, EngineError)]
        assert len(vencedoras) == 1, resultados
        assert len(recusadas) == 7, resultados
        # NENHUMA EXCEÇÃO INESPERADA: todas as recusas são do motor, e não um
        # `asyncpg` vazando ou um estado meio gravado.
        assert len(vencedoras) + len(recusadas) == len(resultados)

    async def test_o_estado_final_e_o_da_vencedora_e_nada_ficou_pela_metade(
        self, construido: dict[str, Any]
    ) -> None:
        import asyncio

        montagem, saida = construido["montagem"], construido["saida"]
        agora = montagem.clock.now()
        resultados = await asyncio.gather(
            *(
                montagem.repo.transition(
                    saida.version.id,
                    target=DatasetVersionStatus.FAILED,
                    at=agora,
                    failure_reason=f"corredora {n}",
                )
                for n in range(4)
            ),
            return_exceptions=True,
        )
        vencedora = next(r for r in resultados if not isinstance(r, BaseException))
        relida = await montagem.repo.version_by_id(saida.version.id)
        assert relida is not None
        assert relida.status is DatasetVersionStatus.FAILED
        assert relida.failure_reason == vencedora.failure_reason
        assert relida.raw_content_fingerprint == saida.raw_content_fingerprint

    async def test_a_transicao_e_condicional_ao_estado_anterior_no_SQL(
        self,
    ) -> None:
        """A cláusula que serializa sem Redis existe, e está no `UPDATE`."""
        from tests.support.ast_checks import FONTE

        adaptador = (FONTE / "adapters" / "postgres" / "feature_dataset.py").read_text(
            encoding="utf-8"
        )
        assert "WHERE id = $1 AND status = $14" in adaptador


class TestAGradeNaoPadraoSobreviveAoPostgreSQL:
    """§31. A REGRESSÃO do defeito encontrado no benchmark.

    A `spec` guardava só `(nome, versão, impressão)`. Reconstruir a grade por
    nome trazia os limites PADRÃO — uma grade de cinco cortes voltava com
    noventa e um, e a conferência de impressão acusava sem conseguir consertar.
    Este teste faz a ida e a volta pelo `jsonb` de verdade.
    """

    async def test_uma_grade_de_cinco_cortes_volta_com_CINCO(
        self, database: Database, object_store: Any, publicado: dict[str, Any]
    ) -> None:
        from sports_intelligence.domain.features.dataset.grid import SnapshotGridPolicy
        from sports_intelligence.domain.shared.versioning import DatasetVersion
        from tests.support.dataset_e2e import Montagem, divisao_do_corpus

        reduzida = SnapshotGridPolicy(
            name="E2E_GRADE_CURTA_V1",
            first_half_last_minute=2,
            second_half_last_minute=4,
        )
        assert reduzida.regulation_size == 5

        montagem = Montagem(database, object_store)
        origem = origem_publicada(publicado)
        criada = await montagem.criar.execute(
            dataset_name="grade-curta",
            version=DatasetVersion(major=1, minor=0),
            source_version_id=origem.version_id,
            split=await divisao_do_corpus(database, publicado),
            grid=reduzida,
            actor=ATOR,
        )

        # A IDA E A VOLTA PELO BANCO, antes de construir.
        relida = await montagem.repo.version_by_id(criada.id)
        assert relida is not None
        assert relida.spec.grid == reduzida
        assert relida.spec.grid.regulation_size == 5
        assert relida.spec.grid_fingerprint == reduzida.fingerprint

        saida = await montagem.construir.execute(
            version_id=criada.id,
            source=origem,
            dataset_name="grade-curta",
            actor=ATOR,
        )
        assert saida.rows_written == saida.matches_processed * 5
        assert saida.rows_written < saida.matches_processed * 91

    async def test_a_grade_padrao_continua_com_NOVENTA_E_UM(
        self, construido: dict[str, Any]
    ) -> None:
        """§33 — o contrato da política real: 1 + 45 + 45."""
        saida = construido["saida"]
        assert saida.version.spec.grid == DEFAULT_SNAPSHOT_GRID
        assert saida.version.spec.grid.regulation_size == 91
        assert saida.rows_written == saida.matches_processed * 91


class TestOSpecPersistidoResisteAAdulteracao:
    """§32, contra PostgreSQL de verdade."""

    async def test_uma_coluna_indexada_adulterada_faz_a_leitura_RECUSAR(
        self, construido: dict[str, Any], database: Database
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        async with database.acquire() as conexao:
            await conexao.execute(
                "UPDATE historical_feature_dataset_versions "
                "SET grid_fingerprint = $2 WHERE id = $1",
                _uuid.UUID(saida.version.id),
                "f" * 64,
            )
        with pytest.raises(ConflictError, match="discorda do documento"):
            await montagem.repo.version_by_id(saida.version.id)

    async def test_o_documento_adulterado_tambem_e_RECUSADO(
        self, construido: dict[str, Any], database: Database
    ) -> None:
        montagem, saida = construido["montagem"], construido["saida"]
        documento = saida.version.spec.as_canonical()
        grade = documento["grid"]
        assert isinstance(grade, dict)
        adulterado = {**documento, "grid": {**grade, "second_half_last_minute": 60}}
        async with database.acquire() as conexao:
            await conexao.execute(
                "UPDATE historical_feature_dataset_versions SET spec = $2 WHERE id = $1",
                _uuid.UUID(saida.version.id),
                json.dumps(adulterado, sort_keys=True),
            )
        with pytest.raises(Exception, match="impressão diferente da gravada"):
            await montagem.repo.version_by_id(saida.version.id)
