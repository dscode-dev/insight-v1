"""O que descreve uma partida ANTES dela acontecer.

    atlas.match_record  →  25 números por partida, em ordem cronológica

A REGRA QUE GOVERNA ESTE MÓDULO INTEIRO: nada que só se sabe depois do apito
final pode descrever a partida. Placar, chutes, escanteios e cartões DAQUELA
partida são resultado, não contexto — usá-los seria descrever o jogo com a
resposta na mão. Eles entram, sim, mas como média móvel dos jogos ANTERIORES
de cada clube, que é informação que existia antes da bola rolar.

A cotação é a exceção, e por um motivo concreto: ela é publicada antes do
jogo. `market.opening` e `market.closing` são o que o mercado achava antes do
apito inicial, então descrevem a partida legitimamente.

POR QUE ESTE MÓDULO EXISTE E NÃO O `HistoricalProjectionV3`. Aquele lê o lake
e não conhece mercado nem estatística — os dois blocos que passaram a existir
com `atlas.match.v1`. Reaproveita-se dele a matemática de Elo e força
(`atlas/strength/formulas.py`), que é a mesma; o que muda é a fonte e o que
mais se extrai dela.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Iterator

from atlas.vector.contexto import _Tabela, coordenadas, distancia_km, em_jogo

#: Quantos jogos anteriores compõem uma média móvel.
#:
#: DEZ, E NÃO CINCO, POR MEDIÇÃO. Começou em 5 — o que a literatura de forma
#: usa. A lente `gols` não batia a taxa base com isso (+1,7%, dentro de uma
#: margem de 3,7), e a hipótese era que volume de gols é mais ruidoso que
#: resultado e precisa de janela maior. Medido em 5, 10 e 20:
#:
#:     janela   gols     resultado  desempenho  contexto
#:        5    +1,7% ✗    +10,7%      +9,7%      +3,3% ✗
#:       10    +5,9% ✓    +12,0%      +8,8%      +1,7% ✗
#:       20    +4,4% ✓
#:
#: `gols` sai de inconclusiva para conclusiva; as outras se movem DENTRO da
#: própria margem, ou seja, não mudam de forma mensurável. 20 é pior que 10:
#: janela longa demais dilui o estado recente.
#:
#: Isto atravessa toda feature de janela, então é um só lugar de propósito —
#: e mudar de novo exige remedir as quatro lentes, não só a que motivou.
JANELA = 10

#: Elo. K alto move rápido demais com 380 jogos por temporada; 20 é o valor
#: que `atlas/strength` já usa, mantido para os dois caminhos concordarem.
ELO_INICIAL = 1500.0
ELO_K = 20.0


@dataclass(frozen=True)
class Feature:
    """Uma dimensão, com o que ela é e por que está aqui."""

    nome: str
    descricao: str
    #: Fonte da informação: 'historico' (jogos anteriores) ou 'mercado'
    #: (cotação publicada antes do apito). Serve para a régua reportar
    #: quanto cada bloco contribui.
    bloco: str


FEATURES: tuple[Feature, ...] = (
    # --- Força relativa, do histórico ---
    Feature("elo_delta", "diferença de Elo entre mandante e visitante", "historico"),
    Feature("home_attack", "gols marcados por jogo pelo mandante, janela móvel", "historico"),
    Feature("away_attack", "gols marcados por jogo pelo visitante", "historico"),
    Feature("home_defense", "gols sofridos por jogo pelo mandante", "historico"),
    Feature("away_defense", "gols sofridos por jogo pelo visitante", "historico"),
    Feature("home_form", "pontos por jogo do mandante na janela", "historico"),
    Feature("away_form", "pontos por jogo do visitante na janela", "historico"),
    Feature("h2h_advantage", "vantagem histórica no confronto direto", "historico"),
    Feature("rest_advantage", "diferença de dias de descanso", "historico"),
    Feature("season_progress", "fração da temporada já disputada", "historico"),
    # --- Produção e disciplina, do histórico (nunca da partida corrente) ---
    Feature("home_shots_rate", "chutes por jogo do mandante, janela móvel", "historico"),
    Feature("away_shots_rate", "chutes por jogo do visitante", "historico"),
    Feature("home_accuracy", "fração dos chutes do mandante que vão ao alvo", "historico"),
    Feature("away_accuracy", "fração dos chutes do visitante que vão ao alvo", "historico"),
    Feature("home_corners_rate", "escanteios por jogo do mandante", "historico"),
    Feature("away_corners_rate", "escanteios por jogo do visitante", "historico"),
    Feature("home_discipline", "cartões por jogo do mandante", "historico"),
    Feature("away_discipline", "cartões por jogo do visitante", "historico"),
    Feature("expected_goals_total", "gols por jogo esperados, somando os dois lados", "historico"),
    # --- Mercado: publicado ANTES do apito, logo descreve a partida ---
    Feature("implied_home", "probabilidade implícita do mandante, no fechamento", "mercado"),
    Feature("implied_draw", "probabilidade implícita do empate, no fechamento", "mercado"),
    Feature("implied_away", "probabilidade implícita do visitante, no fechamento", "mercado"),
    Feature("favourite_margin", "quanto o favorito se destaca do segundo", "mercado"),
    Feature("line_movement", "quanto a probabilidade do mandante andou da abertura ao fechamento", "mercado"),
    Feature("overround", "margem da casa — proxy de confiança do mercado", "mercado"),
    # --- Mercado, as colunas que estavam no arquivo e ninguém lia ---
    #
    # 106 colunas baixadas, 29 usadas. Estas três eram das 77 ignoradas, e
    # cada uma responde algo que nenhuma das outras responde.
    Feature(
        "market_disagreement",
        "quanto as casas discordam do preço — melhor preço contra a média",
        "mercado",
    ),
    Feature(
        "implied_over_2_5",
        "probabilidade implícita de o jogo passar da linha de gols",
        "mercado",
    ),
    Feature(
        "handicap_line",
        "diferença de gols que o mercado espera, na direção do mandante",
        "mercado",
    ),
    # --- Contexto: a tabela e a geografia ---
    #
    # Medido: o mercado separa as partidas argentinas 38% menos que as
    # inglesas, e a ordem desse desvio é exatamente a ordem do desempenho das
    # lentes. Num campeonato equilibrado o que distingue duas partidas não é
    # qualidade, é contexto — e o mercado precifica qualidade.
    Feature("table_position_home", "posição do mandante na tabela, normalizada", "contexto"),
    Feature("table_position_away", "posição do visitante na tabela, normalizada", "contexto"),
    Feature("stakes", "quanto a temporada ainda está indefinida para os dois", "contexto"),
    Feature("travel_distance", "km entre as cidades dos dois clubes", "contexto"),
)

NOMES: tuple[str, ...] = tuple(f.nome for f in FEATURES)


@dataclass
class _Clube:
    elo: float = ELO_INICIAL
    gols_pro: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    gols_contra: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    pontos: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    chutes: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    no_alvo: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    escanteios: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    cartoes: deque = field(default_factory=lambda: deque(maxlen=JANELA))
    ultimo_jogo: datetime | None = None
    jogos: int = 0


def _media(valores: deque, padrao: float = 0.0) -> float:
    return sum(valores) / len(valores) if valores else padrao


def _prob_implicitas(precos: dict[str, Any]) -> tuple[float, float, float, float]:
    """Probabilidades implícitas normalizadas, e o overround.

    Uma cotação decimal `p` implica `1/p`. As três somam mais que 1 — o
    excesso é a margem da casa. Normalizar remove a margem e deixa três
    números que somam 1, que é o que se pode comparar entre casas e entre
    épocas; a margem sai como dimensão própria porque ela também diz algo
    (mercado raso cobra mais).
    """
    inversos = [1.0 / float(precos[chave]) for chave in ("home", "draw", "away")]
    total = sum(inversos)
    if total <= 0:
        return 0.0, 0.0, 0.0, 0.0
    return inversos[0] / total, inversos[1] / total, inversos[2] / total, total


@dataclass(frozen=True)
class Linha:
    """Uma partida, com o que se sabia dela antes do apito."""

    uid: str
    competition: str
    season: str
    kickoff: datetime
    home: str
    away: str
    features: dict[str, float]
    #: O desfecho. NÃO entra no vetor — serve para a régua medir se a
    #: vizinhança recuperada descreve alguma coisa.
    label: str


def _rotulo(casa: int, fora: int) -> str:
    if casa > fora:
        return "HOME_WIN"
    if fora > casa:
        return "AWAY_WIN"
    return "DRAW"


def construir(documentos: Iterable[dict]) -> Iterator[Linha]:
    """Percorre as partidas em ordem de data e emite uma linha por jogo.

    WALK-FORWARD, E É ISSO QUE TORNA ESTAS FEATURES HONESTAS: o estado de
    cada clube é lido ANTES de a partida ser aplicada a ele. Inverter as duas
    metades do laço faria cada partida se descrever com o próprio resultado —
    o vetor ficaria excelente e não significaria nada.
    """
    clubes: dict[str, _Clube] = defaultdict(_Clube)
    jogos_na_temporada: dict[tuple[str, str], int] = defaultdict(int)
    h2h: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])

    # A CLASSIFICAÇÃO, montada jogo a jogo junto com o resto.
    tabelas: dict[tuple[str, str], _Tabela] = defaultdict(_Tabela)
    mapa_coord = coordenadas()

    # `documentos` é um iterável que pode ser um gerador, e o tamanho de cada
    # temporada precisa ser conhecido ANTES do laço — `season_progress`
    # dividia por 380 fixo, e as temporadas argentinas vão de 190 a 510.
    documentos = list(documentos)
    for documento in documentos:
        chave = (
            documento["identity"]["competition"],
            documento["identity"]["season"],
        )
        tabelas[chave].total_de_partidas += 1

    for documento in documentos:
        identidade = documento["identity"]
        resultado = documento["result"]
        # Blocos que uma competição pode legitimamente não ter — ver
        # `EXIGENCIA_POR_COMPETICAO`. Ausentes, as dimensões que dependem
        # deles são OMITIDAS mais abaixo, nunca preenchidas com zero.
        mercado = documento.get("market") or {}
        estatistica = documento.get("stats")

        casa, fora = identidade["home_club_id"], identidade["away_club_id"]
        kickoff = _instante(identidade["kickoff_utc"])
        chave_temporada = (identidade["competition"], identidade["season"])
        tabela = tabelas[chave_temporada]
        c, f = clubes[casa], clubes[fora]

        implicita_casa, implicita_empate, implicita_fora, overround = _prob_implicitas(
            mercado["closing"]
        )
        ordenadas = sorted([implicita_casa, implicita_empate, implicita_fora], reverse=True)
        # Sem abertura não há movimento de linha. `None` aqui vira dimensão
        # ausente; zero diria "o mercado não se mexeu", que é uma afirmação
        # sobre algo que não foi observado.
        abertura = mercado.get("opening")
        abertura_casa = _prob_implicitas(abertura)[0] if abertura else None

        par = tuple(sorted((casa, fora)))
        historico = h2h[par]
        total_h2h = sum(historico)
        # Positivo favorece o MANDANTE desta partida, e o par é guardado em
        # ordem alfabética — sem esta inversão, metade dos confrontos teria
        # o sinal trocado.
        if total_h2h:
            vitorias_casa = historico[0] if par[0] == casa else historico[1]
            vitorias_fora = historico[1] if par[0] == casa else historico[0]
            vantagem = (vitorias_casa - vitorias_fora) / total_h2h
        else:
            vantagem = 0.0

        descanso_casa = _dias(c.ultimo_jogo, kickoff)
        descanso_fora = _dias(f.ultimo_jogo, kickoff)

        features = {
            "elo_delta": (c.elo - f.elo) / 400.0,
            "home_attack": _media(c.gols_pro),
            "away_attack": _media(f.gols_pro),
            "home_defense": _media(c.gols_contra),
            "away_defense": _media(f.gols_contra),
            "home_form": _media(c.pontos),
            "away_form": _media(f.pontos),
            "h2h_advantage": vantagem,
            "rest_advantage": max(-1.0, min(1.0, (descanso_casa - descanso_fora) / 14.0)),
            # FRAÇÃO DA TEMPORADA, contra o tamanho REAL dela.
            #
            # Dividia por 380 fixo. A Premier League tem 380 e não se notava;
            # as temporadas argentinas do corpus vão de 190 a 510, então a
            # dimensão de maior peso de `contexto` estava comprimida a um
            # terço da escala lá — ou estourando 1,0 nas de 510.
            "season_progress": min(
                1.0,
                jogos_na_temporada[chave_temporada]
                / max(tabelas[chave_temporada].total_de_partidas, 1),
            ),
            "expected_goals_total": _media(c.gols_pro) + _media(f.gols_pro),
            "implied_home": implicita_casa,
            "implied_draw": implicita_empate,
            "implied_away": implicita_fora,
            "favourite_margin": ordenadas[0] - ordenadas[1],
            "overround": overround - 1.0,
        }

        # AS DIMENSÕES QUE PODEM FALTAR, E POR QUE FALTAR É DIFERENTE DE ZERO.
        #
        # Uma janela vazia de chutes daria `_media([]) == 0.0`, e 0 chutes por
        # jogo não é "não observado" — é o extremo inferior da escala. Gravado
        # assim, todo clube sem estatística viraria um outlier idêntico aos
        # outros clubes sem estatística, e as partidas do Brasileirão
        # apareceriam parecidíssimas entre si por um motivo que não existe.
        #
        # Omitida, a dimensão é lida como a média do corpus na consulta, o que
        # padroniza para zero e não entra nem no produto interno nem na norma
        # do cosseno: ela realmente não informa nada.
        if c.chutes:
            features["home_shots_rate"] = _media(c.chutes)
            features["home_accuracy"] = _proporcao(c.no_alvo, c.chutes)
        if f.chutes:
            features["away_shots_rate"] = _media(f.chutes)
            features["away_accuracy"] = _proporcao(f.no_alvo, f.chutes)
        if c.escanteios:
            features["home_corners_rate"] = _media(c.escanteios)
        if f.escanteios:
            features["away_corners_rate"] = _media(f.escanteios)
        if c.cartoes:
            features["home_discipline"] = _media(c.cartoes)
        if f.cartoes:
            features["away_discipline"] = _media(f.cartoes)
        if abertura_casa is not None:
            features["line_movement"] = implicita_casa - abertura_casa

        # CONTEXTO: a tabela ANTES desta partida, e a geografia.
        #
        # `tabela` só recebe este jogo no fim do laço, junto com o Elo e as
        # janelas — a mesma regra walk-forward. Ler a classificação já com o
        # resultado dentro faria a posição descrever o próprio desfecho.
        posicao_casa = tabela.posicao_normalizada(casa)
        posicao_fora = tabela.posicao_normalizada(fora)
        if posicao_casa is not None:
            features["table_position_home"] = posicao_casa
        if posicao_fora is not None:
            features["table_position_away"] = posicao_fora

        # O QUE ESTÁ EM JOGO, para o lado que tem mais a perder. Um jogo em
        # que um dos dois luta contra o rebaixamento é um jogo tenso, mesmo
        # que o outro não tenha nada — e a média dos dois esconderia isso.
        aposta_casa = em_jogo(tabela, casa, identidade["competition"])
        aposta_fora = em_jogo(tabela, fora, identidade["competition"])
        apostas = [a for a in (aposta_casa, aposta_fora) if a is not None]
        if apostas:
            features["stakes"] = max(apostas)

        km = distancia_km(casa, fora, mapa_coord)
        if km is not None:
            features["travel_distance"] = km

        # QUANTO AS CASAS DISCORDAM. O melhor preço disponível sempre paga
        # mais que a média, então a soma das probabilidades implícitas dele é
        # sempre menor. A diferença entre as duas somas é o espalhamento do
        # mercado: perto de zero, todo mundo precifica igual; longe, as casas
        # não concordam sobre o que este jogo é.
        #
        # Nenhuma cotação de uma casa só carrega isso, e era tudo o que o
        # Atlas lia. É também o único sinal novo que existe em TODAS as
        # competições — over/under e handicap não existem nos arquivos
        # sul-americanos.
        espalhamento = mercado.get("spread")
        if isinstance(espalhamento, dict):
            consenso = espalhamento.get("consensus")
            melhor = espalhamento.get("best")
            if isinstance(consenso, dict) and isinstance(melhor, dict):
                features["market_disagreement"] = _soma_implicitas(
                    consenso
                ) - _soma_implicitas(melhor)

        # A PERGUNTA DA LENTE `gols`, RESPONDIDA PELO MERCADO. Normalizada
        # entre over e under: a cotação de over sozinha carrega a margem da
        # casa e não daria para comparar entre partidas.
        totais = mercado.get("totals")
        if isinstance(totais, dict):
            try:
                p_over = 1.0 / float(totais["over"])
                p_under = 1.0 / float(totais["under"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                p_over = p_under = 0.0
            if p_over + p_under > 0:
                features["implied_over_2_5"] = p_over / (p_over + p_under)

        # O FAVORITISMO NUMA ESCALA CONTÍNUA. As três cotações do 1x2
        # arredondam partidas diferentes para o mesmo lugar; a linha do
        # handicap distingue -0,25 de -0,75.
        handicap = mercado.get("handicap")
        if isinstance(handicap, dict) and handicap.get("line") is not None:
            features["handicap_line"] = float(handicap["line"])

        gols_casa, gols_fora = resultado["home_goals"], resultado["away_goals"]
        yield Linha(
            uid=documento.get("__uid__", ""),
            competition=identidade["competition"],
            season=identidade["season"],
            kickoff=kickoff,
            home=casa,
            away=fora,
            features=features,
            label=_rotulo(gols_casa, gols_fora),
        )

        # --- só a partir daqui a partida existe para os próximos jogos ---
        _aplicar(c, f, gols_casa, gols_fora, estatistica, kickoff)
        # A classificação entra aqui, junto com o resto do estado. Movê-la
        # para antes do `yield` faria a posição de cada clube já conter o
        # resultado da partida que ela deveria descrever.
        tabela.aplicar(casa, fora, gols_casa, gols_fora)
        jogos_na_temporada[chave_temporada] += 1
        indice = 0 if gols_casa > gols_fora else 1 if gols_fora > gols_casa else 2
        if indice == 2:
            historico[2] += 1
        elif par[0] == casa:
            historico[0 if indice == 0 else 1] += 1
        else:
            historico[1 if indice == 0 else 0] += 1


def _aplicar(
    c: _Clube,
    f: _Clube,
    gols_casa: int,
    gols_fora: int,
    estatistica: dict | None,
    kickoff: datetime,
) -> None:
    esperado_casa = 1.0 / (1.0 + 10 ** ((f.elo - c.elo) / 400.0))
    real_casa = 1.0 if gols_casa > gols_fora else 0.5 if gols_casa == gols_fora else 0.0
    ajuste = ELO_K * (real_casa - esperado_casa)
    c.elo += ajuste
    f.elo -= ajuste

    for clube, pro, contra, pontos, lado in (
        (c, gols_casa, gols_fora, _pontos(gols_casa, gols_fora), "home"),
        (f, gols_fora, gols_casa, _pontos(gols_fora, gols_casa), "away"),
    ):
        clube.gols_pro.append(pro)
        clube.gols_contra.append(contra)
        clube.pontos.append(pontos)
        # Sem estatística a janela não avança — e não avança com zero.
        # Empurrar 0 chutes diria que o clube não finalizou, e a média móvel
        # carregaria essa afirmação por dez jogos.
        if estatistica is not None:
            dados = estatistica[lado]
            clube.chutes.append(float(dados["shots"]))
            clube.no_alvo.append(float(dados["shots_on_target"]))
            clube.escanteios.append(float(dados["corners"]))
            clube.cartoes.append(
                float(dados["yellow_cards"]) + float(dados["red_cards"])
            )
        clube.ultimo_jogo = kickoff
        clube.jogos += 1


def _pontos(pro: int, contra: int) -> float:
    return 3.0 if pro > contra else 1.0 if pro == contra else 0.0


def _soma_implicitas(precos: dict) -> float:
    """Soma das probabilidades implícitas das três saídas.

    Sem normalizar, de propósito: é justamente a margem embutida que se quer
    comparar entre o melhor preço e a média do mercado.
    """
    total = 0.0
    for lado in ("home", "draw", "away"):
        try:
            valor = float(precos[lado])
        except (KeyError, TypeError, ValueError):
            return 0.0
        if valor <= 0:
            return 0.0
        total += 1.0 / valor
    return total


def _proporcao(numerador: deque, denominador: deque) -> float:
    total = sum(denominador)
    return sum(numerador) / total if total else 0.0


def _dias(anterior: datetime | None, atual: datetime) -> float:
    # Sem jogo anterior, 7 dias: o intervalo típico de calendário. Zero diria
    # "jogou ontem", que é falso e empurraria a estreia de todo clube para um
    # extremo da escala.
    return 7.0 if anterior is None else max(0.0, (atual - anterior).total_seconds() / 86400.0)


def _instante(valor: str) -> datetime:
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
