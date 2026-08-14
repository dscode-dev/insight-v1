"""Benchmark de ingestão e validação — e o que ele afirma e não afirma.

O QUE ELE AFIRMA. Que o pico de memória NÃO cresce com o tamanho do arquivo.
Essa é a única propriedade deste PR que precisa de medição para ser
verdadeira: ela não é visível no tipo, não é garantida pelo teste de unidade e
é destruída por uma linha inocente — um `await request.body()`, um
`b"".join(chunks)`, um `pl.read_csv` sem `n_rows`.

O QUE ELE NÃO AFIRMA. Nenhum SLO. Os números de tempo dependem da máquina, do
disco e do que mais estiver rodando; transformá-los em asserção produziria uma
suíte que falha por ruído e que, por isso, passa a ser ignorada. Eles são
REPORTADOS — para o relatório do PR e para comparação futura.

A ASSERÇÃO DE MEMÓRIA É RELATIVA, não absoluta. "Menos de 50 MB" seria um
número arbitrário que muda com a versão do Python. "O arquivo é N vezes maior
que o pico" é a propriedade de verdade, e ela sobrevive a mudança de máquina.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ingestion.historical.raw_archive import RawDatasetArchive
from sports_intelligence.ingestion.historical.upload import StreamingReceiver
from sports_intelligence.ingestion.validation.structural import (
    StructuralValidator,
    ValidationLimits,
)
from sports_intelligence.ports.clock import FrozenClock

pytestmark = pytest.mark.performance

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)
LINHAS = 100_000


def _dataset() -> Dataset:
    return Dataset.register(
        name="benchmark-intake",
        version=V1,
        source=DatasetSource(
            source_name="gerado",
            source_type=SourceType.MANUAL,
            license_class=LicenseClass.PUBLIC_DOMAIN,
            retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
        ),
        declared_competitions=frozenset({CompetitionCode.PREMIER_LEAGUE}),
        declared_seasons=(),
        created_at=AGORA,
        created_by="benchmark",
    )


def _csv(linhas: int) -> bytes:
    cabecalho = b"Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A\n"
    corpo = b"".join(
        f"2019-08-09,Team{i % 20},Team{(i + 7) % 20},{i % 5},{i % 4},2.10,3.40,3.60\n".encode()
        for i in range(linhas)
    )
    return cabecalho + corpo


def _jsonl(linhas: int) -> bytes:
    return b"".join(
        f'{{"date":"2019-08-09","home":"Team{i % 20}","goals":{i % 5},"odds":2.1}}\n'.encode()
        for i in range(linhas)
    )


def _parquet(caminho: Path, linhas: int) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    tabela = pa.table(
        {
            "Date": ["2019-08-09"] * linhas,
            "HomeTeam": [f"Team{i % 20}" for i in range(linhas)],
            "FTHG": [i % 5 for i in range(linhas)],
            "B365H": [2.1] * linhas,
        }
    )
    pq.write_table(tabela, caminho)
    return caminho.read_bytes()


async def _stream(dados: bytes, bloco: int = 64 * 1024) -> AsyncIterator[bytes]:
    for i in range(0, len(dados), bloco):
        yield dados[i : i + bloco]


def _relatar(nome: str, bytes_: int, segundos: float, pico: int) -> None:
    mb = bytes_ / 1_048_576
    print(
        f"\n  {nome:<28} {mb:7.1f} MB · {segundos:6.2f}s · "
        f"{mb / segundos if segundos else 0:7.1f} MB/s · pico {pico / 1_048_576:6.1f} MB"
    )


class TestPicoDeMemoria:
    async def test_recepcao_nao_cresce_com_o_arquivo(self, tmp_path: Path) -> None:
        """A propriedade central deste PR, medida.

        O `SpooledTemporaryFile` mantém o conteúdo em memória até um limiar e
        transborda para disco depois. Com o limiar em 256 KB e um arquivo de
        vários MB, o pico precisa ficar em ordem de grandeza abaixo do
        tamanho do arquivo — senão alguém materializou o stream.
        """
        dados = _csv(LINHAS)
        tracemalloc.start()
        async with StreamingReceiver(
            max_bytes=len(dados) * 2, spool_threshold=256 * 1024
        ) as receptor:
            recebido = await receptor.consume(_stream(dados))
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert recebido.size_bytes == len(dados)
        assert recebido.content_hash == ContentHash.of(dados)
        _relatar("recepção CSV 100k", len(dados), 0.0, pico)
        # RELATIVO E NÃO ABSOLUTO: a propriedade é "não cresce com o arquivo",
        # e um teto em MB seria um número que muda com a versão do Python.
        assert pico < len(dados) / 4, (
            f"pico de {pico} bytes para um arquivo de {len(dados)}: "
            "algo materializou o stream"
        )

    async def test_hash_confere_com_o_calculado_de_uma_vez(self, tmp_path: Path) -> None:
        """O hash em blocos precisa dar o mesmo resultado do hash direto.

        Parece óbvio e é exatamente o tipo de coisa que quebra em silêncio
        quando alguém mexe no laço de leitura.
        """
        dados = _csv(1000)
        async with StreamingReceiver(max_bytes=len(dados) * 2) as receptor:
            recebido = await receptor.consume(_stream(dados, bloco=7))
        assert recebido.content_hash == ContentHash.of(dados)


class TestThroughput:
    async def _medir(
        self, tmp_path: Path, conteudo: bytes, nome: str, formato: DatasetFormat
    ) -> tuple[float, int, int]:
        store = FilesystemObjectStore(tmp_path / "bruto")
        archive = RawDatasetArchive(store)
        base = _dataset()
        arquivo = DatasetFile.intent(
            dataset_id=base.id,
            version=V1,
            original_filename=nome,
            file_format=formato,
            content_hash=ContentHash.of(conteudo),
            size_bytes=len(conteudo),
            uploaded_at=AGORA,
            uploaded_by="benchmark",
            provenance=base.source.to_provenance(ingested_at=AGORA),
        )
        await archive.store(arquivo, iter([conteudo]))
        confirmado = arquivo.confirm_stored()

        validador = StructuralValidator(
            archive=archive,
            clock=FrozenClock(AGORA),
            limits=ValidationLimits(
                max_file_size_bytes=512 * 1024 * 1024,
                max_rows_per_file=10_000_000,
                max_issues=100,
            ),
        )
        tracemalloc.start()
        comeco = time.perf_counter()
        relatorio = await validador.validate(base.with_files((confirmado,)))
        duracao = time.perf_counter() - comeco
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert not relatorio.has_blocking_issues, [str(i) for i in relatorio.issues]
        return duracao, pico, relatorio.rows_observed

    async def test_csv_100k(self, tmp_path: Path) -> None:
        dados = _csv(LINHAS)
        duracao, pico, linhas = await self._medir(
            tmp_path, dados, "bench.csv", DatasetFormat.CSV
        )
        _relatar("validação CSV 100k", len(dados), duracao, pico)
        assert linhas == LINHAS

    async def test_jsonl_100k(self, tmp_path: Path) -> None:
        dados = _jsonl(LINHAS)
        duracao, pico, linhas = await self._medir(
            tmp_path, dados, "bench.jsonl", DatasetFormat.JSONL
        )
        _relatar("validação JSONL 100k", len(dados), duracao, pico)
        assert linhas == LINHAS

    async def test_parquet_100k(self, tmp_path: Path) -> None:
        """O Parquet é lido pelo RODAPÉ: schema e contagem sem tocar os dados.

        É por isso que ele é o formato preferencial interno.
        """
        dados = _parquet(tmp_path / "origem.parquet", LINHAS)
        duracao, pico, linhas = await self._medir(
            tmp_path, dados, "bench.parquet", DatasetFormat.PARQUET
        )
        _relatar("validação Parquet 100k", len(dados), duracao, pico)
        assert linhas == LINHAS

    async def test_pico_do_parquet_nao_cresce_com_o_numero_de_linhas(
        self, tmp_path: Path
    ) -> None:
        """A afirmação "lê o rodapé" medida da única forma que a prova.

        A TENTATIVA ÓBVIA NÃO FUNCIONA. "O pico é menor que o arquivo" parece
        certa e é enganosa: estes dados são repetitivos, então 100 mil linhas
        comprimem para poucos kilobytes — e QUALQUER leitura, por mais
        econômica, tem pico maior que um arquivo de 8 KB. O teste falharia
        justamente porque o Parquet é bom demais.

        A propriedade de verdade é outra: o pico não cresce com a QUANTIDADE
        DE LINHAS. Dez mil e cem mil linhas precisam custar o mesmo — se
        alguém trocar a leitura do rodapé por `read_table`, o pico do segundo
        salta e este teste falha.
        """
        pequeno = _parquet(tmp_path / "pequeno.parquet", 10_000)
        _, pico_pequeno, _ = await self._medir(
            tmp_path / "a", pequeno, "pequeno.parquet", DatasetFormat.PARQUET
        )
        grande = _parquet(tmp_path / "grande.parquet", 500_000)
        _, pico_grande, linhas = await self._medir(
            tmp_path / "b", grande, "grande.parquet", DatasetFormat.PARQUET
        )
        _relatar("parquet 10k (referência)", len(pequeno), 0.0, pico_pequeno)
        _relatar("parquet 500k (50x linhas)", len(grande), 0.0, pico_grande)
        assert linhas == 500_000
        # 50 vezes mais linhas. Se a leitura fosse dos DADOS, o pico
        # acompanharia; lendo o rodapé, ele fica na mesma ordem de grandeza.
        assert pico_grande < pico_pequeno * 4, (
            f"pico saltou de {pico_pequeno} para {pico_grande} com 50x mais linhas: "
            "a leitura deixou de ser só do rodapé"
        )
