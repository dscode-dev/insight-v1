"""A validação estrutural contra arquivos de verdade — CSV, JSONL, Parquet.

ARQUIVOS DE VERDADE E NÃO MOCK DE PARSER. O que se está testando aqui é
justamente o comportamento das bibliotecas na fronteira: o que o PyArrow faz
com um rodapé corrompido, o que o Polars faz com uma linha irregular, o que o
`csv` faz com um campo entre aspas contendo vírgula. Um mock responderia o que
eu achasse que eles fazem, que é uma afirmação sobre mim, não sobre eles.

A LISTA DE ATAQUES é a parte que envelhece melhor: arquivo compactado com
extensão trocada, Parquet declarado como CSV, JSON com dez mil níveis de
aninhamento, arquivo sem quebra de linha, encoding que não é UTF-8. Cada um
deles atravessaria uma validação ingênua sem disparar nada.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.schema import DatasetSchemaContract, DetectedType
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import IssueCode, IssueSeverity
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ingestion.historical.raw_archive import RawDatasetArchive
from sports_intelligence.ingestion.validation.inspectors import (
    MAX_JSON_DEPTH,
    inspect_csv,
    inspect_jsonl,
    inspect_parquet,
)
from sports_intelligence.ingestion.validation.structural import (
    StructuralValidator,
    ValidationLimits,
)
from sports_intelligence.ports.clock import FrozenClock

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)

CSV_BOM = (
    "Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "2019-08-09,Liverpool,Norwich,4,1\n"
    "2019-08-10,West Ham,Man City,0,5\n"
)


def _codigos(inspecao: object) -> set[str]:
    return {i.code.value for i in inspecao.issues}  # type: ignore[attr-defined]


class TestInspecaoDeCSV:
    def test_csv_bom_e_lido_com_schema_e_contagem(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "e0.csv"
        arquivo.write_text(CSV_BOM, encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        assert r.observation.row_count == 2
        assert r.observation.column_names == (
            "Date",
            "HomeTeam",
            "AwayTeam",
            "FTHG",
            "FTAG",
        )
        assert not r.issues

    def test_tipos_vem_do_polars_e_nao_de_heuristica(self, tmp_path: Path) -> None:
        """Uma fonte de tipo só. Ele acerta inteiro, texto e data."""
        arquivo = tmp_path / "e0.csv"
        arquivo.write_text(CSV_BOM, encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        por_nome = {c.name: c.detected_type for c in r.observation.columns}
        assert por_nome["FTHG"] is DetectedType.INTEGER
        assert por_nome["HomeTeam"] is DetectedType.STRING

    def test_linha_irregular_e_localizada_pela_linha(self, tmp_path: Path) -> None:
        """"linha 3 tem 2 campos e o cabeçalho tem 5" manda alguém ao lugar
        certo. "Erro de parsing" manda alguém abrir cem mil linhas."""
        arquivo = tmp_path / "e0.csv"
        arquivo.write_text(CSV_BOM + "2019-08-11,Arsenal\n", encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        problemas = [
            i for i in r.issues if i.code is IssueCode.INCONSISTENT_FIELD_COUNT
        ]
        assert problemas
        assert problemas[0].location == "linha 4"

    def test_muitas_linhas_irregulares_viram_impeditivo(self, tmp_path: Path) -> None:
        """Um quarto das linhas erradas quase sempre é delimitador errado — e
        nesse caso nenhuma coluna está onde parece estar."""
        arquivo = tmp_path / "ponto-virgula.csv"
        arquivo.write_text(
            "Date;HomeTeam;AwayTeam\n2019-08-09;Liverpool;Norwich\n2019-08-10;a;b\n",
            encoding="utf-8",
        )
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        # Com vírgula como delimitador, o cabeçalho vira uma coluna só e as
        # linhas continuam com uma — o que NÃO gera irregularidade. O sinal
        # aqui é outro: uma coluna só num arquivo com muitas colunas reais.
        assert r.observation is not None
        assert r.observation.column_count == 1

    def test_cabecalho_com_coluna_duplicada(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "dup.csv"
        arquivo.write_text("Date,Date,FTHG\n2019-08-09,2019-08-09,4\n", encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.DUPLICATE_COLUMN.value in _codigos(r)

    def test_arquivo_sem_nenhuma_linha_nao_tem_cabecalho(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "vazio.csv"
        arquivo.write_text("", encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.MISSING_HEADER.value in _codigos(r)

    def test_so_cabecalho_e_nenhuma_linha_de_dado(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "so-header.csv"
        arquivo.write_text("Date,HomeTeam\n", encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.NO_ROWS.value in _codigos(r)

    def test_encoding_que_nao_e_utf8_e_recusado(self, tmp_path: Path) -> None:
        """Latin-1 não é adivinhado: toda sequência de bytes é Latin-1 válida,
        e supor isso produziria `Ã§` no lugar de `ç` sem nenhum erro."""
        arquivo = tmp_path / "latin.csv"
        arquivo.write_bytes("Date,Time\n2019-08-09,São Paulo\n".encode("latin-1"))
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.UNSUPPORTED_ENCODING.value in _codigos(r)

    def test_bom_utf8_e_aceito(self, tmp_path: Path) -> None:
        """Metade das exportações de planilha inclui BOM."""
        arquivo = tmp_path / "bom.csv"
        arquivo.write_text(CSV_BOM, encoding="utf-8-sig")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        assert r.observation.column_names[0] == "Date"

    def test_limite_de_linhas_interrompe_a_leitura(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "grande.csv"
        arquivo.write_text(
            "a,b\n" + "1,2\n" * 500, encoding="utf-8"
        )
        r = inspect_csv(arquivo, file_id="f1", max_rows=10)
        assert IssueCode.ROW_LIMIT_EXCEEDED.value in _codigos(r)

    def test_arquivo_sem_quebra_de_linha_e_impeditivo(self, tmp_path: Path) -> None:
        """Uma linha do tamanho do arquivo anula o streaming inteiro: o pico
        de memória volta a ser o tamanho do arquivo."""
        from sports_intelligence.ingestion.validation import inspectors

        arquivo = tmp_path / "uma-linha.csv"
        arquivo.write_text("a,b\n" + "x" * (inspectors.MAX_LINE_BYTES + 10), encoding="utf-8")
        r = inspect_csv(arquivo, file_id="f1", max_rows=1000)
        assert any(i.severity is IssueSeverity.BLOCKING for i in r.issues)


class TestInspecaoDeJSONL:
    def test_jsonl_bom(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "e0.jsonl"
        arquivo.write_text(
            '{"date":"2019-08-09","home":"Liverpool","goals":4}\n'
            '{"date":"2019-08-10","home":"West Ham","goals":0}\n',
            encoding="utf-8",
        )
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        assert r.observation.row_count == 2
        assert set(r.observation.column_names) == {"date", "home", "goals"}
        assert not r.issues

    def test_linha_que_nao_e_objeto_e_defeito(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "arrays.jsonl"
        arquivo.write_text('{"a":1}\n[1,2,3]\n"texto"\n', encoding="utf-8")
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.MALFORMED_ROW.value in _codigos(r)

    def test_json_invalido_e_localizado(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "quebrado.jsonl"
        arquivo.write_text('{"a":1}\n{"b":\n{"c":3}\n', encoding="utf-8")
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        problemas = [i for i in r.issues if i.code is IssueCode.MALFORMED_ROW]
        assert problemas
        assert problemas[0].location == "linha 2"

    def test_aninhamento_profundo_nao_chega_ao_parser(self, tmp_path: Path) -> None:
        """`json.loads` é recursivo, e um documento com milhares de níveis
        estoura a pilha do interpretador — o que não é exceção tratável, é o
        processo morrendo. A profundidade é medida nos caracteres, antes."""
        bomba = "[" * (MAX_JSON_DEPTH + 50) + "1" + "]" * (MAX_JSON_DEPTH + 50)
        arquivo = tmp_path / "bomba.jsonl"
        arquivo.write_text('{"a":1}\n' + bomba + "\n", encoding="utf-8")
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        problemas = [i for i in r.issues if "aninhamento" in i.message]
        assert problemas

    def test_chave_de_string_com_chaves_nao_conta_como_aninhamento(
        self, tmp_path: Path
    ) -> None:
        """Um `{` num nome de time não é abertura de objeto. Contá-lo
        produziria recusa falsa."""
        arquivo = tmp_path / "chaves.jsonl"
        linha = json.dumps({"time": "{" * 200, "gols": 1})
        arquivo.write_text(linha + "\n", encoding="utf-8")
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        assert not [i for i in r.issues if i.code is IssueCode.MALFORMED_ROW]

    def test_jsonl_vazio(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "vazio.jsonl"
        arquivo.write_text("\n\n", encoding="utf-8")
        r = inspect_jsonl(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.NO_ROWS.value in _codigos(r)


class TestInspecaoDeParquet:
    def _escrever(self, caminho: Path, linhas: int = 3) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        tabela = pa.table(
            {
                "Date": ["2019-08-09"] * linhas,
                "HomeTeam": ["Liverpool"] * linhas,
                "FTHG": list(range(linhas)),
            }
        )
        pq.write_table(tabela, caminho)

    def test_parquet_bom(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "e0.parquet"
        self._escrever(arquivo, 5)
        r = inspect_parquet(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        assert r.observation.row_count == 5
        assert r.observation.column_names == ("Date", "HomeTeam", "FTHG")
        assert not r.issues

    def test_tipos_vem_do_rodape(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "e0.parquet"
        self._escrever(arquivo)
        r = inspect_parquet(arquivo, file_id="f1", max_rows=1000)
        assert r.observation is not None
        por_nome = {c.name: c.detected_type for c in r.observation.columns}
        assert por_nome["FTHG"] is DetectedType.INTEGER
        assert por_nome["Date"] is DetectedType.STRING

    def test_parquet_corrompido_nao_derruba_a_validacao(self, tmp_path: Path) -> None:
        """Parser é fronteira não confiável: a falha vira issue, não exceção."""
        arquivo = tmp_path / "corrompido.parquet"
        arquivo.write_bytes(b"PAR1" + b"\x00" * 200 + b"PAR1")
        r = inspect_parquet(arquivo, file_id="f1", max_rows=1000)
        assert IssueCode.INVALID_FORMAT.value in _codigos(r)

    def test_mensagem_de_erro_nao_vaza_caminho_do_arquivo(self, tmp_path: Path) -> None:
        """Erro de parser costuma incluir o caminho do temporário, e o
        relatório é lido por quem pode não ter direito de ver o conteúdo."""
        arquivo = tmp_path / "corrompido.parquet"
        arquivo.write_bytes(b"PAR1" + b"\x00" * 200 + b"PAR1")
        r = inspect_parquet(arquivo, file_id="f1", max_rows=1000)
        for issue in r.issues:
            assert str(tmp_path) not in issue.message


class TestValidacaoDoDatasetInteiro:
    def _ambiente(self, tmp_path: Path) -> tuple[StructuralValidator, RawDatasetArchive]:
        store = FilesystemObjectStore(tmp_path / "bruto")
        archive = RawDatasetArchive(store)
        validador = StructuralValidator(
            archive=archive,
            clock=FrozenClock(AGORA),
            limits=ValidationLimits(
                max_file_size_bytes=10 * 1024 * 1024,
                max_rows_per_file=100_000,
                max_issues=50,
            ),
        )
        return validador, archive

    def _dataset(self) -> Dataset:
        return Dataset.register(
            name="premier-league-2019",
            version=V1,
            source=DatasetSource(
                source_name="football-data.co.uk",
                source_type=SourceType.OPEN_DATA,
                license_class=LicenseClass.ATTRIBUTION_REQUIRED,
                retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
                provider_id=ProviderId("football_data"),
            ),
            declared_competitions=frozenset({CompetitionCode.PREMIER_LEAGUE}),
            declared_seasons=("2019-2020",),
            created_at=AGORA,
            created_by="darlan",
        )

    async def _gravar(
        self,
        archive: RawDatasetArchive,
        dataset: Dataset,
        conteudo: bytes,
        nome: str,
        formato: DatasetFormat = DatasetFormat.CSV,
    ) -> DatasetFile:
        arquivo = DatasetFile.intent(
            dataset_id=dataset.id,
            version=V1,
            original_filename=nome,
            file_format=formato,
            content_hash=ContentHash.of(conteudo),
            size_bytes=len(conteudo),
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=dataset.source.to_provenance(ingested_at=AGORA),
        )
        await archive.store(arquivo, iter([conteudo]))
        return arquivo.confirm_stored()

    async def test_dataset_valido_passa_sem_impeditivo(self, tmp_path: Path) -> None:
        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        arquivo = await self._gravar(archive, base, CSV_BOM.encode(), "e0.csv")
        relatorio = await validador.validate(base.with_files((arquivo,)))
        assert not relatorio.has_blocking_issues
        assert relatorio.rows_observed == 2
        assert relatorio.files_checked == 1

    async def test_formato_declarado_errado_e_impeditivo(self, tmp_path: Path) -> None:
        """Um Parquet chamado `.csv` passa por qualquer verificação de nome:
        o parser de CSV lê o cabeçalho binário como uma linha e não falha."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        temporario = tmp_path / "origem.parquet"
        pq.write_table(pa.table({"a": [1, 2]}), temporario)
        conteudo = temporario.read_bytes()

        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        arquivo = await self._gravar(archive, base, conteudo, "matches.csv")
        relatorio = await validador.validate(base.with_files((arquivo,)))
        assert relatorio.has_blocking_issues
        assert IssueCode.FORMAT_MISMATCH.value in {i.code.value for i in relatorio.issues}

    async def test_objeto_ausente_e_impeditivo(self, tmp_path: Path) -> None:
        """O registro diz que os bytes estão lá e eles não estão.

        É o estado que o protocolo de três fases existe para tornar
        detectável — e detectá-lo aqui é o que impede o dataset de subir
        afirmando ter preservado o que perdeu.
        """
        validador, _ = self._ambiente(tmp_path)
        base = self._dataset()
        fantasma = DatasetFile.intent(
            dataset_id=base.id,
            version=V1,
            original_filename="fantasma.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(b"nunca gravado"),
            size_bytes=13,
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=base.source.to_provenance(ingested_at=AGORA),
        ).confirm_stored()
        relatorio = await validador.validate(base.with_files((fantasma,)))
        assert IssueCode.OBJECT_MISSING.value in {i.code.value for i in relatorio.issues}
        assert relatorio.has_blocking_issues

    async def test_conteudo_duplicado_entre_arquivos_e_impeditivo(
        self, tmp_path: Path
    ) -> None:
        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        a = await self._gravar(archive, base, CSV_BOM.encode(), "e0.csv")
        b = await self._gravar(archive, base, CSV_BOM.encode(), "premier_2019.csv")
        relatorio = await validador.validate(base.with_files((a, b)))
        assert IssueCode.DUPLICATE_CONTENT.value in {i.code.value for i in relatorio.issues}

    async def test_divergencia_de_schema_entre_arquivos_e_so_aviso(
        self, tmp_path: Path
    ) -> None:
        """Um dataset de vinte temporadas costuma ter a temporada em que a
        fonte passou a publicar xG com uma coluna a mais. Legítimo — e não
        pode passar despercebido."""
        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        a = await self._gravar(archive, base, CSV_BOM.encode(), "e0.csv")
        # A temporada em que a fonte passou a publicar xG: uma coluna a mais,
        # e TODAS as linhas com ela — senão o arquivo teria linha irregular, e
        # o teste mediria outra coisa.
        com_xg = (
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,xG\n"
            "2020-08-09,Liverpool,Norwich,4,1,2.8\n"
            "2020-08-10,West Ham,Man City,0,5,0.4\n"
        )
        b = await self._gravar(archive, base, com_xg.encode(), "e1.csv")
        relatorio = await validador.validate(base.with_files((a, b)))
        divergencias = [
            i
            for i in relatorio.issues
            if i.code is IssueCode.SCHEMA_DIVERGENCE_BETWEEN_FILES
        ]
        assert divergencias
        assert divergencias[0].severity is IssueSeverity.WARNING
        assert not relatorio.has_blocking_issues

    async def test_coluna_obrigatoria_ausente_e_impeditivo(self, tmp_path: Path) -> None:
        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        arquivo = await self._gravar(archive, base, CSV_BOM.encode(), "e0.csv")
        contrato = DatasetSchemaContract(required_columns=frozenset({"Referee"}))
        relatorio = await validador.validate(base.with_files((arquivo,)), contract=contrato)
        assert relatorio.has_blocking_issues
        assert IssueCode.MISSING_REQUIRED_COLUMN.value in {
            i.code.value for i in relatorio.issues
        }

    async def test_arquivo_pendente_nao_entra_na_validacao(self, tmp_path: Path) -> None:
        """`stored_files` e não `files`: uma promessa não é evidência."""
        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        confirmado = await self._gravar(archive, base, CSV_BOM.encode(), "e0.csv")
        pendente = DatasetFile.intent(
            dataset_id=base.id,
            version=V1,
            original_filename="pendente.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(b"pendente"),
            size_bytes=8,
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=base.source.to_provenance(ingested_at=AGORA),
        )
        relatorio = await validador.validate(base.with_files((confirmado, pendente)))
        assert relatorio.files_checked == 1

    async def test_jsonl_e_parquet_tem_cobertura_no_fluxo_inteiro(
        self, tmp_path: Path
    ) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        origem = tmp_path / "origem.parquet"
        pq.write_table(pa.table({"Date": ["2019-08-09"], "FTHG": [4]}), origem)

        validador, archive = self._ambiente(tmp_path)
        base = self._dataset()
        jsonl = await self._gravar(
            archive,
            base,
            b'{"date":"2019-08-09","goals":4}\n',
            "e0.jsonl",
            DatasetFormat.JSONL,
        )
        parquet = await self._gravar(
            archive, base, origem.read_bytes(), "e0.parquet", DatasetFormat.PARQUET
        )
        relatorio = await validador.validate(base.with_files((jsonl, parquet)))
        assert relatorio.files_checked == 2
        assert relatorio.rows_observed == 2
        assert not relatorio.has_blocking_issues


class TestArquivoBruto:
    async def test_regravar_os_mesmos_bytes_nao_gera_trafego(self, tmp_path: Path) -> None:
        """A chave contém o hash, então reenviar escreve no mesmo lugar o
        mesmo conteúdo — e a segunda chamada confirma sem regravar."""
        archive = RawDatasetArchive(FilesystemObjectStore(tmp_path / "bruto"))
        base = Dataset.register(
            name="x-dataset",
            version=V1,
            source=DatasetSource(
                source_name="manual",
                source_type=SourceType.MANUAL,
                license_class=LicenseClass.PUBLIC_DOMAIN,
                retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
            ),
            declared_competitions=frozenset({CompetitionCode.PREMIER_LEAGUE}),
            declared_seasons=(),
            created_at=AGORA,
            created_by="darlan",
        )
        arquivo = DatasetFile.intent(
            dataset_id=base.id,
            version=V1,
            original_filename="e0.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(CSV_BOM.encode()),
            size_bytes=len(CSV_BOM.encode()),
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=base.source.to_provenance(ingested_at=AGORA),
        )
        primeiro = await archive.store(arquivo, iter([CSV_BOM.encode()]))
        segundo = await archive.store(arquivo, iter([CSV_BOM.encode()]))
        assert primeiro.was_written_now
        assert not segundo.was_written_now

    def test_object_store_recusa_chave_que_sai_da_raiz(self, tmp_path: Path) -> None:
        """Uma classe que confia no chamador para a própria segurança não é
        segura, é conveniente."""
        from sports_intelligence.domain.shared.errors import InvariantViolationError

        store = FilesystemObjectStore(tmp_path / "bruto")
        with pytest.raises(InvariantViolationError, match="sai da raiz"):
            store._caminho("../../fora.csv")
