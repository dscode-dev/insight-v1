"""A leitura do dataset CRU e a escrita do NORMALIZADO.

DOIS PORTS, E NÃO UM. Ler o cru e escrever o normalizado são operações opostas
sobre bucket, com preocupações opostas: a leitura precisa de PROJEÇÃO e PODA de
partição; a escrita precisa de esquema explícito e ordem preservada. Um port só
teria metade dos métodos irrelevante para cada chamador.

A LEITURA É EM FLUXO, E É A DECISÃO DE ESCALA DESTE PR (§99). Um dataset de
noventa e uma mil linhas por cento e cinco colunas não entra na memória como
lista de objetos; a interface devolve LOTES, e o tamanho do lote é do chamador.

A PROJEÇÃO É EXPLÍCITA porque metade das colunas do arquivo não é lida pelo
ajuste. Ajustar vinte e nove eixos não precisa dos setenta e seis que passam
direto, e o formato colunar só entrega essa economia se alguém pedir.

A PODA DE PARTIÇÃO TAMBÉM (§29). O ajuste lê `split=REFERENCE` e nada mais.
Filtrar depois de ler funcionaria e leria o dobro — e, pior, deixaria a
correção do ajuste depender de um `if` em vez da estrutura do bucket.

A ORDEM É CONTRATO, e não conveniência. O leitor entrega as linhas em ordem de
`(partida, corte)` DENTRO de cada partição, e as partições em ordem canônica.
As impressões deste PR são todas ordenadas e RECUSAM a inversão: um leitor que
entregasse fora de ordem pararia a construção em vez de produzir um dataset
irreprodutível.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.manifest import NormalizedObjectRef
from sports_intelligence.domain.features.normalized.rows import NormalizedFeatureRow
from sports_intelligence.domain.features.normalized.transform import RawFeatureRowView


@runtime_checkable
class RawFeatureDatasetReaderPort(Protocol):
    """Lê as linhas materializadas de uma versão CRUA, em fluxo e em ordem."""

    async def partitions(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
    ) -> Sequence[tuple[DatasetSplit, str, str]]:
        """As partições daquela versão, em ordem canônica.

        ELAS SÃO DESCOBERTAS NO BUCKET, e não deduzidas do banco. O que importa
        para a construção é o que EXISTE no object store: um objeto órfão que o
        registro não conhece tem de aparecer aqui para que a validação o veja.
        """
        ...

    def stream_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
        feature_keys: Sequence[str] | None = None,
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[RawFeatureRowView]]:
        """As linhas em LOTES, projetadas e podadas.

        `feature_keys is None` LÊ TODOS OS EIXOS. É o caso da construção
        normalizada, que precisa dos cento e cinco; o ajuste passa os vinte e
        nove e paga um quarto do custo de leitura.

        `batch_rows` É DO CHAMADOR porque a pressão de memória é dele: o ajuste
        acumula por eixo e aguenta lotes grandes; a construção segura linhas
        normalizadas e não aguenta.
        """
        ...

    async def row_count(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
    ) -> int:
        """Quantas linhas há, SEM ler valor nenhum.

        ELE EXISTE PARA O CONTRATO 1:1 (§94). Conferir a cardinalidade lendo o
        dataset inteiro faria a validação custar o mesmo que a construção, e o
        Parquet já guarda a contagem nos metadados do rodapé.
        """
        ...


@runtime_checkable
class NormalizedFeatureDatasetMaterializerPort(Protocol):
    """Escreve as linhas normalizadas, e diz o que escreveu."""

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit,
        competition: str,
        season: str,
        part_index: int,
        rows: Sequence[NormalizedFeatureRow],
        source_object_key: str = "",
    ) -> NormalizedObjectRef | None:
        """UM pedaço de uma partição normalizada. `None` quando não há linha.

        O ESQUEMA É DERIVADO DO PLANO, e não inferido do lote. Um eixo
        integralmente `ARTIFACT_DEGENERATE_SCALE` numa competição sairia como
        coluna `null` no arquivo dela e `double` na outra, e ler o conjunto
        quebraria em cima de dado correto.

        SÃO TRÊS FAMÍLIAS DE COLUNA, e não duas. Além do valor e da
        disponibilidade da NORMALIZAÇÃO, viaja a disponibilidade de ORIGEM: sem
        ela, «não havia valor» e «havia valor e não havia escala» chegam ao
        leitor como o mesmo `null` (§62).
        """
        ...

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> NormalizedObjectRef:
        """Grava o `manifest.json` ao lado dos dados."""
        ...

    async def verify_object(
        self, *, object_key: str
    ) -> tuple[str, int, Sequence[tuple[str, int, str, str]]]:
        """Baixa o objeto UMA vez: `(sha256, bytes, linhas)`.

        AS LINHAS VOLTAM COMO `(partida, corte, metade, digesto)` — quatro
        colunas de duzentas e trinta e três. É para isso que o formato é
        colunar: reconferir a impressão não pode custar ler cento e cinco
        valores por linha.

        E VOLTAM NA ORDEM DO ARQUIVO. A validação existe para descobrir se
        foram gravadas fora de ordem; ordenar aqui esconderia o defeito.
        """
        ...

    def manifest_key(self, *, dataset_name: str, version: str) -> str: ...

    def partition_prefix(self, *, dataset_name: str, version: str) -> str: ...
