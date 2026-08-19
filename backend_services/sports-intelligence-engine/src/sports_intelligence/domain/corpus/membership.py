"""Quem pertence a qual versão do corpus — e por que isso não se deriva.

A TENTAÇÃO É DERIVAR (§114). «Os fatos do corpus 1.0 são os que existiam no
banco quando ele foi publicado» parece bastar, e não basta: o registro
canônico é global e cresce depois; um `Match` construído por um build de
pesquisa está lá e não pertence ao corpus comercial; e a mesma partida entra em
três versões com famílias diferentes em cada uma.

Derivar por data seria pior ainda — bastaria alguém corrigir um fato para a
versão publicada mudar de conteúdo sem mudar de nome.

Então a pertinência é GRAVADA, partida a partida, e congelada quando a versão
fica `READY` (§115).

O FATO NÃO É DUPLICADO (§116). O `Match` canônico continua sendo um só, no
registro; o que existe por versão é uma LINHA DE PERTINÊNCIA que aponta para
ele. Duplicar o fato faria a mesma partida existir cinco vezes com cinco ids,
que é exatamente o que a resolução de identidade passou três PRs impedindo.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Self, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.quality.coverage import FAMILY_ORDER, CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    SeasonId,
)


@final
@dataclass(frozen=True, slots=True, order=True)
class BuildContribution:
    """UM build que contribuiu para uma partida do corpus (PR-04.3.1 §33).

    POR QUE ISTO É UMA LISTA E NÃO UM CAMPO. O PR-04.3 guardava um
    `build_run_id` por membro, e a composição escolhia qual — na prática, o
    mais recente. Quando dois builds produzem a MESMA partida (duas
    temporadas construídas em execuções diferentes, ou um reprocessamento
    que confirma o anterior), guardar um só apaga metade da linhagem: «por que
    esta partida está no corpus» passa a ter uma resposta onde havia duas, e a
    resposta apagada era tão verdadeira quanto a que ficou.

    `included_families` É POR CONTRIBUIÇÃO e o membro guarda a UNIÃO. As duas
    coisas são diferentes e as duas importam: a união é o que o corpus publica,
    e a parcela é o que cada build autorizou.
    """

    build_run_id: str
    quality_assessment_id: str
    included_families: tuple[CoverageFamily, ...] = ()

    def __post_init__(self) -> None:
        if not self.build_run_id.strip():
            raise ValidationError("contribuição sem execução de construção")
        if not self.quality_assessment_id.strip():
            raise ValidationError(
                "contribuição sem avaliação de qualidade: «por que esta partida "
                "está no corpus» ficaria sem resposta (PR-04.2 §50)"
            )


@final
@dataclass(frozen=True, slots=True)
class CorpusMember:
    """Uma partida DENTRO de uma versão do corpus, com o que dela entrou.

    A GRANULARIDADE É A PARTIDA e não o fato individual, e é deliberado: o
    `Match` é a unidade que o PR-05 vai iterar, e as famílias que entraram
    ficam na própria linha. Uma linha por fato multiplicaria a tabela por cinco
    para responder a mesma pergunta com mais junções.

    `content_fingerprint` É O QUE FAZ A IMPRESSÃO DO CORPUS SER SEMÂNTICA
    (§32). Sem ele, dois corpus com as mesmas partidas e placares DIFERENTES
    teriam a mesma impressão — e ela deixaria de responder «este é o mesmo
    corpus?», que é a única coisa que ela existe para responder.
    """

    match_id: MatchId
    competition: CompetitionCode
    competition_id: CompetitionId
    season_label: str
    season_id: SeasonId
    #: A UNIÃO das famílias que entraram, vindas de todos os contribuintes.
    included_families: tuple[CoverageFamily, ...]
    #: TODOS os builds que contribuíram, com a avaliação de cada um. Plural de
    #: propósito: nenhum deles vence os outros (PR-04.3.1 §24, §33).
    contributions: tuple[BuildContribution, ...]
    #: O digest do CONTEÚDO dos fatos incluídos desta partida.
    content_fingerprint: ContentHash

    def __post_init__(self) -> None:
        if not self.included_families:
            raise ValidationError(
                f"{self.match_id} entrou no corpus sem nenhuma família — um membro "
                "sem conteúdo é uma linha que afirma pertencer e não traz nada"
            )
        if len(set(self.included_families)) != len(self.included_families):
            raise ValidationError(f"{self.match_id} com família repetida")
        if not self.contributions:
            raise ValidationError(
                f"{self.match_id} sem nenhum build contribuinte: «por que esta "
                "partida está no corpus» ficaria sem resposta (PR-04.2 §50)"
            )
        execucoes = [c.build_run_id for c in self.contributions]
        if len(set(execucoes)) != len(execucoes):
            raise ValidationError(
                f"{self.match_id} com a mesma execução contribuindo duas vezes — a "
                "linhagem contaria o mesmo build em dobro"
            )
        # A UNIÃO PRECISA COBRIR AS PARCELAS. Uma família que um build incluiu
        # e o membro não declara é conteúdo publicado sem estar no manifesto.
        das_contribuicoes = {f for c in self.contributions for f in c.included_families}
        if not das_contribuicoes <= set(self.included_families):
            faltando = sorted(f.value for f in das_contribuicoes - set(self.included_families))
            raise ValidationError(
                f"{self.match_id}: os builds incluíram {faltando} e o membro não "
                "declara — a união precisa cobrir o que cada contribuinte trouxe"
            )

    @classmethod
    def of(
        cls,
        *,
        match_id: MatchId,
        competition: CompetitionCode,
        competition_id: CompetitionId,
        season_label: str,
        season_id: SeasonId,
        included_families: tuple[CoverageFamily, ...],
        contributions: tuple[BuildContribution, ...],
        content_fingerprint: ContentHash,
    ) -> Self:
        """Constrói com as famílias em ORDEM CANÔNICA (§33)."""
        presentes = set(included_families)
        return cls(
            match_id=match_id,
            competition=competition,
            competition_id=competition_id,
            season_label=season_label,
            season_id=season_id,
            included_families=tuple(f for f in FAMILY_ORDER if f in presentes),
            # ORDENADAS POR EXECUÇÃO, e não por ordem de chegada: a linhagem
            # de um membro não pode depender de qual página veio primeiro.
            contributions=tuple(sorted(contributions)),
            content_fingerprint=content_fingerprint,
        )

    @property
    def partition_key(self) -> tuple[str, str]:
        return (self.competition.value, self.season_label)

    def includes(self, family: CoverageFamily) -> bool:
        return family in self.included_families

    @property
    def build_run_ids(self) -> tuple[str, ...]:
        return tuple(c.build_run_id for c in self.contributions)

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra na impressão do corpus.

        AS CONTRIBUIÇÕES FICAM DE FORA (§31). Elas são UUID de execução: duas
        publicações independentes dos MESMOS fatos teriam ids diferentes, e
        incluí-las faria a impressão dizer «corpus diferente» sobre corpus
        idêntico — o oposto do que ela responde. A linhagem continua gravada;
        o que não entra é a impressão.
        """
        return {
            "competition": self.competition.value,
            "content": self.content_fingerprint.value,
            "families": [f.value for f in self.included_families],
            "match_id": str(self.match_id),
            "season": self.season_label,
        }

    def __str__(self) -> str:
        familias = ",".join(f.value for f in self.included_families)
        return f"{self.match_id} [{familias}] @ {self.competition.value}/{self.season_label}"


@final
@dataclass(frozen=True, slots=True)
class CorpusEventMember:
    """UM evento canônico DENTRO de uma versão do corpus (PR-04.4.2 §5, §6).

    POR QUE ELA EXISTE, e por que não bastava derivar. «Os eventos do corpus
    1.0 são os da partida que está no corpus 1.0» é falso das duas pontas: uma
    versão pode publicar a partida SEM eventos — porque não declarou execução
    de evento nenhuma, ou porque a licença os excluiu do escopo comercial —, e
    o registro canônico de eventos é global e cresce depois da publicação.
    Derivar faria uma versão publicada mudar de conteúdo sem mudar de nome.

    A AUTORIDADE É O `CanonicalEventId` (§7). Dois chutes do mesmo jogador no
    mesmo minuto são dois eventos, e colapsá-los por «mesma partida, mesmo
    jogador, mesmo minuto» apagaria um fato que aconteceu.

    AS CONTRIBUIÇÕES SÃO PLURAIS (§66, §68). O mesmo evento canônico pode ter
    sido produzido por duas execuções — um reprocessamento que confirma a
    primeira —, e as duas linhagens são igualmente verdadeiras. O que NÃO se
    duplica é a pertinência: uma linha por evento por versão.
    """

    event_id: uuid.UUID
    match_id: MatchId
    competition: CompetitionCode
    season_label: str
    #: TODAS as execuções de canonicalização que produziram este evento.
    event_build_run_ids: tuple[str, ...]
    #: O digest do CONTEÚDO do evento — o mesmo que o registro grava. É ele que
    #: permite conferir, sem reler o evento inteiro, que a versão publica o
    #: conteúdo que ela imprimiu.
    content_digest: ContentHash

    def __post_init__(self) -> None:
        if not self.event_build_run_ids:
            raise ValidationError(
                f"evento {self.event_id} no corpus sem execução contribuinte: «por "
                "que este evento está no corpus» ficaria sem resposta"
            )
        if len(set(self.event_build_run_ids)) != len(self.event_build_run_ids):
            raise ValidationError(
                f"evento {self.event_id} com a mesma execução contribuindo duas "
                "vezes — a linhagem contaria o mesmo build em dobro"
            )

    @classmethod
    def of(
        cls,
        *,
        event_id: uuid.UUID,
        match_id: MatchId,
        competition: CompetitionCode,
        season_label: str,
        event_build_run_ids: Sequence[str],
        content_digest: ContentHash,
    ) -> Self:
        """Constrói com as contribuições em ordem determinística."""
        return cls(
            event_id=event_id,
            match_id=match_id,
            competition=competition,
            season_label=season_label,
            event_build_run_ids=tuple(sorted(set(event_build_run_ids))),
            content_digest=content_digest,
        )

    @property
    def partition_key(self) -> tuple[str, str]:
        return (self.competition.value, self.season_label)

    def __str__(self) -> str:
        return f"{self.event_id} @ {self.match_id}"


@final
@dataclass(frozen=True, slots=True)
class MembershipCounts:
    """Quantas partidas e quantas famílias, por partição.

    ELAS SÃO CONTADAS E NÃO ESTIMADAS (§100). Um manifesto com número
    aproximado é um manifesto que ninguém pode usar para conferir nada — e
    conferir é a única razão de ele existir.
    """

    matches: int = 0
    by_family: dict[str, int] = field(default_factory=dict)
    by_partition: dict[str, int] = field(default_factory=dict)
    #: OS NÚMEROS DE EVENTO (PR-04.4.2 §31). Eles são contagem do que a versão
    #: publica — nunca estimativa, e nunca analítica esportiva.
    events: EventCorpusCounts = field(default_factory=lambda: EventCorpusCounts())

    @classmethod
    def of(cls, members: tuple[CorpusMember, ...]) -> Self:
        por_familia: dict[str, int] = {}
        por_particao: dict[str, int] = {}
        for membro in members:
            for familia in membro.included_families:
                por_familia[familia.value] = por_familia.get(familia.value, 0) + 1
            chave = f"{membro.competition.value}/{membro.season_label}"
            por_particao[chave] = por_particao.get(chave, 0) + 1
        return cls(
            matches=len(members),
            by_family=dict(sorted(por_familia.items())),
            by_partition=dict(sorted(por_particao.items())),
        )

    def merged_with(self, other: MembershipCounts) -> MembershipCounts:
        """Soma dois lotes — é como a publicação acumula sem materializar tudo."""
        familias = dict(self.by_family)
        for nome, quantas in other.by_family.items():
            familias[nome] = familias.get(nome, 0) + quantas
        particoes = dict(self.by_partition)
        for nome, quantas in other.by_partition.items():
            particoes[nome] = particoes.get(nome, 0) + quantas
        return MembershipCounts(
            matches=self.matches + other.matches,
            by_family=dict(sorted(familias.items())),
            by_partition=dict(sorted(particoes.items())),
            events=self.events.merged_with(other.events),
        )

    def with_events(self, events: EventCorpusCounts) -> MembershipCounts:
        """As mesmas partidas, com os números de evento somados."""
        return MembershipCounts(
            matches=self.matches,
            by_family=dict(self.by_family),
            by_partition=dict(self.by_partition),
            events=self.events.merged_with(events),
        )

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica — e ela entra na IMPRESSÃO do corpus (§10).

        A CHAVE `events` SÓ APARECE QUANDO HÁ EVENTO, e a condição não é
        estética: esta forma é o rodapé da impressão, e emitir `"events": 0`
        num corpus sem eventos mudaria a impressão de TODA versão já
        publicada — que é exatamente o que o §62 e o §117 proíbem. Um corpus
        sem eventos produz hoje os mesmos bytes que produzia antes deste PR.

        No documento do manifesto vale o mesmo: a ausência da chave é a
        declaração honesta de «esta versão não publica eventos», e ela é
        indistinguível da forma que as versões antigas já têm.
        """
        forma: dict[str, object] = {
            "by_family": dict(sorted(self.by_family.items())),
            "by_partition": dict(sorted(self.by_partition.items())),
            "matches": self.matches,
        }
        if self.events.total:
            forma["events"] = self.events.as_canonical()
        return forma


@final
@dataclass(frozen=True, slots=True)
class EventCorpusCounts:
    """Os números de evento que o manifesto publica (PR-04.4.2 §31, §54).

    ELES SÃO CONTAGEM E NÃO ANALÍTICA. «Quantos eventos, de que tipos, em que
    estado, quantos com jogador e quantos com coordenada» descreve o CONTEÚDO
    do corpus — é o que alguém confere contra o arquivo. «Chutes por jogo» e
    «taxa de conversão» seriam interpretação, e interpretação tem versão de
    modelo e mora no PR-05.

    `spatially_eligible` É O DENOMINADOR HONESTO (§27). Ele conta só os tipos
    que acontecem num ponto do campo: pôr o apito inicial e a substituição no
    denominador faria uma fonte espacialmente completa parecer incompleta.
    """

    total: int = 0
    with_player: int = 0
    with_team: int = 0
    with_coordinates: int = 0
    spatially_eligible: int = 0
    matches_with_events: int = 0
    matches_with_coordinates: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)

    @classmethod
    def of(cls, events: Sequence[CanonicalMatchEvent]) -> EventCorpusCounts:
        """Conta os eventos de UMA partida."""
        por_tipo: dict[str, int] = {}
        por_estado: dict[str, int] = {}
        com_jogador = com_time = com_coordenada = elegiveis = 0
        for evento in events:
            por_tipo[evento.type.value] = por_tipo.get(evento.type.value, 0) + 1
            por_estado[evento.status.value] = por_estado.get(evento.status.value, 0) + 1
            if evento.player_id is not None:
                com_jogador += 1
            if evento.team_id is not None:
                com_time += 1
            if evento.start_location is not None:
                com_coordenada += 1
            if evento.type.supports_location:
                elegiveis += 1
        return cls(
            total=len(events),
            with_player=com_jogador,
            with_team=com_time,
            with_coordinates=com_coordenada,
            spatially_eligible=elegiveis,
            matches_with_events=1 if events else 0,
            matches_with_coordinates=1 if com_coordenada else 0,
            by_type=dict(sorted(por_tipo.items())),
            by_status=dict(sorted(por_estado.items())),
        )

    def merged_with(self, other: EventCorpusCounts) -> EventCorpusCounts:
        """Soma dois lotes — é como o acumulador cresce sem guardar eventos."""
        return EventCorpusCounts(
            total=self.total + other.total,
            with_player=self.with_player + other.with_player,
            with_team=self.with_team + other.with_team,
            with_coordinates=self.with_coordinates + other.with_coordinates,
            spatially_eligible=self.spatially_eligible + other.spatially_eligible,
            matches_with_events=self.matches_with_events + other.matches_with_events,
            matches_with_coordinates=(
                self.matches_with_coordinates + other.matches_with_coordinates
            ),
            by_type=_somados(self.by_type, other.by_type),
            by_status=_somados(self.by_status, other.by_status),
        )

    @property
    def spatial_ratio(self) -> float | None:
        """A cobertura espacial: com coordenada ÷ espacialmente elegíveis (§28).

        `None` E NUNCA `0.0` QUANDO NÃO HÁ DENOMINADOR. Um corpus cujos eventos
        são todos estruturais não tem 0% de cobertura espacial — ele tem
        cobertura espacial indefinida, e as duas coisas pedem ações opostas de
        quem investiga.
        """
        if not self.spatially_eligible:
            return None
        return self.with_coordinates / self.spatially_eligible

    def as_canonical(self) -> dict[str, object]:
        return {
            "by_status": dict(sorted(self.by_status.items())),
            "by_type": dict(sorted(self.by_type.items())),
            "matches_with_coordinates": self.matches_with_coordinates,
            "matches_with_events": self.matches_with_events,
            "spatially_eligible": self.spatially_eligible,
            "total": self.total,
            "with_coordinates": self.with_coordinates,
            "with_player": self.with_player,
            "with_team": self.with_team,
        }


def _somados(esquerda: dict[str, int], direita: dict[str, int]) -> dict[str, int]:
    somado = dict(esquerda)
    for chave, quantos in direita.items():
        somado[chave] = somado.get(chave, 0) + quantos
    return dict(sorted(somado.items()))
