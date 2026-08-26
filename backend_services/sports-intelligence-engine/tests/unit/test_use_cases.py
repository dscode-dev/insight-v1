"""Os casos de uso, no caminho real: repositório, relógio e publicação.

POR QUE TESTAR AQUI E NÃO SÓ NO DOMÍNIO. O domínio já valida seus
invariantes, e testes que o chamam direto provam isso. O que ESTES testes
provam é que o caminho real — coordenar port, relógio e evento — não contorna
nenhum deles, que é onde a regra costuma vazar.

Os duplos são in-memory e vivem aqui: um port sem duplo obriga cada teste a
inventar o próprio, e duplos divergentes testam coisas diferentes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from sports_intelligence.application.use_cases.football import (
    ChangeMatchLifecycle,
    ConfirmLineup,
    RecordCanonicalEvents,
    RecordOddsQuotes,
    RegisterCompetition,
    RegisterMatch,
    RegisterSeason,
    RegisterTeam,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.envelope import EventEnvelope
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.matches.lifecycle import (
    IllegalTransitionError,
    MatchLifecycle,
)
from sports_intelligence.domain.matches.lineup import Lineup, LineupEntry, LineupStatus
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    OddsMarket,
    OddsQuote,
    OddsSelection,
)
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import DataProvenance, SourceType
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import (
    MatchClock,
    ObservationTimes,
    Period,
    instant,
)
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ports.clock import FrozenClock

AGORA = instant(datetime(2025, 3, 8, 18, 0, tzinfo=UTC))
KICKOFF = instant(datetime(2025, 3, 8, 17, 30, tzinfo=UTC))
REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(2020, 1, 1, tzinfo=UTC)),
    regulation_version="2024/25",
)
PROV = DataProvenance(
    source_type=SourceType.COMMERCIAL_PROVIDER,
    provider_id=ProviderId("provedor_a"),
    source_record_id="x",
    times=ObservationTimes.at_once(AGORA),
)


class MemoriaCompeticoes:
    def __init__(self) -> None:
        self.itens: dict[CompetitionCode, Competition] = {}

    async def upsert(self, competition: Competition) -> None:
        self.itens[competition.code] = competition

    async def by_code(self, code: CompetitionCode) -> Competition | None:
        return self.itens.get(code)


class MemoriaTemporadas:
    def __init__(self) -> None:
        self.itens: dict[SeasonId, Season] = {}

    async def upsert(self, season: Season) -> None:
        self.itens[season.id] = season

    async def by_id(self, season_id: SeasonId) -> Season | None:
        return self.itens.get(season_id)


class MemoriaTimes:
    def __init__(self) -> None:
        self.itens: dict[TeamId, Team] = {}

    async def upsert(self, team: Team) -> None:
        self.itens[team.id] = team

    async def by_id(self, team_id: TeamId) -> Team | None:
        return self.itens.get(team_id)


class MemoriaPartidas:
    def __init__(self) -> None:
        self.itens: dict[MatchId, Match] = {}

    async def upsert(self, match: Match) -> None:
        self.itens[match.id] = match

    async def by_id(self, match_id: MatchId) -> Match | None:
        return self.itens.get(match_id)


class MemoriaEscalacoes:
    def __init__(self) -> None:
        self.itens: list[Lineup] = []

    async def confirm(self, lineup: Lineup) -> None:
        self.itens.append(lineup)

    async def for_match(self, match_id: MatchId) -> Sequence[Lineup]:
        return [x for x in self.itens if x.match_id == match_id]


class MemoriaEventos:
    def __init__(self) -> None:
        self.itens: list[CanonicalMatchEvent] = []

    async def append(self, events: Sequence[CanonicalMatchEvent]) -> int:
        self.itens.extend(events)
        return len(events)

    async def for_match(self, match_id: MatchId) -> Sequence[CanonicalMatchEvent]:
        return [e for e in self.itens if e.match_id == match_id]


class MemoriaOdds:
    def __init__(self) -> None:
        self.itens: list[OddsQuote] = []

    async def record(self, quotes: Sequence[OddsQuote]) -> int:
        self.itens.extend(quotes)
        return len(quotes)

    async def series(self, match_id: MatchId) -> Sequence[OddsQuote]:
        return [q for q in self.itens if q.match_id == match_id]


class PublicadorEmMemoria:
    def __init__(self) -> None:
        self.publicados: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.publicados.append(envelope)

    async def publish_batch(self, envelopes: Sequence[EventEnvelope]) -> None:
        self.publicados.extend(envelopes)

    @property
    def tipos(self) -> list[str]:
        return [e.event_type for e in self.publicados]


@pytest.fixture
def contexto() -> dict[str, object]:
    return {
        "competicoes": MemoriaCompeticoes(),
        "temporadas": MemoriaTemporadas(),
        "times": MemoriaTimes(),
        "partidas": MemoriaPartidas(),
        "escalacoes": MemoriaEscalacoes(),
        "eventos": MemoriaEventos(),
        "odds": MemoriaOdds(),
        "publisher": PublicadorEmMemoria(),
        "clock": FrozenClock(AGORA),
    }


async def _montar(ctx: dict[str, object]) -> tuple[Season, Team, Team]:
    await RegisterCompetition(ctx["competicoes"]).execute(  # type: ignore[arg-type]
        CompetitionCode.PREMIER_LEAGUE
    )
    temporada = await RegisterSeason(
        ctx["competicoes"],  # type: ignore[arg-type]
        ctx["temporadas"],  # type: ignore[arg-type]
    ).execute(
        code=CompetitionCode.PREMIER_LEAGUE,
        label="2024-2025",
        starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
        regime=REGIME,
    )
    registrar = RegisterTeam(ctx["times"])  # type: ignore[arg-type]
    casa = await registrar.execute(canonical_name="Arsenal", country="GB")
    fora = await registrar.execute(canonical_name="Chelsea", country="GB")
    return temporada, casa, fora


async def _partida(ctx: dict[str, object]) -> Match:
    temporada, casa, fora = await _montar(ctx)
    return await RegisterMatch(
        ctx["partidas"],  # type: ignore[arg-type]
        ctx["temporadas"],  # type: ignore[arg-type]
        ctx["times"],  # type: ignore[arg-type]
        ctx["clock"],  # type: ignore[arg-type]
        ctx["publisher"],  # type: ignore[arg-type]
    ).execute(
        season_id=temporada.id,
        stage=Stage(type=StageType.LEAGUE, round_number=28),
        home_team_id=casa.id,
        away_team_id=fora.id,
        scheduled_kickoff=KICKOFF,
    )


class TestRegistro:
    async def test_competicao_vem_do_catalogo(self, contexto: dict[str, object]) -> None:
        """Não aceita nome nem região: aceitá-los permitiria duas Premier
        Leagues com nomes diferentes."""
        competicao = await RegisterCompetition(contexto["competicoes"]).execute(  # type: ignore[arg-type]
            CompetitionCode.LA_LIGA
        )
        assert competicao.name == "LaLiga"

    async def test_temporada_exige_competicao_registrada(self, contexto: dict[str, object]) -> None:
        with pytest.raises(NotFoundError):
            await RegisterSeason(
                contexto["competicoes"],  # type: ignore[arg-type]
                contexto["temporadas"],  # type: ignore[arg-type]
            ).execute(
                code=CompetitionCode.BRA_SERIE_A,
                label="2025",
                starts_at=instant(datetime(2025, 4, 1, tzinfo=UTC)),
                ends_at=instant(datetime(2025, 12, 1, tzinfo=UTC)),
                regime=REGIME,
            )

    async def test_partida_publica_evento_de_dominio(self, contexto: dict[str, object]) -> None:
        partida = await _partida(contexto)
        publisher = contexto["publisher"]
        assert isinstance(publisher, PublicadorEmMemoria)
        assert "match.registered" in publisher.tipos
        assert publisher.publicados[-1].match_id == partida.id

    async def test_partida_fora_da_temporada_e_recusada(self, contexto: dict[str, object]) -> None:
        """Quase sempre temporada errada — e ela contaminaria a tabela de uma
        edição que não a teve."""
        temporada, casa, fora = await _montar(contexto)
        with pytest.raises(ConflictError, match="fora da temporada"):
            await RegisterMatch(
                contexto["partidas"],  # type: ignore[arg-type]
                contexto["temporadas"],  # type: ignore[arg-type]
                contexto["times"],  # type: ignore[arg-type]
                contexto["clock"],  # type: ignore[arg-type]
                contexto["publisher"],  # type: ignore[arg-type]
            ).execute(
                season_id=temporada.id,
                stage=Stage(type=StageType.LEAGUE, round_number=1),
                home_team_id=casa.id,
                away_team_id=fora.id,
                scheduled_kickoff=instant(datetime(2025, 8, 15, tzinfo=UTC)),
            )

    async def test_partida_com_time_desconhecido_e_recusada(
        self, contexto: dict[str, object]
    ) -> None:
        temporada, casa, _ = await _montar(contexto)
        with pytest.raises(NotFoundError):
            await RegisterMatch(
                contexto["partidas"],  # type: ignore[arg-type]
                contexto["temporadas"],  # type: ignore[arg-type]
                contexto["times"],  # type: ignore[arg-type]
                contexto["clock"],  # type: ignore[arg-type]
                contexto["publisher"],  # type: ignore[arg-type]
            ).execute(
                season_id=temporada.id,
                stage=Stage(type=StageType.LEAGUE, round_number=1),
                home_team_id=casa.id,
                away_team_id=TeamId.new(),
                scheduled_kickoff=KICKOFF,
            )


class TestLifecycle:
    async def test_a_transicao_passa_pelo_grafo_do_dominio(
        self, contexto: dict[str, object]
    ) -> None:
        """É isto que impede uma partida cancelada de voltar a ficar ao vivo."""
        partida = await _partida(contexto)
        caso = ChangeMatchLifecycle(
            contexto["partidas"],  # type: ignore[arg-type]
            contexto["clock"],  # type: ignore[arg-type]
            contexto["publisher"],  # type: ignore[arg-type]
        )
        with pytest.raises(IllegalTransitionError):
            await caso.execute(
                match_id=partida.id, target=MatchLifecycle.LIVE, reason="pulando etapa"
            )

    async def test_transicao_valida_persiste_e_publica(self, contexto: dict[str, object]) -> None:
        partida = await _partida(contexto)
        atualizada = await ChangeMatchLifecycle(
            contexto["partidas"],  # type: ignore[arg-type]
            contexto["clock"],  # type: ignore[arg-type]
            contexto["publisher"],  # type: ignore[arg-type]
        ).execute(
            match_id=partida.id,
            target=MatchLifecycle.SCHEDULED,
            reason="confirmada pelo provedor",
        )
        assert atualizada.lifecycle is MatchLifecycle.SCHEDULED
        publisher = contexto["publisher"]
        assert isinstance(publisher, PublicadorEmMemoria)
        assert "match.lifecycle.changed" in publisher.tipos
        assert publisher.publicados[-1].payload["reason"] == "confirmada pelo provedor"


class TestConfirmLineup:
    async def test_a_checagem_cruzada_e_o_ponto(self, contexto: dict[str, object]) -> None:
        """Sozinha, uma escalação é válida. O erro caro — o mesmo jogador nos
        dois times, vindo de resolução que fundiu homônimos — só aparece ao
        confrontar as duas."""
        partida = await _partida(contexto)
        comum = PlayerId.new()
        caso = ConfirmLineup(
            contexto["partidas"],  # type: ignore[arg-type]
            contexto["escalacoes"],  # type: ignore[arg-type]
            contexto["clock"],  # type: ignore[arg-type]
            contexto["publisher"],  # type: ignore[arg-type]
        )
        await caso.execute(
            Lineup(
                match_id=partida.id,
                team_id=partida.home_team_id,
                entries=(LineupEntry(player_id=comum, status=LineupStatus.STARTER),),
            )
        )
        with pytest.raises(ValueError, match="nos dois times"):
            await caso.execute(
                Lineup(
                    match_id=partida.id,
                    team_id=partida.away_team_id,
                    entries=(LineupEntry(player_id=comum, status=LineupStatus.STARTER),),
                )
            )

    async def test_time_que_nao_joga_a_partida_e_recusado(
        self, contexto: dict[str, object]
    ) -> None:
        partida = await _partida(contexto)
        with pytest.raises(ConflictError, match="não joga"):
            await ConfirmLineup(
                contexto["partidas"],  # type: ignore[arg-type]
                contexto["escalacoes"],  # type: ignore[arg-type]
                contexto["clock"],  # type: ignore[arg-type]
                contexto["publisher"],  # type: ignore[arg-type]
            ).execute(
                Lineup(
                    match_id=partida.id,
                    team_id=TeamId.new(),
                    entries=(LineupEntry(player_id=PlayerId.new(), status=LineupStatus.STARTER),),
                )
            )


class TestGravacaoDeFatos:
    async def test_eventos_de_partidas_diferentes_no_mesmo_lote(
        self, contexto: dict[str, object]
    ) -> None:
        partida = await _partida(contexto)
        eventos = (
            CanonicalMatchEvent.record(
                match_id=partida.id,
                type=EventType.PASS,
                clock=MatchClock(Period.FIRST_HALF, 10),
                sequence=1,
                provenance=PROV,
                quality=DataQuality.perfect(),
                team_id=partida.home_team_id,
                player_id=PlayerId.new(),
            ),
            CanonicalMatchEvent.record(
                match_id=MatchId.new(),
                type=EventType.PASS,
                clock=MatchClock(Period.FIRST_HALF, 11),
                sequence=2,
                provenance=PROV,
                quality=DataQuality.perfect(),
                team_id=TeamId.new(),
                player_id=PlayerId.new(),
            ),
        )
        with pytest.raises(ConflictError, match="partidas diferentes"):
            await RecordCanonicalEvents(
                contexto["partidas"],  # type: ignore[arg-type]
                contexto["eventos"],  # type: ignore[arg-type]
            ).execute(eventos)

    async def test_a_gravacao_devolve_quantos_entraram(self, contexto: dict[str, object]) -> None:
        """'Gravado com sucesso' sem contagem é afirmação sem medida."""
        partida = await _partida(contexto)
        quantos = await RecordOddsQuotes(
            contexto["partidas"],  # type: ignore[arg-type]
            contexto["odds"],  # type: ignore[arg-type]
        ).execute(
            [
                OddsQuote.observe(
                    match_id=partida.id,
                    bookmaker=BookmakerRef("pinnacle"),
                    market=OddsMarket.MATCH_RESULT_1X2,
                    selection=OddsSelection.HOME,
                    decimal_odds="1.95",
                    observed_at=AGORA,
                    provenance=PROV,
                )
            ]
        )
        assert quantos == 1

    async def test_lote_vazio_e_no_op(self, contexto: dict[str, object]) -> None:
        assert (
            await RecordCanonicalEvents(
                contexto["partidas"],  # type: ignore[arg-type]
                contexto["eventos"],  # type: ignore[arg-type]
            ).execute([])
            == 0
        )
