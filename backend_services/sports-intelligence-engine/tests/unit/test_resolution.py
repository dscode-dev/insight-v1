"""Os resolvers: competição, temporada, time, jogador e partida.

O QUE ESTES TESTES PROTEGEM É UMA ASSIMETRIA. Não é «o resolver acerta»: é que
ele PREFERE NÃO DECIDIR quando a evidência não basta. Metade dos casos aqui
verifica um `AMBIGUOUS` ou um `REVIEW_REQUIRED` — e cada um deles seria um
merge errado num sistema que maximiza merges.

    Custo(falso merge) > Custo(não resolvido)

Um `PlayerId` errado contamina influência de jogador, força de elenco, estados
históricos e grafo tático, e a contaminação não é detectável depois porque
tudo continua somando. Um registro não resolvido é visível e consertável.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from sports_intelligence.domain.competitions.catalog import CompetitionCode, entry_for
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import (
    ResolutionMethod,
    ResolutionStatus,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import EvidenceKind, ExplanationCode
from sports_intelligence.domain.resolution.mappings import (
    EntityAlias,
    ProviderEntityMapping,
    assert_mapping_is_consistent,
)
from sports_intelligence.domain.resolution.policy import (
    DEFAULT_MATCH_POLICY,
    DEFAULT_RESOLUTION_POLICY,
)
from sports_intelligence.domain.shared.errors import ConflictError
from sports_intelligence.domain.shared.identity import ProviderId, ProviderRef, TeamId
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.sources.mapping import SeasonConvention
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from sports_intelligence.ingestion.resolution.context import (
    ContextBuilder,
    ResolutionContext,
)
from sports_intelligence.ingestion.resolution.resolvers import (
    MatchCandidateInput,
    Outcome,
    ResolverBundle,
)
from sports_intelligence.ingestion.resolution.seasons import parse_season_label

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
POLITICA = DEFAULT_RESOLUTION_POLICY
PROVEDOR = ProviderId("football_data")


@pytest.fixture
def bundle() -> ResolverBundle:
    return ResolverBundle.build()


def _regime() -> CompetitionRegime:
    return CompetitionRegime(
        code=RegimeCode.DOUBLE_ROUND_ROBIN,
        effective_from=instant(datetime(2000, 1, 1, tzinfo=UTC)),
        regulation_version="v1",
    )


def _competicao(codigo: CompetitionCode = CompetitionCode.PREMIER_LEAGUE) -> Competition:
    return Competition.from_code(codigo)


def _temporada(competicao: Competition, rotulo: str, inicio: int, fim: int) -> Season:
    return Season.create(
        competition_id=competicao.id,
        label=rotulo,
        starts_at=instant(datetime(inicio, 8, 1, tzinfo=UTC)),
        ends_at=instant(datetime(fim, 5, 31, tzinfo=UTC)),
        regime=_regime(),
    )


def _time(nome: str, pais: str = "GB") -> Team:
    return Team.register(canonical_name=nome, country=pais)


def _contexto(
    *,
    competicoes: tuple[Competition, ...] = (),
    temporadas: tuple[Season, ...] = (),
    times: tuple[Team, ...] = (),
    jogadores: tuple[Player, ...] = (),
    vinculos: tuple[PlayerTeamTenure, ...] = (),
    partidas: tuple[Match, ...] = (),
    aliases: tuple[EntityAlias, ...] = (),
    mapeamentos: tuple[ProviderEntityMapping, ...] = (),
    consultas: tuple[str, ...] = (),
) -> ResolutionContext:
    return (
        ContextBuilder(NameNormalizer(), AGORA)
        .with_competitions(competicoes)
        .with_seasons(temporadas)
        .with_teams(times)
        .with_team_candidates(_candidatos_por_token(times, consultas))
        .with_players(jogadores, vinculos)
        .with_player_candidates(_candidatos_por_token(jogadores, consultas))
        .with_matches(partidas)
        .with_aliases(aliases)
        .with_mappings(mapeamentos)
        .build()
    )


def _candidatos_por_token(
    entidades: tuple[Any, ...], consultas: tuple[str, ...]
) -> tuple[Any, ...]:
    """Espelha em memória a busca de candidatos que o PostgreSQL faz.

    POR QUE O HELPER PRECISA DISTO. Desde o PR-03.2 o universo de candidatos
    de similaridade é POR NOME CONSULTADO, e não «tudo que o contexto tem» —
    é o que torna a decisão independente do tamanho do lote (§29 a §33). O
    carregamento real é uma consulta com `&&` sobre os tokens do nome; aqui a
    mesma regra roda em memória.

    AS CONSULTAS SÃO DECLARADAS PELO TESTE, e é o ponto: o carregador real
    também só conhece os nomes que o lote trouxe. Um helper que adivinhasse a
    consulta esconderia justamente a dependência que este PR tornou explícita.

    O nome canônico de cada entidade entra como consulta implícita, porque o
    caminho exato precisa dele e todo teste que resolve por chave o usa.
    """
    n = NameNormalizer()
    pares = []
    for consulta in (*consultas, *(e.canonical_name for e in entidades)):
        normalizada = n.normalize(consulta)
        tokens = set(normalizada.split())
        for entidade in entidades:
            if tokens & set(n.normalize(entidade.canonical_name).split()):
                pares.append((normalizada, entidade))
    return tuple(dict.fromkeys(pares))


def _alias(tipo: SubjectType, entidade: object, texto: str) -> EntityAlias:
    n = NameNormalizer()
    return EntityAlias(
        id=f"alias-{texto}",
        entity_type=tipo,
        entity_id=entidade,  # type: ignore[arg-type]
        alias_original=texto,
        alias_normalized=n.normalize(texto),
        normalizer_version=n.version,
        created_at=AGORA,
        created_by="teste",
    )


# ============================================================ competição ====


class TestCompetitionResolution:
    def test_nome_canonico_resolve(self, bundle: ResolverBundle) -> None:
        competicao = _competicao()
        resultado = bundle.competition.resolve(
            bundle.normalized(competicao.name),
            context=_contexto(competicoes=(competicao,)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == competicao.id
        assert resultado.method is ResolutionMethod.EXACT_CANONICAL_KEY

    def test_codigo_resolve(self, bundle: ResolverBundle) -> None:
        resultado = bundle.competition.resolve(
            bundle.normalized("PREMIER_LEAGUE"), context=_contexto(), policy=POLITICA
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == entry_for(CompetitionCode.PREMIER_LEAGUE).id

    def test_epl_resolve_por_alias(self, bundle: ResolverBundle) -> None:
        """`EPL → PREMIER_LEAGUE` (§83), e por ALIAS — não por fuzzy.

        O catálogo tem cinco itens com nomes distintos; similaridade livre
        aqui só criaria o risco de `Premier League` casar com `Liga Premier`
        de outro país. Aliases são explícitos e corrigíveis com um `DELETE`.
        """
        alvo = entry_for(CompetitionCode.PREMIER_LEAGUE).id
        resultado = bundle.competition.resolve(
            bundle.normalized("EPL"),
            context=_contexto(aliases=(_alias(SubjectType.COMPETITION, alvo, "EPL"),)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == alvo
        assert resultado.method is ResolutionMethod.EXACT_ALIAS

    def test_fora_do_catalogo_e_rejeitado(self, bundle: ResolverBundle) -> None:
        """`REJECTED` e não `UNRESOLVED`, e a diferença importa.

        `UNRESOLVED` diz «não achei, talvez ache depois»; `REJECTED` diz
        «decidi que isto não é uma das cinco». A Bundesliga não vai aparecer
        no catálogo da V1, e mantê-la em `UNRESOLVED` faria a fila crescer
        com casos que nunca resolvem.
        """
        resultado = bundle.competition.resolve(
            bundle.normalized("Bundesliga"), context=_contexto(), policy=POLITICA
        )
        assert resultado.status is ResolutionStatus.REJECTED
        assert resultado.entity_id is None
        assert any(e.explanation is ExplanationCode.OUT_OF_CATALOG for e in resultado.evidence)


# ============================================================= temporada ====


class TestSeasonParsing:
    @pytest.mark.parametrize(
        ("rotulo", "inicio", "fim"),
        [("2023/24", 2023, 2024), ("2023-24", 2023, 2024), ("2023-2024", 2023, 2024)],
    )
    def test_formas_cruzadas_sao_equivalentes(self, rotulo: str, inicio: int, fim: int) -> None:
        pista = parse_season_label(rotulo)
        assert (pista.start_year, pista.end_year) == (inicio, fim)
        assert not pista.ambiguous

    def test_ano_sozinho_sem_convencao_fica_ambiguo(self) -> None:
        """`2024` NÃO resolve universalmente (§15).

        No Brasileirão é a temporada de 2024; numa fonte de Premier League
        costuma ser 2023/24 — ou 2024/25, conforme o publicador. Escolher um
        default erraria metade das fontes em silêncio.
        """
        pista = parse_season_label("2024")
        assert pista.ambiguous
        assert pista.end_year is None

    def test_convencao_declarada_desambigua(self) -> None:
        civil = parse_season_label("2024", convention=SeasonConvention.CALENDAR_YEAR)
        cruzada = parse_season_label("2024", convention=SeasonConvention.SPLIT_YEAR)
        assert (civil.start_year, civil.end_year) == (2024, 2024)
        assert (cruzada.start_year, cruzada.end_year) == (2024, 2025)
        assert not civil.ambiguous
        assert not cruzada.ambiguous

    def test_virada_de_seculo(self) -> None:
        """`1999/00` e 1999-2000, e nao 1999-1900."""
        pista = parse_season_label("1999/00")
        assert (pista.start_year, pista.end_year) == (1999, 2000)

    def test_rotulo_irreconhecivel(self) -> None:
        assert parse_season_label("temporada passada").unparseable


class TestSeasonResolution:
    def test_rotulo_exato_resolve(self, bundle: ResolverBundle) -> None:
        competicao = _competicao()
        temporada = _temporada(competicao, "2023-2024", 2023, 2024)
        resultado = bundle.season.resolve(
            bundle.normalized("2023-2024"),
            competition=competicao.id,
            context=_contexto(competicoes=(competicao,), temporadas=(temporada,)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == temporada.id

    def test_brasileirao_usa_ano_civil(self, bundle: ResolverBundle) -> None:
        """A mesma escrita, `2024`, com significado diferente por liga (§84)."""
        competicao = _competicao(CompetitionCode.BRA_SERIE_A)
        temporada = Season.create(
            competition_id=competicao.id,
            label="2024",
            starts_at=instant(datetime(2024, 4, 1, tzinfo=UTC)),
            ends_at=instant(datetime(2024, 12, 8, tzinfo=UTC)),
            regime=_regime(),
        )
        resultado = bundle.season.resolve(
            bundle.normalized("2024"),
            competition=competicao.id,
            context=_contexto(competicoes=(competicao,), temporadas=(temporada,)),
            policy=POLITICA,
            convention=SeasonConvention.CALENDAR_YEAR,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == temporada.id

    def test_data_da_partida_desambigua_o_ano_sozinho(self, bundle: ResolverBundle) -> None:
        """A evidência mais forte que existe para temporada.

        Uma partida de setembro de 2023 está na 2023/24 da Premier League. A
        janela registrada responde isso sem precisar da convenção da fonte.
        """
        competicao = _competicao()
        anterior = _temporada(competicao, "2022-2023", 2022, 2023)
        atual = _temporada(competicao, "2023-2024", 2023, 2024)
        resultado = bundle.season.resolve(
            bundle.normalized("2023"),
            competition=competicao.id,
            context=_contexto(competicoes=(competicao,), temporadas=(anterior, atual)),
            policy=POLITICA,
            match_date=date(2023, 9, 15),
        )
        assert resultado.entity_id == atual.id or resultado.status.needs_human


# ================================================================== time ====


class TestTeamResolution:
    def test_nome_canonico_exato(self, bundle: ResolverBundle) -> None:
        city = _time("Manchester City")
        resultado = bundle.team.resolve(
            bundle.normalized("Manchester City"),
            context=_contexto(times=(city,)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == city.id

    def test_sufixo_societario_nao_impede_o_casamento(self, bundle: ResolverBundle) -> None:
        """`Manchester City FC` normaliza para `manchester city` (§85)."""
        city = _time("Manchester City")
        resultado = bundle.team.resolve(
            bundle.normalized("Manchester City FC"),
            context=_contexto(times=(city,)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == city.id

    def test_man_city_resolve_por_alias(self, bundle: ResolverBundle) -> None:
        """CENÁRIO A: `Man City` e `Manchester City FC` → o mesmo `TeamId`.

        A ABREVIAÇÃO PASSA PELO ALIAS, e não por similaridade: `man` e
        `manchester` são palavras diferentes, e um algoritmo que as casasse
        casaria também `man united` com `manchester united` E com meia dúzia
        de outros. Abreviação de fonte é registrada, não inferida.
        """
        city = _time("Manchester City")
        contexto = _contexto(
            times=(city,), aliases=(_alias(SubjectType.TEAM, city.id, "Man City"),)
        )
        por_alias = bundle.team.resolve(
            bundle.normalized("Man City"), context=contexto, policy=POLITICA
        )
        por_nome = bundle.team.resolve(
            bundle.normalized("Manchester City FC"), context=contexto, policy=POLITICA
        )
        assert por_alias.entity_id == por_nome.entity_id == city.id
        assert por_alias.method is ResolutionMethod.EXACT_ALIAS

    def test_mapeamento_de_provedor_vence_tudo(self, bundle: ResolverBundle) -> None:
        city = _time("Manchester City")
        mapeamento = ProviderEntityMapping.create(
            provider_ref=ProviderRef(provider=PROVEDOR, external_id="MCI"),
            entity_type=SubjectType.TEAM,
            canonical_entity_id=city.id,
            resolution_decision_id="decisao-1",
            at=AGORA,
            created_by="teste",
        )
        resultado = bundle.team.resolve(
            bundle.normalized("Alguma Grafia Estranha"),
            context=_contexto(times=(city,), mapeamentos=(mapeamento,)),
            policy=POLITICA,
            provider_ref="MCI",
            provider_id=PROVEDOR,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == city.id
        assert resultado.method is ResolutionMethod.EXACT_PROVIDER_MAPPING
        assert resultado.confidence.value == 1.0

    def test_sporting_cp_nao_funde_com_sporting_gijon(self, bundle: ResolverBundle) -> None:
        """O caso que fundiu clubes entre continentes no motor anterior.

        `Sporting CP` NÃO pode virar `sporting`, e o país é a evidência que
        separa. A normalização preserva o qualificador e a similaridade fica
        abaixo do limiar — o resultado é revisão, nunca merge.
        """
        cp = _time("Sporting CP", pais="PT")
        gijon = _time("Sporting Gijon", pais="ES")
        resultado = bundle.team.resolve(
            bundle.normalized("Sporting"),
            context=_contexto(times=(cp, gijon)),
            policy=POLITICA,
            country="PT",
        )
        assert resultado.status is not ResolutionStatus.RESOLVED

    def test_nome_proximo_de_pais_diferente_nao_resolve(self, bundle: ResolverBundle) -> None:
        mineiro = _time("Atletico Mineiro", pais="BR")
        madrid = _time("Atletico Madrid", pais="ES")
        resultado = bundle.team.resolve(
            bundle.normalized("Atletico"),
            context=_contexto(times=(mineiro, madrid), consultas=("Atletico",)),
            policy=POLITICA,
        )
        assert resultado.status is not ResolutionStatus.RESOLVED
        assert len(resultado.alternatives) >= 2

    def test_nome_desconhecido_fica_sem_resolucao(self, bundle: ResolverBundle) -> None:
        resultado = bundle.team.resolve(
            bundle.normalized("Clube Que Nao Existe"),
            context=_contexto(times=(_time("Arsenal"),)),
            policy=POLITICA,
        )
        assert resultado.status is ResolutionStatus.UNRESOLVED


# ============================================================== jogador ====


class TestPlayerResolution:
    def _joao(self, nascimento: date, clube: TeamId | None = None) -> Player:
        return Player.register(
            canonical_name="Joao Silva", date_of_birth=nascimento, nationality="BR"
        )

    def test_nome_data_e_clube_batendo_resolve(self, bundle: ResolverBundle) -> None:
        """Três evidências corroborantes — o mínimo que a política exige."""
        flamengo = _time("Flamengo", pais="BR")
        jogador = self._joao(date(1994, 7, 12))
        vinculo = PlayerTeamTenure(
            player_id=jogador.id,
            team_id=flamengo.id,
            valid_from=instant(datetime(2022, 1, 1, tzinfo=UTC)),
        )
        resultado = bundle.player.resolve(
            bundle.normalized("Joao Silva"),
            context=_contexto(times=(flamengo,), jogadores=(jogador,), vinculos=(vinculo,)),
            policy=POLITICA,
            date_of_birth=date(1994, 7, 12),
            nationality="BR",
            team=flamengo.id,
            at=instant(datetime(2023, 5, 1, tzinfo=UTC)),
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == jogador.id

    def test_homonimo_sem_data_nunca_resolve(self, bundle: ResolverBundle) -> None:
        """CENÁRIO B: mesmo nome, sem nada que os distinga (§21, §86).

        O nome bate perfeitamente nos dois — e é JUSTAMENTE POR ISSO que não
        se pode resolver. Um merge aqui somaria as carreiras de duas pessoas.
        """
        um = self._joao(date(1994, 7, 12))
        outro = self._joao(date(1999, 3, 4))
        resultado = bundle.player.resolve(
            bundle.normalized("Joao Silva"),
            context=_contexto(jogadores=(um, outro)),
            policy=POLITICA,
        )
        assert resultado.status in (
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.REVIEW_REQUIRED,
            ResolutionStatus.UNRESOLVED,
        )
        assert resultado.entity_id is None

    def test_data_de_nascimento_diferente_nao_resolve(self, bundle: ResolverBundle) -> None:
        """Duas pessoas com o mesmo nome e datas diferentes são duas pessoas."""
        jogador = self._joao(date(1994, 7, 12))
        resultado = bundle.player.resolve(
            bundle.normalized("Joao Silva"),
            context=_contexto(jogadores=(jogador,)),
            policy=POLITICA,
            date_of_birth=date(1999, 3, 4),
        )
        assert resultado.status is not ResolutionStatus.RESOLVED
        assert any(
            e.kind is EvidenceKind.DATE_OF_BIRTH and e.contradicts for e in resultado.evidence
        )

    def test_clube_na_data_reduz_a_confianca(self, bundle: ResolverBundle) -> None:
        """«João Silva, Flamengo, 2023» ≠ «João Silva, Palmeiras, 2026» (§20).

        O vínculo NA DATA — não o clube atual — é o que separa. `team_at`
        devolve `None` fora da janela, e devolver o clube atual como
        aproximação reescreveria o passado.
        """
        flamengo = _time("Flamengo", pais="BR")
        palmeiras = _time("Palmeiras", pais="BR")
        jogador = self._joao(date(1994, 7, 12))
        vinculo = PlayerTeamTenure(
            player_id=jogador.id,
            team_id=flamengo.id,
            valid_from=instant(datetime(2022, 1, 1, tzinfo=UTC)),
            valid_to=instant(datetime(2024, 12, 31, tzinfo=UTC)),
        )
        contexto = _contexto(times=(flamengo, palmeiras), jogadores=(jogador,), vinculos=(vinculo,))
        certo = bundle.player.resolve(
            bundle.normalized("Joao Silva"),
            context=contexto,
            policy=POLITICA,
            date_of_birth=date(1994, 7, 12),
            team=flamengo.id,
            at=instant(datetime(2023, 5, 1, tzinfo=UTC)),
        )
        errado = bundle.player.resolve(
            bundle.normalized("Joao Silva"),
            context=contexto,
            policy=POLITICA,
            date_of_birth=date(1994, 7, 12),
            team=palmeiras.id,
            at=instant(datetime(2023, 5, 1, tzinfo=UTC)),
        )
        assert certo.confidence.value > errado.confidence.value


# ============================================================== partida ====


class TestMatchResolution:
    def _cenario(self) -> tuple[Competition, Season, Team, Team, Match]:
        competicao = _competicao()
        temporada = _temporada(competicao, "2019-2020", 2019, 2020)
        arsenal = _time("Arsenal")
        chelsea = _time("Chelsea")
        partida = Match.register(
            competition_id=competicao.id,
            season_id=temporada.id,
            regime=_regime(),
            stage=Stage(type=StageType.LEAGUE, round_number=1),
            home_team_id=arsenal.id,
            away_team_id=chelsea.id,
            scheduled_kickoff=instant(datetime(2019, 8, 10, 15, 0, tzinfo=UTC)),
        )
        return competicao, temporada, arsenal, chelsea, partida

    def _resolver(
        self,
        bundle: ResolverBundle,
        entrada: MatchCandidateInput,
        cenario: tuple[Competition, Season, Team, Team, Match],
    ) -> Outcome:
        """O contexto é montado do MESMO cenário que produziu a partida.

        Recriar competição e temporada aqui produziria ids derivados iguais —
        as duas derivam de chave natural — e mesmo assim seria frágil: o
        confronto é indexado por (temporada, mandante, visitante), e um time
        recriado teria id sorteado diferente.
        """
        competicao, temporada, _casa, _fora, partida = cenario
        return bundle.match.resolve(
            entrada,
            context=_contexto(
                competicoes=(competicao,), temporadas=(temporada,), partidas=(partida,)
            ),
            policy=POLITICA,
            match_policy=DEFAULT_MATCH_POLICY,
        )

    def test_mesma_partida_com_horario_identico(self, bundle: ResolverBundle) -> None:
        cenario = self._cenario()
        _c, temporada, casa, fora, partida = cenario
        resultado = self._resolver(
            bundle,
            MatchCandidateInput(
                competition=partida.competition_id,
                season=temporada.id,
                home=casa.id,
                away=fora.id,
                kickoff=partida.kickoff,
            ),
            cenario,
        )
        assert resultado.status is ResolutionStatus.RESOLVED
        assert resultado.entity_id == partida.id

    def test_deriva_pequena_de_horario_ainda_resolve(self, bundle: ResolverBundle) -> None:
        """Fontes divergem em minutos por arredondamento e hora cheia (§25)."""
        cenario = self._cenario()
        _c, temporada, casa, fora, partida = cenario
        resultado = self._resolver(
            bundle,
            MatchCandidateInput(
                competition=partida.competition_id,
                season=temporada.id,
                home=casa.id,
                away=fora.id,
                kickoff=instant(partida.kickoff + timedelta(minutes=10)),
            ),
            cenario,
        )
        assert resultado.status is ResolutionStatus.RESOLVED

    def test_mando_invertido_nao_resolve_sozinho(self, bundle: ResolverBundle) -> None:
        """CENÁRIO: `Arsenal x Chelsea` contra `Chelsea x Arsenal` (§24).

        Trocar automaticamente resolveria o caso em que a fonte errou e
        DESTRUIRIA o caso em que são os dois jogos do returno. A penalidade
        derruba o candidato para a faixa de revisão.
        """
        cenario = self._cenario()
        _c, temporada, casa, fora, partida = cenario
        resultado = self._resolver(
            bundle,
            MatchCandidateInput(
                competition=partida.competition_id,
                season=temporada.id,
                home=fora.id,
                away=casa.id,
                kickoff=partida.kickoff,
            ),
            cenario,
        )
        assert resultado.status is not ResolutionStatus.RESOLVED

    def test_competicao_diferente_nao_funde(self, bundle: ResolverBundle) -> None:
        """Copa e liga entre os mesmos times na mesma data existem (§87, §96)."""
        cenario = self._cenario()
        _c, temporada, casa, fora, partida = cenario
        outra = _competicao(CompetitionCode.UEFA_CHAMPIONS_LEAGUE)
        resultado = self._resolver(
            bundle,
            MatchCandidateInput(
                competition=outra.id,
                season=temporada.id,
                home=casa.id,
                away=fora.id,
                kickoff=partida.kickoff,
            ),
            cenario,
        )
        assert resultado.status is not ResolutionStatus.RESOLVED

    def test_horario_muito_distante_nao_resolve(self, bundle: ResolverBundle) -> None:
        cenario = self._cenario()
        _c, temporada, casa, fora, partida = cenario
        resultado = self._resolver(
            bundle,
            MatchCandidateInput(
                competition=partida.competition_id,
                season=temporada.id,
                home=casa.id,
                away=fora.id,
                kickoff=instant(partida.kickoff + timedelta(days=40)),
            ),
            cenario,
        )
        assert resultado.status is not ResolutionStatus.RESOLVED


# ========================================================= determinismo ====


class TestDeterminismo:
    def test_a_mesma_entrada_produz_a_mesma_decisao(self, bundle: ResolverBundle) -> None:
        """CENÁRIO F, primeira metade (§92).

        Mesma entrada, mesma versão, mesmo estado do registro → mesma decisão
        e a MESMA ORDEM de candidatos. Sem desempate explícito, dois
        candidatos com o mesmo score sairiam do banco em ordem arbitrária.
        """
        times = (_time("Atletico Mineiro", "BR"), _time("Atletico Madrid", "ES"))
        contexto = _contexto(times=times)
        primeiro = bundle.team.resolve(
            bundle.normalized("Atletico"), context=contexto, policy=POLITICA
        )
        segundo = bundle.team.resolve(
            bundle.normalized("Atletico"), context=contexto, policy=POLITICA
        )
        assert primeiro.status is segundo.status
        assert primeiro.confidence == segundo.confidence
        assert [a.canonical_entity_id for a in primeiro.alternatives] == [
            a.canonical_entity_id for a in segundo.alternatives
        ]

    def test_alternativas_saem_ordenadas_por_score(self, bundle: ResolverBundle) -> None:
        contexto = _contexto(
            times=(_time("Atletico Mineiro", "BR"), _time("Atletico Madrid", "ES"))
        )
        resultado = bundle.team.resolve(
            bundle.normalized("Atletico"), context=contexto, policy=POLITICA
        )
        scores = [a.score for a in resultado.alternatives]
        assert scores == sorted(scores, reverse=True)


# ============================================================ mapeamento ====


class TestMappings:
    def test_reapontar_mapeamento_e_conflito(self) -> None:
        """O caso mais caro deste PR.

        Um mapeamento existente aponta `MCI → Manchester City`; uma execução
        nova conclui `MCI → Melbourne City`. Sobrescrever em silêncio faria
        todo o histórico já resolvido apontar para o clube errado — e nada
        falharia.
        """
        city = _time("Manchester City")
        melbourne = _time("Melbourne City", pais="AU")
        referencia = ProviderRef(provider=PROVEDOR, external_id="MCI")
        existente = ProviderEntityMapping.create(
            provider_ref=referencia,
            entity_type=SubjectType.TEAM,
            canonical_entity_id=city.id,
            resolution_decision_id="d1",
            at=AGORA,
            created_by="teste",
        )
        proposto = ProviderEntityMapping.create(
            provider_ref=referencia,
            entity_type=SubjectType.TEAM,
            canonical_entity_id=melbourne.id,
            resolution_decision_id="d2",
            at=AGORA,
            created_by="teste",
        )
        with pytest.raises(ConflictError, match="já aponta"):
            assert_mapping_is_consistent(existente, proposto)

    def test_mapeamento_igual_nao_e_conflito(self) -> None:
        city = _time("Manchester City")
        referencia = ProviderRef(provider=PROVEDOR, external_id="MCI")
        argumentos = {
            "provider_ref": referencia,
            "entity_type": SubjectType.TEAM,
            "canonical_entity_id": city.id,
            "at": AGORA,
            "created_by": "teste",
        }
        assert_mapping_is_consistent(
            ProviderEntityMapping.create(resolution_decision_id="d1", **argumentos),  # type: ignore[arg-type]
            ProviderEntityMapping.create(resolution_decision_id="d2", **argumentos),  # type: ignore[arg-type]
        )

    def test_janela_de_validade_governa_a_busca(self) -> None:
        """Provedor recicla id, e sem janela o histórico ganharia jogos de
        outro clube — em silêncio."""
        city = _time("Manchester City")
        expirado = ProviderEntityMapping.create(
            provider_ref=ProviderRef(provider=PROVEDOR, external_id="4417"),
            entity_type=SubjectType.TEAM,
            canonical_entity_id=city.id,
            resolution_decision_id="d1",
            at=AGORA,
            created_by="teste",
            valid_to=instant(datetime(2020, 1, 1, tzinfo=UTC)),
        )
        assert not expirado.covers(AGORA)
        assert expirado.covers(instant(datetime(2019, 6, 1, tzinfo=UTC)))
