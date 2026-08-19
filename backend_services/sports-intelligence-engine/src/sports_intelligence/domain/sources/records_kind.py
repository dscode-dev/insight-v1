"""O que UMA LINHA da fonte descreve — e por que isso precisou de um nome.

O INTAKE INTEIRO, DO PR-02 ATÉ AQUI, SUPÕE UMA LINHA POR PARTIDA. A suposição
nunca foi escrita porque nunca precisou ser: toda fonte histórica que o motor
leu descreve uma partida por linha, com placar, escanteios e cotações como
COLUNAS daquela linha.

    Competition,Season,Kickoff,Home,Away,HG,AG,Corners,OddsH
    Premier League,2024/25,…,Arsenal,Chelsea,2,1,7,2.10

Um evento não cabe nesse formato, e a tentação de fazê-lo caber é forte e
errada:

    EVENT_1_TYPE, EVENT_1_MINUTE, EVENT_1_PLAYER,
    EVENT_2_TYPE, EVENT_2_MINUTE, EVENT_2_PLAYER, …

Isso é modelar uma coleção como colunas numeradas. Ela quebra no primeiro jogo
com mais eventos que colunas, obriga o mapeamento a declarar um papel por
posição, e transforma «quantos chutes houve» numa varredura de sufixos. O
PR-04.4.1 §9 proíbe explicitamente.

    dado ESCALAR da partida   um valor por partida     HOME_SCORE, ATTENDANCE
    fluxo de EVENTOS          N linhas por partida     um evento por linha

`RecordKind` é o nome dessa diferença. Ele é DECLARADO pelo operador no
mapeamento — nunca detectado a partir do arquivo (§75, §76): adivinhar a forma
de um arquivo é o tipo de acerto que funciona em noventa e nove datasets e
corrompe o centésimo em silêncio.
"""

from __future__ import annotations

from enum import StrEnum
from typing import final


@final
class RecordKind(StrEnum):
    """O que uma linha da fonte representa. Fechado, e pequeno de propósito.

    DUAS ENTRADAS E NÃO QUATRO. `LINEUP_RECORD` e `ODDS_RECORD` são formas
    plausíveis e não existem: escalação e cotação chegam hoje como colunas da
    linha da partida, e criar os rótulos antes de existir um leitor para eles
    seria vocabulário sem comportamento — o §6 é explícito em não generalizar
    sem necessidade.
    """

    #: Uma linha descreve os atributos de UMA partida. O padrão histórico, e
    #: o que todo mapeamento anterior ao PR-04.4.1 significa.
    MATCH_RECORD = "MATCH_RECORD"
    #: Uma linha descreve UM evento de uma partida. N linhas por partida.
    EVENT_RECORD = "EVENT_RECORD"

    @property
    def is_event_stream(self) -> bool:
        return self is RecordKind.EVENT_RECORD

    @property
    def rows_per_match(self) -> str:
        """A cardinalidade, em texto, para mensagem de erro legível."""
        return "uma" if self is RecordKind.MATCH_RECORD else "muitas"
