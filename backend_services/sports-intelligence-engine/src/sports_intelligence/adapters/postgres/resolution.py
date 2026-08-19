"""Os repositórios de resolução e fusão, em SQL escrito à mão.

TODA CONSULTA DE LEITURA É EM MASSA. Não há um único método que receba um
valor e devolva um candidato — a assinatura dos ports já impedia, e aqui o
SQL cumpre: `= ANY($1)` em vez de um `SELECT` por linha. É a diferença entre
seis consultas por lote e setecentas mil por dataset (§42, §74).

NENHUM `UPDATE` SOBRE DECISÃO, EVIDÊNCIA, EXECUÇÃO CONCLUÍDA OU SAÍDA DE
FUSÃO. Um teste de arquitetura lê este arquivo e falha se aparecer. As duas
exceções são declaradas e visíveis: fechar uma execução em curso
(`status = 'RUNNING'` na cláusula `WHERE`) e mover um item da fila de revisão
— as duas condicionais ao estado anterior, que é como esta base faz
concorrência desde o PR-02.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.competitions.catalog import CompetitionCode, entry_for
from sports_intelligence.domain.competitions.models import Competition, Season
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.fusion.models import FusionGroup
from sports_intelligence.domain.fusion.runs import (
    FusedMatchCandidate,
    FusionCounts,
    FusionRun,
)
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.confidence_scale import EvidenceOutcome
from sports_intelligence.domain.resolution.decisions import (
    DecisionVersions,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionInput,
    ResolutionMethod,
    ResolutionStatus,
    SourceValue,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import (
    EvidenceKind,
    ExplanationCode,
    ResolutionAlternative,
    ResolutionEvidence,
)
from sports_intelligence.domain.resolution.mappings import EntityAlias, ProviderEntityMapping
from sports_intelligence.domain.resolution.review import (
    ResolutionReviewItem,
    ReviewFilter,
    ReviewStatus,
    ReviewSubject,
)
from sports_intelligence.domain.resolution.runs import ResolutionRun, RunStatus
from sports_intelligence.domain.resolution.versions import (
    NormalizerVersion,
    PolicyVersion,
    ResolverVersion,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    DatasetId,
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import (
    MappingStatus,
    SourceFieldMapping,
    SourceMappingDefinition,
    ValueTransform,
)
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ingestion.normalization.names import NameNormalizer

_SEED_ACTOR: Final[str] = "catalog-seed"

#: Quantos candidatos de fusão vão ao banco por rodada de `unnest`. Troca
#: idas ao banco por tamanho de array; o valor sai do benchmark do PR-03.1,
#: onde quinhentos candidatos deram três consultas por rodada sem pico de
#: memória visível.
_CANDIDATOS_POR_RODADA: Final[int] = 500

#: Os aliases das cinco competições. Cada um é verificável por qualquer
#: pessoa que conheça futebol, e um alias errado se corrige com um `DELETE` —
#: enquanto uma regra errada no resolver exigiria deploy (§14).
COMPETITION_ALIASES: Final[dict[CompetitionCode, tuple[str, ...]]] = {
    CompetitionCode.PREMIER_LEAGUE: (
        "EPL",
        "English Premier League",
        "ENG Premier League",
        "Barclays Premier League",
        "England Premier League",
        "E0",
    ),
    CompetitionCode.LA_LIGA: (
        "Spanish La Liga",
        "LaLiga",
        "La Liga Santander",
        "Primera Division",
        "ESP La Liga",
        "SP1",
    ),
    CompetitionCode.BRA_SERIE_A: (
        "Brasileirao",
        "Campeonato Brasileiro",
        "Campeonato Brasileiro Serie A",
        "Serie A Brasil",
        "BRA Serie A",
    ),
    CompetitionCode.UEFA_CHAMPIONS_LEAGUE: (
        "UCL",
        "UEFA Champions League",
        "Champions",
        "Liga dos Campeoes",
    ),
    CompetitionCode.CONMEBOL_LIBERTADORES: (
        "Copa Libertadores",
        "CONMEBOL Libertadores",
        "Libertadores da America",
    ),
}


@final
class PostgresProviderMappingRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def by_external_ids(
        self, provider: ProviderId, subject: SubjectType, external_ids: Sequence[str]
    ) -> Sequence[ProviderEntityMapping]:
        if not external_ids:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT * FROM provider_entity_mappings
                WHERE provider_id = $1 AND entity_type = $2
                  AND provider_entity_id = ANY($3::text[])
                ORDER BY provider_entity_id, created_at
                """,
                str(provider),
                subject.value,
                list(dict.fromkeys(external_ids)),
            )
        return [_para_mapeamento(linha) for linha in linhas]

    async def create_if_absent(self, mapping: ProviderEntityMapping) -> ProviderEntityMapping:
        """`ON CONFLICT DO NOTHING` sobre o índice parcial dos vigentes.

        DEVOLVE O EXISTENTE quando já há um, e é quem chamou que compara. A
        camada de aplicação usa `assert_mapping_is_consistent` para
        transformar uma divergência em conflito explícito — reapontar em
        silêncio reescreveria todo o histórico lido sob a tradução antiga.
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO provider_entity_mappings (
                    id, provider_id, entity_type, provider_entity_id,
                    canonical_entity_id, resolution_decision_id,
                    valid_from, valid_to, created_at, created_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (provider_id, entity_type, provider_entity_id)
                    WHERE valid_to IS NULL
                DO NOTHING
                """,
                uuid.UUID(mapping.id),
                str(mapping.provider_id),
                mapping.entity_type.value,
                mapping.provider_entity_id,
                mapping.canonical_entity_id.value,
                uuid.UUID(mapping.resolution_decision_id),
                mapping.valid_from,
                mapping.valid_to,
                mapping.created_at,
                mapping.created_by,
            )
            linha = await conexao.fetchrow(
                """
                SELECT * FROM provider_entity_mappings
                WHERE provider_id = $1 AND entity_type = $2
                  AND provider_entity_id = $3 AND valid_to IS NULL
                """,
                str(mapping.provider_id),
                mapping.entity_type.value,
                mapping.provider_entity_id,
            )
        return _para_mapeamento(linha) if linha is not None else mapping

    async def by_canonical(
        self, subject: SubjectType, canonical_id: str
    ) -> Sequence[ProviderEntityMapping]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM provider_entity_mappings "
                "WHERE entity_type = $1 AND canonical_entity_id = $2 ORDER BY created_at",
                subject.value,
                uuid.UUID(canonical_id),
            )
        return [_para_mapeamento(linha) for linha in linhas]


@final
class PostgresEntityAliasRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def by_normalized(
        self, subject: SubjectType, normalized: Sequence[str]
    ) -> Sequence[EntityAlias]:
        if not normalized:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT * FROM entity_aliases
                WHERE entity_type = $1 AND alias_normalized = ANY($2::text[])
                ORDER BY alias_normalized, created_at
                """,
                subject.value,
                list(dict.fromkeys(normalized)),
            )
        return [_para_alias(linha) for linha in linhas]

    async def create_if_absent(self, alias: EntityAlias) -> EntityAlias:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO entity_aliases (
                    id, entity_type, entity_id, alias_original, alias_normalized,
                    normalizer_major, normalizer_minor, provider_id,
                    valid_from, valid_to, resolution_decision_id, created_at, created_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (entity_type, alias_normalized, normalizer_major,
                             normalizer_minor, coalesce(provider_id, ''))
                    WHERE valid_to IS NULL
                DO NOTHING
                """,
                uuid.UUID(alias.id),
                alias.entity_type.value,
                alias.entity_id.value,
                alias.alias_original,
                alias.alias_normalized,
                alias.normalizer_version.major,
                alias.normalizer_version.minor,
                str(alias.provider_id) if alias.provider_id else None,
                alias.valid_from,
                alias.valid_to,
                uuid.UUID(alias.resolution_decision_id) if alias.resolution_decision_id else None,
                alias.created_at,
                alias.created_by,
            )
        return alias

    async def by_entity(self, subject: SubjectType, entity_id: str) -> Sequence[EntityAlias]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM entity_aliases WHERE entity_type = $1 AND entity_id = $2 "
                "ORDER BY created_at",
                subject.value,
                uuid.UUID(entity_id),
            )
        return [_para_alias(linha) for linha in linhas]


async def seed_competition_aliases(
    database: Database, *, normalizer: NameNormalizer, at: Any
) -> int:
    """Semeia os aliases das cinco competições. Idempotente.

    OS IDs SÃO DERIVADOS PELA MESMA FUNÇÃO QUE O RESTO DO MOTOR USA
    (`entry_for(code).id`), e é por isso que este seed vive em Python e não em
    SQL: literais no arquivo de migration criariam uma segunda fonte de
    verdade que divergiria em silêncio no dia em que o namespace de derivação
    mudasse — com o alias apontando para um id que não é de competição
    nenhuma.
    """
    inseridos = 0
    async with database.acquire() as conexao:
        for codigo, nomes in COMPETITION_ALIASES.items():
            entidade = entry_for(codigo).id
            for nome in (*nomes, codigo.value, entry_for(codigo).name):
                normalizado = normalizer.normalize(nome)
                if not normalizado:
                    continue
                resultado = await conexao.execute(
                    """
                    INSERT INTO entity_aliases (
                        id, entity_type, entity_id, alias_original, alias_normalized,
                        normalizer_major, normalizer_minor, created_at, created_by
                    )
                    VALUES ($1, 'COMPETITION', $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (entity_type, alias_normalized, normalizer_major,
                                 normalizer_minor, coalesce(provider_id, ''))
                        WHERE valid_to IS NULL
                    DO NOTHING
                    """,
                    uuid.uuid4(),
                    entidade.value,
                    nome,
                    normalizado,
                    normalizer.version.major,
                    normalizer.version.minor,
                    at,
                    _SEED_ACTOR,
                )
                inseridos += 1 if str(resultado).endswith(" 1") else 0
    return inseridos


@final
class PostgresCanonicalRegistry:
    """A leitura em massa do registro canônico. Seis consultas por lote."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def competitions(self) -> Sequence[Competition]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT id, code, name, region, competition_type, active FROM competitions"
            )
        return [
            Competition(
                id=CompetitionId(linha["id"]),
                code=CompetitionCode(linha["code"]),
                name=linha["name"],
                region=linha["region"],
                competition_type=linha["competition_type"],
                active=linha["active"],
            )
            for linha in linhas
        ]

    async def seasons_of(self, competitions: Sequence[CompetitionId]) -> Sequence[Season]:
        if not competitions:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT id, competition_id, label, starts_at, ends_at,
                       regime_code, regime_from, regime_to, regulation_version
                FROM seasons WHERE competition_id = ANY($1::uuid[])
                ORDER BY starts_at
                """,
                [c.value for c in competitions],
            )
        return [_para_temporada(linha) for linha in linhas]

    async def teams_by_normalized_names(self, normalized: Sequence[str]) -> Sequence[Team]:
        """Times cujo nome canônico normalizado está no lote, MAIS os
        alcançáveis por alias.

        A COLUNA NORMALIZADA É MATERIALIZADA (§66): normalizar dentro do `SQL`
        exigiria uma função equivalente à do Python, e as duas divergiriam.
        """
        if not normalized:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT DISTINCT t.id, t.canonical_name, t.country, t.short_name, t.active
                FROM teams t
                LEFT JOIN entity_aliases a
                       ON a.entity_type = 'TEAM' AND a.entity_id = t.id
                WHERE t.normalized_name = ANY($1::text[])
                   OR a.alias_normalized = ANY($1::text[])
                """,
                list(dict.fromkeys(normalized)),
            )
        return [_para_time(linha) for linha in linhas]

    async def teams_by_ids(self, ids: Sequence[TeamId]) -> Sequence[Team]:
        if not ids:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT id, canonical_name, country, short_name, active FROM teams "
                "WHERE id = ANY($1::uuid[])",
                [t.value for t in ids],
            )
        return [_para_time(linha) for linha in linhas]

    async def team_candidates_for_names(
        self, normalized: Sequence[str], *, limit_per_name: int
    ) -> Sequence[tuple[str, Team]]:
        """Times que compartilham ao menos um TOKEN com cada nome consultado.

        UMA CONSULTA PARA N NOMES. `unnest` gera a lista de nomes e o
        `LATERAL` roda a busca uma vez por nome — do lado do banco, num
        round trip só. A alternativa seria uma consulta por nome, que é o
        N+1 que a arquitetura inteira existe para não ter.

        `&&` SOBRE `string_to_array` usa o índice GIN da migration 0004. Sem
        o índice isto vira sequential scan por nome e a correção de
        determinismo viraria uma regressão de performance.

        A ORDEM DENTRO DO `LATERAL` DECIDE QUEM SOBREVIVE AO `LIMIT`, e o
        teste de integração provou que ela não pode ser o id: um registro com
        três mil jogadores chamados `Silva NNNNN` empurrava os homônimos
        exatos de `Rodrigo Silva` para fora do corte, e a resolução passava a
        comparar o nome certo com cinquenta pessoas erradas.

        Então a ordem é: nome EXATO primeiro, depois mais tokens em comum,
        e o id só como desempate final — que continua sendo obrigatório, senão
        QUAL candidato sobrevive viria da ordem física das linhas (§36).
        """
        if not normalized:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT q.nome AS consulta, t.id, t.canonical_name, t.country,
                       t.short_name, t.active
                FROM unnest($1::text[]) AS q(nome)
                JOIN LATERAL (
                    SELECT * FROM teams t
                    WHERE string_to_array(t.normalized_name, ' ')
                          && string_to_array(q.nome, ' ')
                    ORDER BY
                        -- O NOME EXATO VEM SEMPRE PRIMEIRO. É o caso mais
                        -- perigoso do motor — dois homônimos exatos —, e ele
                        -- não pode ser cortado pelo `LIMIT` por causa de mil
                        -- entidades que só compartilham um sobrenome comum.
                        (t.normalized_name = q.nome) DESC,
                        -- Depois, quem compartilha MAIS tokens. `Rodrigo
                        -- Silva` ganha de `Silva 00208`, que só tem `silva`.
                        cardinality(ARRAY(
                            SELECT unnest(string_to_array(t.normalized_name, ' '))
                            INTERSECT
                            SELECT unnest(string_to_array(q.nome, ' '))
                        )) DESC,
                        -- E o id fecha o desempate, para que o corte seja o
                        -- mesmo em toda execução (§36).
                        t.id
                    LIMIT $2
                ) t ON true
                """,
                list(dict.fromkeys(normalized)),
                limit_per_name,
            )
        return [(linha["consulta"], _para_time(linha)) for linha in linhas]

    async def player_candidates_for_names(
        self, normalized: Sequence[str], *, limit_per_name: int
    ) -> Sequence[tuple[str, Player]]:
        if not normalized:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT q.nome AS consulta, p.id, p.canonical_name, p.date_of_birth,
                       p.nationality, p.preferred_foot, p.primary_position, p.active
                FROM unnest($1::text[]) AS q(nome)
                JOIN LATERAL (
                    SELECT * FROM players p
                    WHERE string_to_array(p.normalized_name, ' ')
                          && string_to_array(q.nome, ' ')
                    ORDER BY
                        -- O NOME EXATO VEM SEMPRE PRIMEIRO. É o caso mais
                        -- perigoso do motor — dois homônimos exatos —, e ele
                        -- não pode ser cortado pelo `LIMIT` por causa de mil
                        -- entidades que só compartilham um sobrenome comum.
                        (p.normalized_name = q.nome) DESC,
                        -- Depois, quem compartilha MAIS tokens. `Rodrigo
                        -- Silva` ganha de `Silva 00208`, que só tem `silva`.
                        cardinality(ARRAY(
                            SELECT unnest(string_to_array(p.normalized_name, ' '))
                            INTERSECT
                            SELECT unnest(string_to_array(q.nome, ' '))
                        )) DESC,
                        -- E o id fecha o desempate, para que o corte seja o
                        -- mesmo em toda execução (§36).
                        p.id
                    LIMIT $2
                ) p ON true
                """,
                list(dict.fromkeys(normalized)),
                limit_per_name,
            )
        return [(linha["consulta"], _para_jogador(linha)) for linha in linhas]

    async def players_by_normalized_names(self, normalized: Sequence[str]) -> Sequence[Player]:
        if not normalized:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT DISTINCT p.id, p.canonical_name, p.date_of_birth, p.nationality,
                       p.preferred_foot, p.primary_position, p.active
                FROM players p
                LEFT JOIN entity_aliases a
                       ON a.entity_type = 'PLAYER' AND a.entity_id = p.id
                WHERE p.normalized_name = ANY($1::text[])
                   OR a.alias_normalized = ANY($1::text[])
                """,
                list(dict.fromkeys(normalized)),
            )
        return [_para_jogador(linha) for linha in linhas]

    async def tenures_of(self, players: Sequence[str]) -> Sequence[PlayerTeamTenure]:
        if not players:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT player_id, team_id, valid_from, valid_to FROM player_team_tenures "
                "WHERE player_id = ANY($1::uuid[]) ORDER BY valid_from",
                [uuid.UUID(p) for p in players],
            )
        return [
            PlayerTeamTenure(
                player_id=PlayerId(linha["player_id"]),
                team_id=TeamId(linha["team_id"]),
                valid_from=instant(linha["valid_from"]),
                valid_to=instant(linha["valid_to"]) if linha["valid_to"] else None,
            )
            for linha in linhas
        ]

    async def matches_of_fixtures(
        self, fixtures: Sequence[tuple[SeasonId, TeamId, TeamId]]
    ) -> Sequence[Match]:
        """As partidas dos confrontos do lote, numa consulta só.

        `unnest` COM TRÊS ARRAYS PARALELOS é o que permite passar N triplas
        numa consulta. A alternativa — um `OR` por confronto — produziria um
        SQL de quilômetros e um plano ruim.
        """
        if not fixtures:
            return []
        temporadas = [f[0].value for f in fixtures]
        mandantes = [f[1].value for f in fixtures]
        visitantes = [f[2].value for f in fixtures]
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT m.* FROM matches m
                JOIN unnest($1::uuid[], $2::uuid[], $3::uuid[])
                     AS alvo(season_id, home_team_id, away_team_id)
                  ON m.season_id = alvo.season_id
                 AND m.home_team_id = alvo.home_team_id
                 AND m.away_team_id = alvo.away_team_id
                """,
                temporadas,
                mandantes,
                visitantes,
            )
        return [_para_partida(linha) for linha in linhas]


@final
class PostgresSourceMappingRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, definition: SourceMappingDefinition) -> SourceMappingDefinition:
        """Aposenta o ativo e grava o novo, na MESMA transação.

        Separadas, uma falha entre as duas deixaria o dataset sem mapeamento
        ativo — e a execução seguinte não teria como ler o arquivo.
        """
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                "UPDATE source_mapping_definitions SET status = 'SUPERSEDED' "
                "WHERE dataset_id = $1 AND status = 'ACTIVE'",
                definition.dataset_id.value,
            )
            await conexao.execute(
                """
                INSERT INTO source_mapping_definitions (
                    id, dataset_id, version_major, version_minor, provider_id,
                    version, status, fields, conventions, description,
                    created_at, created_by, record_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                uuid.UUID(definition.id),
                definition.dataset_id.value,
                definition.dataset_version.major,
                definition.dataset_version.minor,
                str(definition.provider_id),
                definition.version,
                definition.status.value,
                json.dumps([_campo_para_json(f) for f in definition.fields]),
                json.dumps(definition.conventions),
                definition.description,
                definition.created_at,
                definition.created_by,
                # O `RecordKind` PRECISA SOBREVIVER AO BANCO (PR-04.4.1 §5).
                # Sem a coluna, um mapeamento gravado como `EVENT_RECORD` era
                # relido como `MATCH_RECORD` — o default — e o próprio domínio
                # recusava o mapeamento que acabara de ser aceito.
                definition.record_kind.value,
            )
        return definition

    async def active_for(self, dataset_id: DatasetId) -> SourceMappingDefinition | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM source_mapping_definitions "
                "WHERE dataset_id = $1 AND status = 'ACTIVE'",
                dataset_id.value,
            )
        return _para_mapeamento_de_fonte(linha) if linha else None

    async def by_id(self, mapping_id: str) -> SourceMappingDefinition | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM source_mapping_definitions WHERE id = $1",
                uuid.UUID(mapping_id),
            )
        return _para_mapeamento_de_fonte(linha) if linha else None

    async def history_for(self, dataset_id: DatasetId) -> Sequence[SourceMappingDefinition]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM source_mapping_definitions WHERE dataset_id = $1 "
                "ORDER BY version DESC",
                dataset_id.value,
            )
        return [_para_mapeamento_de_fonte(linha) for linha in linhas]


@final
class PostgresResolutionRunRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create(self, run: ResolutionRun) -> ResolutionRun:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO resolution_runs (
                    id, dataset_id, version_major, version_minor, manifest_fingerprint,
                    resolver_major, resolver_minor, normalizer_major, normalizer_minor,
                    policy_major, policy_minor, status, started_at,
                    triggered_by, triggered_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                uuid.UUID(run.id),
                run.dataset_id.value,
                run.dataset_version.major,
                run.dataset_version.minor,
                run.manifest_fingerprint.value,
                run.versions.resolver.major,
                run.versions.resolver.minor,
                run.versions.normalizer.major,
                run.versions.normalizer.minor,
                run.versions.policy.major,
                run.versions.policy.minor,
                run.status.value,
                run.started_at,
                run.triggered_by.id,
                run.triggered_by.kind.value,
            )
        return run

    async def finish(self, run: ResolutionRun) -> bool:
        """Fecha SE ainda estiver em curso. A condição é o lock.

        Dois workers fechando a mesma execução produziriam duas contagens, e a
        segunda sobrescreveria a primeira.
        """
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE resolution_runs
                SET status = $2, completed_at = $3, failure_reason = $4,
                    total_records = $5, resolved = $6, unresolved = $7,
                    ambiguous = $8, review_required = $9, rejected = $10
                WHERE id = $1 AND status = 'RUNNING'
                """,
                uuid.UUID(run.id),
                run.status.value,
                run.completed_at,
                run.failure_reason,
                run.counts.total,
                run.counts.resolved,
                run.counts.unresolved,
                run.counts.ambiguous,
                run.counts.review_required,
                run.counts.rejected,
            )
        return _linhas(resultado) > 0

    async def by_id(self, run_id: str) -> ResolutionRun | None:
        try:
            identificador = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM resolution_runs WHERE id = $1", identificador
            )
        return _para_execucao(linha) if linha else None

    async def for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 20
    ) -> Sequence[ResolutionRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM resolution_runs WHERE dataset_id = $1 "
                "ORDER BY started_at DESC LIMIT $2",
                dataset_id.value,
                min(limit, 100),
            )
        return [_para_execucao(linha) for linha in linhas]


@final
class PostgresResolutionDecisionRepository:
    """Decisões. APPEND-ONLY: não há `UPDATE` nesta classe."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def append_many(self, decisions: Sequence[ResolutionDecision], *, run_id: str) -> int:
        if not decisions:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.executemany(
                """
                INSERT INTO resolution_decisions (
                    id, run_id, subject_type, provider_id, provider_entity_id,
                    source_raw, source_normalized, normalizer_major, normalizer_minor,
                    status, method, confidence, canonical_entity_id,
                    resolver_major, resolver_minor, policy_major, policy_minor,
                    dataset_id, dataset_version_major, dataset_version_minor,
                    manifest_fingerprint, record_ref, decided_at, decided_by,
                    decided_by_kind, reason
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                        $17,$18,$19,$20,$21,$22,$23,$24,$25,$26)
                """,
                [_decisao_para_tupla(d, run_id) for d in decisions],
            )
            await conexao.executemany(
                """
                INSERT INTO resolution_evidence (
                    decision_id, ordinal, kind, outcome, explanation, weight,
                    source_value, canonical_value
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    (
                        uuid.UUID(d.id),
                        ordem,
                        e.kind.value,
                        e.outcome.value,
                        e.explanation.value,
                        e.weight,
                        e.source_value,
                        e.canonical_value,
                    )
                    for d in decisions
                    for ordem, e in enumerate(d.evidence)
                ],
            )
            await conexao.executemany(
                """
                INSERT INTO resolution_alternatives (
                    decision_id, ordinal, canonical_entity_id, score,
                    evidence_summary, label
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (
                        uuid.UUID(d.id),
                        ordem,
                        a.canonical_entity_id.value,
                        a.score,
                        a.evidence_summary,
                        a.label,
                    )
                    for d in decisions
                    for ordem, a in enumerate(d.alternatives)
                ],
            )
        return len(decisions)

    async def by_run(
        self,
        run_id: str,
        *,
        subject: SubjectType | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[Sequence[ResolutionDecision], int]:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM resolution_decisions WHERE run_id = $1 "
                "AND ($2::text IS NULL OR subject_type = $2)",
                uuid.UUID(run_id),
                subject.value if subject else None,
            )
            linhas = await conexao.fetch(
                "SELECT * FROM resolution_decisions WHERE run_id = $1 "
                "AND ($2::text IS NULL OR subject_type = $2) "
                "ORDER BY decided_at, id LIMIT $3 OFFSET $4",
                uuid.UUID(run_id),
                subject.value if subject else None,
                min(limit, 500),
                offset,
            )
            decisoes = [
                _para_decisao(linha, await self._evidencias(conexao, linha["id"]), ())
                for linha in linhas
            ]
        return decisoes, int(total or 0)

    async def by_id(self, decision_id: str) -> ResolutionDecision | None:
        try:
            identificador = uuid.UUID(decision_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM resolution_decisions WHERE id = $1", identificador
            )
            if linha is None:
                return None
            evidencias = await self._evidencias(conexao, identificador)
            alternativas = await self._alternativas(
                conexao, identificador, SubjectType(linha["subject_type"])
            )
        return _para_decisao(linha, evidencias, alternativas)

    async def resolved_entities_of_run(self, run_id: str, subject: SubjectType) -> dict[str, str]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT record_ref, canonical_entity_id, id
                FROM resolution_decisions
                WHERE run_id = $1 AND subject_type = $2 AND status = 'RESOLVED'
                  AND record_ref IS NOT NULL
                """,
                uuid.UUID(run_id),
                subject.value,
            )
        return {
            linha["record_ref"]: f"{linha['canonical_entity_id']}|{linha['id']}" for linha in linhas
        }

    async def confidences_for_records(
        self, run_ids: Sequence[str], record_refs: Sequence[str]
    ) -> dict[str, dict[SubjectType, float]]:
        """A confiança POR TIPO de cada linha de fonte do lote, numa consulta.

        A MENOR CONFIANÇA VENCE quando a mesma linha tem duas decisões do
        mesmo tipo em execuções diferentes. É o elo mais fraco outra vez, e
        pelo mesmo motivo: a maior faria uma reexecução mais permissiva
        apagar a evidência de que a anterior duvidou.
        """
        if not run_ids or not record_refs:
            return {}
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT record_ref, subject_type, min(confidence) AS confidence
                FROM resolution_decisions
                WHERE run_id = ANY($1::uuid[])
                  AND record_ref = ANY($2::text[])
                  AND status = 'RESOLVED'
                GROUP BY record_ref, subject_type
                """,
                [uuid.UUID(r) for r in run_ids],
                list(dict.fromkeys(record_refs)),
            )
        saida: dict[str, dict[SubjectType, float]] = {}
        for linha in linhas:
            saida.setdefault(linha["record_ref"], {})[SubjectType(linha["subject_type"])] = float(
                linha["confidence"]
            )
        return saida

    @staticmethod
    async def _evidencias(conexao: Any, decision_id: uuid.UUID) -> tuple[ResolutionEvidence, ...]:
        linhas = await conexao.fetch(
            "SELECT * FROM resolution_evidence WHERE decision_id = $1 ORDER BY ordinal",
            decision_id,
        )
        return tuple(
            ResolutionEvidence(
                kind=EvidenceKind(linha["kind"]),
                outcome=EvidenceOutcome(linha["outcome"]),
                explanation=ExplanationCode(linha["explanation"]),
                weight=linha["weight"],
                source_value=linha["source_value"],
                canonical_value=linha["canonical_value"],
            )
            for linha in linhas
        )

    @staticmethod
    async def _alternativas(
        conexao: Any, decision_id: uuid.UUID, subject: SubjectType
    ) -> tuple[ResolutionAlternative, ...]:
        linhas = await conexao.fetch(
            "SELECT * FROM resolution_alternatives WHERE decision_id = $1 ORDER BY ordinal",
            decision_id,
        )
        return tuple(
            ResolutionAlternative(
                canonical_entity_id=_id_canonico(subject, linha["canonical_entity_id"]),
                score=linha["score"],
                evidence_summary=linha["evidence_summary"],
                label=linha["label"],
            )
            for linha in linhas
        )


@final
class PostgresReviewQueueRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create_many(self, items: Sequence[ResolutionReviewItem]) -> int:
        if not items:
            return 0
        async with self._db.acquire() as conexao:
            await conexao.executemany(
                """
                INSERT INTO resolution_review_items (
                    id, run_id, subject_type, provider_id, source_raw, source_normalized,
                    normalizer_major, normalizer_minor, record_ref, context,
                    reason_status, candidates, status, created_at
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (run_id, record_ref, subject_type) DO NOTHING
                """,
                [
                    (
                        uuid.UUID(item.id),
                        uuid.UUID(item.run_id),
                        item.subject.subject_type.value,
                        str(item.subject.provider_id),
                        item.subject.source_value.raw,
                        item.subject.source_value.normalized,
                        item.subject.source_value.normalizer_version.major,
                        item.subject.source_value.normalizer_version.minor,
                        item.subject.record_ref,
                        json.dumps(item.subject.context),
                        item.reason_status.value,
                        json.dumps(
                            [
                                {
                                    "entity_id": str(c.canonical_entity_id),
                                    "evidence": c.evidence_summary,
                                    "label": c.label,
                                    "score": c.score,
                                }
                                for c in item.candidates
                            ]
                        ),
                        item.status.value,
                        item.created_at,
                    )
                    for item in items
                ],
            )
        return len(items)

    async def list(
        self, *, filters: ReviewFilter, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[ResolutionReviewItem], int]:
        condicoes = ["1 = 1"]
        parametros: list[Any] = []

        def _p(valor: Any) -> str:
            parametros.append(valor)
            return f"${len(parametros)}"

        if filters.status is not None:
            condicoes.append(f"status = {_p(filters.status.value)}")
        if filters.subject_type is not None:
            condicoes.append(f"subject_type = {_p(filters.subject_type.value)}")
        if filters.run_id is not None:
            condicoes.append(f"run_id = {_p(uuid.UUID(filters.run_id))}")
        if filters.assigned_to is not None:
            condicoes.append(f"assigned_to = {_p(filters.assigned_to)}")
        onde = " AND ".join(condicoes)

        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                f"SELECT count(*) FROM resolution_review_items WHERE {onde}", *parametros
            )
            linhas = await conexao.fetch(
                f"SELECT * FROM resolution_review_items WHERE {onde} "
                f"ORDER BY created_at, id LIMIT ${len(parametros) + 1} "
                f"OFFSET ${len(parametros) + 2}",
                *parametros,
                min(limit, 200),
                offset,
            )
        return [_para_item_de_revisao(linha) for linha in linhas], int(total or 0)

    async def by_id(self, item_id: str) -> ResolutionReviewItem | None:
        try:
            identificador = uuid.UUID(item_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM resolution_review_items WHERE id = $1", identificador
            )
        return _para_item_de_revisao(linha) if linha else None

    async def update_status(self, item: ResolutionReviewItem, *, expected_status: str) -> bool:
        """Condicional ao estado anterior — impede decisão dupla."""
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE resolution_review_items
                SET status = $2, assigned_to = $3, assigned_to_kind = $4,
                    resolved_at = $5, resolved_by = $6, resolved_by_kind = $7,
                    resolution_decision_id = $8, decision_reason = $9
                WHERE id = $1 AND status = $10
                """,
                uuid.UUID(item.id),
                item.status.value,
                item.assigned_to.id if item.assigned_to else None,
                item.assigned_to.kind.value if item.assigned_to else None,
                item.resolved_at,
                item.resolved_by.id if item.resolved_by else None,
                item.resolved_by.kind.value if item.resolved_by else None,
                uuid.UUID(item.resolution_decision_id) if item.resolution_decision_id else None,
                item.decision_reason,
                expected_status,
            )
        return _linhas(resultado) > 0


@final
class PostgresFusionRunRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create(self, run: FusionRun) -> FusionRun:
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                """
                INSERT INTO fusion_runs (
                    id, policy_major, policy_minor, status, started_at,
                    triggered_by, triggered_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.UUID(run.id),
                run.policy_version.major,
                run.policy_version.minor,
                run.status.value,
                run.started_at,
                run.triggered_by.id,
                run.triggered_by.kind.value,
            )
            await conexao.executemany(
                "INSERT INTO fusion_run_inputs (fusion_run_id, resolution_run_id) VALUES ($1, $2)",
                [(uuid.UUID(run.id), uuid.UUID(r)) for r in run.input_resolution_run_ids],
            )
        return run

    async def finish(self, run: FusionRun) -> bool:
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE fusion_runs
                SET status = $2, completed_at = $3, failure_reason = $4,
                    groups = $5, multi_source_groups = $6, fields_selected = $7,
                    conflicts = $8, unresolved_conflicts = $9, observation_sets = $10,
                    output_fingerprint = $11
                WHERE id = $1 AND status = 'RUNNING'
                """,
                uuid.UUID(run.id),
                run.status.value,
                run.completed_at,
                run.failure_reason,
                run.counts.groups,
                run.counts.multi_source_groups,
                run.counts.fields_selected,
                run.counts.conflicts,
                run.counts.unresolved_conflicts,
                run.counts.observation_sets,
                run.output_fingerprint.value if run.output_fingerprint else None,
            )
        return _linhas(resultado) > 0

    async def by_id(self, run_id: str) -> FusionRun | None:
        try:
            identificador = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow("SELECT * FROM fusion_runs WHERE id = $1", identificador)
            if linha is None:
                return None
            entradas = await conexao.fetch(
                "SELECT resolution_run_id FROM fusion_run_inputs WHERE fusion_run_id = $1 "
                "ORDER BY resolution_run_id",
                identificador,
            )
        return _para_fusao(linha, tuple(str(e["resolution_run_id"]) for e in entradas))

    async def recent(self, *, limit: int = 20) -> Sequence[FusionRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM fusion_runs ORDER BY started_at DESC LIMIT $1",
                min(limit, 100),
            )
            saida = []
            for linha in linhas:
                entradas = await conexao.fetch(
                    "SELECT resolution_run_id FROM fusion_run_inputs "
                    "WHERE fusion_run_id = $1 ORDER BY resolution_run_id",
                    linha["id"],
                )
                saida.append(
                    _para_fusao(linha, tuple(str(e["resolution_run_id"]) for e in entradas))
                )
        return saida

    async def save_groups(self, run_id: str, groups: Sequence[FusionGroup]) -> int:
        if not groups:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.executemany(
                """
                INSERT INTO fusion_groups (
                    id, fusion_run_id, canonical_match_id, record_count, providers
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (fusion_run_id, canonical_match_id) DO NOTHING
                """,
                [
                    (
                        uuid.UUID(g.id),
                        uuid.UUID(run_id),
                        g.canonical_match_id.value,
                        len(g.observation_records),
                        [str(p) for p in g.providers],
                    )
                    for g in groups
                ],
            )
            await conexao.executemany(
                """
                INSERT INTO fusion_group_records (
                    group_id, record_ref, provider_id, source_type,
                    license_class, resolution_decision_id
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (group_id, record_ref) DO NOTHING
                """,
                [
                    (
                        uuid.UUID(g.id),
                        str(r.record_ref),
                        str(r.provider_id),
                        r.source_type.value,
                        r.license_class.value,
                        uuid.UUID(r.resolution_decision_id),
                    )
                    for g in groups
                    # AS OBSERVAÇÕES EXTRAS TAMBÉM SÃO GRAVADAS. Sem elas, a
                    # cotação da segunda casa existiria no candidato e não
                    # teria linha de grupo que a ligasse ao arquivo bruto —
                    # procedência pela metade é o defeito que a fusão inteira
                    # existe para não cometer (§83).
                    for r in g.observation_records
                ],
            )
        return len(groups)

    async def save_candidates(self, run_id: str, candidates: Sequence[FusedMatchCandidate]) -> int:
        if not candidates:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(candidates), _CANDIDATOS_POR_RODADA):
                await self._gravar_rodada(
                    conexao,
                    run_id,
                    candidates[inicio : inicio + _CANDIDATOS_POR_RODADA],
                )
        return len(candidates)

    @staticmethod
    async def _gravar_rodada(
        conexao: Any, run_id: str, candidates: Sequence[FusedMatchCandidate]
    ) -> None:
        """Grava um bloco de candidatos em TRÊS consultas, não em três por campo.

        O QUE ESTAVA AQUI ANTES era um `INSERT` por candidato, um por campo e
        um por conjunto de contribuições — e o benchmark do PR-03.1 mediu o
        resultado: **276.009 consultas para 12.000 grupos**, vinte e três por
        grupo. É N+1 clássico, só que na ESCRITA, onde a assinatura em massa
        dos ports não protegia: `save_candidates` recebe a coleção inteira e
        gastava as idas ao banco por dentro.

        `unnest` COM ARRAYS PARALELOS resolve os dois primeiros níveis. O
        terceiro — as contribuições — depende do `id` gerado pelo `bigserial`
        do campo, e é por isso que o `INSERT` de campos usa `RETURNING`: ele
        devolve `(id, candidate_id, field_name)`, e o mapa reconstruído em
        memória liga cada contribuição ao campo dela.

        `ON CONFLICT DO NOTHING` COM `RETURNING` NÃO DEVOLVE A LINHA EM
        CONFLITO — e a semântica anterior era exatamente essa: campo já
        gravado, contribuições puladas. O `dict` reconstruído simplesmente não
        tem a chave, e as contribuições daquele campo não entram.

        EM BLOCOS, e não tudo de uma vez: um `unnest` com um milhão de
        elementos por array troca o N+1 por um pico de memória, que é o outro
        jeito de derrubar o processo.
        """
        ids: list[uuid.UUID] = []
        for _ in candidates:
            ids.append(uuid.uuid4())

        await conexao.executemany(
            """
            INSERT INTO fused_candidates (
                id, fusion_run_id, group_id, canonical_match_id,
                schema_version, fingerprint, body, most_restrictive_license
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (fusion_run_id, canonical_match_id) DO NOTHING
            """,
            [
                (
                    identificador,
                    uuid.UUID(run_id),
                    uuid.UUID(candidato.group_id),
                    candidato.canonical_match_id.value,
                    candidato.schema_version,
                    candidato.fingerprint.value,
                    json.dumps(candidato.as_canonical()),
                    candidato.most_restrictive_license.value,
                )
                for identificador, candidato in zip(ids, candidates, strict=True)
            ],
        )

        campos = [
            (identificador, campo)
            for identificador, candidato in zip(ids, candidates, strict=True)
            for campo in candidato.fields
        ]
        if not campos:
            return

        linhas = await conexao.fetch(
            """
            INSERT INTO fused_fields (
                candidate_id, field_name, rule, selected_value,
                selected_from, confidence, contribution_count
            )
            SELECT * FROM unnest(
                $1::uuid[], $2::text[], $3::text[], $4::text[],
                $5::text[], $6::double precision[], $7::integer[]
            )
            ON CONFLICT (candidate_id, field_name) DO NOTHING
            RETURNING id, candidate_id, field_name
            """,
            [c for c, _ in campos],
            [f.field_name.value for _, f in campos],
            [f.rule.value for _, f in campos],
            [f.selected_value for _, f in campos],
            [str(f.selected_from) if f.selected_from else None for _, f in campos],
            [f.confidence for _, f in campos],
            [len(f.contributions) for _, f in campos],
        )
        gravados = {(linha["candidate_id"], linha["field_name"]): linha["id"] for linha in linhas}

        contribuicoes = [
            (field_id, campo, contribuicao)
            for candidate_id, campo in campos
            if (field_id := gravados.get((candidate_id, campo.field_name.value))) is not None
            for contribuicao in campo.contributions
        ]
        if not contribuicoes:
            return

        await conexao.execute(
            """
            INSERT INTO fused_field_sources (
                field_id, provider_id, record_ref, value, license_class, was_selected
            )
            SELECT * FROM unnest(
                $1::bigint[], $2::text[], $3::text[], $4::text[], $5::text[], $6::boolean[]
            )
            ON CONFLICT (field_id, provider_id) DO NOTHING
            """,
            [i for i, _, _ in contribuicoes],
            [str(c.provider_id) for _, _, c in contribuicoes],
            [str(c.record_ref) for _, _, c in contribuicoes],
            [c.value for _, _, c in contribuicoes],
            [c.license_class.value for _, _, c in contribuicoes],
            [c.value == campo.selected_value for _, campo, c in contribuicoes],
        )

    async def candidates_of(
        self, run_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[dict[str, object]], int]:
        """Devolve a forma canônica gravada, e não uma reconstrução.

        RELER O `body` É O CERTO AQUI: ele é exatamente a saída que produziu a
        impressão. Remontar o candidato a partir das tabelas normalizadas
        correria o risco de produzir uma forma ligeiramente diferente — e a
        impressão deixaria de conferir.
        """
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM fused_candidates WHERE fusion_run_id = $1",
                uuid.UUID(run_id),
            )
            linhas = await conexao.fetch(
                "SELECT body FROM fused_candidates WHERE fusion_run_id = $1 "
                "ORDER BY canonical_match_id LIMIT $2 OFFSET $3",
                uuid.UUID(run_id),
                min(limit, 200),
                offset,
            )
        return [_corpo(linha["body"]) for linha in linhas], int(total or 0)

    async def group_ids_of(self, run_id: str) -> dict[str, str]:
        """Os grupos que esta execução persistiu, por partida canônica."""
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT canonical_match_id, id FROM fusion_groups WHERE fusion_run_id = $1",
                uuid.UUID(run_id),
            )
        return {str(linha["canonical_match_id"]): str(linha["id"]) for linha in linhas}

    async def conflicts_of(
        self, run_id: str, *, limit: int = 100
    ) -> Sequence[tuple[str, str, str]]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT c.canonical_match_id, f.field_name,
                       string_agg(s.provider_id || '=' || s.value, ' | '
                                  ORDER BY s.provider_id) AS valores
                FROM fused_fields f
                JOIN fused_candidates c ON c.id = f.candidate_id
                JOIN fused_field_sources s ON s.field_id = f.id
                WHERE c.fusion_run_id = $1 AND f.rule = 'CONFLICT_UNRESOLVED'
                GROUP BY c.canonical_match_id, f.field_name
                ORDER BY c.canonical_match_id, f.field_name
                LIMIT $2
                """,
                uuid.UUID(run_id),
                min(limit, 500),
            )
        return [
            (str(linha["canonical_match_id"]), linha["field_name"], linha["valores"])
            for linha in linhas
        ]


def _corpo(body: str | dict[str, Any]) -> dict[str, object]:
    """A forma canônica lida do banco, sem remontar o objeto de domínio.

    DEVOLVE O DICIONÁRIO GRAVADO, e é deliberado: ele é exatamente a saída
    que produziu a impressão. Remontar o `FusedMatchCandidate` só para
    serializá-lo de novo correria o risco de uma forma ligeiramente diferente
    — e a impressão deixaria de conferir.
    """
    return json.loads(body) if isinstance(body, str) else dict(body)


# ------------------------------------------------------------- tradução ----


def _linhas(resultado: str) -> int:
    try:
        return int(str(resultado).rsplit(" ", 1)[-1])
    except ValueError:  # pragma: no cover
        return 0


def _id_canonico(subject: SubjectType, valor: uuid.UUID) -> EntityId:
    """Reconstrói o id com o TIPO CONCRETO que o domínio espera.

    POR QUE NÃO BASTA `EntityId(valor)`. O domínio afirma o tipo concreto —
    `assert isinstance(competicao, CompetitionId)` no caso de uso, `TeamId` na
    entrada do resolver de partida. Um `EntityId` genérico vindo do banco
    passa pelo `mypy`, porque é a superclasse, e explode em produção na
    primeira linha que atravessa a asserção.

    E o tipo NÃO se perdeu: a coluna `entity_type` está do lado, gravada pelo
    mesmo `INSERT`. Isto aqui é lê-la de volta em vez de descartá-la.
    """
    return _CLASSE_DE_SUJEITO.get(subject, EntityId)(valor)


_CLASSE_DE_SUJEITO: Final[dict[SubjectType, type[EntityId]]] = {
    SubjectType.COMPETITION: CompetitionId,
    SubjectType.SEASON: SeasonId,
    SubjectType.TEAM: TeamId,
    SubjectType.PLAYER: PlayerId,
    SubjectType.MATCH: MatchId,
}


def _ator(identificador: str, tipo: str) -> Actor:
    return Actor(id=identificador, kind=ActorKind(tipo))


def _para_mapeamento(linha: Any) -> ProviderEntityMapping:
    return ProviderEntityMapping(
        id=str(linha["id"]),
        provider_id=ProviderId(linha["provider_id"]),
        entity_type=SubjectType(linha["entity_type"]),
        provider_entity_id=linha["provider_entity_id"],
        canonical_entity_id=_id_canonico(
            SubjectType(linha["entity_type"]), linha["canonical_entity_id"]
        ),
        resolution_decision_id=str(linha["resolution_decision_id"]),
        created_at=instant(linha["created_at"]),
        created_by=linha["created_by"],
        valid_from=instant(linha["valid_from"]) if linha["valid_from"] else None,
        valid_to=instant(linha["valid_to"]) if linha["valid_to"] else None,
    )


def _para_alias(linha: Any) -> EntityAlias:
    return EntityAlias(
        id=str(linha["id"]),
        entity_type=SubjectType(linha["entity_type"]),
        entity_id=_id_canonico(SubjectType(linha["entity_type"]), linha["entity_id"]),
        alias_original=linha["alias_original"],
        alias_normalized=linha["alias_normalized"],
        normalizer_version=NormalizerVersion(
            major=linha["normalizer_major"], minor=linha["normalizer_minor"]
        ),
        created_at=instant(linha["created_at"]),
        created_by=linha["created_by"],
        provider_id=ProviderId(linha["provider_id"]) if linha["provider_id"] else None,
        valid_from=instant(linha["valid_from"]) if linha["valid_from"] else None,
        valid_to=instant(linha["valid_to"]) if linha["valid_to"] else None,
        resolution_decision_id=str(linha["resolution_decision_id"])
        if linha["resolution_decision_id"]
        else None,
    )


def _campo_para_json(campo: SourceFieldMapping) -> dict[str, Any]:
    return {
        "column": campo.column,
        "date_format": campo.date_format,
        "role": campo.role.value,
        "timezone": campo.timezone,
        "transform": campo.transform.value,
    }


def _para_mapeamento_de_fonte(linha: Any) -> SourceMappingDefinition:
    campos = json.loads(linha["fields"]) if isinstance(linha["fields"], str) else linha["fields"]
    convencoes = (
        json.loads(linha["conventions"])
        if isinstance(linha["conventions"], str)
        else dict(linha["conventions"] or {})
    )
    return SourceMappingDefinition(
        id=str(linha["id"]),
        dataset_id=DatasetId(linha["dataset_id"]),
        dataset_version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        provider_id=ProviderId(linha["provider_id"]),
        version=linha["version"],
        fields=tuple(
            SourceFieldMapping(
                column=c["column"],
                role=SemanticRole(c["role"]),
                transform=ValueTransform(c["transform"]),
                date_format=c.get("date_format"),
                timezone=c.get("timezone"),
            )
            for c in campos
        ),
        status=MappingStatus(linha["status"]),
        record_kind=RecordKind(linha["record_kind"]),
        created_at=instant(linha["created_at"]),
        created_by=linha["created_by"],
        conventions=convencoes,
        description=linha["description"],
    )


def _para_execucao(linha: Any) -> ResolutionRun:
    from sports_intelligence.domain.resolution.decisions import DecisionCounts

    return ResolutionRun(
        id=str(linha["id"]),
        dataset_id=DatasetId(linha["dataset_id"]),
        dataset_version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        manifest_fingerprint=ContentHash(linha["manifest_fingerprint"]),
        versions=DecisionVersions(
            resolver=ResolverVersion(major=linha["resolver_major"], minor=linha["resolver_minor"]),
            normalizer=NormalizerVersion(
                major=linha["normalizer_major"], minor=linha["normalizer_minor"]
            ),
            policy=PolicyVersion(major=linha["policy_major"], minor=linha["policy_minor"]),
        ),
        status=RunStatus(linha["status"]),
        started_at=instant(linha["started_at"]),
        triggered_by=_ator(linha["triggered_by"], linha["triggered_by_kind"]),
        counts=DecisionCounts(
            total=linha["total_records"],
            resolved=linha["resolved"],
            unresolved=linha["unresolved"],
            ambiguous=linha["ambiguous"],
            review_required=linha["review_required"],
            rejected=linha["rejected"],
        ),
        completed_at=instant(linha["completed_at"]) if linha["completed_at"] else None,
        failure_reason=linha["failure_reason"],
    )


def _decisao_para_tupla(d: ResolutionDecision, run_id: str) -> tuple[Any, ...]:
    return (
        uuid.UUID(d.id),
        uuid.UUID(run_id),
        d.subject_type.value,
        str(d.provider_id),
        d.provider_ref.external_id if d.provider_ref else None,
        d.source_value.raw,
        d.source_value.normalized,
        d.source_value.normalizer_version.major,
        d.source_value.normalizer_version.minor,
        d.status.value,
        d.method.value,
        d.confidence.value,
        d.canonical_entity_id.value if d.canonical_entity_id else None,
        d.versions.resolver.major,
        d.versions.resolver.minor,
        d.versions.policy.major,
        d.versions.policy.minor,
        d.input_ref.dataset_id.value,
        d.input_ref.dataset_version.major,
        d.input_ref.dataset_version.minor,
        d.input_ref.manifest_fingerprint.value,
        d.record_ref,
        d.decided_at,
        d.decided_by.id,
        d.decided_by.kind.value,
        d.reason,
    )


def _para_decisao(
    linha: Any,
    evidencias: tuple[ResolutionEvidence, ...],
    alternativas: tuple[ResolutionAlternative, ...],
) -> ResolutionDecision:
    from sports_intelligence.domain.shared.identity import ProviderRef

    provedor = ProviderId(linha["provider_id"])
    return ResolutionDecision(
        id=str(linha["id"]),
        subject_type=SubjectType(linha["subject_type"]),
        provider_id=provedor,
        source_value=SourceValue(
            raw=linha["source_raw"],
            normalized=linha["source_normalized"],
            normalizer_version=NormalizerVersion(
                major=linha["normalizer_major"], minor=linha["normalizer_minor"]
            ),
        ),
        status=ResolutionStatus(linha["status"]),
        method=ResolutionMethod(linha["method"]),
        confidence=ResolutionConfidence(linha["confidence"]),
        versions=DecisionVersions(
            resolver=ResolverVersion(major=linha["resolver_major"], minor=linha["resolver_minor"]),
            normalizer=NormalizerVersion(
                major=linha["normalizer_major"], minor=linha["normalizer_minor"]
            ),
            policy=PolicyVersion(major=linha["policy_major"], minor=linha["policy_minor"]),
        ),
        decided_at=instant(linha["decided_at"]),
        decided_by=_ator(linha["decided_by"], linha["decided_by_kind"]),
        input_ref=ResolutionInput(
            dataset_id=DatasetId(linha["dataset_id"]),
            dataset_version=DatasetVersion(
                major=linha["dataset_version_major"], minor=linha["dataset_version_minor"]
            ),
            manifest_fingerprint=ContentHash(linha["manifest_fingerprint"]),
        ),
        provider_ref=ProviderRef(provider=provedor, external_id=linha["provider_entity_id"])
        if linha["provider_entity_id"]
        else None,
        record_ref=linha["record_ref"],
        canonical_entity_id=_id_canonico(
            SubjectType(linha["subject_type"]), linha["canonical_entity_id"]
        )
        if linha["canonical_entity_id"]
        else None,
        evidence=evidencias,
        alternatives=alternativas,
        reason=linha["reason"],
    )


def _para_item_de_revisao(linha: Any) -> ResolutionReviewItem:
    contexto = (
        json.loads(linha["context"])
        if isinstance(linha["context"], str)
        else dict(linha["context"] or {})
    )
    candidatos = (
        json.loads(linha["candidates"])
        if isinstance(linha["candidates"], str)
        else list(linha["candidates"] or [])
    )
    return ResolutionReviewItem(
        id=str(linha["id"]),
        run_id=str(linha["run_id"]),
        subject=ReviewSubject(
            subject_type=SubjectType(linha["subject_type"]),
            provider_id=ProviderId(linha["provider_id"]),
            source_value=SourceValue(
                raw=linha["source_raw"],
                normalized=linha["source_normalized"],
                normalizer_version=NormalizerVersion(
                    major=linha["normalizer_major"], minor=linha["normalizer_minor"]
                ),
            ),
            record_ref=linha["record_ref"],
            context=contexto,
        ),
        reason_status=ResolutionStatus(linha["reason_status"]),
        candidates=tuple(
            ResolutionAlternative(
                canonical_entity_id=_id_canonico(
                    SubjectType(linha["subject_type"]), uuid.UUID(c["entity_id"])
                ),
                score=c["score"],
                evidence_summary=c["evidence"],
                label=c.get("label"),
            )
            for c in candidatos
        ),
        status=ReviewStatus(linha["status"]),
        created_at=instant(linha["created_at"]),
        assigned_to=_ator(linha["assigned_to"], linha["assigned_to_kind"])
        if linha["assigned_to"]
        else None,
        resolved_at=instant(linha["resolved_at"]) if linha["resolved_at"] else None,
        resolved_by=_ator(linha["resolved_by"], linha["resolved_by_kind"])
        if linha["resolved_by"]
        else None,
        resolution_decision_id=str(linha["resolution_decision_id"])
        if linha["resolution_decision_id"]
        else None,
        decision_reason=linha["decision_reason"],
    )


def _para_fusao(linha: Any, entradas: tuple[str, ...]) -> FusionRun:
    return FusionRun(
        id=str(linha["id"]),
        input_resolution_run_ids=entradas,
        policy_version=PolicyVersion(major=linha["policy_major"], minor=linha["policy_minor"]),
        status=RunStatus(linha["status"]),
        started_at=instant(linha["started_at"]),
        triggered_by=_ator(linha["triggered_by"], linha["triggered_by_kind"]),
        counts=FusionCounts(
            groups=linha["groups"],
            multi_source_groups=linha["multi_source_groups"],
            fields_selected=linha["fields_selected"],
            conflicts=linha["conflicts"],
            unresolved_conflicts=linha["unresolved_conflicts"],
            observation_sets=linha["observation_sets"],
        ),
        completed_at=instant(linha["completed_at"]) if linha["completed_at"] else None,
        failure_reason=linha["failure_reason"],
        output_fingerprint=ContentHash(linha["output_fingerprint"])
        if linha["output_fingerprint"]
        else None,
    )


def _para_temporada(linha: Any) -> Season:
    from sports_intelligence.domain.competitions.models import CompetitionRegime, RegimeCode

    return Season(
        id=SeasonId(linha["id"]),
        competition_id=CompetitionId(linha["competition_id"]),
        label=linha["label"],
        starts_at=instant(linha["starts_at"]),
        ends_at=instant(linha["ends_at"]),
        regime=CompetitionRegime(
            code=RegimeCode(linha["regime_code"]),
            effective_from=instant(linha["regime_from"]),
            effective_to=instant(linha["regime_to"]) if linha["regime_to"] else None,
            regulation_version=linha["regulation_version"],
        ),
    )


def _para_time(linha: Any) -> Team:
    return Team(
        id=TeamId(linha["id"]),
        canonical_name=linha["canonical_name"],
        country=linha["country"],
        short_name=linha["short_name"],
        active=linha["active"],
    )


def _para_jogador(linha: Any) -> Player:
    from sports_intelligence.domain.players.models import PreferredFoot
    from sports_intelligence.domain.players.positions import Position

    return Player(
        id=PlayerId(linha["id"]),
        canonical_name=linha["canonical_name"],
        date_of_birth=linha["date_of_birth"],
        nationality=linha["nationality"],
        preferred_foot=PreferredFoot(linha["preferred_foot"]) if linha["preferred_foot"] else None,
        primary_position=Position(linha["primary_position"]) if linha["primary_position"] else None,
        active=linha["active"],
    )


def _para_partida(linha: Any) -> Match:
    from sports_intelligence.domain.competitions.models import (
        CompetitionRegime,
        RegimeCode,
        Stage,
        StageType,
    )
    from sports_intelligence.domain.matches.lifecycle import MatchLifecycle

    return Match(
        id=MatchId(linha["id"]),
        competition_id=CompetitionId(linha["competition_id"]),
        season_id=SeasonId(linha["season_id"]),
        regime=CompetitionRegime(
            code=RegimeCode(linha["regime_code"]),
            effective_from=instant(linha["regime_from"]),
            effective_to=None,
            regulation_version=linha["regulation_version"],
        ),
        stage=Stage(
            type=StageType(linha["stage_type"]),
            round_number=linha["round_number"],
            group_label=linha["group_label"],
        ),
        home_team_id=TeamId(linha["home_team_id"]),
        away_team_id=TeamId(linha["away_team_id"]),
        scheduled_kickoff=instant(linha["scheduled_kickoff"]),
        lifecycle=MatchLifecycle(linha["lifecycle"]),
        actual_kickoff=instant(linha["actual_kickoff"]) if linha["actual_kickoff"] else None,
        neutral_venue=linha["neutral_venue"],
    )
