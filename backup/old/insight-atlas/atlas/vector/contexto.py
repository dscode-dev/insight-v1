"""O que a tabela e a geografia dizem sobre uma partida.

POR QUE ESTE MÓDULO EXISTE. Medido sobre o corpus de 15.628 partidas, o
mercado separa os jogos de cada campeonato assim:

    competição            desvio de implied_home    lente `resultado`
    premier_league               0,196                  +13,0%
    la_liga                      0,173                   +9,5%
    brasileirao                  0,138                   +1,0%
    argentina_liga               0,122                   +0,5%

A ordem é a mesma. O sinal dominante da lente é o mercado, e na Argentina ele
separa 38% menos que na Inglaterra — não porque falte dado, mas porque os
jogos são mais parecidos entre si. Adicionar mais colunas de mercado não
resolve isso, e o passo 3 mediu exatamente isso: nenhum ganho conclusivo.

O QUE FALTA NUM CAMPEONATO EQUILIBRADO NÃO É QUALIDADE, É CONTEXTO. Uma
partida da 35ª rodada entre dois times na zona e outra entre dois times sem
nada em jogo têm hoje o mesmo vetor. E o mercado não precifica intensidade,
precifica qualidade — então este é um sinal que ele não carrega.

AS TRÊS COISAS QUE ESTE MÓDULO CALCULA:

  posição na tabela   rank normalizado por pontos por jogo, ANTES da partida
  o que está em jogo  quão perto o clube está de uma fronteira que muda o
                      destino da temporada dele, pesado por quanto resta
  distância           km entre as duas cidades. Grêmio-Fortaleza são 3.500;
                      Arsenal-Chelsea são 8. Não tem análogo europeu, que é
                      exatamente por que vale medir.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CLUB_REGISTRY_PATH = Path("/opt/insight-protos/contracts/clubs/club_registry.json")

#: Raio médio da Terra, em km. Haversine basta: a pergunta é "viagem longa ou
#: curta", e a diferença entre haversine e a distância geodésica real é menor
#: que a diferença entre o aeroporto e o estádio.
RAIO_TERRA_KM = 6371.0

#: As fronteiras que mudam o destino de uma temporada, por competição.
#:
#: DECLARADAS, e só onde o formato é estável. O Brasileirão joga pontos
#: corridos com 20 clubes e 4 rebaixados desde 2006; a Premier League e La
#: Liga rebaixam 3. O futebol argentino mudou de formato quase todo ano no
#: período que temos — de 190 a 510 partidas por temporada — e inventar uma
#: zona ali produziria um número que descreve um campeonato que não existiu.
#:
#: Competição sem entrada aqui não recebe `stakes`. Ausente é neutra; um zero
#: diria "nada em jogo", que é uma afirmação sobre algo não observado.
ZONAS: dict[str, dict[str, int]] = {
    "brasileirao": {"clubes": 20, "continental": 6, "rebaixados": 4},
    "premier_league": {"clubes": 20, "continental": 5, "rebaixados": 3},
    "la_liga": {"clubes": 20, "continental": 5, "rebaixados": 3},
}


@lru_cache(maxsize=1)
def coordenadas(path: Path = CLUB_REGISTRY_PATH) -> dict[str, tuple[float, float]]:
    """club_id → (lat, lon), ou vazio quando o registro não está no lugar.

    Vazio faz a dimensão de distância ser OMITIDA de todas as partidas, e a
    régua reporta a coluna como constante — que é bem melhor que preencher
    tudo com zero e afirmar que todo jogo é em casa.
    """
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    saida: dict[str, tuple[float, float]] = {}
    for clube in dados.get("clubs", []):
        lat, lon = clube.get("latitude"), clube.get("longitude")
        if lat is None or lon is None:
            continue
        saida[str(clube["club_id"])] = (float(lat), float(lon))
    return saida


def distancia_km(a: str, b: str, mapa: dict[str, tuple[float, float]]) -> float | None:
    """Haversine entre as cidades dos dois clubes, ou None se falta uma.

    Zero é uma resposta legítima e frequente: um clássico carioca não tem
    viagem, e os quatro clubes do Rio compartilham as mesmas coordenadas de
    propósito.
    """
    if a not in mapa or b not in mapa:
        return None
    lat1, lon1 = mapa[a]
    lat2, lon2 = mapa[b]
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(h))


@dataclass
class _Tabela:
    """A classificação de uma competição-temporada, montada jogo a jogo."""

    pontos: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    jogos: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    #: Quantas partidas esta competição-temporada tem no total. Preenchido
    #: antes do laço, contando o corpus — e não fixado em 380, que é a
    #: pergunta errada para uma temporada argentina de 190 ou de 510.
    total_de_partidas: int = 0

    def aplicar(self, casa: str, fora: str, gols_casa: int, gols_fora: int) -> None:
        self.jogos[casa] += 1
        self.jogos[fora] += 1
        if gols_casa > gols_fora:
            self.pontos[casa] += 3
        elif gols_fora > gols_casa:
            self.pontos[fora] += 3
        else:
            self.pontos[casa] += 1
            self.pontos[fora] += 1

    def classificacao(self) -> list[str]:
        """Clubes ordenados por pontos por jogo, do primeiro ao último.

        POR JOGO, e não por pontos absolutos: no meio de uma rodada nem todo
        clube jogou o mesmo número de partidas, e ordenar por total colocaria
        quem tem um jogo a mais sempre à frente. Desempate pelo nome, para que
        a ordem seja a mesma em duas execuções — uma tabela que muda entre
        reconstruções faria a dimensão mudar sem o dado mudar.
        """
        return sorted(
            self.jogos,
            key=lambda c: (-(self.pontos[c] / max(self.jogos[c], 1)), c),
        )

    def posicao_normalizada(self, clube: str) -> float | None:
        """0,0 para o líder, 1,0 para o último. `None` antes de o clube jogar.

        `None` e não 0,5: um clube que ainda não entrou em campo não está no
        meio da tabela, ele não está na tabela. Meio é uma afirmação.
        """
        ordem = self.classificacao()
        if clube not in ordem or len(ordem) < 2:
            return None
        return ordem.index(clube) / (len(ordem) - 1)

    def rodadas_restantes(self, clubes_na_competicao: int) -> float:
        """Fração da temporada que ainda falta, de 1,0 a 0,0."""
        if self.total_de_partidas <= 0:
            return 0.0
        jogadas = sum(self.jogos.values()) / 2
        return max(0.0, 1.0 - jogadas / self.total_de_partidas)


def em_jogo(
    tabela: _Tabela, clube: str, competicao: str
) -> float | None:
    """Quanto esta temporada ainda está indefinida PARA ESTE CLUBE.

    A ideia: um clube importa-se com a partida quando está perto de uma
    fronteira que muda o destino dele — o topo que dá vaga continental, o
    fundo que rebaixa — e quando ainda há temporada suficiente para essa
    fronteira ser cruzada.

        1,0   em cima de uma fronteira, com temporada pela frente
        0,0   longe de qualquer fronteira, ou temporada decidida

    NÃO É PREVISÃO. É uma descrição da situação de tabela no momento do
    apito, computada só com jogos anteriores — a mesma regra walk-forward de
    todas as outras dimensões.

    `None` quando a competição não tem zonas declaradas (o futebol argentino,
    cujo formato mudou quase todo ano) ou quando o clube ainda não jogou.
    """
    zonas = ZONAS.get(competicao)
    if zonas is None:
        return None

    ordem = tabela.classificacao()
    if clube not in ordem or len(ordem) < 2:
        return None

    posicao = ordem.index(clube) + 1  # 1 = líder
    total = len(ordem)

    # As duas fronteiras, em número de posições de distância. `continental` é
    # a última vaga que classifica; `rebaixados` conta de baixo para cima.
    fronteiras = (
        abs(posicao - zonas["continental"]),
        abs(posicao - (total - zonas["rebaixados"])),
    )
    distancia = min(fronteiras)

    # Normaliza pela metade da tabela: a 10 posições de qualquer fronteira,
    # num campeonato de 20, não há o que decidir.
    proximidade = max(0.0, 1.0 - distancia / (total / 2))

    # E pesa por quanto ainda resta. Uma equipe colada na fronteira na 3ª
    # rodada não tem nada em jogo ainda; na 35ª, tem tudo.
    #
    # `1 - restante` porque o que aumenta a aposta é a temporada ACABANDO:
    # quanto menos jogos sobram, menos chance de corrigir.
    restante = tabela.rodadas_restantes(total)
    urgencia = 1.0 - restante

    return round(proximidade * urgencia, 4)
