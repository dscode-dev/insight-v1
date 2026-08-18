"""Os fatos de UMA partida, como o corpus os publica.

POR QUE ESTE OBJETO EXISTE, e não bastava ler a membership: a publicação
precisa de duas coisas sobre cada partida, e as duas saem do MESMO conteúdo.

    a impressão do conteúdo    para o §32 — dois corpus com as mesmas
                               partidas e placares diferentes não são o
                               mesmo corpus
    as linhas do Parquet       para o §43 — o que de fato é escrito

Calculá-las em duas passagens abriria a porta para elas discordarem: a
impressão descreveria um conteúdo e o arquivo carregaria outro, e a conferência
do §67 passaria mesmo assim. Uma passagem só, sobre um objeto só.

ELE NÃO RECALCULA NADA (§133). Não avalia qualidade, não resolve identidade,
não decide licença. Ele recebe os fatos que o build já construiu e as famílias
que a decisão de build já autorizou, e os serializa.

AUSENTE É `None`, E `None` VIRA `NULL` (§46). Zero é um placar; ausente é a
falta de um. Um `0` no lugar de um `NULL` produz estatística que soma
perfeitamente e está errada — o pior tipo, porque nada denuncia.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.fingerprint import (
    canonical_json,
    decimal_text,
    instant_text,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import FAMILY_ORDER, CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError

#: As famílias que este PR sabe materializar. `EVENT` não está aqui pela mesma
#: razão do PR-04.2: nenhum `SemanticRole` carrega evento, então não há o que
#: escrever — e um arquivo vazio afirmaria uma cobertura que não existe.
MATERIALIZABLE_FAMILIES: Final[frozenset[CoverageFamily]] = frozenset(
    {CoverageFamily.MATCH, CoverageFamily.LINEUP, CoverageFamily.ODDS}
)


@final
@dataclass(frozen=True, slots=True)
class MatchCorpusFacts:
    """Tudo que uma partida contribui para uma versão do corpus.

    `included_families` VEM DA DECISÃO DE BUILD e não é inferida da presença
    dos fatos. A diferença aparece exatamente no caso que importa: um build
    comercial que excluiu `ODDS` por licença pode ter as observações em mãos —
    inferir «tem odds, logo inclui odds» republicaria o que a política acabou
    de recusar.
    """

    match: Match
    competition: CompetitionCode
    season_label: str
    included_families: tuple[CoverageFamily, ...]
    build_run_id: str
    quality_assessment_id: str
    result: MatchResult | None = None
    lineups: tuple[Lineup, ...] = ()
    odds: tuple[CanonicalOddsObservation, ...] = ()

    def __post_init__(self) -> None:
        if not self.included_families:
            raise ValidationError(
                f"{self.match.id} sem família incluída — ela não deveria ter chegado "
                "à composição do corpus (§114)"
            )
        estranhas = set(self.included_families) - MATERIALIZABLE_FAMILIES
        if estranhas:
            nomes = ", ".join(sorted(f.value for f in estranhas))
            raise ValidationError(
                f"{self.match.id} inclui {nomes}, que este PR não materializa. "
                "Publicar a família sem saber escrevê-la faria o manifesto "
                "prometer conteúdo que não existe no corpus"
            )

    @property
    def partition_key(self) -> tuple[str, str]:
        return (self.competition.value, self.season_label)

    def includes(self, family: CoverageFamily) -> bool:
        return family in self.included_families

    # ------------------------------------------------------- impressão --

    def content_fingerprint(self) -> ContentHash:
        """O digest do conteúdo publicado desta partida (§32).

        SÓ AS FAMÍLIAS INCLUÍDAS ENTRAM. É o que faz o corpus de pesquisa e o
        comercial da mesma partida terem impressões diferentes — que é a
        verdade: eles publicam conteúdos diferentes.

        NENHUM ID DE EXECUÇÃO ENTRA (§31). O `build_run_id` muda a cada
        reprocessamento e o conteúdo não; incluí-lo faria a impressão dizer
        «diferente» sobre fatos idênticos.
        """
        return ContentHash(hashlib.sha256(canonical_json(self.content_form())).hexdigest())

    def factual_form(self) -> dict[str, object]:
        """A projeção FACTUAL, por aspecto, para comparar dois builds (§23).

        ELA NÃO É `content_form`. `content_form` descreve o que ESTE build
        publica — inclui a lista de famílias, e por isso dois builds com
        famílias diferentes divergiriam nela mesmo afirmando os mesmos fatos.
        Aqui o que interessa é só o que cada um AFIRMA, aspecto a aspecto,
        para que complementaridade não seja lida como conflito.

        RÓTULO NÃO ENTRA, e a fronteira do PR-04.2.1 sobrevive: a grafia do
        nome do time não está aqui porque o `Match` canônico não é construído
        a partir dela. `Man City` e `Manchester City` já terminaram no mesmo
        `TeamId`, e é o `TeamId` que esta forma carrega.
        """
        return {
            "lineups": [
                self._lineup_form(lineup)
                for lineup in sorted(self.lineups, key=lambda x: str(x.team_id))
            ],
            "match": self._match_form(),
            "odds": sorted(
                (self._odds_form(o) for o in self.odds),
                key=lambda linha: (
                    str(linha["bookmaker"]),
                    str(linha["market"]),
                    str(linha["selection"]),
                    str(linha["line"]),
                ),
            ),
        }

    def content_form(self) -> dict[str, object]:
        """A forma canônica do conteúdo. Ordenada em tudo que é coleção."""
        forma: dict[str, object] = {
            "families": [f.value for f in self.included_families],
            "match_id": str(self.match.id),
        }
        if self.includes(CoverageFamily.MATCH):
            forma["match"] = self._match_form()
        if self.includes(CoverageFamily.LINEUP):
            forma["lineups"] = [
                self._lineup_form(lineup)
                for lineup in sorted(self.lineups, key=lambda x: str(x.team_id))
            ]
        if self.includes(CoverageFamily.ODDS):
            forma["odds"] = sorted(
                (self._odds_form(o) for o in self.odds),
                key=lambda linha: (
                    str(linha["bookmaker"]),
                    str(linha["market"]),
                    str(linha["selection"]),
                    str(linha["line"]),
                ),
            )
        return forma

    def _match_form(self) -> dict[str, object]:
        partida = self.match
        forma: dict[str, object] = {
            "away_team_id": str(partida.away_team_id),
            "competition": self.competition.value,
            "competition_id": str(partida.competition_id),
            "home_team_id": str(partida.home_team_id),
            "lifecycle": partida.lifecycle.value,
            "neutral_venue": partida.neutral_venue,
            "scheduled_kickoff": instant_text(partida.scheduled_kickoff),
            "season": self.season_label,
            "season_id": str(partida.season_id),
            "stage": str(partida.stage),
            "venue": None if partida.venue is None else partida.venue.name,
        }
        if self.result is not None:
            forma["result"] = {
                "extra_time": self._score_form(self.result.extra_time),
                "penalties": self._score_form(self.result.penalties),
                "regular_time": self._score_form(self.result.regular_time),
            }
        else:
            # A chave EXISTE com `None`, e a presença é deliberada: sem ela,
            # «esta partida não tem resultado» e «esta versão não grava
            # resultado» produziriam a mesma impressão.
            forma["result"] = None
        return forma

    @staticmethod
    def _score_form(score: Score | None) -> dict[str, int] | None:
        if score is None:
            return None
        return {"away": score.away, "home": score.home}

    @staticmethod
    def _lineup_form(lineup: Lineup) -> dict[str, object]:
        return {
            "entries": sorted(
                (
                    {
                        "captain": e.captain,
                        "player_id": str(e.player_id),
                        "position": None if e.position is None else e.position.value,
                        "shirt_number": e.shirt_number,
                        "status": e.status.value,
                        "tactical_role": (
                            None if e.tactical_role is None else str(e.tactical_role)
                        ),
                    }
                    for e in lineup.entries
                ),
                key=lambda linha: str(linha["player_id"]),
            ),
            "formation": (None if lineup.formation is None else str(lineup.formation)),
            "team_id": str(lineup.team_id),
        }

    @staticmethod
    def _odds_form(observation: CanonicalOddsObservation) -> dict[str, object]:
        return {
            "bookmaker": observation.bookmaker.code,
            "decimal_odds": decimal_text(observation.decimal_odds),
            "line": decimal_text(observation.line),
            "market": observation.market.value,
            "observed_at": (
                None if observation.observed_at is None else instant_text(observation.observed_at)
            ),
            "selection": observation.selection.value,
        }

    # ----------------------------------------------------- pertinência --

    # NÃO EXISTE `as_member()` AQUI, e a ausência é o ponto (PR-04.3.1 §22).
    # Um membro nasce de uma COMPOSIÇÃO — `domain/corpus/composition.py` —,
    # porque só ela sabe se a partida veio de um build ou de vários, se os
    # fatos concordam e qual é a união das famílias. Um atalho daqui para o
    # membro reintroduziria exatamente o «um build vence» que a composição
    # existe para eliminar.

    # -------------------------------------------------- materialização --

    def rows_for(self, family: CoverageFamily) -> list[dict[str, object]]:
        """As linhas que esta partida contribui para o arquivo da família.

        LISTA VAZIA QUANDO A FAMÍLIA NÃO ENTROU, e nunca uma linha com tudo
        nulo: uma linha nula seria contada na cobertura e afirmaria presença.
        """
        if not self.includes(family):
            return []
        if family is CoverageFamily.MATCH:
            return [self._match_row()]
        if family is CoverageFamily.LINEUP:
            return self._lineup_rows()
        if family is CoverageFamily.ODDS:
            return self._odds_rows()
        return []

    def _match_row(self) -> dict[str, object]:
        partida = self.match
        resultado = self.result
        regular = None if resultado is None else resultado.regular_time
        prorrogacao = None if resultado is None else resultado.extra_time
        penaltis = None if resultado is None else resultado.penalties
        return {
            "match_id": str(partida.id),
            "competition": self.competition.value,
            "competition_id": str(partida.competition_id),
            "season": self.season_label,
            "season_id": str(partida.season_id),
            "stage": str(partida.stage),
            "home_team_id": str(partida.home_team_id),
            "away_team_id": str(partida.away_team_id),
            "scheduled_kickoff": partida.scheduled_kickoff,
            "actual_kickoff": partida.actual_kickoff,
            "lifecycle": partida.lifecycle.value,
            "venue": None if partida.venue is None else partida.venue.name,
            "neutral_venue": partida.neutral_venue,
            "home_goals": None if regular is None else regular.home,
            "away_goals": None if regular is None else regular.away,
            "extra_time_home_goals": None if prorrogacao is None else prorrogacao.home,
            "extra_time_away_goals": None if prorrogacao is None else prorrogacao.away,
            "penalty_home_goals": None if penaltis is None else penaltis.home,
            "penalty_away_goals": None if penaltis is None else penaltis.away,
            "outcome": None if regular is None else regular.outcome.value,
        }

    def _lineup_rows(self) -> list[dict[str, object]]:
        linhas: list[dict[str, object]] = []
        for lineup in sorted(self.lineups, key=lambda x: str(x.team_id)):
            for entrada in sorted(lineup.entries, key=lambda e: str(e.player_id)):
                linhas.append(
                    {
                        "match_id": str(self.match.id),
                        "competition": self.competition.value,
                        "season": self.season_label,
                        "team_id": str(lineup.team_id),
                        "formation": (None if lineup.formation is None else str(lineup.formation)),
                        "player_id": str(entrada.player_id),
                        "status": entrada.status.value,
                        "shirt_number": entrada.shirt_number,
                        "position": (None if entrada.position is None else entrada.position.value),
                        "tactical_role": (
                            None if entrada.tactical_role is None else str(entrada.tactical_role)
                        ),
                        "captain": entrada.captain,
                    }
                )
        return linhas

    def _odds_rows(self) -> list[dict[str, object]]:
        linhas: list[dict[str, object]] = []
        for observacao in sorted(
            self.odds,
            key=lambda o: (
                o.bookmaker.code,
                o.market.value,
                o.selection.value,
                decimal_text(o.line) or "",
            ),
        ):
            linhas.append(
                {
                    "match_id": str(self.match.id),
                    "competition": self.competition.value,
                    "season": self.season_label,
                    "bookmaker": observacao.bookmaker.code,
                    "market": observacao.market.value,
                    "selection": observacao.selection.value,
                    # `Decimal` E NÃO `float` (§47): uma odd é preço, e
                    # `float(Decimal("2.05"))` não é 2.05. O schema Parquet
                    # declara `decimal128`, e a conversão nunca acontece.
                    "decimal_odds": observacao.decimal_odds,
                    "line": observacao.line,
                    # `None` quando a fonte não declara. Nunca o kickoff.
                    "observed_at": observacao.observed_at,
                }
            )
        return linhas


def families_present(facts: MatchCorpusFacts) -> tuple[CoverageFamily, ...]:
    """As famílias incluídas em ordem canônica — a do `FAMILY_ORDER`."""
    presentes = set(facts.included_families)
    return tuple(f for f in FAMILY_ORDER if f in presentes)
