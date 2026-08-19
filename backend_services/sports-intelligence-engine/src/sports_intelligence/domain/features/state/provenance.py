"""De onde veio cada parte do estado.

A PERGUNTA QUE ISTO RESPONDE (§58): «este 2-1 saiu de quais gols?», «quem
mudou o elenco em campo?», «quais cotações estão aqui dentro?». Sem ela, o
estado é uma afirmação sem defesa — e o dia em que alguém discordar do placar,
a única saída seria reconstruir tudo e torcer.

ELA É POR COMPONENTE, e não um saco único. «Este estado veio de 47 fatos» não
ajuda ninguém; «o placar veio destes dois gols, o campo veio desta escalação
mais estas três substituições» ajuda.

LIMITADA POR DESENHO (§59). O padrão é o mesmo do resto do motor: contagem
exata, amostra limitada e digest do conjunto inteiro. O placar quase sempre
cabe inteiro — gols são poucos —, e a lista de eventos efetivos não cabe:
reconstruir dez mil partidas carregando cada id inline multiplicaria o custo
por três ordens de grandeza.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Self, final

from sports_intelligence.domain.features.provenance import (
    FeatureContribution,
    FeatureProvenance,
    FeatureProvenanceClass,
)


def _de_eventos(ids: Iterable[uuid.UUID]) -> FeatureProvenance:
    """A procedência a partir de ids de evento — ordenada e com digest.

    ELA REAPROVEITA `FeatureProvenance` (PR-05.1) em vez de criar um segundo
    formato: as duas respondem a mesma pergunta, e dois formatos divergiriam no
    primeiro campo novo.
    """
    return FeatureProvenance.of(
        FeatureProvenanceClass.DERIVED_FROM_CANONICAL,
        (FeatureContribution(kind="EVENT", reference=str(i)) for i in ids),
    )


@final
@dataclass(frozen=True, slots=True)
class MatchStateProvenance:
    """O que sustentou cada componente do estado.

    `initial_lineup_teams` GUARDA OS TIMES, e não as escalações: a escalação
    inicial é publicada pelo corpus e imutável — quem a quer inteira vai ao
    corpus com o `match_id` e o `team_id`. O que o estado precisa registrar é
    que ELA foi a base (§61).
    """

    #: Os gols que produziram o placar (§60). Cardinalidade pequena por
    #: natureza, então quase sempre a amostra é o conjunto.
    score: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    #: Substituições e expulsões que mudaram o elenco em campo (§61).
    on_field: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    #: Os cartões que produziram a disciplina.
    discipline: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    #: As observações de cotação presentes no estado (§62).
    odds: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    #: O conjunto INTEIRO de eventos efetivos — o elo com a projeção.
    effective_events: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    #: Os times cuja escalação inicial alimentou o estado em campo.
    initial_lineup_teams: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        *,
        score_events: Iterable[uuid.UUID] = (),
        on_field_events: Iterable[uuid.UUID] = (),
        discipline_events: Iterable[uuid.UUID] = (),
        effective_events: Iterable[uuid.UUID] = (),
        odds_references: Iterable[str] = (),
        initial_lineup_teams: Iterable[str] = (),
    ) -> Self:
        return cls(
            score=_de_eventos(score_events),
            on_field=_de_eventos(on_field_events),
            discipline=_de_eventos(discipline_events),
            effective_events=_de_eventos(effective_events),
            odds=FeatureProvenance.of(
                FeatureProvenanceClass.OBSERVED_INPUT,
                (
                    FeatureContribution(kind="ODDS", reference=r)
                    for r in odds_references
                ),
            ),
            initial_lineup_teams=tuple(sorted(set(initial_lineup_teams))),
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "discipline": self.discipline.as_canonical(),
            "effective_events": self.effective_events.as_canonical(),
            "initial_lineup_teams": list(self.initial_lineup_teams),
            "odds": self.odds.as_canonical(),
            "on_field": self.on_field.as_canonical(),
            "score": self.score.as_canonical(),
        }

    def __str__(self) -> str:
        return (
            f"placar {self.score.count} · campo {self.on_field.count} · "
            f"disciplina {self.discipline.count} · odds {self.odds.count}"
        )
