"""Os ports da resolução e da fusão — carregamento em MASSA, sempre.

A ASSINATURA É O ANTÍDOTO CONTRA O N+1 (§42, §74). Nenhum método aqui recebe
um valor e devolve um candidato: todos recebem uma coleção e devolvem uma
coleção. Um port com `find_team_by_name(name: str)` convida ao laço por linha,
e o laço por linha é a diferença entre uma execução de dois minutos e uma de
três horas.

    proibido      find_team_by_name(nome) -> Team | None
    exigido       teams_by_normalized_names(nomes) -> Sequence[Team]

APPEND-ONLY ONDE A HISTÓRIA IMPORTA. Decisões, evidências, execuções e saídas
de fusão não têm `update`. Reprocessar emite outra execução; a anterior fica
exatamente como estava, e a diferença entre as duas é o que mostra o que o
resolver novo passou a enxergar (ADR-0019, ADR-0020).

A EXCEÇÃO É A FILA DE REVISÃO, e ela é declarada: um item muda de estado
porque um humano o pegou e decidiu. Mesmo ali, a decisão que sai é uma
`ResolutionDecision` nova — nunca uma edição da anterior.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.competitions.models import Competition, Season
from sports_intelligence.domain.fusion.models import FusionGroup
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate, FusionRun
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.resolution.decisions import (
    ResolutionDecision,
    SubjectType,
)
from sports_intelligence.domain.resolution.mappings import (
    EntityAlias,
    ProviderEntityMapping,
)
from sports_intelligence.domain.resolution.review import (
    ResolutionReviewItem,
    ReviewFilter,
)
from sports_intelligence.domain.resolution.runs import ResolutionRun
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    DatasetId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.sources.mapping import SourceMappingDefinition
from sports_intelligence.domain.teams.models import Team


@runtime_checkable
class ProviderMappingRepositoryPort(Protocol):
    """Mapeamentos de provedor. A evidência mais forte que existe."""

    async def by_external_ids(
        self, provider: ProviderId, subject: SubjectType, external_ids: Sequence[str]
    ) -> Sequence[ProviderEntityMapping]:
        """Todos os mapeamentos de um lote, numa consulta.

        RECEBE A LISTA INTEIRA de ids distintos do lote. Um lote de mil linhas
        de Premier League tem vinte ids de clube; consultar mil vezes o que
        são vinte buscas é exatamente o desperdício que o lote existe para
        evitar.
        """
        ...

    async def create_if_absent(self, mapping: ProviderEntityMapping) -> ProviderEntityMapping:
        """Cria, ou devolve o que já existe para aquela referência.

        A CONSTRAINT É QUEM DECIDE. Dois workers resolvendo o mesmo provedor
        em paralelo chegam juntos, os dois consultam, os dois não encontram, e
        os dois inserem — só o banco impede (§34, §93).

        DEVOLVE O EXISTENTE quando já há um. Quem chamou compara e descobre se
        houve divergência; sobrescrever em silêncio reapontaria todo o
        histórico já resolvido sob a tradução antiga.
        """
        ...

    async def by_canonical(
        self, subject: SubjectType, canonical_id: str
    ) -> Sequence[ProviderEntityMapping]:
        """Todos os provedores que apontam para uma entidade. Para auditoria:
        «quais fontes já foram ligadas a este clube?»"""
        ...


@runtime_checkable
class EntityAliasRepositoryPort(Protocol):
    """Aliases fora da entidade (§17) — nomes pelos quais ela já foi vista."""

    async def by_normalized(
        self, subject: SubjectType, normalized: Sequence[str]
    ) -> Sequence[EntityAlias]:
        """Os aliases de um lote de nomes normalizados, numa consulta."""
        ...

    async def create_if_absent(self, alias: EntityAlias) -> EntityAlias: ...

    async def by_entity(self, subject: SubjectType, entity_id: str) -> Sequence[EntityAlias]: ...


@runtime_checkable
class CanonicalRegistryPort(Protocol):
    """A leitura em massa do registro canônico, para montar o contexto.

    PORT PRÓPRIO E NÃO OS REPOSITÓRIOS DO PR-01. Aqueles são de escrita e de
    leitura por id, com a forma que os casos de uso futebolísticos precisam.
    Este existe só para carregar candidatos em bloco, e a diferença de forma é
    o ponto: misturar os dois faria o repositório de time ganhar um método
    que só a resolução usa.
    """

    async def competitions(self) -> Sequence[Competition]:
        """As cinco. Sempre todas — o catálogo é fechado e minúsculo."""
        ...

    async def seasons_of(self, competitions: Sequence[CompetitionId]) -> Sequence[Season]: ...

    async def teams_by_normalized_names(
        self, normalized: Sequence[str]
    ) -> Sequence[Team]: ...

    async def teams_by_ids(self, ids: Sequence[TeamId]) -> Sequence[Team]: ...

    async def team_candidates_for_names(
        self, normalized: Sequence[str], *, limit_per_name: int
    ) -> Sequence[tuple[str, Team]]:
        """Candidatos de similaridade POR NOME — o universo estável (§35).

        DEVOLVE PARES `(nome consultado, time)` e não uma lista solta: é o
        par que permite ao contexto indexar por nome, e é a indexação por nome
        que torna a decisão independente do lote. Uma lista solta seria de
        novo «tudo que o lote carregou».

        `limit_per_name` LIMITA POR NOME, não no total. Um teto global faria
        o corte depender de quantos nomes vieram no lote — trocaria uma
        dependência de lote por outra.
        """
        ...

    async def player_candidates_for_names(
        self, normalized: Sequence[str], *, limit_per_name: int
    ) -> Sequence[tuple[str, Player]]:
        """O mesmo para jogador."""
        ...

    async def players_by_normalized_names(
        self, normalized: Sequence[str]
    ) -> Sequence[Player]: ...

    async def tenures_of(self, players: Sequence[str]) -> Sequence[PlayerTeamTenure]:
        """Os vínculos dos candidatos, para a evidência temporal (§20)."""
        ...

    async def matches_of_fixtures(
        self, fixtures: Sequence[tuple[SeasonId, TeamId, TeamId]]
    ) -> Sequence[Match]:
        """As partidas dos confrontos do lote.

        A CHAVE DE AGRUPAMENTO É (temporada, mandante, visitante), e ela
        reduz o espaço de busca de «todas as partidas» para «as deste
        confronto nesta temporada» — que são uma ou duas. Sem ela, resolver
        partida varreria a tabela inteira por linha.
        """
        ...


@runtime_checkable
class SourceMappingRepositoryPort(Protocol):
    """As definições de mapeamento de fonte, versionadas."""

    async def save(self, definition: SourceMappingDefinition) -> SourceMappingDefinition:
        """Grava uma versão nova e aposenta a anterior, na mesma transação.

        APOSENTAR E NÃO SOBRESCREVER: execuções antigas rodaram sob a versão
        anterior e precisam continuar explicáveis por ela.
        """
        ...

    async def active_for(self, dataset_id: DatasetId) -> SourceMappingDefinition | None: ...

    async def by_id(self, mapping_id: str) -> SourceMappingDefinition | None: ...

    async def history_for(
        self, dataset_id: DatasetId
    ) -> Sequence[SourceMappingDefinition]: ...


@runtime_checkable
class ResolutionRunRepositoryPort(Protocol):
    """Execuções de resolução. Uma concluída é imutável (ADR-0019)."""

    async def create(self, run: ResolutionRun) -> ResolutionRun: ...

    async def finish(self, run: ResolutionRun) -> bool:
        """Fecha a execução SE ela ainda estiver em curso. `False` se não.

        Condicional ao estado anterior, como toda transição desta base: dois
        workers fechando a mesma execução produziriam duas contagens, e a
        segunda sobrescreveria a primeira.
        """
        ...

    async def by_id(self, run_id: str) -> ResolutionRun | None: ...

    async def for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 20
    ) -> Sequence[ResolutionRun]:
        """As execuções de um dataset, da mais nova para a mais velha.

        PLURAL É O PONTO: o mesmo dataset passa por várias execuções com
        versões diferentes de resolver, e todas coexistem.
        """
        ...


@runtime_checkable
class ResolutionDecisionRepositoryPort(Protocol):
    """Decisões. APPEND-ONLY — não há `update` neste protocolo."""

    async def append_many(self, decisions: Sequence[ResolutionDecision], *, run_id: str) -> int:
        """Grava um lote. Devolve quantas entraram.

        O NÚMERO IMPORTA: «gravado com sucesso» sem contagem é uma afirmação
        sem medida, e é assim que um lote que entrou pela metade passa por
        completo.
        """
        ...

    async def by_run(
        self, run_id: str, *, subject: SubjectType | None = None, limit: int = 200, offset: int = 0
    ) -> tuple[Sequence[ResolutionDecision], int]: ...

    async def by_id(self, decision_id: str) -> ResolutionDecision | None: ...

    async def confidences_for_records(
        self, run_ids: Sequence[str], record_refs: Sequence[str]
    ) -> dict[str, dict[SubjectType, float]]:
        """`record_ref → {tipo de identidade: confiança}` das decisões RESOLVED.

        É O QUE A AVALIAÇÃO DE QUALIDADE CONSOME (§13). Ela precisa da
        confiança POR TIPO — competição, temporada, time, partida — para
        conferir cada uma contra o piso DELA, e não contra uma média que
        deixaria um jogador em 0,4 passar escondido atrás de quatro
        identidades em 0,95.

        EM MASSA, POR LOTE DE REFERÊNCIAS. Buscar decisão a decisão faria uma
        consulta por linha de fonte — o N+1 que a assinatura destes ports
        existe para impedir. `record_refs` é o lote que está sendo avaliado.
        """
        ...

    async def resolved_entities_of_run(
        self, run_id: str, subject: SubjectType
    ) -> dict[str, str]:
        """`record_ref → canonical_entity_id` das decisões RESOLVED.

        É O QUE A FUSÃO CONSOME. Só `RESOLVED` entra: um registro cuja
        identidade não foi provada não tem como virar `ResolvedSourceRecord`,
        e é assim que a ordem obrigatória vira assinatura (ADR-0022).
        """
        ...


@runtime_checkable
class ReviewQueueRepositoryPort(Protocol):
    """A fila de revisão. O único port desta família com mudança de estado."""

    async def create_many(self, items: Sequence[ResolutionReviewItem]) -> int:
        """Cria itens, ignorando os que já existem para o mesmo sujeito.

        A IDEMPOTÊNCIA AQUI É POR (execução, referência de registro, sujeito).
        Sem ela, reexecutar uma resolução que falhou no meio duplicaria a
        fila — e um operador decidiria duas vezes a mesma coisa (§93).
        """
        ...

    async def list(
        self, *, filters: ReviewFilter, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[ResolutionReviewItem], int]: ...

    async def by_id(self, item_id: str) -> ResolutionReviewItem | None: ...

    async def update_status(
        self, item: ResolutionReviewItem, *, expected_status: str
    ) -> bool:
        """Muda o estado SE ele ainda for o esperado. `False` se não era.

        É o que impede dois operadores de decidirem o mesmo item em paralelo
        e produzirem duas decisões conflitantes.
        """
        ...


@runtime_checkable
class FusionRunRepositoryPort(Protocol):
    """Execuções de fusão e suas saídas. Também append-only (ADR-0020)."""

    async def create(self, run: FusionRun) -> FusionRun: ...

    async def finish(self, run: FusionRun) -> bool: ...

    async def by_id(self, run_id: str) -> FusionRun | None: ...

    async def recent(self, *, limit: int = 20) -> Sequence[FusionRun]: ...

    async def save_groups(self, run_id: str, groups: Sequence[FusionGroup]) -> int: ...

    async def save_candidates(
        self, run_id: str, candidates: Sequence[FusedMatchCandidate]
    ) -> int: ...

    async def candidates_of(
        self, run_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[dict[str, object]], int]:
        """A forma CANÔNICA gravada, e não o objeto de domínio remontado.

        DELIBERADO. O que está no banco é exatamente a saída que produziu a
        impressão; remontar o `FusedMatchCandidate` para serializá-lo de novo
        correria o risco de uma forma ligeiramente diferente — e a impressão
        deixaria de conferir, que é justamente o que ela existe para fazer.
        """
        ...

    async def group_ids_of(self, run_id: str) -> dict[str, str]:
        """`canonical_match_id → id do grupo` que ESTA execução persistiu.

        É O ELO QUE A LINHAGEM DO PR-04.2 PRECISA (§47, §48). Quem relê as
        fontes para remontar os candidatos produz grupos NOVOS, com ids
        sorteados; se a avaliação gravasse esses, o `fusion_group_id` do
        veredito apontaria para um grupo que nunca foi persistido — e a
        travessia até o `record_ref` terminaria num beco.

        Devolver o mapa é o que permite realinhar os grupos remontados aos que
        de fato existem no banco.
        """
        ...

    async def conflicts_of(
        self, run_id: str, *, limit: int = 100
    ) -> Sequence[tuple[str, str, str]]:
        """(match_id, campo, valores em conflito) dos não resolvidos.

        A CONSULTA QUE O OPERADOR DE FATO FAZ. Ela existe como método próprio
        porque carregar todos os candidatos para filtrar conflitos em Python
        traria megabytes para mostrar dez linhas.
        """
        ...
