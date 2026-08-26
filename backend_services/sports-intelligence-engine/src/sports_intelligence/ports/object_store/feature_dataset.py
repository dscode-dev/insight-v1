"""A materialização do dataset de features em Parquet.

AQUI O PARQUET NÃO É CÓPIA — E ESSA É A DIFERENÇA PARA O CORPUS (ADR-0037). Os
fatos canônicos moram no PostgreSQL e o Parquet do corpus é uma segunda visão
deles; as LINHAS DE FEATURE não moram em lugar nenhum além do object store. O
banco guarda a identidade da versão, as políticas, as contagens e os ponteiros
para os objetos; o conteúdo — cento e cinco valores por linha, noventa e uma
linhas por partida — está no arquivo e só nele.

POR ISSO O PORT NÃO É OPCIONAL. Uma versão sem materialização não é uma versão
com menos comodidade: é uma versão sem conteúdo. Publicá-la seria publicar um
nome apontando para nada, e é por isso que o caso de uso a recusa.

REGERAR CONTINUA POSSÍVEL, e é o que sustenta a decisão: a versão do corpus é
imutável, as políticas são impressas, e a construção é determinística — apagar
o bucket custa uma reconstrução, e não um fato perdido.

NÃO EXISTE `overwrite`. As chaves incluem a versão, que é imutável.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.dataset.manifest import FeatureObjectRef
from sports_intelligence.domain.features.dataset.rows import (
    MaterializedFeatureRow,
    MaterializedObjectContent,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit


@runtime_checkable
class FeatureDatasetMaterializerPort(Protocol):
    """Escreve as linhas de uma versão como Parquet, e diz o que escreveu."""

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit,
        competition: str,
        season: str,
        part_index: int,
        rows: Sequence[MaterializedFeatureRow],
    ) -> FeatureObjectRef | None:
        """Escreve UM PEDAÇO de uma partição. Devolve o objeto, ou `None`.

        `part_index` MANTÉM A MEMÓRIA CONSTANTE. Uma temporada inteira de uma
        liga grande é meio milhão de linhas de 105 colunas; acumulá-la até o
        fim da varredura para escrever um arquivo só faria o pico de memória
        ser o tamanho da maior partição.

        A ORDEM DAS LINHAS É A DA CHAVE, e o adapter NÃO reordena. A impressão
        de conteúdo é ordenada, e uma reordenação silenciosa aqui faria o
        arquivo discordar da impressão que a construção calculou — sem que
        nada denunciasse até a validação.

        `None` QUANDO NÃO HÁ LINHA, pela mesma razão do corpus: um Parquet de
        zero linha é indistinguível de uma partição que ninguém escreveu.

        A PARTIÇÃO É `split=/competition=/season=` NESSA ORDEM. A metade vem
        primeiro porque é o predicado mais grosso e o mais usado — «a população
        de referência» tem de podar a avaliação inteira sem abrir arquivo
        nenhum.

        O SCHEMA É EXPLÍCITO E DERIVADO DO CATÁLOGO. Inferir do primeiro lote
        faria uma feature integralmente indisponível numa partição virar coluna
        `null` num arquivo e `double` noutro, e a leitura do conjunto quebraria
        em cima de dado correto.

        INDISPONÍVEL É `NULL`, NUNCA ZERO (ADR-0009). E a disponibilidade vai
        numa coluna própria: `NULL` sozinho diria que não há número e não diria
        por quê, e «a fonte não publica» exige ação diferente de «o corte
        proibiu».
        """
        ...

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> FeatureObjectRef:
        """Grava o `manifest.json` ao lado dos dados."""
        ...

    async def verify_object(self, *, object_key: str) -> MaterializedObjectContent:
        """Baixa o objeto UMA vez e devolve o que a conferência precisa (§115).

        TRÊS COLUNAS DE DUZENTAS E TRINTA E TRÊS, e é para isso que o formato é
        colunar: reconferir a impressão de um milhão de linhas não pode custar
        ler cento e cinco valores por linha. O hash sai dos bytes baixados,
        então a conferência de integridade e a de conteúdo custam um download
        só.

        AS LINHAS VOLTAM NA ORDEM DO ARQUIVO, e não ordenadas por quem lê. A
        validação precisa descobrir se elas foram gravadas fora de ordem;
        ordenar aqui esconderia exatamente o defeito que ela procura.
        """
        ...

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        """Onde o `manifest.json` daquela versão fica."""
        ...

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        """O prefixo comum de tudo que esta versão escreve."""
        ...
