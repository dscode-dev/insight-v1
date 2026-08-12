"""As cinco categorias de consulta, e o que cada uma olha.

O PROBLEMA QUE ISTO RESOLVE. Até aqui havia UMA consulta de similaridade,
sobre o vetor inteiro, respondendo a qualquer pergunta com a mesma
vizinhança. Perguntar "quem tende a vencer" e "quanto gol costuma ter" dava
exatamente os mesmos vizinhos, porque as duas percorriam as mesmas 25
dimensões com o mesmo peso — a diferença ficava só no texto da resposta.

UMA LENTE É UM SUBCONJUNTO DE DIMENSÕES COM PESOS. A similaridade passa a ser
calculada só sobre o que a pergunta usa. Duas partidas podem ser vizinhas
para `gols` e distantes para `resultado`, o que é o comportamento correto:
são perguntas diferentes sobre o mesmo jogo.

POR QUE PESO E NÃO SÓ SELEÇÃO. Dentro de uma pergunta as dimensões não valem
o mesmo. Para o resultado, a probabilidade implícita do mercado carrega mais
que os dias de descanso — e tratar as duas igualmente é uma afirmação sobre o
futebol que ninguém fez.

DE ONDE VÊM OS PESOS. Não de otimização: são declarados, redondos, e cada um
tem um motivo escrito. Ajustar peso contra o próprio corpus até o número
subir é como se constrói algo que só funciona no passado. A régua mede se a
lente bate a taxa base da SUA pergunta; se não bater, o problema é a lente,
e a resposta é repensá-la, não afinar decimais.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Categoria = Literal[
    "resultado", "gols", "desempenho_time", "confronto", "contexto"
]


#: A lente `confronto` não tenta descrever desfecho: ela devolve o retrospecto
#: entre os dois times. Medir "concordância de desfecho" nela produz um número
#: que ninguém deveria usar, e é por isso que ele não é usado — a medida é
#: apurada e guardada, e a resposta continua sendo o registro.
NAO_DESCREVEM_DESFECHO: frozenset[str] = frozenset({"confronto"})


@dataclass(frozen=True)
class Lente:
    categoria: Categoria
    pergunta: str
    #: dimensão → peso. Só o que está aqui entra na similaridade.
    pesos: dict[str, float]
    #: Restrições duras aplicadas ANTES da similaridade. Uma lente que
    #: precisa de contexto igual não deve descobri-lo por proximidade.
    filtros: tuple[str, ...]
    #: O que a resposta descreve. Nomeado aqui para que o contrato de saída
    #: não seja inventado no caminho.
    descreve: str

    @property
    def dimensoes(self) -> tuple[str, ...]:
        return tuple(self.pesos)


LENTES: dict[str, Lente] = {
    "resultado": Lente(
        categoria="resultado",
        pergunta="Como terminam jogos em situação parecida com esta?",
        pesos={
            # O mercado é o resumo mais denso que existe da situação: ele já
            # embute lesões, escalação e notícia que o histórico não vê. Peso
            # maior por isso, não por preferência.
            "implied_home": 1.0,
            "implied_draw": 0.8,
            "implied_away": 1.0,
            "favourite_margin": 0.7,
            # A mesma informação do 1x2 numa escala contínua: -0,25 e -0,75
            # são partidas diferentes que as três cotações arredondam para
            # perto do mesmo lugar.
            "handicap_line": 0.7,
            # Peso modesto e deliberado: discordância entre casas é o único
            # sinal novo disponível na América do Sul, e é lá que `resultado`
            # não bate a taxa base. Vale medir. Se não ajudar, a régua diz —
            # e o peso sai, em vez de ficar por parecer razoável.
            "market_disagreement": 0.4,
            "line_movement": 0.5,
            "elo_delta": 0.9,
            "home_form": 0.6,
            "away_form": 0.6,
            "h2h_advantage": 0.4,
            "rest_advantage": 0.2,
            # `travel_distance` (0,4) E `table_position` (0,5 cada) ESTIVERAM
            # AQUI E SAÍRAM MEDIDOS. Não ajudaram em nenhuma competição, e na
            # Argentina levaram a lente de +0,5% para -1,7%. A posição na
            # tabela é redundante com Elo e mercado para a pergunta "como
            # termina" — os dois já dizem quem é melhor, com mais resolução.
        },
        filtros=(),
        descreve="distribuição dos desfechos entre as partidas vizinhas",
    ),
    "gols": Lente(
        categoria="gols",
        pergunta="Que volume de gols esse tipo de jogo costuma ter?",
        pesos={
            # A PERGUNTA DA LENTE, RESPONDIDA PELO MERCADO. Peso igual ao
            # do histórico de gols e não maior: as duas dizem coisas
            # diferentes — uma é o que os times vinham fazendo, a outra é o
            # que o mercado acha DESTE jogo. Ausente na América do Sul, onde
            # a coluna não existe; ausente é neutra, não zero.
            "implied_over_2_5": 1.0,
            "expected_goals_total": 1.0,
            "home_attack": 0.9,
            "away_attack": 0.9,
            "home_defense": 0.9,
            "away_defense": 0.9,
            # Chute e precisão são produção ofensiva sem depender de o gol
            # ter saído — descrevem a tendência mesmo em janela de azar.
            "home_shots_rate": 0.6,
            "away_shots_rate": 0.6,
            "home_accuracy": 0.5,
            "away_accuracy": 0.5,
            "home_corners_rate": 0.3,
            "away_corners_rate": 0.3,
            # O empate provável costuma acompanhar jogo travado; entra com
            # peso baixo porque a relação existe e é fraca.
            "implied_draw": 0.3,
        },
        filtros=(),
        descreve="média de gols e frequência de jogos acima de 2,5 entre os vizinhos",
    ),
    "desempenho_time": Lente(
        categoria="desempenho_time",
        pergunta="O que esperar de cada lado, separadamente?",
        pesos={
            "home_form": 1.0,
            "away_form": 1.0,
            "home_attack": 0.8,
            "away_attack": 0.8,
            "home_defense": 0.8,
            "away_defense": 0.8,
            "home_shots_rate": 0.6,
            "away_shots_rate": 0.6,
            "home_accuracy": 0.5,
            "away_accuracy": 0.5,
            # Disciplina descreve o temperamento do jogo, que é parte de
            # "como este time se comporta" — e é a única dimensão em que a
            # arbitragem aparece.
            "home_discipline": 0.4,
            "away_discipline": 0.4,
            "rest_advantage": 0.3,
            "elo_delta": 0.5,
            # `table_position` (0,7 cada) E `travel_distance` (0,3) ESTIVERAM
            # AQUI E SAÍRAM MEDIDOS. A hipótese era que a tabela carrega o que
            # a janela de 10 jogos não sabe. Medido: La Liga caiu de +7,5%
            # para +5,1% e o Brasileirão atravessou de -2,4% para -3,9%
            # (conclusivamente pior). Duas competições na mesma direção não é
            # ruído.
        },
        filtros=(),
        descreve="produção, disciplina e forma de cada lado nas partidas vizinhas",
    ),
    "confronto": Lente(
        categoria="confronto",
        pergunta="O que a história específica deste par diz?",
        pesos={
            "h2h_advantage": 1.0,
            "elo_delta": 0.6,
            "implied_home": 0.5,
            "implied_away": 0.5,
            "home_form": 0.3,
            "away_form": 0.3,
        },
        # A ÚNICA lente com filtro duro pelo par — e o filtro é o que a
        # define, não um detalhe. Medido: com o filtro ela acerta 8,2 pontos
        # ABAIXO da taxa base; sem ele, 12,3 ACIMA. Ou seja, os pesos são
        # ótimos e a restrição é que destrói.
        #
        # O filtro FICA mesmo assim, porque tirá-lo transformaria esta lente
        # em outra cópia de `resultado` — e a pergunta "o que já aconteceu
        # entre estes dois" é legítima e não tem outro lugar. O que mudou foi
        # a RESPOSTA: ela deixou de votar desfecho e passou a devolver o
        # retrospecto, que é um fato e não uma descrição desta partida.
        filtros=("mesmo_par",),
        descreve=(
            "o REGISTRO dos encontros entre estes dois clubes — histórico, "
            "não descrição desta partida"
        ),
    ),
    "contexto": Lente(
        categoria="contexto",
        pergunta="O que o momento da competição impõe?",
        pesos={
            "season_progress": 1.0,
            # O QUE ESTÁ EM JOGO. É a pergunta literal desta lente — "o que o
            # momento da competição impõe" — e até aqui ela só tinha a fração
            # da temporada, que diz QUANDO e não O QUÊ. Duas partidas da 35ª
            # rodada, uma entre times na zona e outra entre times sem nada,
            # tinham exatamente o mesmo vetor.
            "stakes": 1.0,
            "table_position_home": 0.8,
            "table_position_away": 0.8,
            # A margem da casa é proxy de quanto o mercado tem certeza, que
            # é uma propriedade do momento tanto quanto do jogo.
            "overround": 0.7,
            # `market_disagreement` ESTEVE AQUI COM PESO 0,8 E SAIU MEDIDO.
            #
            # A hipótese era boa: quanto as casas discordam parece contexto,
            # e é o único sinal novo que existe em toda competição. Medido
            # com 900 consultas por campeonato, não melhorou nenhum deles de
            # forma conclusiva, e no Brasileirão levou `contexto` de -3,1%
            # (dentro da margem) para -4,5% (conclusivamente pior que a taxa
            # base). Um peso que só piora onde é medido não fica por parecer
            # razoável.
            #
            # A dimensão continua existindo e sendo gravada: ela é um fato
            # sobre a partida. O que saiu foi a afirmação de que ela ajuda a
            # descrever contexto.
            "favourite_margin": 0.6,
            "line_movement": 0.6,
            "home_discipline": 0.4,
            "away_discipline": 0.4,
            "rest_advantage": 0.5,
        },
        # Fase de temporada só é comparável dentro da mesma competição:
        # a 30ª rodada do Brasileirão e da Premier não são o mesmo momento.
        filtros=("mesma_competicao",),
        descreve="como se comportam as partidas no mesmo momento da competição",
    ),
}


def lente(categoria: str) -> Lente:
    try:
        return LENTES[categoria]
    except KeyError:
        raise ValueError(
            f"categoria desconhecida: {categoria!r} — "
            f"use uma de {', '.join(sorted(LENTES))}"
        ) from None
