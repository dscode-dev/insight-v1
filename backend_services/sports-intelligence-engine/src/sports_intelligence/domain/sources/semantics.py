"""O papel semântico de uma coluna — e o que ele deliberadamente não é.

A DECLARAÇÃO QUE ESTE MÓDULO PERMITE:

    a coluna `HomeTeam` do arquivo carrega HOME_TEAM_NAME

E a que ele NÃO permite:

    a coluna `HomeTeam` carrega TeamId

A distância entre as duas é o PR inteiro. `HOME_TEAM_NAME` diz «aqui há um
texto que a fonte usa para nomear o mandante» — uma afirmação sobre o ARQUIVO,
que o operador pode fazer olhando o cabeçalho. `TeamId` seria uma afirmação
sobre o MUNDO, e ela exige resolução com evidência, confiança e possibilidade
de falhar.

POR QUE ISSO PRECISA SER CONFIGURAÇÃO E NÃO CÓDIGO. `row["HomeTeam"]` dentro
do resolver amarra o resolver a um provedor: a próxima fonte chama de `home`,
a terceira de `Mandante`, e a saída passa a ser um `if` por fonte dentro da
lógica de identidade. Com mapeamento declarado, o resolver conhece apenas
papéis semânticos, e uma fonte nova é um arquivo de configuração.

NADA AQUI É EXECUTÁVEL (§81). O mapeamento é um dicionário de coluna para
papel, mais transformações de um catálogo FECHADO. Não há expressão, não há
`eval`, não há lambda em texto. Um mapeamento vindo de fora é entrada não
confiável, e entrada não confiável nunca vira código.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class SemanticRole(StrEnum):
    """O que uma coluna carrega. Catálogo fechado.

    FECHADO porque o resolver despacha sobre isto: um papel que ele não
    conhece não tem como ser usado, e aceitá-lo no mapeamento criaria a
    ilusão de que a coluna está sendo lida.
    """

    # ---- identidade de contexto
    COMPETITION_NAME = "COMPETITION_NAME"
    COMPETITION_CODE = "COMPETITION_CODE"
    SEASON_LABEL = "SEASON_LABEL"
    STAGE_NAME = "STAGE_NAME"
    ROUND_NUMBER = "ROUND_NUMBER"

    # ---- identidade de partida
    HOME_TEAM_NAME = "HOME_TEAM_NAME"
    AWAY_TEAM_NAME = "AWAY_TEAM_NAME"
    HOME_TEAM_PROVIDER_ID = "HOME_TEAM_PROVIDER_ID"
    AWAY_TEAM_PROVIDER_ID = "AWAY_TEAM_PROVIDER_ID"
    MATCH_PROVIDER_ID = "MATCH_PROVIDER_ID"
    KICKOFF = "KICKOFF"
    KICKOFF_DATE = "KICKOFF_DATE"
    KICKOFF_TIME = "KICKOFF_TIME"
    VENUE_NAME = "VENUE_NAME"

    # ---- identidade de time e jogador
    TEAM_NAME = "TEAM_NAME"
    TEAM_PROVIDER_ID = "TEAM_PROVIDER_ID"
    TEAM_COUNTRY = "TEAM_COUNTRY"
    PLAYER_NAME = "PLAYER_NAME"
    PLAYER_PROVIDER_ID = "PLAYER_PROVIDER_ID"
    PLAYER_DOB = "PLAYER_DOB"
    PLAYER_NATIONALITY = "PLAYER_NATIONALITY"
    PLAYER_POSITION = "PLAYER_POSITION"

    # ---- observações. NÃO participam da identidade; entram na fusão.
    HOME_SCORE = "HOME_SCORE"
    AWAY_SCORE = "AWAY_SCORE"
    HOME_SHOTS = "HOME_SHOTS"
    AWAY_SHOTS = "AWAY_SHOTS"
    HOME_SHOTS_ON_TARGET = "HOME_SHOTS_ON_TARGET"
    AWAY_SHOTS_ON_TARGET = "AWAY_SHOTS_ON_TARGET"
    HOME_CORNERS = "HOME_CORNERS"
    AWAY_CORNERS = "AWAY_CORNERS"
    HOME_XG = "HOME_XG"
    AWAY_XG = "AWAY_XG"
    HOME_POSSESSION = "HOME_POSSESSION"
    AWAY_POSSESSION = "AWAY_POSSESSION"
    HOME_FORMATION = "HOME_FORMATION"
    AWAY_FORMATION = "AWAY_FORMATION"
    ATTENDANCE = "ATTENDANCE"
    REFEREE_NAME = "REFEREE_NAME"

    # ---- odds. Observações por casa, NUNCA fundidas entre si (§54).
    BOOKMAKER_NAME = "BOOKMAKER_NAME"
    ODDS_HOME = "ODDS_HOME"
    ODDS_DRAW = "ODDS_DRAW"
    ODDS_AWAY = "ODDS_AWAY"

    @property
    def is_identity(self) -> bool:
        """Se este papel participa da RESOLUÇÃO de identidade.

        A distinção governa o pipeline: papéis de identidade alimentam os
        resolvers; papéis de observação só entram depois, na fusão, e apenas
        para registros cuja identidade já foi provada (ADR-0022).
        """
        return self in _IDENTIDADE

    @property
    def is_observation(self) -> bool:
        return not self.is_identity

    @property
    def is_identity_label(self) -> bool:
        """Se este papel é apenas o NOME que uma fonte dá a uma entidade.

        A DISTINÇÃO QUE ESTE PROPRIEDADE EXISTE PARA FAZER (PR-04.2.1 §4, §11).
        Nem todo papel de identidade afirma um FATO. Há dois tipos, e tratá-los
        igual erra nos dois sentidos:

            RÓTULO      `Man City`, `Manchester City FC`, um id de provedor
                        É evidência para RECONHECER a entidade. Depois que a
                        resolução provou que os três são `TeamId(X)`, a
                        diferença textual entre eles não afirma nada sobre o
                        mundo — e tratá-la como desacordo faria toda fusão
                        multi-fonte legítima reprovar por consistência.

            FATO        `kickoff`, `rodada`, `estádio`, `fase`
                        A fonte está afirmando algo sobre a partida. Duas
                        fontes com 20:00 e 23:00 discordam de verdade, e a
                        fonte que afirma é PROCEDÊNCIA FACTUAL do núcleo — com
                        as consequências de licença que isso implica.

        O CATÁLOGO É FECHADO porque a classificação decide duas coisas caras:
        se um desacordo é conflito, e se uma licença restrita contamina o fato
        canônico. Deixá-la implícita faria cada leitor decidir sozinho.
        """
        return self in _RÓTULOS_DE_IDENTIDADE

    @property
    def is_factual(self) -> bool:
        """Se este papel AFIRMA alguma coisa sobre o mundo.

        Tudo que não é rótulo de identidade: as observações e os papéis de
        identidade que carregam fato (`KICKOFF` e companhia).
        """
        return not self.is_identity_label

    @property
    def is_odds(self) -> bool:
        """Odds são observação de UMA casa, não campo de partida.

        Duas casas cotando 2,00 e 2,05 NÃO estão em conflito — estão dizendo
        coisas diferentes sobre o mesmo jogo, e as duas são verdade. Fundi-las
        numa cotação única destruiria a informação inteira (§54).
        """
        return self in _ODDS

    @property
    def value_kind(self) -> ValueKind:
        return _TIPOS.get(self, ValueKind.TEXT)


class ValueKind(StrEnum):
    """O tipo esperado do valor, para conversão declarativa e segura."""

    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"


_IDENTIDADE: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.COMPETITION_NAME,
        SemanticRole.COMPETITION_CODE,
        SemanticRole.SEASON_LABEL,
        SemanticRole.STAGE_NAME,
        SemanticRole.ROUND_NUMBER,
        SemanticRole.HOME_TEAM_NAME,
        SemanticRole.AWAY_TEAM_NAME,
        SemanticRole.HOME_TEAM_PROVIDER_ID,
        SemanticRole.AWAY_TEAM_PROVIDER_ID,
        SemanticRole.MATCH_PROVIDER_ID,
        SemanticRole.KICKOFF,
        SemanticRole.KICKOFF_DATE,
        SemanticRole.KICKOFF_TIME,
        SemanticRole.VENUE_NAME,
        SemanticRole.TEAM_NAME,
        SemanticRole.TEAM_PROVIDER_ID,
        SemanticRole.TEAM_COUNTRY,
        SemanticRole.PLAYER_NAME,
        SemanticRole.PLAYER_PROVIDER_ID,
        SemanticRole.PLAYER_DOB,
        SemanticRole.PLAYER_NATIONALITY,
        SemanticRole.PLAYER_POSITION,
    }
)

#: OS PAPÉIS QUE SÃO SÓ NOME (PR-04.2.1 §4, §5, §11).
#:
#: Todos eles são consumidos pela RESOLUÇÃO e não sobrevivem à passagem para o
#: canônico: `Man City` vira `TeamId(X)`, e o que o corpus guarda é o id. Uma
#: fonte que escreve o nome de outro jeito ajudou a reconhecer a entidade e não
#: afirmou nada sobre a partida.
#:
#: `SEASON_LABEL` E `COMPETITION_NAME` ESTÃO AQUI pelo mesmo motivo: `2024/25`
#: e `2024-2025` são a mesma temporada, provada por decisão de resolução.
#:
#: `KICKOFF` NÃO ESTÁ, e a ausência é a decisão do §12: o horário é um FATO
#: sobre a partida, e duas fontes com 20:00 e 23:00 discordam de verdade.
_RÓTULOS_DE_IDENTIDADE: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.COMPETITION_NAME,
        SemanticRole.COMPETITION_CODE,
        SemanticRole.SEASON_LABEL,
        SemanticRole.HOME_TEAM_NAME,
        SemanticRole.AWAY_TEAM_NAME,
        SemanticRole.HOME_TEAM_PROVIDER_ID,
        SemanticRole.AWAY_TEAM_PROVIDER_ID,
        SemanticRole.MATCH_PROVIDER_ID,
        SemanticRole.TEAM_NAME,
        SemanticRole.TEAM_PROVIDER_ID,
        SemanticRole.TEAM_COUNTRY,
        SemanticRole.PLAYER_NAME,
        SemanticRole.PLAYER_PROVIDER_ID,
        SemanticRole.PLAYER_DOB,
        SemanticRole.PLAYER_NATIONALITY,
        SemanticRole.PLAYER_POSITION,
    }
)

_ODDS: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.BOOKMAKER_NAME,
        SemanticRole.ODDS_HOME,
        SemanticRole.ODDS_DRAW,
        SemanticRole.ODDS_AWAY,
    }
)

_TIPOS: Final[dict[SemanticRole, ValueKind]] = {
    SemanticRole.ROUND_NUMBER: ValueKind.INTEGER,
    SemanticRole.KICKOFF: ValueKind.TIMESTAMP,
    SemanticRole.KICKOFF_DATE: ValueKind.DATE,
    SemanticRole.KICKOFF_TIME: ValueKind.TIME,
    SemanticRole.PLAYER_DOB: ValueKind.DATE,
    SemanticRole.HOME_SCORE: ValueKind.INTEGER,
    SemanticRole.AWAY_SCORE: ValueKind.INTEGER,
    SemanticRole.HOME_SHOTS: ValueKind.INTEGER,
    SemanticRole.AWAY_SHOTS: ValueKind.INTEGER,
    SemanticRole.HOME_SHOTS_ON_TARGET: ValueKind.INTEGER,
    SemanticRole.AWAY_SHOTS_ON_TARGET: ValueKind.INTEGER,
    SemanticRole.HOME_CORNERS: ValueKind.INTEGER,
    SemanticRole.AWAY_CORNERS: ValueKind.INTEGER,
    SemanticRole.ATTENDANCE: ValueKind.INTEGER,
    SemanticRole.HOME_XG: ValueKind.DECIMAL,
    SemanticRole.AWAY_XG: ValueKind.DECIMAL,
    SemanticRole.HOME_POSSESSION: ValueKind.DECIMAL,
    SemanticRole.AWAY_POSSESSION: ValueKind.DECIMAL,
    SemanticRole.ODDS_HOME: ValueKind.DECIMAL,
    SemanticRole.ODDS_DRAW: ValueKind.DECIMAL,
    SemanticRole.ODDS_AWAY: ValueKind.DECIMAL,
}

#: Os papéis mínimos para que um dataset de partidas seja resolvível. Sem os
#: quatro, não há como sequer procurar uma partida.
MATCH_REQUIRED_ROLES: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.HOME_TEAM_NAME,
        SemanticRole.AWAY_TEAM_NAME,
        SemanticRole.SEASON_LABEL,
    }
)
