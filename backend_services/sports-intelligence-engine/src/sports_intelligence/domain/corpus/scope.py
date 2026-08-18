"""O escopo de um corpus — e por que ele é uma lista, não um filtro textual.

A DECISÃO ESTRUTURAL QUE ISTO PRESERVA (§15). A V1 decidiu que a recuperação
histórica é PARTICIONADA POR COMPETIÇÃO — não filtrada. A diferença aparece
quando o corpus cresce: um filtro varre tudo e descarta; uma partição nem lê.

Para que a partição exista lá na frente, o escopo precisa ser explícito AQUI,
com identidade canônica em vez de texto. `"Premier League 2024/25"` como
string obrigaria quem lê a fazer parse; `(PREMIER_LEAGUE, SeasonId(...))`
permite `WHERE competition_id = ...` e um diretório `competition=.../season=...`
no object store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId, SeasonId


@final
@dataclass(frozen=True, slots=True, order=True)
class ScopeEntry:
    """Uma (competição, temporada) que o corpus cobre.

    CARREGA O CÓDIGO E OS IDS. O código é o que vira caminho no object store e
    linha legível no manifesto; os ids são o que vira `WHERE` no banco. Guardar
    só um dos dois obrigaria a traduzir — e a tradução é onde se erra.

    `order=True` PORQUE A ORDEM ENTRA NA IMPRESSÃO (§33). Dois corpus com as
    mesmas competições em ordem de inserção diferente precisam produzir a mesma
    impressão, e ordenar exige que a ordem exista.
    """

    competition: CompetitionCode
    season_label: str
    competition_id: CompetitionId
    season_id: SeasonId

    def __post_init__(self) -> None:
        if not self.season_label.strip():
            raise ValidationError(
                "entrada de escopo sem rótulo de temporada: o manifesto ficaria "
                "com uma partição que ninguém consegue nomear"
            )

    @property
    def partition_key(self) -> tuple[str, str]:
        """`(competição, temporada)` — a chave de partição do corpus.

        É ELA QUE VIRA DIRETÓRIO e que vira índice. Um par, e não uma string
        concatenada: concatenar obrigaria a separar de novo, e o separador
        escolhido apareceria dentro de um rótulo de temporada no primeiro
        país que usa barra.
        """
        return (self.competition.value, self.season_label)

    def as_canonical(self) -> dict[str, str]:
        return {
            "competition": self.competition.value,
            "competition_id": str(self.competition_id),
            "season": self.season_label,
            "season_id": str(self.season_id),
        }

    def __str__(self) -> str:
        return f"{self.competition.value}/{self.season_label}"


@final
@dataclass(frozen=True, slots=True)
class CorpusScope:
    """O que este corpus cobre, e para que ele pode ser usado.

    O ESCOPO DE USO ENTRA AQUI e não numa flag ao lado, porque ele MUDA O
    CONTEÚDO: o corpus de pesquisa e o comercial nascem dos mesmos fatos e
    materializam famílias diferentes (§16). Tratá-lo como metadado faria dois
    conteúdos diferentes parecerem a mesma coisa com uma etiqueta.
    """

    entries: tuple[ScopeEntry, ...]
    usage: UsageScope

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValidationError(
                "corpus sem escopo: ele cobriria o quê? Um escopo vazio publicaria "
                "um corpus que nenhuma consulta consegue selecionar"
            )
        chaves = [e.partition_key for e in self.entries]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({f"{c}/{s}" for c, s in chaves if chaves.count((c, s)) > 1})
            raise ValidationError(
                f"partição declarada duas vezes no mesmo escopo: {repetidas} — os "
                "fatos dela entrariam em dobro nas contagens"
            )

    @classmethod
    def of(cls, *entries: ScopeEntry, usage: UsageScope) -> Self:
        """Constrói em ORDEM CANÔNICA, independente da ordem de chamada (§33)."""
        return cls(entries=tuple(sorted(entries)), usage=usage)

    @property
    def competitions(self) -> tuple[CompetitionCode, ...]:
        return tuple(sorted({e.competition for e in self.entries}, key=lambda c: c.value))

    @property
    def seasons(self) -> tuple[str, ...]:
        return tuple(sorted({e.season_label for e in self.entries}))

    @property
    def competition_ids(self) -> tuple[CompetitionId, ...]:
        return tuple(sorted({e.competition_id for e in self.entries}, key=str))

    @property
    def season_ids(self) -> tuple[SeasonId, ...]:
        return tuple(sorted({e.season_id for e in self.entries}, key=str))

    def covers(self, competition_id: CompetitionId, season_id: SeasonId) -> bool:
        """Se um fato desta (competição, temporada) pertence a este escopo.

        POR ID E NÃO POR NOME (§65). Casar por nome de time e data aproximada
        é como um fato da temporada A entra na temporada B — e o histórico
        passa a somar duas edições diferentes na mesma linha.
        """
        return any(
            e.competition_id == competition_id and e.season_id == season_id for e in self.entries
        )

    def entry_for(self, competition_id: CompetitionId, season_id: SeasonId) -> ScopeEntry | None:
        return next(
            (
                e
                for e in self.entries
                if e.competition_id == competition_id and e.season_id == season_id
            ),
            None,
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "competitions": [c.value for c in self.competitions],
            "entries": [e.as_canonical() for e in self.entries],
            "seasons": list(self.seasons),
            "usage": self.usage.value,
        }

    def __str__(self) -> str:
        return f"{self.usage} · " + ", ".join(str(e) for e in self.entries)
