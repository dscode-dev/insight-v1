"""Escreve o corpus no PostgreSQL — o único caminho de escrita do registro.

POR QUE O `INSERT` MORA NUM ARQUIVO DE TESTE. `PostgresCanonicalRegistry` só
LÊ, e é deliberado: povoar o registro canônico é o PR-04 (construção histórica
canônica), e um método de escrita no adapter agora seria uma porta aberta para
que qualquer caminho criasse entidade canônica sem passar pela qualidade.

O que este módulo faz é montar CENÁRIO, e cenário de teste pode escrever no
banco de teste. A distinção fica visível pelo lugar: nada em `src/` ganha a
capacidade de criar um `TeamId` novo por causa deste arquivo.

`ON CONFLICT DO NOTHING` EM TUDO. O corpus é derivado por `uuid5`, então
semear duas vezes é semear o mesmo — e o segundo `INSERT` é ruído, não erro.
É o que permite reusar o mesmo registro entre o benchmark e a integração sem
pagar a semeadura duas vezes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.competitions.models import Competition, Season
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.mappings import EntityAlias
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer
from tests.support.corpus import Corpus

#: As tabelas que um cenário suja e que o próximo precisa encontrar vazias.
#: NÃO INCLUI o registro canônico: ele é derivado e idempotente, e reescrevê-lo
#: a cada teste custaria segundos por teste sem isolar nada (§49).
TABELAS_DE_EXECUCAO: tuple[str, ...] = (
    "fusion_runs",
    "resolution_runs",
    "source_mapping_definitions",
    "datasets",
    "dataset_audit_log",
    "provider_entity_mappings",
)


async def limpar_execucoes(database: Database) -> None:
    """Zera o que uma execução produz, preservando o registro canônico.

    `TRUNCATE ... CASCADE` e não `DROP SCHEMA`: reaplicar as migrations por
    teste custaria segundos por teste, e o que se quer isolar é o DADO.
    """
    async with database.acquire() as conexao:
        await conexao.execute(
            f"TRUNCATE {', '.join(TABELAS_DE_EXECUCAO)} RESTART IDENTITY CASCADE"
        )


async def seed_corpus(database: Database, corpus: Corpus) -> None:
    """Grava competições, temporadas, times, aliases, jogadores e partidas."""
    normalizador = NameNormalizer()
    async with database.acquire() as conexao, conexao.transaction():
        await _competicoes(conexao, corpus.competitions)
        await _temporadas(conexao, corpus.seasons, normalizador)
        await _times(conexao, [t.team for t in corpus.teams], normalizador)
        await _aliases(conexao, corpus.aliases)
        await _jogadores(conexao, corpus.players, normalizador)
        await _vinculos(conexao, corpus.tenures)
        await _partidas(conexao, corpus.matches)


async def _competicoes(conexao: Any, competicoes: Sequence[Competition]) -> None:
    await conexao.executemany(
        """
        INSERT INTO competitions (id, code, name, region, competition_type, active)
        VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING
        """,
        [
            (c.id.value, c.code.value, c.name, c.region, c.competition_type, c.active)
            for c in competicoes
        ],
    )


async def _temporadas(
    conexao: Any, temporadas: Sequence[Season], normalizador: NameNormalizer
) -> None:
    await conexao.executemany(
        """
        INSERT INTO seasons (
            id, competition_id, label, normalized_label, starts_at, ends_at,
            regime_code, regime_from, regime_to, regulation_version
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (id) DO NOTHING
        """,
        [
            (
                s.id.value,
                s.competition_id.value,
                s.label,
                normalizador.normalize(s.label),
                s.starts_at,
                s.ends_at,
                s.regime.code.value,
                s.regime.effective_from,
                s.regime.effective_to,
                s.regime.regulation_version,
            )
            for s in temporadas
        ],
    )


async def _times(conexao: Any, times: Sequence[Team], normalizador: NameNormalizer) -> None:
    await conexao.executemany(
        """
        INSERT INTO teams (
            id, canonical_name, normalized_name, normalizer_major, normalizer_minor,
            country, short_name, active
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT (id) DO NOTHING
        """,
        [
            (
                t.id.value,
                t.canonical_name,
                # A COLUNA NORMALIZADA É ESCRITA PELO MESMO NORMALIZADOR que a
                # resolução usa (§66). Escrevê-la com outra regra faria a busca
                # em massa não encontrar o que existe — e o sintoma seria
                # «nada resolve», sem nenhum erro.
                normalizador.normalize(t.canonical_name),
                normalizador.version.major,
                normalizador.version.minor,
                t.country,
                t.short_name,
                t.active,
            )
            for t in times
        ],
    )


async def _aliases(conexao: Any, aliases: Sequence[EntityAlias]) -> None:
    await conexao.executemany(
        """
        INSERT INTO entity_aliases (
            id, entity_type, entity_id, alias_original, alias_normalized,
            normalizer_major, normalizer_minor, provider_id, valid_from, valid_to,
            resolution_decision_id, created_at, created_by
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, NULL, NULL, NULL, $8, $9)
        ON CONFLICT (entity_type, alias_normalized, normalizer_major,
                     normalizer_minor, coalesce(provider_id, ''))
            WHERE valid_to IS NULL
        DO NOTHING
        """,
        [
            (
                uuid.UUID(a.id),
                a.entity_type.value,
                a.entity_id.value,
                a.alias_original,
                a.alias_normalized,
                a.normalizer_version.major,
                a.normalizer_version.minor,
                a.created_at,
                a.created_by,
            )
            for a in aliases
        ],
    )


async def _jogadores(
    conexao: Any, jogadores: Sequence[Player], normalizador: NameNormalizer
) -> None:
    await conexao.executemany(
        """
        INSERT INTO players (
            id, canonical_name, normalized_name, normalizer_major, normalizer_minor,
            date_of_birth, nationality, preferred_foot, primary_position, active
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (id) DO NOTHING
        """,
        [
            (
                j.id.value,
                j.canonical_name,
                normalizador.normalize(j.canonical_name),
                normalizador.version.major,
                normalizador.version.minor,
                j.date_of_birth,
                j.nationality,
                j.preferred_foot.value if j.preferred_foot else None,
                j.primary_position.value if j.primary_position else None,
                j.active,
            )
            for j in jogadores
        ],
    )


async def _vinculos(conexao: Any, vinculos: Sequence[PlayerTeamTenure]) -> None:
    if not vinculos:
        return
    # SEM `ON CONFLICT`: a chave é `bigserial`, então não há o que conflitar.
    # A guarda contra duplicata é a limpeza prévia, e ela é explícita.
    await conexao.execute(
        "DELETE FROM player_team_tenures WHERE player_id = ANY($1::uuid[])",
        [v.player_id.value for v in vinculos],
    )
    await conexao.executemany(
        """
        INSERT INTO player_team_tenures (player_id, team_id, valid_from, valid_to)
        VALUES ($1, $2, $3, $4)
        """,
        [(v.player_id.value, v.team_id.value, v.valid_from, v.valid_to) for v in vinculos],
    )


async def _partidas(conexao: Any, partidas: Sequence[Match]) -> None:
    await conexao.executemany(
        """
        INSERT INTO matches (
            id, competition_id, season_id, home_team_id, away_team_id,
            scheduled_kickoff, actual_kickoff, stage_type, round_number, group_label,
            regime_code, regime_from, regulation_version, lifecycle, neutral_venue
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (id) DO NOTHING
        """,
        [
            (
                m.id.value,
                m.competition_id.value,
                m.season_id.value,
                m.home_team_id.value,
                m.away_team_id.value,
                m.scheduled_kickoff,
                m.actual_kickoff,
                m.stage.type.value,
                m.stage.round_number,
                m.stage.group_label,
                m.regime.code.value,
                m.regime.effective_from,
                m.regime.regulation_version,
                m.lifecycle.value,
                m.neutral_venue,
            )
            for m in partidas
        ],
    )
