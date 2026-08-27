"""O cenário do PR-06.2 — o do PR-06.1, mais AUSÊNCIA de verdade.

O PROBLEMA QUE ELE RESOLVE (§139, §140). O cenário do PR-06.1 produz cobertura
de 100 % em todo candidato: os oito eixos que sobreviveram ao ajuste são todos
de xG em janela móvel, e a janela é computável em TODO corte de TODA partida —
ela vale zero quando não houve chute, e zero é um valor medido. Um E2E assim
passaria sem nunca tocar o piso de cobertura, a penalidade ou a atrição, que é
o PR inteiro.

    «Um cenário onde todos os candidates têm 100 % coverage não valida
     este PR.» — §140

O QUE ELE PRODUZ, MEDIDO — e não estimado:

    perfil resolvido   6 eixos: xG em janela de 10 min (casa/fora/diferença) e
                       o gap até a partida anterior (casa/fora/diferença)
    piso               5s ≥ 3·6 = 18  →  s ≥ 4, e o mínimo absoluto é 4
    candidatos         s = 6 (completos) · s = 4 (EXATAMENTE no piso) ·
                       s = 3 (ABAIXO do piso, recusados)

DE ONDE VEM A AUSÊNCIA — e a resposta saiu de MEDIÇÃO, depois de a primeira
hipótese se mostrar errada.

A HIPÓTESE ERRADA ERA O MERCADO. `_do_mercado` devolve indisponível quando a
partida não tem cotação elegível, então publicar odds para parte das partidas
pareceria a fonte natural de ausência — e são seis eixos de uma vez. O cenário
publica as cotações (setenta e duas observações canônicas chegam ao banco), e
TODO eixo de mercado continua saindo `INSUFFICIENT_SAMPLE` com
`available_count = 0`.

    O MOTIVO É O FAIL-CLOSED DO PR-05.1, e ele está certo. Uma cotação sem
    `observed_at` é classificada `FactKind.ODDS_CLOSING`, que mapeia para
    `TemporalAvailability.UNKNOWN`; a guarda de vazamento recusa, e o estado
    sai `TEMPORALLY_UNAVAILABLE` em todo corte. E o caminho de ingestão NÃO
    TEM papel semântico para o carimbo de observação de uma cotação — não há
    por onde declará-lo.

    Ou seja: hoje a família de mercado é estruturalmente indisponível de ponta
    a ponta, e os catorze eixos de mercado `INSUFFICIENT_SAMPLE` medidos no
    PR-05.5.2 não são artefato de corpus pequeno. As cotações ficam no cenário
    de propósito, e há teste que fixa esse comportamento.

A FONTE QUE FUNCIONA É O CONTEXTO. `PREV_KICKOFF_GAP_HOURS` devolve
indisponível quando o time não tem partida anterior naquela competição — o que
é ausência real, por partida, sem nada fabricado.

TRÊS COISAS PRECISARAM MUDAR EM RELAÇÃO AO PR-06.1:

**OS APITOS DEIXARAM DE SER EQUIDISTANTES.** Com sete dias exatos entre todas
as partidas, todo gap vale 168 horas, o IQR da competição é zero e os eixos de
contexto saem `DEGENERATE_SCALE` — indisponíveis para TODO mundo, o que os tira
do perfil em vez de os tornar parcialmente ausentes.

**O RODÍZIO GIRA.** Com `away = (i + 1) % TIMES` fixo, o visitante é sempre o
time que estreia naquela partida: `ctx_..._away` nunca tem observação, e o eixo
sai por amostra insuficiente. Girando o deslocamento, os dois lados passam a
ter histórico depois da primeira volta.

**A DENSIDADE DE CHUTES CAIU DE DEZ PARA QUATRO.** Com dez, nove eixos de xG
cabem no perfil; como a janela de xG é computável em todo corte, todo candidato
teria pelo menos nove eixos e NENHUM cairia abaixo do piso. Com quatro, só as
janelas de dez minutos sobrevivem — e aí a ausência do contexto move a
cobertura de um candidato de um lado para o outro da fronteira.

NADA DISSO É FABRICAÇÃO DE AUSÊNCIA. Uma liga de verdade tem times estreando na
competição e partidas sem cotação publicada; o cenário reproduz as duas coisas
num corpus pequeno o bastante para caber num E2E.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.teams.models import Team
from tests.support.corpus import Corpus, TimeSintetico
from tests.support.retrieval_scenario import referencia_de_partida

#: Quantas partidas o cenário do PR-06.2 gera.
#:
#: DEZOITO, e não doze. O corpus precisa de partidas bastantes para que a
#: metade de REFERÊNCIA tenha as duas coisas ao mesmo tempo — partidas COM
#: cotação e partidas SEM —, e ainda junte trinta observações por eixo de
#: mercado. Com doze, a referência teria cinco partidas e o corte entre «com» e
#: «sem» deixaria um dos dois lados pequeno demais para provar qualquer coisa.
PARTIDAS: Final[int] = 18

#: Quantos times o cenário tem.
#:
#: SEIS, e o número é o que faz os eixos de CONTEXTO caberem no perfil. O gap
#: até a partida anterior só existe a partir da segunda aparição de cada time;
#: com times demais, a metade de referência acaba antes de todos terem uma
#: segunda, e `ctx_..._away` fica com observações de menos para o ajuste.
TIMES: Final[int] = 6

#: Quantos chutes cada time dá por partida.
#:
#: QUATRO, E NÃO DEZ. O número saiu de medição, e a tabela é curta:
#:
#:     10 chutes  ->  9 eixos de xG no perfil  ->  s >= 9 sempre
#:      6 chutes  ->  5 eixos de xG            ->  s >= 5 sempre
#:      4 chutes  ->  3 eixos de xG            ->  s = 3, 4 ou 6
#:
#: Só a última linha produz candidato ABAIXO do piso, e é por isso que ela é a
#: escolhida: com xG em todo corte, o piso só é alcançável quando os eixos de
#: xG que cabem no perfil são poucos o bastante.
CHUTES_POR_TIME: Final[int] = 4

#: Os intervalos entre apitos consecutivos, em dias.
#:
#: ELES SÃO VARIADOS DE PROPÓSITO. Ver o cabeçalho: sete dias fixos zeram o IQR
#: do gap e tiram os eixos de contexto do perfil. A sequência se repete, e é
#: determinística — o cenário não sorteia nada.
INTERVALOS: Final[tuple[int, ...]] = (3, 7, 4, 10, 5, 14)

#: De quantas em quantas partidas UMA fica sem cotação.
#:
#: UMA A CADA TRÊS, e o número tem conta atrás. Dois terços das partidas com
#: odds dão, na metade de referência, observações de sobra para o ajuste; o
#: terço restante é a ausência que o piso de cobertura precisa enxergar.
SEM_COTACAO_A_CADA: Final[int] = 3

_SEMENTE: Final[str] = "pr062e2e"
_FIM_DE_LINHA: Final[bytes] = bytes([10])

CABECALHO_DE_ODDS: Final[bytes] = b"Competition,Season,Kickoff,Home,Away,Book,OddsH,OddsD,OddsA\n"

#: As duas casas. DUAS, e com preços diferentes — ver o cabeçalho.
CASAS: Final[tuple[str, ...]] = ("BET365", "PINNACLE")


def tem_cotacao(indice: int) -> bool:
    """Se a partida `indice` publica cotação.

    ELA É UMA FUNÇÃO E NÃO UMA LISTA para que o teste possa perguntar o mesmo
    que o gerador respondeu — «este candidato deveria ter mercado?» é a
    pergunta que separa uma ausência esperada de um defeito de leitura.
    """
    return indice % SEM_COTACAO_A_CADA != 0


def cenario(regime: Any, *, partidas: int = PARTIDAS) -> Corpus:
    """Partidas com apitos IRREGULARES, na mesma competição.

    `partidas` É PARAMETRIZÁVEL PARA O BENCHMARK, e o padrão é o do E2E. O
    cenário de medição precisa de um universo maior que oito candidatos — ver
    o §146 —, e a alternativa seria um segundo gerador que divergiria deste no
    dia em que um dos dois mudasse.
    """
    liga = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
    temporada = Season.create(
        competition_id=liga.id,
        label="2024/25",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=regime,
    )
    times = _times()
    jogadores = tuple(
        Player(
            id=PlayerId.derive(_SEMENTE, f"jogador-{i:02d}"),
            canonical_name=f"Atleta {i:02d}",
            nationality="GB",
        )
        for i in range(TIMES)
    )
    jogos = tuple(
        Match(
            id=MatchId.derive(_SEMENTE, f"partida-{i:02d}"),
            competition_id=liga.id,
            season_id=temporada.id,
            regime=regime,
            stage=Stage(type=StageType.LEAGUE, round_number=1 + i),
            home_team_id=times[i % TIMES].id,
            away_team_id=times[_adversario(i)].id,
            scheduled_kickoff=instant(
                datetime(2024, 9, 1, 15, 0, tzinfo=UTC) + timedelta(days=_dias_ate(i))
            ),
            lifecycle=MatchLifecycle.RECONCILED,
        )
        for i in range(partidas)
    )
    return Corpus(
        competitions=(liga,),
        seasons=(temporada,),
        teams=tuple(
            TimeSintetico(team=t, competition=CompetitionCode.PREMIER_LEAGUE, alias="")
            for t in times
        ),
        aliases=(),
        players=jogadores,
        tenures=(),
        matches=jogos,
    )


def _times() -> list[Team]:
    return [
        Team(
            id=TeamId.derive(_SEMENTE, f"time-{i:02d}"),
            canonical_name=f"Clube PR62-{i:02d}",
            country="GB",
        )
        for i in range(TIMES)
    ]


def _adversario(indice: int) -> int:
    """Quem joga fora na partida `indice`.

    O RODÍZIO GIRA, e o motivo é o contexto: com `away = (i + 1) % TIMES` fixo,
    o time visitante da partida `i` é sempre o que estreia nela — logo ele
    NUNCA tem partida anterior, `ctx_..._away` fica sem observação, e o eixo sai
    do perfil por amostra insuficiente em vez de virar ausência parcial.

    Girando o deslocamento a cada volta, todos os times já apareceram depois da
    primeira rodada completa, e as partidas seguintes têm os dois lados com
    histórico — que é a mistura que o §139 pede.

    O DESLOCAMENTO NUNCA É ZERO, e a aritmética é o que garante isso. A versão
    ingênua — `(i + 1 + i // TIMES) % TIMES` — passa em dezoito partidas e
    QUEBRA em noventa e seis: quando `i // TIMES ≡ 5 (mod 6)`, o deslocamento
    volta a ser múltiplo de seis e o mandante enfrenta a si mesmo. O
    construtor de `Match` recusa, e com razão. Tomando o resto por
    `TIMES - 1` e somando um, o deslocamento fica em `1..TIMES-1` por
    construção, para todo `i`.
    """
    deslocamento = 1 + (indice // TIMES) % (TIMES - 1)
    return (indice + deslocamento) % TIMES


def _dias_ate(indice: int) -> int:
    """Quantos dias depois da primeira partida a partida `indice` acontece."""
    return sum(INTERVALOS[j % len(INTERVALOS)] for j in range(indice))


def fonte_publica(corpus: Corpus) -> bytes:
    """O CSV da ingestão — uma linha por partida."""
    por_id = {t.team.id: t.team for t in corpus.teams}
    linhas = [b"Competition,Season,Kickoff,Home,Away,HG,AG\n"]
    for i, jogo in enumerate(corpus.matches):
        casa = por_id[jogo.home_team_id].canonical_name
        fora = por_id[jogo.away_team_id].canonical_name
        linhas.append(
            (
                f"Premier League,2024/25,{jogo.scheduled_kickoff.isoformat()},"
                f"{casa},{fora},{1 + i % 3},{i % 2}\n"
            ).encode()
        )
    return b"".join(linhas)


def fonte_de_odds(corpus: Corpus) -> bytes:
    """As cotações — DUAS casas, e só em parte das partidas.

    OS PREÇOS VARIAM ENTRE PARTIDAS E ENTRE CASAS, e as duas variações têm
    função: a primeira dá dispersão à MEDIANA da competição, a segunda dá
    dispersão ao IQR entre casas. Sem uma delas, metade dos eixos de mercado
    sai `DEGENERATE_SCALE` e some do perfil — que é o oposto do que este
    cenário existe para produzir.
    """
    por_id = {t.team.id: t.team for t in corpus.teams}
    linhas = [CABECALHO_DE_ODDS]
    for i, jogo in enumerate(corpus.matches):
        if not tem_cotacao(i):
            continue
        casa = por_id[jogo.home_team_id].canonical_name
        fora = por_id[jogo.away_team_id].canonical_name
        for n, book in enumerate(CASAS):
            local = 1.50 + 0.13 * ((i + 2 * n) % 11)
            empate = 3.10 + 0.17 * ((i + 3 * n) % 7)
            visitante = 2.40 + 0.21 * ((i + 5 * n) % 9)
            linha = (
                f"Premier League,2024/25,{jogo.scheduled_kickoff.isoformat()},"
                f"{casa},{fora},{book},{local:.2f},{empate:.2f},{visitante:.2f}"
            )
            linhas.append(linha.encode() + _FIM_DE_LINHA)
    return b"".join(linhas)


def fonte_de_eventos(corpus: Corpus, cabecalho: bytes) -> bytes:
    """Os mesmos chutes densos do PR-06.1, sobre dezoito partidas.

    A DENSIDADE NÃO MUDOU e não deveria mudar: ela é o que faz os eixos de xG
    caberem no perfil, e o PR-06.2 mede o efeito da política de AUSÊNCIA — não
    o de um espaço de features diferente.
    """
    linhas = [cabecalho]
    for i, _ in enumerate(corpus.matches):
        ref = referencia_de_partida(i)
        atleta = f"pr061-player-{i % TIMES:02d}"
        sequencia = 0
        for n in range(CHUTES_POR_TIME):
            for lado in ("h", "a"):
                sequencia += 1
                time_do_chute = f"pr061-team-{lado}{i:02d}"
                minuto = 3 + n * 8 + (i + n + (0 if lado == "h" else 4)) % 7
                periodo = "FIRST_HALF" if minuto <= 45 else "SECOND_HALF"
                xg = 0.05 + 0.07 * ((i + 3 * n + (0 if lado == "h" else 2)) % 9)
                tipo = "goal" if n % 4 == 1 and lado == "h" else "shot"
                linha = (
                    f"e{i:02d}{lado}{n:02d},{ref},{tipo},{periodo},{minuto},0,"
                    f"{sequencia},{time_do_chute},{atleta},0.90,0.50,GOAL,"
                    f"RIGHT_FOOT,{xg:.2f},,NEW,"
                )
                linhas.append(linha.encode() + _FIM_DE_LINHA)
    return b"".join(linhas)
