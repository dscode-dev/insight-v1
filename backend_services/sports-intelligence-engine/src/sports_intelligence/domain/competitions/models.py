"""Competição, temporada, regime e fase.

A DISTINÇÃO QUE ESTE MÓDULO EXISTE PARA FAZER: uma competição não é a mesma
coisa em duas épocas. A Champions League de 2020 tinha fase de grupos com 32
clubes; a de 2025 tem uma league phase com 36. São formatos diferentes, com
números diferentes de jogos, sob regulamentos diferentes.

Um histórico que ignora isso compara coisas incomparáveis — e o faz em
silêncio, porque a competição "é a mesma".

Por isso `CompetitionRegime` existe: um estado histórico sabe sob qual regime
aconteceu, e uma comparação entre regimes diferentes é uma decisão explícita
em vez de um acidente.

NÃO É O REGULAMENTO INTEIRO. Codificar a FIFA aqui seria um projeto próprio e
envelheceria em um ano. O regime guarda o suficiente para responder "sob que
formato isto aconteceu" e apontar para a versão do regulamento.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.competitions.catalog import (
    CompetitionCode,
    CompetitionType,
    entry_for,
)
from sports_intelligence.domain.shared.identity import CompetitionId, SeasonId
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class Competition:
    """Uma das cinco da V1, materializada a partir do catálogo.

    O construtor é privado por convenção: use `Competition.from_code`. Criar
    uma competição fora do catálogo é o que o catálogo fechado impede.
    """

    id: CompetitionId
    code: CompetitionCode
    name: str
    region: str
    competition_type: CompetitionType
    active: bool = True

    @classmethod
    def from_code(cls, code: CompetitionCode, *, active: bool = True) -> Self:
        entrada = entry_for(code)
        return cls(
            id=entrada.id,
            code=entrada.code,
            name=entrada.name,
            region=entrada.region,
            competition_type=entrada.competition_type,
            active=active,
        )


class RegimeCode(StrEnum):
    """O formato de uma competição numa época.

    Fechado como o catálogo, e pelo mesmo motivo: um regime por string livre
    produz dois nomes para o mesmo formato na primeira vez que alguém digita.
    """

    #: Pontos corridos, turno e returno. Brasileirão, Premier League, LaLiga.
    DOUBLE_ROUND_ROBIN = "DOUBLE_ROUND_ROBIN"
    #: Grupos seguidos de mata-mata. Champions até 2023-2024; Libertadores.
    GROUP_STAGE_KNOCKOUT = "GROUP_STAGE_KNOCKOUT"
    #: Tabela única com adversários sorteados, seguida de mata-mata.
    #: Champions a partir de 2024-2025.
    LEAGUE_PHASE_KNOCKOUT = "LEAGUE_PHASE_KNOCKOUT"


@final
@dataclass(frozen=True, slots=True)
class CompetitionRegime:
    """Sob que formato e regulamento uma época aconteceu.

    `effective_to` ausente quer dizer "vigente", e é o estado normal do regime
    corrente — não um dado faltando.
    """

    code: RegimeCode
    effective_from: Instant
    regulation_version: str
    effective_to: Instant | None = None

    def __post_init__(self) -> None:
        if not self.regulation_version.strip():
            raise ValueError(
                "regulation_version é obrigatória: sem ela não há como dizer QUAL versão "
                "das regras valia, e duas temporadas do mesmo formato podem ter regras diferentes"
            )
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to é anterior a effective_from")

    @property
    def is_current(self) -> bool:
        return self.effective_to is None

    def covers(self, moment: Instant) -> bool:
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment <= self.effective_to


@final
@dataclass(frozen=True, slots=True)
class Season:
    """Uma edição de uma competição, com o regime sob o qual ocorreu."""

    id: SeasonId
    competition_id: CompetitionId
    label: str
    starts_at: Instant
    ends_at: Instant
    regime: CompetitionRegime

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("temporada sem label")
        if self.ends_at < self.starts_at:
            raise ValueError(
                f"temporada {self.label} termina ({self.ends_at.isoformat()}) antes de "
                f"começar ({self.starts_at.isoformat()})"
            )
        # O regime precisa cobrir a temporada inteira. Uma temporada que
        # atravessa a fronteira de dois regimes é duas coisas diferentes, e
        # tratá-la como uma faria o histórico comparar formatos distintos.
        if not self.regime.covers(self.starts_at):
            raise ValueError(
                f"o regime {self.regime.code} não cobre o início da temporada {self.label}"
            )
        if not self.regime.covers(self.ends_at):
            raise ValueError(
                f"o regime {self.regime.code} não cobre o fim da temporada {self.label}"
            )

    @classmethod
    def create(
        cls,
        *,
        competition_id: CompetitionId,
        label: str,
        starts_at: Instant,
        ends_at: Instant,
        regime: CompetitionRegime,
    ) -> Self:
        """Id derivado de (competição, label): a mesma temporada tem o mesmo
        id em qualquer execução, o que torna a reingestão idempotente."""
        return cls(
            id=SeasonId.derive(str(competition_id), label.strip()),
            competition_id=competition_id,
            label=label.strip(),
            starts_at=starts_at,
            ends_at=ends_at,
            regime=regime,
        )

    def contains(self, moment: Instant) -> bool:
        return self.starts_at <= moment <= self.ends_at


class StageType(StrEnum):
    """A fase da competição.

    NEM TODA COMPETIÇÃO TEM TODAS. Uma liga nacional só tem `LEAGUE`; a
    Libertadores tem qualificatória, grupos e quatro rodadas de mata-mata.
    Assumir estrutura única é o que faz um modelo quebrar na segunda
    competição.
    """

    QUALIFYING = "QUALIFYING"
    LEAGUE = "LEAGUE"
    GROUP_STAGE = "GROUP_STAGE"
    LEAGUE_PHASE = "LEAGUE_PHASE"
    PLAYOFF = "PLAYOFF"
    ROUND_OF_16 = "ROUND_OF_16"
    QUARTER_FINAL = "QUARTER_FINAL"
    SEMI_FINAL = "SEMI_FINAL"
    FINAL = "FINAL"

    @property
    def is_knockout(self) -> bool:
        """Mata-mata elimina; fase de tabela não.

        A diferença importa para descrever contexto: um empate na 20ª rodada
        e um empate numa semifinal são situações opostas.
        """
        return self in (
            StageType.PLAYOFF,
            StageType.ROUND_OF_16,
            StageType.QUARTER_FINAL,
            StageType.SEMI_FINAL,
            StageType.FINAL,
        )


@final
@dataclass(frozen=True, slots=True)
class Stage:
    """A fase de uma partida, com rodada ou grupo quando fizerem sentido.

    `round_number` e `group_label` são opcionais porque a maioria das
    combinações não os tem: uma final não tem rodada, uma rodada de liga não
    tem grupo. Ausência aqui é estrutural, não dado faltando.
    """

    type: StageType
    round_number: int | None = None
    group_label: str | None = None

    def __post_init__(self) -> None:
        if self.round_number is not None and self.round_number < 1:
            raise ValueError(f"rodada precisa ser positiva, recebeu {self.round_number}")
        if self.group_label is not None and not self.group_label.strip():
            raise ValueError("group_label vazio: omita em vez de mandar vazio")
        # Mata-mata não tem rodada de liga. Um "quartas de final, rodada 12"
        # é um dado misturado de duas competições.
        if self.type.is_knockout and self.round_number is not None:
            raise ValueError(
                f"{self.type} é mata-mata e não tem número de rodada; "
                "para identificar ida e volta, use partidas distintas"
            )
        if self.group_label is not None and self.type is not StageType.GROUP_STAGE:
            raise ValueError(f"{self.type} não tem grupo")

    def __str__(self) -> str:
        if self.group_label:
            return f"{self.type}[{self.group_label}]"
        if self.round_number:
            return f"{self.type}#{self.round_number}"
        return str(self.type)
