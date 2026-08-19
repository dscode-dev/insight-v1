"""As referências do provedor → ids canônicos. EM LOTE, e sem resolver nada.

A DISTINÇÃO QUE ESTE MÓDULO EXISTE PARA MANTER (§10, §11, §12):

    RESOLVER    texto → entidade, com evidência, confiança e possibilidade de
                falhar. É o PR-03, e ele tem fila de revisão, decisões
                versionadas e ADR próprio.

    TRADUZIR    id do provedor → id canônico, consultando o que a resolução
                JÁ provou. É o que acontece aqui.

Reimplementar a primeira aqui criaria um segundo resolvedor com outras regras,
e o dia em que os dois discordassem — sobre o mesmo nome, no mesmo dataset —
não haveria como saber qual estava certo. Então este módulo só LÊ
`ProviderEntityMapping`, e o que não está lá simplesmente não resolve.

TUDO EM LOTE (§68). Um arquivo de eventos de uma temporada tem centenas de
milhares de linhas e algumas dezenas de entidades distintas: vinte clubes,
seiscentos jogadores, trezentas e oitenta partidas. Consultar por linha faria
cem mil consultas para responder novecentas perguntas — é exatamente o N+1 que
o PR-03.1 mediu e corrigiu, voltando pela porta dos eventos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import final

from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.ports.repositories.resolution import (
    ProviderMappingRepositoryPort,
)


@final
@dataclass(frozen=True, slots=True)
class EventReferences:
    """As traduções de UM lote. O que não está aqui não resolveu.

    AS AUSENTES SIMPLESMENTE NÃO ENTRAM NO MAPA, em vez de virarem `None`
    dentro dele: um mapa completo com valores nulos obrigaria todo leitor a
    distinguir «ausente» de «presente e nulo», e alguém erraria. O mapa
    incompleto é o tipo dizendo a verdade.
    """

    matches: dict[str, MatchId] = field(default_factory=dict)
    teams: dict[str, TeamId] = field(default_factory=dict)
    players: dict[str, PlayerId] = field(default_factory=dict)

    def match_for(self, record: HistoricalEventRecord) -> MatchId | None:
        return self.matches.get(record.match_reference)

    def team_for(self, record: HistoricalEventRecord) -> TeamId | None:
        if record.team_reference is None:
            return None
        return self.teams.get(record.team_reference)

    def player_for(self, record: HistoricalEventRecord) -> PlayerId | None:
        if record.player_reference is None:
            return None
        return self.players.get(record.player_reference)

    def player_by_reference(self, reference: str | None) -> PlayerId | None:
        if reference is None:
            return None
        return self.players.get(reference)

    def __str__(self) -> str:
        return (
            f"{len(self.matches)} partida(s), {len(self.teams)} time(s), "
            f"{len(self.players)} jogador(es)"
        )


@final
@dataclass(frozen=True, slots=True)
class EventReferenceReader:
    """Lê as traduções de um lote inteiro. TRÊS consultas, não 3N.

    ELE NÃO CRIA MAPEAMENTO. `create_if_absent` existe no port e não é chamado
    daqui: criar um mapeamento é afirmar que uma referência do provedor
    corresponde a uma entidade nossa, e essa afirmação precisa de evidência —
    que é o que a resolução produz e este módulo apenas consome (§12).
    """

    mappings: ProviderMappingRepositoryPort

    async def read(
        self, provider: ProviderId, records: Sequence[HistoricalEventRecord]
    ) -> EventReferences:
        if not records:
            return EventReferences()

        das_partidas = sorted({r.match_reference for r in records})
        dos_times = sorted({r.team_reference for r in records if r.team_reference})
        # OS JOGADORES DO DETALHE ENTRAM AQUI TAMBÉM. Uma substituição carrega
        # dois jogadores que não estão em `player_reference`, e esquecê-los
        # faria toda substituição falhar por identidade — com a referência
        # bem ali, na linha.
        dos_jogadores = sorted(
            {
                referencia
                for r in records
                for referencia in (
                    r.player_reference,
                    r.detail("EVENT_PLAYER_OUT_PROVIDER_ID"),
                    r.detail("EVENT_PLAYER_IN_PROVIDER_ID"),
                )
                if referencia
            }
        )

        partidas = await self.mappings.by_external_ids(provider, SubjectType.MATCH, das_partidas)
        times = (
            await self.mappings.by_external_ids(provider, SubjectType.TEAM, dos_times)
            if dos_times
            else []
        )
        jogadores = (
            await self.mappings.by_external_ids(provider, SubjectType.PLAYER, dos_jogadores)
            if dos_jogadores
            else []
        )

        return EventReferences(
            matches={m.provider_entity_id: MatchId(m.canonical_entity_id.value) for m in partidas},
            teams={m.provider_entity_id: TeamId(m.canonical_entity_id.value) for m in times},
            players={
                m.provider_entity_id: PlayerId(m.canonical_entity_id.value) for m in jogadores
            },
        )
