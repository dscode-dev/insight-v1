"""O corpus sintético do benchmark — determinístico, e realista onde importa.

POR QUE NÃO SÃO STRINGS ALEATÓRIAS (§4). Um benchmark sobre texto aleatório
mede o normalizador e mais nada: nenhum nome casa, nenhum alias resolve,
nenhum candidato é pontuado, e o número que sai é o custo de percorrer uma
lista. O que precisamos medir é a RESOLUÇÃO — e ela só acontece quando o texto
da fonte tem uma entidade canônica do outro lado esperando por ele.

Então o corpus tem os dois lados: um registro canônico (competições,
temporadas, times, jogadores, partidas) e linhas de fonte que apontam para
ele por caminhos DIFERENTES e conhecidos:

    ALIAS       `Ashford Rov`      → alias registrado, casamento exato
    CANONICAL   `Ashford Rovers`   → nome canônico normalizado, exato
    SIMILAR     `Sahford Rovers`   → só similaridade: pontua, NÃO resolve
    UNKNOWN     `Clube Externo 71` → nada parecido: nem candidato gera

A distribuição entre eles é declarada e verificada, e é ela que faz o
benchmark exercitar o caminho barato, o intermediário e a busca de candidatos
em proporções que a gente escolheu em vez de descobrir.

DETERMINISMO É REQUISITO, NÃO CONVENIÊNCIA (§6). Duas execuções do benchmark
que gerem corpus diferente não são comparáveis, e a comparação entre execuções
é a única coisa que um número de throughput permite fazer. Todo id é derivado
por `uuid5` de uma chave natural, e todo sorteio passa por um `random.Random`
com semente explícita. Não há `uuid4` nem `random` de módulo neste arquivo.
"""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import EntityAlias
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer

#: A semente do corpus. Mudá-la muda TODO o cenário, e por isso ela é uma
#: constante deste arquivo e não um parâmetro com valor padrão espalhado.
SEED: Final[int] = 20_260_813

_INICIO_DOS_REGIMES: Final[datetime] = datetime(1990, 1, 1, tzinfo=UTC)

#: Cem topônimos, montados de vinte prefixos por cinco sufixos. São falsos de
#: propósito: nenhum clube real aparece aqui, então o benchmark não depende de
#: um catálogo que pode mudar.
_PREFIXOS: Final[tuple[str, ...]] = (
    "Ash", "Brad", "Chel", "Dun", "East", "Fair", "Glen", "Hart", "Kirk", "Lang",
    "Marl", "North", "Oak", "Pen", "Red", "Ship", "Thorn", "Vale", "West", "York",
)
_SUFIXOS: Final[tuple[str, ...]] = ("ford", "bury", "ton", "field", "dale")

#: Os núcleos são DISJUNTOS entre competições. É o que garante que dois times
#: de ligas diferentes nunca normalizem para a mesma chave por acidente — uma
#: colisão não intencional viraria ambiguidade e sujaria a distribuição.
_NUCLEOS: Final[dict[CompetitionCode, tuple[str, ...]]] = {
    CompetitionCode.PREMIER_LEAGUE: ("Rovers", "Wanderers", "Albion"),
    CompetitionCode.LA_LIGA: ("Deportivo", "Atletico", "Union"),
    CompetitionCode.BRA_SERIE_A: ("Esporte", "Nautico", "Portuaria"),
    CompetitionCode.UEFA_CHAMPIONS_LEAGUE: ("Olympique", "Sparta", "Dinamo"),
    CompetitionCode.CONMEBOL_LIBERTADORES: ("Nacional", "Central", "Junior"),
}
_PAISES: Final[dict[CompetitionCode, str]] = {
    CompetitionCode.PREMIER_LEAGUE: "GB",
    CompetitionCode.LA_LIGA: "ES",
    CompetitionCode.BRA_SERIE_A: "BR",
    CompetitionCode.UEFA_CHAMPIONS_LEAGUE: "DE",
    CompetitionCode.CONMEBOL_LIBERTADORES: "AR",
}
#: Competições cuja temporada atravessa o ano civil. É o que decide o formato
#: do rótulo canônico — e é a distinção que faz `2024` ser ambíguo (§15).
_ANO_PARTIDO: Final[frozenset[CompetitionCode]] = frozenset(
    {
        CompetitionCode.PREMIER_LEAGUE,
        CompetitionCode.LA_LIGA,
        CompetitionCode.UEFA_CHAMPIONS_LEAGUE,
    }
)

#: `Kickoff` CARREGA O FUSO. Sem ele, o horário da fonte vira meia-noite UTC,
#: o afastamento para o horário registrado fica em quinze horas e a evidência
#: temporal desaba de 1,00 para 0,15 — o bastante para a partida NÃO resolver.
#: É o comportamento certo do resolver (§25) e seria o cenário errado aqui:
#: mediríamos a recusa, não a resolução.
CABECALHO: Final[tuple[str, ...]] = (
    "Competition", "Season", "Date", "Kickoff", "Round",
    "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS",
)


class Caminho(StrEnum):
    """Por qual porta do resolver a linha entra. Conhecido na geração."""

    ALIAS = "ALIAS"
    CANONICAL = "CANONICAL"
    SIMILAR = "SIMILAR"
    UNKNOWN = "UNKNOWN"


#: A distribuição do benchmark (§5). Ela NÃO é 100% caminho barato de
#: propósito: um benchmark em que tudo resolve por chave exata mede um
#: `dict.get` e chama isso de resolução de identidade.
DISTRIBUICAO: Final[tuple[tuple[Caminho, float], ...]] = (
    (Caminho.ALIAS, 0.55),
    (Caminho.CANONICAL, 0.25),
    (Caminho.SIMILAR, 0.12),
    (Caminho.UNKNOWN, 0.08),
)


def _regime(codigo: RegimeCode = RegimeCode.DOUBLE_ROUND_ROBIN) -> CompetitionRegime:
    return CompetitionRegime(
        code=codigo,
        effective_from=instant(_INICIO_DOS_REGIMES),
        regulation_version="benchmark-v1",
    )


def _lugares() -> tuple[str, ...]:
    return tuple(f"{p}{s}" for p in _PREFIXOS for s in _SUFIXOS)


@final
@dataclass(frozen=True, slots=True)
class TimeSintetico:
    """Um clube do corpus e as quatro grafias pelas quais ele pode chegar."""

    team: Team
    competition: CompetitionCode
    alias: str

    @property
    def canonical(self) -> str:
        return self.team.canonical_name

    @property
    def similar(self) -> str:
        """A grafia com duas letras trocadas: pontua alto e NÃO resolve.

        A troca é no começo da primeira palavra de propósito: o bônus de
        prefixo do Jaro-Winkler só vale para prefixo idêntico, então mexer ali
        derruba o score para a faixa em que o resolver manda revisar — que é
        exatamente o caminho caro que queremos medir.
        """
        palavras = self.canonical.split(" ")
        cabeca = palavras[0]
        trocada = cabeca[1] + cabeca[0] + cabeca[2:]
        return " ".join([trocada, *palavras[1:]])


@final
@dataclass(frozen=True, slots=True)
class Corpus:
    """O registro canônico do cenário, inteiro e em memória.

    CABE EM MEMÓRIA DE PROPÓSITO: ele é o LADO DE DENTRO, o que já se conhece.
    O lado de fora — as cem mil linhas — nunca é materializado como lista:
    sai como bytes de CSV e volta em lotes, que é o caminho que o motor de
    verdade usa.
    """

    competitions: tuple[Competition, ...]
    seasons: tuple[Season, ...]
    teams: tuple[TimeSintetico, ...]
    aliases: tuple[EntityAlias, ...]
    players: tuple[Player, ...]
    tenures: tuple[PlayerTeamTenure, ...]
    matches: tuple[Match, ...]

    @property
    def size(self) -> str:
        return (
            f"{len(self.competitions)} competições · {len(self.seasons)} temporadas · "
            f"{len(self.teams)} times · {len(self.aliases)} aliases · "
            f"{len(self.players)} jogadores · {len(self.matches)} partidas"
        )

    def season_of(self, match: Match) -> Season:
        return next(s for s in self.seasons if s.id == match.season_id)

    def competition_of(self, match: Match) -> Competition:
        return next(c for c in self.competitions if c.id == match.competition_id)

    def team_of(self, team_id: TeamId) -> TimeSintetico:
        return next(t for t in self.teams if t.team.id == team_id)


def build_corpus(
    *,
    seasons_per_competition: int = 3,
    teams_per_competition: int = 60,
    players: int = 3_000,
    first_season_start_year: int = 2021,
) -> Corpus:
    """O registro canônico do benchmark. Mesma entrada, mesma saída, sempre."""
    normalizador = NameNormalizer()
    lugares = _lugares()

    competicoes: list[Competition] = []
    temporadas: list[Season] = []
    times: list[TimeSintetico] = []
    aliases: list[EntityAlias] = []
    partidas: list[Match] = []

    for codigo in CompetitionCode:
        competicao = Competition.from_code(codigo)
        competicoes.append(competicao)

        do_torneio: list[TimeSintetico] = []
        nucleos = _NUCLEOS[codigo]
        for indice in range(teams_per_competition):
            lugar = lugares[indice % len(lugares)]
            nucleo = nucleos[indice // len(lugares)]
            nome = f"{lugar} {nucleo}"
            sintetico = TimeSintetico(
                team=Team(
                    # DERIVADO, e não sorteado: `Team.register` usa `uuid4`, o
                    # que é certo em produção e errado num corpus que precisa
                    # ser o mesmo em duas execuções.
                    id=TeamId.derive("benchmark", codigo.value, nome),
                    canonical_name=nome,
                    country=_PAISES[codigo],
                ),
                competition=codigo,
                alias=f"{lugar} {nucleo[:3]}",
            )
            do_torneio.append(sintetico)
            times.append(sintetico)
            aliases.append(
                EntityAlias(
                    id=str(TeamId.derive("benchmark-alias", codigo.value, nome)),
                    entity_type=SubjectType.TEAM,
                    entity_id=sintetico.team.id,
                    alias_original=sintetico.alias,
                    alias_normalized=normalizador.normalize(sintetico.alias),
                    normalizer_version=normalizador.version,
                    created_at=instant(datetime(2026, 1, 1, tzinfo=UTC)),
                    created_by="benchmark-corpus",
                )
            )

        for n in range(seasons_per_competition):
            ano = first_season_start_year + n
            rotulo = f"{ano}/{str(ano + 1)[-2:]}" if codigo in _ANO_PARTIDO else str(ano)
            inicio = datetime(ano, 8, 1, tzinfo=UTC) if codigo in _ANO_PARTIDO else datetime(
                ano, 1, 15, tzinfo=UTC
            )
            fim = inicio + timedelta(days=300)
            temporada = Season.create(
                competition_id=competicao.id,
                label=rotulo,
                starts_at=instant(inicio),
                ends_at=instant(fim),
                regime=_regime(),
            )
            temporadas.append(temporada)
            partidas.extend(_partidas_da_temporada(competicao, temporada, do_torneio, inicio))

    jogadores, vinculos = _elenco(times, players)
    return Corpus(
        competitions=tuple(competicoes),
        seasons=tuple(temporadas),
        teams=tuple(times),
        aliases=tuple(aliases),
        players=tuple(jogadores),
        tenures=tuple(vinculos),
        matches=tuple(partidas),
    )


def _partidas_da_temporada(
    competicao: Competition,
    temporada: Season,
    times: Sequence[TimeSintetico],
    inicio: datetime,
) -> list[Match]:
    """Turno único entre todos os times, uma rodada por dia útil de calendário.

    UM CONFRONTO POR PAR, e não ida e volta: o resolver de partida distingue
    ida de volta pelo horário, e um corpus com os dois faria toda linha ter
    dois candidatos legítimos — o que mediria o desempate, não a resolução.
    O confronto invertido continua sendo gerado pelo LADO DA FONTE, nos casos
    negativos, que é onde ele interessa.
    """
    saida: list[Match] = []
    total = len(times)
    dia = 0
    for i in range(total):
        for j in range(i + 1, total):
            rodada = (i + j) % 38 + 1
            kickoff = inicio + timedelta(days=dia // 10, hours=15 + (dia % 3))
            dia += 1
            saida.append(
                Match(
                    id=MatchId.derive(
                        "benchmark",
                        str(temporada.id),
                        str(times[i].team.id),
                        str(times[j].team.id),
                    ),
                    competition_id=competicao.id,
                    season_id=temporada.id,
                    regime=_regime(),
                    stage=Stage(type=StageType.LEAGUE, round_number=rodada),
                    home_team_id=times[i].team.id,
                    away_team_id=times[j].team.id,
                    scheduled_kickoff=instant(kickoff),
                    lifecycle=MatchLifecycle.RECONCILED,
                )
            )
    return saida


def _elenco(
    times: Sequence[TimeSintetico], quantos: int
) -> tuple[list[Player], list[PlayerTeamTenure]]:
    """Jogadores e vínculos, distribuídos deterministicamente entre os times.

    ELES NÃO SÃO LIDOS PELO DATASET DE PARTIDAS — nenhuma coluna carrega
    `PLAYER_NAME`. Existem porque o registro precisa ter o TAMANHO de um
    registro de verdade: um índice de nome de jogador com trinta linhas tem
    seletividade que nenhum plano de produção terá, e medir contra ele
    produziria um número otimista sem dizer que é.
    """
    sorteio = random.Random(SEED)
    nomes = ("Silva", "Souza", "Pereira", "Moreau", "Kovacs", "Andersen", "Bianchi", "Novak")
    jogadores: list[Player] = []
    vinculos: list[PlayerTeamTenure] = []
    for n in range(quantos):
        nome = f"{nomes[n % len(nomes)]} {n:05d}"
        jogador = Player(
            id=PlayerId.derive("benchmark", nome),
            canonical_name=nome,
            date_of_birth=date(1990 + n % 15, 1 + n % 12, 1 + n % 28),
            nationality=None,
        )
        jogadores.append(jogador)
        clube = times[sorteio.randrange(len(times))]
        vinculos.append(
            PlayerTeamTenure(
                player_id=jogador.id,
                team_id=clube.team.id,
                valid_from=instant(datetime(2020, 7, 1, tzinfo=UTC)),
                valid_to=None,
            )
        )
    return jogadores, vinculos


# ================================================== o lado de fora: as linhas ==


def caminhos(total: int) -> list[Caminho]:
    """A sequência de caminhos das `total` linhas, na distribuição declarada.

    A LISTA É CONSTRUÍDA E EMBARALHADA, e não sorteada linha a linha: sortear
    dá a distribuição só em média, e a média de cem mil sorteios ainda varia o
    bastante para mover as contagens do relatório entre execuções. Construída,
    a proporção é EXATA — e continua determinística porque o embaralhamento
    usa a mesma semente.
    """
    saida: list[Caminho] = []
    for caminho, fatia in DISTRIBUICAO:
        saida.extend([caminho] * int(total * fatia))
    while len(saida) < total:
        saida.append(Caminho.ALIAS)
    sorteio = random.Random(SEED)
    sorteio.shuffle(saida)
    return saida[:total]


def _grafia(sintetico: TimeSintetico, caminho: Caminho, indice: int) -> str:
    if caminho is Caminho.ALIAS:
        return sintetico.alias
    if caminho is Caminho.CANONICAL:
        return sintetico.canonical
    if caminho is Caminho.SIMILAR:
        return sintetico.similar
    return f"Clube Externo {indice % 997:03d}"


def linhas(
    corpus: Corpus, *, total: int, shots_offset: int = 0
) -> Iterator[tuple[str, ...]]:
    """As linhas da fonte, na ordem em que um arquivo de verdade estaria.

    `shots_offset` DESLOCA APENAS OS CHUTES, e existe para a fusão: duas
    fontes que concordam em tudo produziriam só `EXACT_AGREEMENT`, e o
    benchmark de fusão mediria o caminho fácil. Com o deslocamento, o placar
    continua concordando e os chutes divergem — que é o par de casos reais
    (§21, §22).

    ORDENADAS PELA PARTIDA, que é a ordem de calendário: os arquivos públicos
    de futebol saem assim, e a ordem importa para o benchmark porque ela é o
    que dá LOCALIDADE ao lote. Um lote de mil linhas embaralhadas entre quinze
    temporadas carrega candidatos de quinze temporadas; o mesmo lote em ordem
    de calendário carrega os de uma. O ganho do lote depende da localidade, e
    medir com dado embaralhado mediria o pior caso chamando-o de caso.
    """
    plano = caminhos(total)
    for n, caminho in enumerate(plano):
        partida = corpus.matches[n % len(corpus.matches)]
        temporada = corpus.season_of(partida)
        competicao = corpus.competition_of(partida)
        casa = corpus.team_of(partida.home_team_id)
        fora = corpus.team_of(partida.away_team_id)
        gols_casa = (n * 7) % 5
        gols_fora = (n * 3) % 4
        yield (
            competicao.name,
            temporada.label,
            partida.scheduled_kickoff.date().isoformat(),
            partida.scheduled_kickoff.isoformat(),
            str(partida.stage.round_number or 1),
            _grafia(casa, caminho, n),
            _grafia(fora, caminho, n),
            str(gols_casa),
            str(gols_fora),
            str(6 + (n % 14) + shots_offset),
            str(4 + (n % 11) + shots_offset),
        )


def csv_bytes(corpus: Corpus, *, total: int, shots_offset: int = 0) -> bytes:
    """O arquivo, montado em memória uma vez e escrito no object store.

    Cem mil linhas dão uns seis megabytes: cabe. Um corpus de milhões teria
    que ser escrito em disco por partes — e é por isso que a função devolve
    bytes em vez de esconder a decisão atrás de um iterador.
    """
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(CABECALHO)
    escritor.writerows(linhas(corpus, total=total, shots_offset=shots_offset))
    return buffer.getvalue().encode()
