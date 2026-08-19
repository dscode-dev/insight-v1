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

    # ---- eventos (PR-04.4.1). UMA LINHA É UM EVENTO, e nenhum destes papéis
    # aparece num `MATCH_RECORD`: eles descrevem um fato pontual da partida,
    # não um atributo dela. A separação é imposta pelo `RecordKind` e
    # verificada no mapeamento — um arquivo não pode ser as duas coisas.
    #
    # NÃO EXISTE `EVENT_1_*`. Modelar uma coleção como colunas numeradas
    # quebra no primeiro jogo com mais eventos que colunas (§9).
    EVENT_PROVIDER_ID = "EVENT_PROVIDER_ID"
    EVENT_TYPE = "EVENT_TYPE"
    EVENT_PERIOD = "EVENT_PERIOD"
    EVENT_MINUTE = "EVENT_MINUTE"
    #: O `+3` de `45+3`. SEPARADO do minuto porque achatá-los confunde o
    #: terceiro minuto de acréscimo do primeiro tempo com o terceiro do
    #: segundo — momentos táticos opostos (§15, `MatchClock`).
    EVENT_STOPPAGE = "EVENT_STOPPAGE"
    #: A ordem DENTRO do período, quando a fonte a declara. É o desempate do
    #: §18: dois eventos no mesmo minuto precisam de ordem determinística, e
    #: inventá-la sem procedência seria fabricar sequência (§17).
    EVENT_SEQUENCE = "EVENT_SEQUENCE"
    EVENT_TEAM_PROVIDER_ID = "EVENT_TEAM_PROVIDER_ID"
    EVENT_TEAM_NAME = "EVENT_TEAM_NAME"
    EVENT_PLAYER_PROVIDER_ID = "EVENT_PLAYER_PROVIDER_ID"
    EVENT_PLAYER_NAME = "EVENT_PLAYER_NAME"
    #: Coordenadas NORMALIZADAS pela fonte, em [0,1]. O motor não converte
    #: metros: as dimensões do campo variam e a fonte é quem as conhece.
    EVENT_X = "EVENT_X"
    EVENT_Y = "EVENT_Y"
    EVENT_END_X = "EVENT_END_X"
    EVENT_END_Y = "EVENT_END_Y"
    #: `NEW` / `CORRECTION` / `CANCELLATION`. A revisão é DECLARADA pela
    #: fonte; deduzi-la de um id repetido faria toda reingestão parecer
    #: correção (§21, §22, §23).
    EVENT_REVISION_TYPE = "EVENT_REVISION_TYPE"
    EVENT_SUPERSEDES_PROVIDER_ID = "EVENT_SUPERSEDES_PROVIDER_ID"

    # ---- detalhes tipados. Só os que os contratos do PR-01 já sabem receber:
    # um papel cujo valor não tem onde morar é um papel que descarta dado em
    # silêncio.
    EVENT_OUTCOME = "EVENT_OUTCOME"
    EVENT_BODY_PART = "EVENT_BODY_PART"
    #: xG OBSERVADO pela fonte. Nunca calculado aqui (§119).
    EVENT_XG = "EVENT_XG"
    EVENT_CARD_TYPE = "EVENT_CARD_TYPE"
    EVENT_PLAYER_OUT_PROVIDER_ID = "EVENT_PLAYER_OUT_PROVIDER_ID"
    EVENT_PLAYER_IN_PROVIDER_ID = "EVENT_PLAYER_IN_PROVIDER_ID"

    @property
    def is_event(self) -> bool:
        """Se este papel só faz sentido num `EVENT_RECORD`.

        A PROPRIEDADE EXISTE PARA A GUARDA DO MAPEAMENTO: um arquivo de
        partidas com `EVENT_MINUTE` mapeado, ou um de eventos sem
        `EVENT_TYPE`, são erros de declaração — e é melhor recusá-los na
        configuração do que descobrir na leitura.
        """
        return self in _EVENTO

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
        return self in _RÓTULOS_DE_IDENTIDADE_COMPLETOS

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

#: OS PAPÉIS DE EVENTO. Fechado, e a lista é a definição de `is_event`.
_EVENTO: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.EVENT_PROVIDER_ID,
        SemanticRole.EVENT_TYPE,
        SemanticRole.EVENT_PERIOD,
        SemanticRole.EVENT_MINUTE,
        SemanticRole.EVENT_STOPPAGE,
        SemanticRole.EVENT_SEQUENCE,
        SemanticRole.EVENT_TEAM_PROVIDER_ID,
        SemanticRole.EVENT_TEAM_NAME,
        SemanticRole.EVENT_PLAYER_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_NAME,
        SemanticRole.EVENT_X,
        SemanticRole.EVENT_Y,
        SemanticRole.EVENT_END_X,
        SemanticRole.EVENT_END_Y,
        SemanticRole.EVENT_REVISION_TYPE,
        SemanticRole.EVENT_SUPERSEDES_PROVIDER_ID,
        SemanticRole.EVENT_OUTCOME,
        SemanticRole.EVENT_BODY_PART,
        SemanticRole.EVENT_XG,
        SemanticRole.EVENT_CARD_TYPE,
        SemanticRole.EVENT_PLAYER_OUT_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_IN_PROVIDER_ID,
    }
)

#: OS PAPÉIS DE EVENTO QUE SÃO SÓ RÓTULO (PR-04.2.1 §4, PR-04.4.1 §49).
#:
#: `EVENT_TEAM_NAME` e `EVENT_PLAYER_NAME` servem para RECONHECER quem agiu; o
#: evento canônico não é construído a partir do texto, e sim do
#: `TeamId`/`PlayerId` que a resolução já provou. Contá-los na pegada de
#: licença faria uma fonte restrita condenar um evento por ter dito o nome do
#: jogador — a mesma lavagem pelo caminho da identidade que o PR-04.2.1
#: fechou para partidas.
#:
#: O QUE NÃO ESTÁ AQUI é o que a fonte AFIRMA: tipo, período, minuto,
#: acréscimo, coordenadas, desfecho, xG. Esses são fato, e quem os afirma é
#: procedência factual do evento.
_ROTULOS_DE_EVENTO: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.EVENT_TEAM_NAME,
        SemanticRole.EVENT_PLAYER_NAME,
        SemanticRole.EVENT_TEAM_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_OUT_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_IN_PROVIDER_ID,
        SemanticRole.EVENT_PROVIDER_ID,
        SemanticRole.EVENT_SUPERSEDES_PROVIDER_ID,
    }
)
#: Os rótulos de identidade DEPOIS de o PR-04.4.1 acrescentar os de evento. A
#: união mora numa constante só porque `is_identity_label` precisa enxergar as
#: duas famílias — uma fronteira que valesse para partida e não para evento
#: seria uma porta aberta com um cadeado ao lado.
_RÓTULOS_DE_IDENTIDADE_COMPLETOS: Final[frozenset[SemanticRole]] = (
    _RÓTULOS_DE_IDENTIDADE | _ROTULOS_DE_EVENTO
)

_TIPOS: Final[dict[SemanticRole, ValueKind]] = {
    SemanticRole.EVENT_MINUTE: ValueKind.INTEGER,
    SemanticRole.EVENT_STOPPAGE: ValueKind.INTEGER,
    SemanticRole.EVENT_SEQUENCE: ValueKind.INTEGER,
    SemanticRole.EVENT_X: ValueKind.DECIMAL,
    SemanticRole.EVENT_Y: ValueKind.DECIMAL,
    SemanticRole.EVENT_END_X: ValueKind.DECIMAL,
    SemanticRole.EVENT_END_Y: ValueKind.DECIMAL,
    SemanticRole.EVENT_XG: ValueKind.DECIMAL,
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
