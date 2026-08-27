"""O cenário de VÁRIAS partidas — o que a recuperação exige e o E2E do PR-05 não dá.

O CENÁRIO PADRÃO TEM UMA PARTIDA SÓ, e a divisão é atômica por partida: ele
nunca produz as duas metades. A recuperação precisa das duas — a query vem da
AVALIAÇÃO e os candidatos da REFERÊNCIA —, então ela traz o próprio cenário.

ELE PASSA PELO MESMO CAMINHO, e é isso que o torna um E2E de verdade: fonte
pública, resolução, fusão, qualidade, build canônico, canonicalização de
eventos e publicação do corpus. Nada é montado em memória; o que muda é quantas
partidas entram e quantos eventos elas têm.

O xG VARIA ENTRE PARTIDAS DE PROPÓSITO. Um valor constante produziria IQR zero,
o artefato sairia `DEGENERATE_SCALE`, e o perfil resolvido ficaria vazio — o
cenário provaria a atrição e não provaria a distância. Aqui ele prova as duas.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.resolution import (
    PostgresProviderMappingRepository,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping
from sports_intelligence.domain.shared.identity import (
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.teams.models import Team
from tests.support.corpus import Corpus, TimeSintetico

#: Quantas partidas o cenário gera.
#:
#: DOZE, e o número tem motivo. A metade de referência precisa juntar trinta
#: observações disponíveis por eixo para o ajuste sair `FITTED` (PR-05.4 §121);
#: seis partidas em noventa e um cortes dão folga larga, e o dobro faria o E2E
#: custar minutos sem provar nada a mais.
PARTIDAS: Final[int] = 12

#: Quantos times o cenário tem. Um a mais que a metade das partidas, para que
#: nenhum enfrente a si mesmo no rodízio.
TIMES: Final[int] = PARTIDAS // 2 + 2

#: Quantos chutes cada TIME dá por partida. DEZ, e o número saiu de medição —
#: ver `fonte_de_eventos`. Ele não descreve futebol; ele dá às janelas móveis a
#: dispersão que doze partidas não produzem sozinhas.
CHUTES_POR_TIME: Final[int] = 10

_SEMENTE: Final[str] = "pr061e2e"

#: A quebra de linha do CSV, como bytes. Ela é uma constante porque escrevê-la
#: dentro de uma f-string exige escapes que já quebraram este arquivo uma vez.
_FIM_DE_LINHA: Final[bytes] = bytes([10])


def _times() -> list[Team]:
    return [
        Team(
            id=TeamId.derive(_SEMENTE, f"time-{i:02d}"),
            canonical_name=f"Clube {i:02d}",
            country="GB",
        )
        for i in range(TIMES)
    ]


def cenario(regime: Any) -> Corpus:
    """Doze partidas da mesma competição, com apitos distintos e crescentes.

    OS APITOS SÃO ESPAÇADOS DE SETE DIAS, e é isso que torna a mediana uma
    fronteira útil: metade das partidas cai de cada lado, e a recuperação tem
    query e candidatos. Apitos iguais fariam `percentile_disc` devolver o
    mínimo, e o dataset inteiro cairia numa metade só.
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
    partidas = tuple(
        Match(
            id=MatchId.derive(_SEMENTE, f"partida-{i:02d}"),
            competition_id=liga.id,
            season_id=temporada.id,
            regime=regime,
            stage=Stage(type=StageType.LEAGUE, round_number=1 + i),
            home_team_id=times[i % TIMES].id,
            away_team_id=times[(i + 1) % TIMES].id,
            scheduled_kickoff=instant(
                datetime(2024, 9, 1, 15, 0, tzinfo=UTC) + timedelta(days=7 * i)
            ),
            lifecycle=MatchLifecycle.RECONCILED,
        )
        for i in range(PARTIDAS)
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
        matches=partidas,
    )


def fonte_publica(corpus: Corpus) -> bytes:
    """O CSV que a ingestão lê — uma linha por partida."""
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


def referencia_de_partida(indice: int) -> str:
    return f"pr061-match-{indice:02d}"


def tabela_de_tipos(provider_id: ProviderId) -> EventTypeMapping:
    """O mapa de tipos do cenário — CHUTE e GOL.

    O `shot` É O QUE IMPORTA, e a medição é que diz. `RollingFamily.XG` lê
    `EventType.SHOT`, e não `EventType.GOAL`: um cenário só com gols produz xG
    ZERO em todo corte, o IQR da competição é nulo, todo eixo robusto sai do
    perfil, e nenhuma query é comparável. O E2E passaria — pulando tudo que
    importa.
    """
    return EventTypeMapping(
        provider_id=provider_id,
        entries={"shot": EventType.SHOT, "goal": EventType.GOAL},
        version=1,
    )


def fonte_de_eventos(corpus: Corpus, cabecalho: bytes) -> bytes:
    """Chutes densos com xG variado, e os gols que alguns deles viram.

    POR QUE CHUTES, E NÃO SÓ GOLS. `RollingFamily.XG` lê `EventType.SHOT`
    (catalog.py): as três famílias de finalização — `SHOT`, `SHOT_ON_TARGET` e
    `XG` — leem o mesmo tipo, e o que muda é o que se extrai dele. Um cenário
    só com gols dá `xg_* = 0.0` em todos os 455 cortes de referência, e o
    ajuste declara — corretamente — `DEGENERATE_SCALE` em todo eixo robusto.

    A DENSIDADE É DELIBERADA E NÃO É FUTEBOL. Dez chutes por time por partida é
    muito; é o que a MEDIÇÃO mostrou ser necessário para a janela móvel ter
    dispersão. A conta é curta:

        `xg_home_5m` soma o xG dos últimos cinco minutos. Cada chute torna a
        janela não nula por cerca de cinco cortes. Com quatro chutes, vinte dos
        noventa e um cortes têm valor — 22 %, e o terceiro quartil ainda cai no
        zero. Com dez, a fração passa de metade e `IQR > 0`.

    UM CORPUS REAL NÃO PRECISA DISSO. A dispersão vem de milhares de partidas
    numa temporada, e não da densidade de uma delas; doze partidas concentram a
    distribuição, e a densidade é como se compensa isso sem inventar mil
    partidas dentro de um E2E.

    O xG VARIA POR CHUTE E POR PARTIDA. Valores constantes dariam janelas não
    nulas e todas iguais — o que zera o IQR pelo outro caminho.
    """
    linhas = [cabecalho]
    for i, _ in enumerate(corpus.matches):
        ref = referencia_de_partida(i)
        atleta = f"pr061-player-{i:02d}"
        sequencia = 0
        for n in range(CHUTES_POR_TIME):
            for lado, time_do_chute in (
                ("h", f"pr061-team-h{i:02d}"),
                ("a", f"pr061-team-a{i:02d}"),
            ):
                sequencia += 1
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


def semear_traducoes(provider_id: ProviderId) -> Any:
    """A função de tradução, ligada ao provedor que o cenário vai usar.

    ELA É UMA FÁBRICA porque o `provider_id` é decidido por quem monta o corpus,
    e uma constante aqui divergiria dele em silêncio — a resolução não acharia
    tradução nenhuma, e a canonicalização recusaria todos os eventos com a
    mensagem menos útil possível.
    """

    async def _semear(database: Database, corpus: Corpus) -> None:
        repositorio = PostgresProviderMappingRepository(database)
        agora = instant(datetime(2026, 1, 1, tzinfo=UTC))
        por_id = {t.team.id: t.team for t in corpus.teams}
        alvos: list[tuple[SubjectType, str, Any]] = []
        for i, jogo in enumerate(corpus.matches):
            alvos.extend(
                (
                    (SubjectType.MATCH, referencia_de_partida(i), jogo.id.value),
                    (
                        SubjectType.TEAM,
                        f"pr061-team-h{i:02d}",
                        por_id[jogo.home_team_id].id.value,
                    ),
                    (
                        SubjectType.TEAM,
                        f"pr061-team-a{i:02d}",
                        por_id[jogo.away_team_id].id.value,
                    ),
                    (
                        SubjectType.PLAYER,
                        f"pr061-player-{i:02d}",
                        corpus.players[i % len(corpus.players)].id.value,
                    ),
                )
            )
        for tipo, externo, canonico in alvos:
            await repositorio.create_if_absent(
                ProviderEntityMapping(
                    id=str(_uuid.uuid4()),
                    provider_id=provider_id,
                    entity_type=tipo,
                    provider_entity_id=externo,
                    canonical_entity_id=EntityId(canonico),
                    resolution_decision_id=str(_uuid.uuid4()),
                    created_at=agora,
                    created_by="pr061-e2e",
                )
            )

    return _semear
