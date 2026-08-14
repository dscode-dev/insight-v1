"""O contexto de resolução: tudo carregado de uma vez, resolvido em memória.

O N+1 É O DEFEITO QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§42, §74). O caminho
ingênuo resolve linha a linha e consulta o banco por linha:

    100.000 linhas por 7 evidências = 700.000 SELECTs

Cada uma delas é uma ida à rede. Numa máquina razoável isso são horas, e o
sintoma não é erro — é «a resolução está lenta», que ninguém sabe de onde vem.

A SAÍDA É INVERTER A ORDEM. O lote diz quais valores DISTINTOS existem nele —
um lote de mil linhas de Premier League tem vinte nomes de clube, não mil —, o
contexto carrega tudo que pode casar com eles numa consulta por tipo, e os
resolvers passam a trabalhar sobre dicionários em memória.

    ler lote → valores distintos → carregar candidatos → resolver → persistir
      1 I/O        0 I/O            ~6 consultas         0 I/O      1 I/O

O CONTEXTO É SÓ LEITURA E VIVE UM LOTE. Não é cache com invalidação: é uma
fotografia do registro canônico no momento em que o lote começou. Isso importa
para o determinismo — um mapeamento criado no meio do lote não muda decisões
já tomadas no mesmo lote, e reprocessar o lote inteiro produz o mesmo
resultado (§33, §35).

REDIS NÃO ENTRA AQUI (§35). A autoridade é o PostgreSQL e o escopo é uma
execução; um cache distribuído resolveria um problema de leituras repetidas
entre execuções que ainda não existe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import Competition, Season
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.mappings import (
    EntityAlias,
    ProviderEntityMapping,
    alias_lookup_key,
    mapping_lookup_key,
)
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    EntityId,
    PlayerId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer

#: Teto de entidades carregadas por lote. Existe porque um lote com nomes
#: muito genéricos pode casar com meio registro canônico, e materializar tudo
#: anularia a promessa de memória previsível.
MAX_CANDIDATES_LOADED: Final[int] = 50_000


@final
@dataclass(frozen=True, slots=True)
class NormalizedName:
    """Um nome já preparado. Calculado UMA vez por valor distinto do lote.

    Sem isto, cada comparação renormalizaria — e um lote compara cada nome de
    fonte contra dezenas de candidatos, o que faz a normalização rodar
    milhares de vezes sobre os mesmos vinte nomes.
    """

    raw: str
    normalized: str
    tokens: tuple[str, ...]

    @classmethod
    def of(cls, raw: str, normalizer: NameNormalizer) -> NormalizedName:
        return cls(
            raw=raw,
            normalized=normalizer.normalize(raw),
            tokens=normalizer.tokens(raw),
        )


@final
@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """A fotografia do registro canônico para um lote.

    TODOS OS ÍNDICES SÃO DICIONÁRIOS, e a busca é O(1). O único caminho que
    varre é a similaridade de nome, e ela varre apenas os candidatos do tipo
    certo — não o registro inteiro.
    """

    #: Quando este contexto foi montado. Congela as janelas de validade:
    #: um mapeamento que expira no meio do lote continua valendo para o lote.
    loaded_at: Instant
    normalizer: NameNormalizer

    # ---- índices exatos, por chave de busca
    mappings: dict[str, ProviderEntityMapping] = field(default_factory=dict)
    aliases: dict[str, tuple[EntityAlias, ...]] = field(default_factory=dict)

    # ---- entidades canônicas, por id
    competitions: dict[CompetitionId, Competition] = field(default_factory=dict)
    seasons: dict[SeasonId, Season] = field(default_factory=dict)
    teams: dict[TeamId, Team] = field(default_factory=dict)
    players: dict[PlayerId, Player] = field(default_factory=dict)
    matches: dict[str, Match] = field(default_factory=dict)

    # ---- índices derivados, montados no carregamento
    #: nome normalizado → times com aquele nome canônico
    teams_by_normalized_name: dict[str, tuple[TeamId, ...]] = field(default_factory=dict)
    #: nome CONSULTADO → os candidatos de similaridade daquele nome.
    #:
    #: O ÍNDICE QUE TORNA A DECISÃO INDEPENDENTE DO LOTE (§29 a §33). Até o
    #: PR-03.1 o resolver varria `teams` inteiro — que continha o que AQUELE
    #: lote tinha carregado por chave exata —, então um lote de cinco mil
    #: linhas enxergava candidatos que um lote de duzentos e cinquenta nem
    #: lia. A medição pegou: 2,7% das listas de alternativas mudavam.
    #:
    #: Aqui a chave é o nome consultado, e o conjunto vem de uma busca que
    #: depende SÓ dele — times que compartilham um token com ele. O que mais
    #: estiver no lote deixou de ter efeito.
    team_candidates_by_name: dict[str, tuple[TeamId, ...]] = field(default_factory=dict)
    #: O mesmo para jogador, pelo mesmo motivo.
    player_candidates_by_name: dict[str, tuple[PlayerId, ...]] = field(default_factory=dict)
    #: nome normalizado → jogadores homônimos. TUPLA e não id único: é
    #: exatamente aqui que os homônimos aparecem, e um dicionário para id
    #: único os esconderia mantendo o último.
    players_by_normalized_name: dict[str, tuple[PlayerId, ...]] = field(default_factory=dict)
    #: (competição, rótulo normalizado) → temporada
    seasons_by_label: dict[tuple[CompetitionId, str], SeasonId] = field(default_factory=dict)
    #: jogador → vínculos, para a evidência temporal
    tenures_by_player: dict[PlayerId, tuple[PlayerTeamTenure, ...]] = field(default_factory=dict)
    #: (temporada, mandante, visitante) → partidas. A chave de agrupamento da
    #: resolução de partida: ela reduz o espaço de busca de «todas as
    #: partidas» para «as deste confronto nesta temporada», que são uma ou
    #: duas.
    matches_by_fixture: dict[tuple[SeasonId, TeamId, TeamId], tuple[str, ...]] = field(
        default_factory=dict
    )
    #: (competição, temporada) → times que de fato participaram. É a
    #: evidência `HISTORICAL_PARTICIPATION`, e ela é o que distingue dois
    #: clubes de nome parecido em países diferentes.
    participants: dict[tuple[CompetitionId, SeasonId], frozenset[TeamId]] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------ buscas --

    def mapping_for(
        self, provider: ProviderId, subject: SubjectType, external_id: str
    ) -> ProviderEntityMapping | None:
        """O mapeamento de uma referência de provedor, se válido AGORA.

        A JANELA É CONFERIDA AQUI e não na consulta SQL: carregar só os
        vigentes esconderia a existência de um mapeamento expirado, e a
        diferença entre «nunca houve» e «houve e expirou» é informação para
        quem investiga um id de provedor que parou de resolver.
        """
        encontrado = self.mappings.get(mapping_lookup_key(provider, subject, external_id))
        if encontrado is None:
            return None
        return encontrado if encontrado.covers(self.loaded_at) else None

    def aliases_for(self, subject: SubjectType, normalized: str) -> tuple[EntityAlias, ...]:
        candidatos = self.aliases.get(alias_lookup_key(subject, normalized), ())
        return tuple(a for a in candidatos if a.covers(self.loaded_at))

    def teams_named(self, normalized: str) -> tuple[TeamId, ...]:
        return self.teams_by_normalized_name.get(normalized, ())

    def team_candidates_for(self, normalized: str) -> tuple[TeamId, ...]:
        """Os candidatos de similaridade DAQUELE nome, e de nenhum outro.

        VAZIO É RESPOSTA LEGÍTIMA: significa que a busca não achou nenhum
        clube que compartilhe um token com o nome. O resolver então não gera
        candidato, e o registro fica `UNRESOLVED` — que é o desfecho certo e
        o mesmo em qualquer tamanho de lote.
        """
        return self.team_candidates_by_name.get(normalized, ())

    def player_candidates_for(self, normalized: str) -> tuple[PlayerId, ...]:
        return self.player_candidates_by_name.get(normalized, ())

    def players_named(self, normalized: str) -> tuple[PlayerId, ...]:
        return self.players_by_normalized_name.get(normalized, ())

    def team_of_player_at(self, player: PlayerId, moment: Instant) -> TeamId | None:
        """O clube do jogador NAQUELA data — não o atual.

        Delegado a `team_at` do PR-01, que devolve `None` quando nenhum
        vínculo cobre a data. Devolver o clube atual como aproximação
        reescreveria o passado, e aqui isso viraria evidência falsa a favor
        de um candidato errado.
        """
        from sports_intelligence.domain.players.models import team_at

        return team_at(self.tenures_by_player.get(player, ()), moment)

    def fixtures(
        self, season: SeasonId, home: TeamId, away: TeamId
    ) -> tuple[Match, ...]:
        ids = self.matches_by_fixture.get((season, home, away), ())
        return tuple(m for i in ids if (m := self.matches.get(i)) is not None)

    def participated(
        self, competition: CompetitionId, season: SeasonId, team: TeamId
    ) -> bool | None:
        """Se o clube jogou aquela competição naquela temporada.

        `None` E NÃO `False` QUANDO NÃO SE SABE. Um registro canônico ainda
        vazio não tem participantes, e responder `False` transformaria
        ignorância em evidência contrária — todo candidato seria penalizado
        por um fato que ninguém verificou.
        """
        conhecidos = self.participants.get((competition, season))
        if conhecidos is None:
            return None
        return team in conhecidos

    def entity_label(self, subject: SubjectType, entity: EntityId) -> str | None:
        """O nome legível de uma entidade, para a fila de revisão.

        Sem ele, um humano abriria a fila e veria dois UUIDs para escolher.
        """
        if subject is SubjectType.TEAM and isinstance(entity, TeamId):
            time = self.teams.get(entity)
            return time.canonical_name if time else None
        if subject is SubjectType.PLAYER and isinstance(entity, PlayerId):
            jogador = self.players.get(entity)
            return jogador.canonical_name if jogador else None
        if subject is SubjectType.COMPETITION and isinstance(entity, CompetitionId):
            competicao = self.competitions.get(entity)
            return competicao.name if competicao else None
        if subject is SubjectType.SEASON and isinstance(entity, SeasonId):
            temporada = self.seasons.get(entity)
            return temporada.label if temporada else None
        return None

    @property
    def loaded_entities(self) -> int:
        return (
            len(self.competitions)
            + len(self.seasons)
            + len(self.teams)
            + len(self.players)
            + len(self.matches)
        )


@final
class ContextBuilder:
    """Monta o contexto a partir do que foi carregado em massa.

    ELE EXISTE PARA QUE OS ÍNDICES DERIVADOS SEJAM MONTADOS NUM LUGAR SÓ. Se
    cada repositório montasse o seu, dois deles normalizariam o nome de forma
    ligeiramente diferente — e um clube passaria a casar por um índice e não
    pelo outro.
    """

    def __init__(self, normalizer: NameNormalizer, loaded_at: Instant) -> None:
        self._normalizer = normalizer
        self._loaded_at = loaded_at
        self._contexto = ResolutionContext(loaded_at=loaded_at, normalizer=normalizer)

    def with_mappings(self, mappings: tuple[ProviderEntityMapping, ...]) -> ContextBuilder:
        for mapeamento in mappings:
            self._contexto.mappings[mapeamento.lookup_key] = mapeamento
        return self

    def with_aliases(self, aliases: tuple[EntityAlias, ...]) -> ContextBuilder:
        for alias in aliases:
            chave = alias.lookup_key
            self._contexto.aliases[chave] = (*self._contexto.aliases.get(chave, ()), alias)
        return self

    def with_competitions(self, competitions: tuple[Competition, ...]) -> ContextBuilder:
        for competicao in competitions:
            self._contexto.competitions[competicao.id] = competicao
        return self

    def with_seasons(self, seasons: tuple[Season, ...]) -> ContextBuilder:
        for temporada in seasons:
            self._contexto.seasons[temporada.id] = temporada
            chave = (temporada.competition_id, self._normalizer.normalize(temporada.label))
            self._contexto.seasons_by_label[chave] = temporada.id
        return self

    def with_team_candidates(
        self, candidates: tuple[tuple[str, Team], ...]
    ) -> ContextBuilder:
        """Registra (nome consultado, time candidato) e indexa por nome.

        ORDENADO PELO ID ao final: a ordem do índice não pode vir da ordem em
        que o PostgreSQL devolveu as linhas, senão o desempate entre
        candidatos de score igual mudaria entre execuções (§36).
        """
        agrupado: dict[str, list[TeamId]] = {}
        for consulta, time in candidates:
            self._contexto.teams[time.id] = time
            agrupado.setdefault(consulta, []).append(time.id)
        for consulta, ids in agrupado.items():
            existentes = self._contexto.team_candidates_by_name.get(consulta, ())
            self._contexto.team_candidates_by_name[consulta] = tuple(
                sorted({*existentes, *ids}, key=str)
            )
        return self

    def with_player_candidates(
        self, candidates: tuple[tuple[str, Player], ...]
    ) -> ContextBuilder:
        agrupado: dict[str, list[PlayerId]] = {}
        for consulta, jogador in candidates:
            self._contexto.players[jogador.id] = jogador
            agrupado.setdefault(consulta, []).append(jogador.id)
        for consulta, ids in agrupado.items():
            existentes = self._contexto.player_candidates_by_name.get(consulta, ())
            self._contexto.player_candidates_by_name[consulta] = tuple(
                sorted({*existentes, *ids}, key=str)
            )
        return self

    def with_teams(self, teams: tuple[Team, ...]) -> ContextBuilder:
        for time in teams:
            self._contexto.teams[time.id] = time
            chave = self._normalizer.normalize(time.canonical_name)
            self._contexto.teams_by_normalized_name[chave] = (
                *self._contexto.teams_by_normalized_name.get(chave, ()),
                time.id,
            )
        return self

    def with_players(
        self,
        players: tuple[Player, ...],
        tenures: tuple[PlayerTeamTenure, ...] = (),
    ) -> ContextBuilder:
        for jogador in players:
            self._contexto.players[jogador.id] = jogador
            chave = self._normalizer.normalize(jogador.canonical_name)
            self._contexto.players_by_normalized_name[chave] = (
                *self._contexto.players_by_normalized_name.get(chave, ()),
                jogador.id,
            )
        for vinculo in tenures:
            self._contexto.tenures_by_player[vinculo.player_id] = (
                *self._contexto.tenures_by_player.get(vinculo.player_id, ()),
                vinculo,
            )
        return self

    def with_matches(self, matches: tuple[Match, ...]) -> ContextBuilder:
        for partida in matches:
            self._contexto.matches[str(partida.id)] = partida
            chave = (partida.season_id, partida.home_team_id, partida.away_team_id)
            self._contexto.matches_by_fixture[chave] = (
                *self._contexto.matches_by_fixture.get(chave, ()),
                str(partida.id),
            )
            participacao = (partida.competition_id, partida.season_id)
            atuais = self._contexto.participants.get(participacao, frozenset())
            self._contexto.participants[participacao] = atuais | {
                partida.home_team_id,
                partida.away_team_id,
            }
        return self

    def build(self) -> ResolutionContext:
        return self._contexto


def competition_code_of(
    context: ResolutionContext, competition: CompetitionId
) -> CompetitionCode | None:
    competicao = context.competitions.get(competition)
    return competicao.code if competicao else None
