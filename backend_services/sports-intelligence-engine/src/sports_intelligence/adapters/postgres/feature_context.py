"""A leitura do passado publicado — SQL escrito à mão, em lote.

DUAS CONSULTAS POR LOTE (§37, §38, §39, §178), e cada uma responde uma pergunta
que a outra não responde bem:

    a JANELA      a partida ATUAL e as anteriores dentro do maior retrospecto,
                  na mesma varredura. É o que alimenta as contagens de 14 e 30
                  dias — e, por `LEFT JOIN`, também traz os dados da partida
                  atual mesmo quando ela não tem anterior nenhuma
    a ÚLTIMA      a anterior mais recente, SEM limite inferior. Ela pode ter
                  três meses — uma parada de seleções, uma lesão de calendário
                  —, e a janela de trinta dias não a encontraria

Uma consulta só não resolve as duas: sem limite inferior, buscar tudo para
contar trinta dias varreria o histórico inteiro; com limite, a última partida
some quando o intervalo é grande. Duas consultas limitadas custam menos que uma
ilimitada.

A COBERTURA É UMA TERCEIRA CONSULTA, feita UMA VEZ POR VERSÃO (§32). Ela é
propriedade da versão publicada — que é imutável (ADR-0026) —, e repeti-la a
cada lote seria pagar vinte vezes por uma resposta que não muda.

A PERTINÊNCIA É O FILTRO PRINCIPAL (§40, §41). `matches` é global: contém tudo
que qualquer build já escreveu. O que a versão publica está em
`historical_canonical_members`, e é o cruzamento com ela que separa «o passado
do corpus 1.0» de «o passado do banco».
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.features.prematch.models import (
    ContextCoverage,
    MatchContextInput,
    PriorMatchRef,
    team_prior_matches,
)
from sports_intelligence.domain.features.prematch.policy import (
    HistoricalContextPolicy,
    PriorMatchEligibility,
)
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId, TeamId
from sports_intelligence.domain.shared.temporal import instant

#: A prova de conclusão da política `PUBLISHED_RESULT` (§19, §20), na forma que
#: cada consulta precisa. Ela é uma junção com `match_results`, e não uma ida a
#: estado externo: o corpus publica o resultado, e é isso que o motor tem.
#:
#: NA JANELA ELA É `EXISTS`, e não `JOIN`: a junção ali é `LEFT`, e um `JOIN`
#: interno com `match_results` a transformaria em interna — a partida atual sem
#: anteriores sumiria do resultado, que é justamente o que o `LEFT` evita.
_EXISTE_RESULTADO: Final[str] = (
    "AND EXISTS (SELECT 1 FROM match_results r WHERE r.match_id = p.id)"
)
_JUNCAO_DE_RESULTADO: Final[str] = "JOIN match_results r ON r.match_id = p.id"


@final
class PostgresHistoricalContextSource:
    """O contexto pré-jogo de um lote de partidas, de UMA versão publicada."""

    def __init__(self, database: Database) -> None:
        self._db = database
        # A COBERTURA É MEMORIZADA POR VERSÃO, e isso é seguro porque uma
        # versão publicada é IMUTÁVEL (ADR-0026): a primeira partida de cada
        # competição nela não muda. Sem o memo, uma execução de vinte lotes
        # pagaria vinte vezes por uma resposta idêntica.
        self._cobertura: dict[str, Mapping[CompetitionId, ContextCoverage]] = {}

    async def coverage(
        self, version_id: str
    ) -> Mapping[CompetitionId, ContextCoverage]:
        """A primeira partida publicada de cada competição, naquela versão."""
        memorizada = self._cobertura.get(version_id)
        if memorizada is not None:
            return memorizada
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT p.competition_id, MIN(p.scheduled_kickoff) AS primeira
                FROM historical_canonical_members m
                JOIN matches p ON p.id = m.match_id
                WHERE m.version_id = $1
                GROUP BY p.competition_id
                """,
                uuid.UUID(version_id),
            )
        cobertura = {
            CompetitionId(linha["competition_id"]): ContextCoverage(
                competition_id=CompetitionId(linha["competition_id"]),
                earliest_kickoff=(
                    None if linha["primeira"] is None else instant(linha["primeira"])
                ),
            )
            for linha in linhas
        }
        self._cobertura[version_id] = cobertura
        return cobertura

    async def load(
        self,
        version_id: str,
        match_ids: Sequence[MatchId],
        *,
        policy: HistoricalContextPolicy,
    ) -> Mapping[MatchId, MatchContextInput]:
        if not match_ids:
            return {}
        versao = uuid.UUID(version_id)
        ids = [m.value for m in match_ids]
        cobertura = await self.coverage(version_id)
        janela = timedelta(days=policy.max_lookback_days)

        async with self._db.acquire() as conexao:
            na_janela = await self._na_janela(conexao, versao, ids, janela, policy)
            ultimas = await self._mais_recentes(conexao, versao, ids, policy)

        atuais: dict[Any, Any] = {}
        anteriores: dict[tuple[Any, Any], list[PriorMatchRef]] = {}
        for linha in na_janela:
            atuais.setdefault(linha["atual"], linha)
            if linha["anterior"] is None:
                continue
            anteriores.setdefault((linha["atual"], linha["team_id"]), []).append(
                PriorMatchRef(
                    kickoff=instant(linha["scheduled_kickoff"]),
                    match_id=MatchId(linha["anterior"]),
                )
            )

        contextos: dict[MatchId, MatchContextInput] = {}
        for identificador, linha in atuais.items():
            atual = MatchId(identificador)
            competicao = CompetitionId(linha["competition_id"])
            contextos[atual] = MatchContextInput(
                match_id=atual,
                competition_id=competicao,
                kickoff=instant(linha["atual_kickoff"]),
                home=team_prior_matches(
                    TeamId(linha["home_team_id"]),
                    _juntar(anteriores, ultimas, identificador, linha["home_team_id"]),
                ),
                away=team_prior_matches(
                    TeamId(linha["away_team_id"]),
                    _juntar(anteriores, ultimas, identificador, linha["away_team_id"]),
                ),
                coverage=cobertura.get(competicao, ContextCoverage(competicao)),
            )
        return contextos

    # ------------------------------------------------------- consultas --

    @staticmethod
    async def _na_janela(
        conexao: Any,
        version_id: uuid.UUID,
        match_ids: Sequence[Any],
        janela: timedelta,
        policy: HistoricalContextPolicy,
    ) -> Sequence[Any]:
        """A partida atual E as anteriores da janela — UMA consulta (§39).

        O `LATERAL` SOBRE OS DOIS TIMES evita duplicar a consulta por lado:
        cada partida atual gera duas linhas de time, e a junção seguinte acha
        as anteriores de cada uma. Sem ele seriam duas consultas iguais com um
        `WHERE` diferente.

        O `LEFT JOIN LATERAL` É O QUE DISPENSA UMA TERCEIRA CONSULTA (§178).
        Sem ele, uma partida sem anteriores sumiria do resultado — e o contexto
        dela precisaria de uma busca própria só para descobrir os times e o
        horário. Com ele, toda partida do lote aparece: com anteriores, ou com
        `NULL`.

        POR QUE `LATERAL` E NÃO UM `LEFT JOIN` PLANO. A primeira versão desta
        consulta juntava `historical_canonical_members mp` só por
        `version_id`, deixando os predicados sobre a partida anterior no `ON`
        da tabela seguinte. Isso produz o produto cartesiano entre as partidas
        do lote, os dois times e a pertinência INTEIRA da versão — quinhentas
        vezes dois vezes dez mil por lote —, e o benchmark de dez mil partidas
        travou nela. Com `LATERAL`, a subconsulta é avaliada UMA vez por par
        `(partida, time)` com todos os filtros dentro, e o planejador consegue
        usar o índice de calendário.
        """
        prova = (
            _EXISTE_RESULTADO
            if policy.eligibility is PriorMatchEligibility.PUBLISHED_RESULT
            else ""
        )
        linhas: Sequence[Any] = await conexao.fetch(
            f"""
            SELECT a.id AS atual, a.competition_id, a.home_team_id, a.away_team_id,
                   a.scheduled_kickoff AS atual_kickoff,
                   t.team_id, ant.anterior, ant.scheduled_kickoff
            FROM historical_canonical_members ma
            JOIN matches a ON a.id = ma.match_id
            CROSS JOIN LATERAL (VALUES (a.home_team_id), (a.away_team_id)) AS t(team_id)
            LEFT JOIN LATERAL (
                SELECT p.id AS anterior, p.scheduled_kickoff
                FROM historical_canonical_members mp
                JOIN matches p ON p.id = mp.match_id
                WHERE mp.version_id = ma.version_id
                  AND p.competition_id = a.competition_id
                  AND p.id <> a.id
                  AND p.scheduled_kickoff < a.scheduled_kickoff
                  AND p.scheduled_kickoff >= a.scheduled_kickoff - $3::interval
                  AND (p.home_team_id = t.team_id OR p.away_team_id = t.team_id)
                  {prova}
            ) AS ant ON TRUE
            WHERE ma.version_id = $1 AND ma.match_id = ANY($2::uuid[])
            ORDER BY a.id, t.team_id, ant.scheduled_kickoff, ant.anterior
            """,
            version_id,
            list(match_ids),
            janela,
        )
        return linhas

    @staticmethod
    async def _mais_recentes(
        conexao: Any,
        version_id: uuid.UUID,
        match_ids: Sequence[Any],
        policy: HistoricalContextPolicy,
    ) -> dict[tuple[Any, Any], list[PriorMatchRef]]:
        """A anterior MAIS RECENTE de cada time, sem limite inferior (§23).

        `DISTINCT ON` com `ORDER BY … DESC` devolve uma linha por par
        `(partida atual, time)`. É a construção do PostgreSQL para «o primeiro
        de cada grupo» e evita trazer o histórico inteiro para descartar quase
        tudo em memória.
        """
        prova = (
            _JUNCAO_DE_RESULTADO
            if policy.eligibility is PriorMatchEligibility.PUBLISHED_RESULT
            else ""
        )
        linhas = await conexao.fetch(
            f"""
            SELECT DISTINCT ON (a.id, t.team_id)
                   a.id AS atual, t.team_id, p.id AS anterior, p.scheduled_kickoff
            FROM historical_canonical_members ma
            JOIN matches a ON a.id = ma.match_id
            CROSS JOIN LATERAL (VALUES (a.home_team_id), (a.away_team_id)) AS t(team_id)
            JOIN historical_canonical_members mp ON mp.version_id = ma.version_id
            JOIN matches p ON p.id = mp.match_id
            {prova}
            WHERE ma.version_id = $1
              AND ma.match_id = ANY($2::uuid[])
              AND p.competition_id = a.competition_id
              AND p.id <> a.id
              AND p.scheduled_kickoff < a.scheduled_kickoff
              AND (p.home_team_id = t.team_id OR p.away_team_id = t.team_id)
            ORDER BY a.id, t.team_id, p.scheduled_kickoff DESC, p.id
            """,
            version_id,
            list(match_ids),
        )
        por_time: dict[tuple[Any, Any], list[PriorMatchRef]] = {}
        for linha in linhas:
            por_time.setdefault((linha["atual"], linha["team_id"]), []).append(
                PriorMatchRef(
                    kickoff=instant(linha["scheduled_kickoff"]),
                    match_id=MatchId(linha["anterior"]),
                )
            )
        return por_time


def _juntar(
    janela: dict[tuple[Any, Any], list[PriorMatchRef]],
    ultimas: dict[tuple[Any, Any], list[PriorMatchRef]],
    atual: Any,
    time: Any,
) -> list[PriorMatchRef]:
    """A união das duas consultas, sem repetir a partida que está nas duas.

    A MAIS RECENTE COSTUMA ESTAR NA JANELA TAMBÉM — e aí ela apareceria duas
    vezes. `TeamPriorMatches` recusa repetição, e com razão: uma partida
    contada duas vezes inflaria a contagem de catorze dias.
    """
    chave = (atual, time)
    vistos: dict[MatchId, PriorMatchRef] = {}
    for referencia in (*janela.get(chave, ()), *ultimas.get(chave, ())):
        vistos.setdefault(referencia.match_id, referencia)
    return list(vistos.values())
