"""A ordem canônica de um fluxo de linhas — e por que ela não é a da chave.

O DEFEITO QUE ESTE MÓDULO CONSERTA apareceu no benchmark e não no E2E, e a
diferença entre os dois é o número de partições.

A PRIMEIRA VERSÃO EXIGIA CHAVE GLOBALMENTE CRESCENTE. Ela vale quando o dataset
inteiro cabe numa partição — que é o caso de um cenário de teste com uma
competição e uma temporada. Ela é FALSA no dataset de produção:

    split=REFERENCE/competition=BRA_SERIE_A/season=2024/part-00000
    split=REFERENCE/competition=PREMIER/season=2024/part-00000

As partidas são identificadas por `uuid5`, então as chaves das duas partições se
INTERCALAM no espaço de identificadores. Ler a segunda depois da primeira
entrega uma chave menor, e a exigência global recusa um fluxo perfeitamente
correto.

A ORDEM CANÔNICA DE UM DATASET PARTICIONADO É EM DOIS NÍVEIS:

    1. as PARTIÇÕES, em ordem de `(metade, competição, temporada)`
    2. as LINHAS, em ordem de chave DENTRO de cada partição

E é exatamente essa a ordem que o leitor entrega: ele ordena as chaves de objeto
— e `split=` vem antes de `competition=`, que vem antes de `season=`, que vem
antes de `part-` — e o Parquet devolve as linhas na ordem do arquivo.

O QUE A GUARDA CONTINUA PEGANDO, e é por isso que ela não foi simplesmente
removida:

    linha repetida        a mesma chave duas vezes na mesma partição
    linha fora de ordem   dentro de uma partição
    partição revisitada   voltar a uma partição já fechada, que é como duas
                          leituras concorrentes se misturariam
    partição fora de ordem o leitor entregando `PREMIER` antes de `BRA_SERIE_A`

O QUE ELA DEIXA DE EXIGIR é a única coisa que era falsa: que a chave cresça
ATRAVÉS de partições.
"""

from __future__ import annotations

from typing import final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.shared.errors import ValidationError

#: A identidade de uma partição, na ordem em que ela entra na comparação.
PartitionKey = tuple[str, str, str]


@final
class PartitionOrderGuard:
    """Recusa um fluxo que não está na ordem canônica de partição e chave.

    ELA É UM OBJETO E NÃO UMA FUNÇÃO porque carrega estado — a partição atual e
    a última chave dela —, e porque três acumuladores diferentes precisam da
    MESMA regra. Três cópias divergiriam na primeira correção feita numa só.
    """

    __slots__ = ("_particao", "_rotulo", "_ultima")

    def __init__(self, *, rotulo: str) -> None:
        self._rotulo = rotulo
        self._particao: PartitionKey | None = None
        self._ultima: HistoricalFeatureSnapshotKey | None = None

    def check(self, partition: PartitionKey, key: HistoricalFeatureSnapshotKey) -> None:
        """Levanta quando a linha chega fora da ordem canônica."""
        if self._particao is None or partition != self._particao:
            if self._particao is not None and partition <= self._particao:
                raise ValidationError(
                    f"{self._rotulo}: partição {partition} depois de "
                    f"{self._particao}. A ordem das partições é canônica, e voltar a "
                    "uma já fechada é como duas leituras concorrentes se misturariam "
                    "sem que a contagem denunciasse",
                    context={
                        "partition": "/".join(partition),
                        "previous": "/".join(self._particao),
                    },
                )
            self._particao = partition
            self._ultima = None
        if self._ultima is not None and key <= self._ultima:
            raise ValidationError(
                f"{self._rotulo}: linha {key} depois de {self._ultima} na partição "
                f"{'/'.join(partition)}. A impressão é ordenada, e aceitar a inversão "
                "faria duas leituras da mesma população parecerem populações "
                "diferentes — ou, pior, a mesma linha entrar duas vezes",
                context={"key": key.text, "previous": self._ultima.text},
            )
        self._ultima = key


def partition_of(*, split: str, competition: str, season: str) -> PartitionKey:
    """A chave de partição, na ordem em que o object store a escreve.

    A METADE VEM PRIMEIRO porque é assim que o caminho é montado
    (`split=/competition=/season=`), e ordenar diferente daqui faria a guarda
    recusar o fluxo que o leitor de fato entrega.
    """
    return (split, competition, season)
