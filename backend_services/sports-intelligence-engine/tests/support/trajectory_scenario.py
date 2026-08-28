"""O cenário do PR-06.3 — o do PR-06.2, com MOVIMENTO deliberado.

O PROBLEMA QUE ELE RESOLVE (§178, §179). Os cenários anteriores só precisavam
que cada âncora tivesse UMA linha; a trajetória precisa de várias linhas da
MESMA partida, no MESMO período, com evolução diferente entre elas. Um cenário
em que todas as curvas fossem constantes produziria `Δ = 0` em tudo, e o
benchmark do §149 — mesmo estado, movimento oposto — não teria como existir.

    «Não crie todas as feature curves constantes. Precisamos de crescente,
     decrescente, estável e parcialmente unavailable.» — §179

COMO O MOVIMENTO É PRODUZIDO. `xg_*_10m` soma o xG dos últimos dez minutos, e
uma janela móvel SOBE quando chegam chutes e DESCE quando os antigos saem. O
cenário controla isso pela POSIÇÃO dos chutes dentro de cada tempo:

    SUBINDO     o xG de cada chute CRESCE ao longo do período — a janela
                móvel sobe minuto a minuto
    DESCENDO    ele decresce — a janela desce
    ESTÁVEL     ele fica no meio — a janela vive num patamar

    e a FORMA ALTERNA POR PARTIDA, de modo que a mesma competição tenha, no
    mesmo minuto, jogos subindo e jogos descendo. É essa mistura que produz o
    par «mesmo estado, movimento oposto» sobre dados reais.

A DENSIDADE PRECISOU SUBIR, e o motivo saiu de medição. A janela de xG tem dez
minutos; com quatro chutes por tempo — a densidade do PR-06.2 — o conteúdo dela
é o MESMO em `t`, `t-1`, `t-3` e `t-5`, e todo deslocamento sai zero. A primeira
versão deste cenário fez exatamente isso, e a sonda mostrou vinte e quatro
células de `Δ = 0`: as curvas existiam no jogo e não existiam na trajetória.

    com chutes a cada três minutos, a janela troca de conteúdo entre um
    minuto e o seguinte, e o deslocamento passa a existir.

O QUE NÃO MUDOU: o espaçamento irregular dos apitos, o rodízio que gira e as
cotações parciais continuam os do PR-06.2.

E OS EIXOS DE CONTEXTO CONTINUAM CONSTANTES DENTRO DA PARTIDA, de propósito.
`ctx_same_comp_prev_gap_hours_*` é um fato de pré-jogo: ele vale o mesmo em
todo corte, logo `Δ = 0` em toda célula dele. Isso não é defeito do cenário —
é o que uma feature de contexto É —, e ter metade do perfil parada e metade se
movendo é exatamente a mistura de «estável» e «crescente/decrescente» que o
§179 pede.
"""

from __future__ import annotations

from typing import Any, Final

from tests.support.availability_scenario import (
    _FIM_DE_LINHA,
    CHUTES_POR_TIME,
    PARTIDAS,
    TIMES,
    cenario,
    fonte_de_odds,
    fonte_publica,
    tem_cotacao,
)
from tests.support.retrieval_scenario import referencia_de_partida

__all__ = [
    "CHUTES_POR_TIME",
    "PARTIDAS",
    "TIMES",
    "cenario",
    "fonte_de_eventos",
    "fonte_de_odds",
    "fonte_publica",
    "tem_cotacao",
]

#: As três formas de curva. A ordem é a de rodízio por partida.
FORMAS: Final[tuple[str, ...]] = ("SUBINDO", "DESCENDO", "ESTAVEL")

#: De quantos em quantos minutos cada time chuta.
#:
#: TRÊS, E O NÚMERO SAIU DE MEDIÇÃO. A janela de xG tem dez minutos; com
#: chutes a cada oito ou mais, o conteúdo dela é o MESMO nos quatro instantes
#: da trajetória — `t`, `t-1`, `t-3`, `t-5` — e todo deslocamento sai zero. A
#: primeira versão deste cenário colocava quatro chutes por tempo e produziu
#: exatamente isso: as curvas existiam no jogo e não existiam na trajetória.
#:
#: Com três, cerca de três chutes vivem na janela a cada instante, e ela troca
#: de conteúdo entre um minuto e o seguinte.
PASSO_DO_CHUTE: Final[int] = 3

#: O xG do primeiro chute e quanto ele anda por minuto de jogo.
#:
#: A INCLINAÇÃO É O QUE FAZ A JANELA SUBIR OU DESCER. Com chutes de xG
#: constante, a soma móvel oscila em torno de um patamar e o sinal de
#: trajetória some no ruído; com xG crescente, a janela cresce mesmo quando o
#: número de chutes dentro dela não muda.
XG_BASE: Final[float] = 0.06
XG_INCLINACAO: Final[float] = 0.010

#: Os primeiros e últimos minutos de cada tempo em que há chute.
_FAIXAS: Final[tuple[tuple[str, int, int], ...]] = (
    ("FIRST_HALF", 3, 45),
    ("SECOND_HALF", 48, 90),
)


def forma_de(indice: int) -> str:
    """A forma da curva daquela partida.

    ELA É UMA FUNÇÃO para que o teste possa perguntar o mesmo que o gerador
    respondeu: «este candidato deveria estar subindo?» é a pergunta que separa
    um movimento esperado de um defeito de montagem.
    """
    return FORMAS[indice % len(FORMAS)]


def _xg(forma: str, minuto: int, primeiro: int, ultimo: int) -> float:
    """O xG de um chute naquele minuto, sob aquela forma.

    SUBINDO e DESCENDO são a MESMA rampa em direções opostas; ESTAVEL é o
    patamar. O valor nunca chega a zero — um chute de xG zero não teria efeito
    nenhum na janela, e a forma sumiria.
    """
    andar = (minuto - primeiro) * XG_INCLINACAO
    total = (ultimo - primeiro) * XG_INCLINACAO
    if forma == "SUBINDO":
        return XG_BASE + andar
    if forma == "DESCENDO":
        return XG_BASE + total - andar
    return XG_BASE + total / 2


def fonte_de_eventos(corpus: Any, cabecalho: bytes) -> bytes:
    """Chutes a cada três minutos, com xG em rampa — a curva do jogo.

    OS DOIS TIMES SEGUEM A MESMA FORMA, com um minuto de deslocamento. Isso
    mantém `xg_diff_10m` pequeno e faz casa e fora se moverem juntos: a
    trajetória mede o movimento do JOGO, e dois times em fases opostas
    produziriam um sinal que nenhuma partida real tem.

    A FORMA ALTERNA POR PARTIDA, então a mesma competição tem, no mesmo
    minuto, jogos subindo e jogos descendo — que é a matéria-prima do golden
    de discriminação de direção.
    """
    linhas = [cabecalho]
    for i, _ in enumerate(corpus.matches):
        ref = referencia_de_partida(i)
        atleta = f"pr061-player-{i % TIMES:02d}"
        forma = forma_de(i)
        sequencia = 0
        for tempo, primeiro, ultimo in _FAIXAS:
            for n, minuto in enumerate(range(primeiro, ultimo + 1, PASSO_DO_CHUTE)):
                for lado in ("h", "a"):
                    sequencia += 1
                    quando = minuto if lado == "h" else min(minuto + 1, ultimo)
                    xg = _xg(forma, quando, primeiro, ultimo)
                    tipo = "goal" if n % 7 == 2 and lado == "h" and i % 2 == 0 else "shot"
                    linha = (
                        f"e{i:02d}{lado}{tempo[0]}{n:02d},{ref},{tipo},{tempo},"
                        f"{quando},0,{sequencia},pr061-team-{lado}{i:02d},{atleta},"
                        f"0.90,0.50,GOAL,RIGHT_FOOT,{xg:.3f},,NEW,"
                    )
                    linhas.append(linha.encode() + _FIM_DE_LINHA)
    return b"".join(linhas)
