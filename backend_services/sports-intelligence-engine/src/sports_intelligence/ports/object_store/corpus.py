"""A materialização do corpus em arquivo — opcional, e o tipo diz isso.

O PARQUET É REPRESENTAÇÃO E NÃO FONTE DA VERDADE (§40, ADR-0027). Os fatos
canônicos moram no PostgreSQL; o Parquet é uma cópia colunar, particionada,
feita para leitura analítica em massa. Se ele for apagado, nada se perde —
regerar é reexecutar a materialização sobre a mesma versão, e o resultado é
byte-comparável porque a versão é imutável.

POR ISSO O PORT É OPCIONAL. Uma versão publicada sem materialização é
`READY` do mesmo jeito: ela tem membership, manifesto e impressão, que é o
que `READY` significa. Fazer o Parquet ser obrigatório amarraria a publicação
a um object store disponível, e a indisponibilidade dele viraria «o corpus não
existe» quando o corpus existe inteiro no banco.

NÃO EXISTE `overwrite`. As chaves incluem a versão do dataset, que é
imutável — reescrever sob a mesma chave seria mudar o conteúdo de uma
publicação sem mudar o nome dela (§10).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.corpus.composition import ComposedMatchCorpusFacts
from sports_intelligence.domain.corpus.manifest import CorpusObjectRef
from sports_intelligence.domain.quality.coverage import CoverageFamily


@runtime_checkable
class CanonicalCorpusMaterializerPort(Protocol):
    """Escreve os fatos de uma versão como objetos, e diz o que escreveu."""

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        family: CoverageFamily,
        competition: str,
        season: str,
        part_index: int,
        facts: Sequence[ComposedMatchCorpusFacts],
    ) -> CorpusObjectRef | None:
        """Escreve UM PEDAÇO de uma partição. Devolve o objeto, ou `None`.

        `part_index` EXISTE PARA QUE A MEMÓRIA SEJA CONSTANTE (§86). Uma
        partição inteira acumulada até o fim da varredura seria o corpus todo
        em memória quando ele cabe numa competição só; escrever um `part-N`
        por lote mantém o pico no tamanho do lote, e um diretório com vários
        `part-*.parquet` é exatamente o que os leitores de Parquet esperam.

        `facts` SÃO OS FATOS COMPOSTOS e não a contribuição de um build. Uma
        partida cujas famílias vieram de dois builds precisa escrever as duas —
        e só o objeto composto carrega a união (PR-04.3.1 §35).

        `None` QUANDO NÃO HÁ LINHA. Uma partição vazia não vira arquivo vazio:
        um Parquet de zero linha é indistinguível, na leitura, de uma partição
        que ninguém escreveu — e as duas exigem ações diferentes de quem
        investiga um buraco na cobertura.

        A GRANULARIDADE É A PARTIÇÃO (§43) porque é ela que a leitura analítica
        poda: `competition=EPL/season=2024-25` é o predicado que evita ler o
        corpus inteiro para responder sobre uma temporada.

        O SCHEMA É EXPLÍCITO E NUNCA INFERIDO (§45). Inferir do primeiro lote
        faz uma coluna toda nula virar `null` num arquivo e `double` noutro, e
        a leitura do conjunto quebra em cima de dado que estava certo.

        AUSENTE É `NULL`, NUNCA ZERO (§46). Zero é um placar; ausente é a
        falta de um. Confundi-los produz estatística errada que soma
        perfeitamente e não tem como ser detectada depois.
        """
        ...

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> CorpusObjectRef:
        """Grava o `manifest.json` ao lado dos dados (§56).

        ELE ACOMPANHA OS DADOS e não só o banco: quem copia o diretório do
        corpus para outro lugar precisa levar junto a descrição do que copiou,
        senão o conteúdo chega sem escopo, sem contagem e sem licença.
        """
        ...

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        """Onde o `manifest.json` daquela versão fica.

        É PURA E EXISTE SEPARADA DA ESCRITA porque a composição precisa gravar
        a chave na linha do manifesto ANTES de o documento ser escrito — e uma
        coluna que nunca é preenchida é pior que uma coluna ausente: ela
        promete um ponteiro e devolve `NULL`.
        """
        ...

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        """O prefixo comum de tudo que esta versão escreve.

        EXISTE PARA A CONFERÊNCIA E PARA A LIMPEZA DE FALHA: uma versão que
        falhou no meio deixa objetos órfãos, e sem o prefixo não há como
        listá-los sem varrer o bucket inteiro.
        """
        ...
