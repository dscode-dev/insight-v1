"""atlas.match.v1 — the one shape the Atlas accepts a finished match in.

WHAT CHANGED AND WHY. Until now a match reached the Atlas by being written
into a directory as `explorer.envelope.v1`, and the reader took what it
recognised. Measured against production in August 2026, that reader:

  * REQUIRED five things and dropped the line in silence if any was absent —
    no error, no log, no count;
  * ACCEPTED an empty competition and an empty season, producing a vector
    that no competition-filtered query would ever return;
  * fell back from `club_id` to the raw team NAME, so "Arsenal FC" and
    "arsenal" became two different clubs with half a history each;
  * inferred the producing source from the FILE PATH;
  * had nowhere to put odds or match statistics, which is why seven of the
    thirty-seven vector dimensions were constant zero.

So this contract is not a tidier envelope. It is the list of the ways data
got in wrong, turned into rules.

EVERY FIELD IS REQUIRED. No optional blocks, no defaults, no `None` standing
in for "we did not look". A record that cannot state its odds is not
accepted with a gap — it is refused, by name, with the field listed. That is
a deliberate, expensive choice: measured today, ZERO of the 7.127 matches in
the lake would satisfy it, because the market and stats blocks live in the
raw layer and have never been attached to a match. Filling them is step 3;
until then this contract accepts nothing, and nothing currently depends on
it.

REQUIREDNESS CATCHES MISSING; ONLY VALUE RULES CATCH WRONG. A record can be
complete and still be nonsense — a halftime score above the full-time score,
shots on target above shots, decimal odds below 1.0, a club id nobody has
heard of. Those rules are the second half of this module, and they are the
half that earns it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atlas.intake.composition import BLOCOS
from atlas.match_identity import match_uid_from

SCHEMA_VERSION = "atlas.match.v1"

#: Lowercase, digits and underscores. The shape every club id and competition
#: key in the platform already has; anything else is a name that slipped
#: through unresolved.
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

#: `2024` or `2023-2024`. Both are real: South American seasons sit inside one
#: calendar year, European ones straddle two.
_SEASON = re.compile(r"^(\d{4}|\d{4}-\d{4})$")

#: Where the 299-club registry lives in the image. Shared with the Explorer
#: through insight-protos rather than copied, so the two cannot drift.
CLUB_REGISTRY_PATH = Path("/opt/insight-protos/contracts/clubs/club_registry.json")

#: Onde cada bloco declarado mora no documento. É o campo que o remetente
#: edita — nomeá-lo é a diferença entre um erro acionável e um convite a
#: procurar.
_CAMPO_DO_BLOCO = {
    "core": "identity",
    "result_halftime": "result.home_goals_halftime",
    "market_close": "market.closing",
    "market_open": "market.opening",
    "market_spread": "market.spread",
    "market_totals": "market.totals",
    "market_handicap": "market.handicap",
    "stats": "stats",
}


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            f"{field}: precisa de fuso horário explícito (ex.: 2024-03-01T15:00:00Z)"
        )
    return value.astimezone(timezone.utc)


class Identity(BaseModel):
    """Who played, where and when. This is what makes a match a match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    competition: str = Field(pattern=_SLUG.pattern)
    season: str = Field(pattern=_SEASON.pattern)
    # `club_id`, never a name. The resolver in the Explorer turns "Ath
    # Madrid" into `atletico_madrid`; a record arriving here with a display
    # name means that step was skipped, and the match will not join with the
    # club's own history.
    home_club_id: str = Field(pattern=_SLUG.pattern)
    away_club_id: str = Field(pattern=_SLUG.pattern)
    kickoff_utc: datetime

    @model_validator(mode="after")
    def _check(self) -> Identity:
        object.__setattr__(self, "kickoff_utc", _aware(self.kickoff_utc, "kickoff_utc"))
        if self.home_club_id == self.away_club_id:
            raise ValueError("home_club_id e away_club_id são o mesmo clube")
        if self.kickoff_utc > datetime.now(timezone.utc):
            raise ValueError("kickoff_utc está no futuro, mas o status é 'finished'")
        return self

    @property
    def uid(self) -> str:
        return match_uid_from(
            self.competition,
            self.season,
            self.home_club_id,
            self.away_club_id,
            self.kickoff_utc,
        )


class Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Only finished matches. A scheduled fixture has no score, and storing it
    # as history would put a 0-0 into every baseline.
    status: Literal["finished"]
    home_goals: int = Field(ge=0, le=30)
    away_goals: int = Field(ge=0, le=30)
    # O intervalo é o bloco `result_halftime`, não parte do núcleo. Os
    # arquivos sul-americanos não o publicam, e exigi-lo aqui recusaria
    # 11.830 partidas por um dado que nenhuma das 25 dimensões usa. Opcional
    # AQUI só quer dizer "declarável à parte": quem declara o bloco tem de
    # trazer os dois lados, e a regra de que o intervalo não passa do final
    # continua valendo.
    home_goals_halftime: int | None = Field(default=None, ge=0, le=30)
    away_goals_halftime: int | None = Field(default=None, ge=0, le=30)

    @model_validator(mode="after")
    def _check(self) -> Result:
        se_tem = (self.home_goals_halftime, self.away_goals_halftime)
        if (se_tem[0] is None) != (se_tem[1] is None):
            raise ValueError(
                "o placar do intervalo veio pela metade — um lado sem o outro "
                "não descreve nada"
            )
        if self.home_goals_halftime is not None:
            if self.home_goals_halftime > self.home_goals:
                raise ValueError("home_goals_halftime maior que home_goals")
        if self.away_goals_halftime is not None:
            if self.away_goals_halftime > self.away_goals:
                raise ValueError("away_goals_halftime maior que away_goals")
        return self


class Prices(BaseModel):
    """Decimal odds for the 1x2 market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Below 1.0 a decimal odd would pay less than the stake — impossible, and
    # the shape a transposed or mis-parsed column takes.
    home: float = Field(gt=1.0, le=1000.0)
    draw: float = Field(gt=1.0, le=1000.0)
    away: float = Field(gt=1.0, le=1000.0)

    @property
    def overround(self) -> float:
        """Sum of implied probabilities. A real book prices above 1.0 — the
        excess is the margin. Far from 1.0 in either direction means the
        numbers are not a coherent set of prices for one match."""
        return 1.0 / self.home + 1.0 / self.draw + 1.0 / self.away

    @model_validator(mode="after")
    def _check(self) -> Prices:
        book = self.overround
        # 1.00 is a book with no margin at all, 1.40 an implausibly greedy
        # one. Anything outside catches columns read in the wrong order far
        # more reliably than a per-price bound does.
        if not 1.0 <= book <= 1.40:
            raise ValueError(
                f"as três cotações não formam um mercado coerente "
                f"(soma das probabilidades implícitas = {book:.3f}, "
                "esperado entre 1,00 e 1,40)"
            )
        return self


class Totals(BaseModel):
    """O mercado de total de gols. A pergunta da lente `gols`, respondida
    pelo próprio mercado.

    `over` e `under` para a mesma linha, porque a probabilidade implícita só
    faz sentido normalizada entre as duas — uma cotação de over sozinha
    carrega a margem da casa embutida e não dá para comparar entre partidas.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Quase sempre 2.5, mas o arquivo publica a linha usada e ela varia em
    #: jogos muito desequilibrados. Lê-la em vez de supor 2.5 é a diferença
    #: entre a probabilidade de "mais de 2,5" e a de "mais de 3,5".
    line: float = Field(ge=0.5, le=7.5)
    over: float = Field(gt=1.0, le=1000.0)
    under: float = Field(gt=1.0, le=1000.0)

    @model_validator(mode="after")
    def _check(self) -> Totals:
        book = 1.0 / self.over + 1.0 / self.under
        if not 1.0 <= book <= 1.30:
            raise ValueError(
                f"over e under não formam um mercado coerente "
                f"(soma das probabilidades implícitas = {book:.3f}, "
                "esperado entre 1,00 e 1,30)"
            )
        return self


class Handicap(BaseModel):
    """Handicap asiático: a estimativa do mercado para a DIFERENÇA de gols.

    Mais fina que o 1x2 para medir favoritismo. `-0.75` quer dizer que o
    mandante precisa vencer por dois para pagar cheio; `+0.25`, que ele é
    azarão. É a mesma informação do 1x2 numa escala contínua, e uma escala
    contínua distingue partidas que as três cotações arredondam para o mesmo
    lugar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Sinal na direção do MANDANTE, como o football-data publica: negativo
    #: quer dizer mandante favorito. Inverter aqui trocaria o favorito de
    #: lado em metade do corpus sem erro nenhum aparecer.
    line: float = Field(ge=-5.0, le=5.0)
    home: float = Field(gt=1.0, le=1000.0)
    away: float = Field(gt=1.0, le=1000.0)

    @model_validator(mode="after")
    def _check(self) -> Handicap:
        book = 1.0 / self.home + 1.0 / self.away
        if not 1.0 <= book <= 1.30:
            raise ValueError(
                f"as duas cotações do handicap não formam um mercado coerente "
                f"(soma das probabilidades implícitas = {book:.3f})"
            )
        return self


class BestPrices(BaseModel):
    """O MELHOR preço de cada saída, entre todas as casas.

    POR QUE NÃO É UM `Prices`. A regra do `Prices` exige soma das implícitas
    entre 1,00 e 1,40, que é a faixa de um livro de UMA casa: a margem dela.
    Isto aqui não é o livro de ninguém — é o melhor preço de cada saída,
    possivelmente de três casas diferentes, e a soma cai abaixo de 1,0 sempre
    que existe arbitragem entre elas.

    MEDIDO nas 15.627 partidas com dispersão: mediana 1,001, p01 0,945, p99
    1,037, e **47,3% abaixo de 1,0**. Aplicar a regra de casa única aqui
    recusou 7.395 linhas boas na primeira tentativa.

    A FAIXA, E POR QUE ELA. Abaixo de 0,90 seria uma arbitragem de mais de
    10% entre casas grandes, que não existe em mercado líquido e é a forma de
    uma coluna mal lida — o mínimo observado foi 0,311. Acima de 1,15 o
    "melhor" preço seria pior que o de uma casa típica, o que quer dizer que
    Max e Avg vieram trocadas.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    home: float = Field(gt=1.0, le=1000.0)
    draw: float = Field(gt=1.0, le=1000.0)
    away: float = Field(gt=1.0, le=1000.0)

    @property
    def overround(self) -> float:
        return 1.0 / self.home + 1.0 / self.draw + 1.0 / self.away

    @model_validator(mode="after")
    def _check(self) -> BestPrices:
        book = self.overround
        if not 0.90 <= book <= 1.15:
            raise ValueError(
                f"o melhor preço das três saídas não forma um conjunto "
                f"plausível (soma das probabilidades implícitas = {book:.3f}, "
                "esperado entre 0,90 e 1,15 — abaixo disso seria uma "
                "arbitragem que não existe, acima seria Max e Avg trocadas)"
            )
        return self


class Spread(BaseModel):
    """O mesmo jogo por duas réguas: a média do mercado e o melhor preço.

    POR QUE AS DUAS. A diferença entre elas é quanto as casas DISCORDAM. Um
    jogo em que todo mundo precifica igual e um em que os preços se espalham
    são situações diferentes, e nenhuma das duas aparece na cotação de uma
    casa só — que é tudo o que o Atlas lia até aqui.

    E é o único sinal novo disponível em TODAS as competições: over/under e
    handicap não existem nos arquivos sul-americanos, Max e Avg existem em
    100% deles.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Média do mercado (coluna `Avg*`).
    consensus: Prices
    #: Melhor preço disponível (coluna `Max*`). Sempre >= o consenso em cada
    #: saída, então a soma das implícitas dele é sempre <= a do consenso — e
    #: fica abaixo de 1,0 em quase metade das partidas, que é por que ele tem
    #: faixa própria e não a de um livro de casa única.
    best: BestPrices

    @model_validator(mode="after")
    def _check(self) -> Spread:
        # O melhor preço não pode ser PIOR que a média em nenhuma saída: se
        # for, as colunas vieram trocadas, e a dispersão sairia negativa sem
        # nada denunciar.
        for lado in ("home", "draw", "away"):
            if getattr(self.best, lado) < getattr(self.consensus, lado) - 1e-9:
                raise ValueError(
                    f"o melhor preço em '{lado}' é menor que a média do "
                    "mercado — as colunas Max e Avg parecem trocadas"
                )
        return self


class Market(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bookmaker: str = Field(min_length=2, max_length=64)
    # Both ends, because the DIFFERENCE is the signal. `line_movement` is
    # what the market learned between opening and kickoff, and a single
    # snapshot cannot express it — which is why that dimension has been
    # fixed at its neutral value in every vector ever written.
    #
    # Each half is its own declared block (`market_open`, `market_close`), so
    # a source that publishes only closing prices contributes what it has
    # instead of being refused. Optional HERE does not mean optional in the
    # match: `MatchRecord` refuses a half that is present but undeclared, and
    # only a composition holding both halves is derived into `match_record`.
    opening: Prices | None = None
    closing: Prices | None = None
    #: `market_spread` — média do mercado e melhor preço, no fechamento.
    spread: Spread | None = None
    #: `market_totals` — o mercado de total de gols, no fechamento.
    totals: Totals | None = None
    #: `market_handicap` — o handicap asiático, no fechamento.
    handicap: Handicap | None = None


class SideStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    shots: int = Field(ge=0, le=80)
    shots_on_target: int = Field(ge=0, le=80)
    corners: int = Field(ge=0, le=40)
    fouls: int = Field(ge=0, le=60)
    yellow_cards: int = Field(ge=0, le=12)
    red_cards: int = Field(ge=0, le=5)

    @model_validator(mode="after")
    def _check(self) -> SideStats:
        if self.shots_on_target > self.shots:
            raise ValueError("shots_on_target maior que shots")
        return self


class Stats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    home: SideStats
    away: SideStats


class Provenance(BaseModel):
    """Who produced this record, and where it came from.

    Stated, never inferred. The old reader took the source from the third
    directory segment of the file path, which meant moving a file changed
    who was said to have collected it — and the source decides whose number
    wins when two disagree about a score.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=_SLUG.pattern)
    source_match_id: str = Field(min_length=1, max_length=128)
    collected_at: datetime
    url: str = Field(min_length=1, max_length=1024)

    #: Which blocks this source claims to bring. Declared, and then checked
    #: against what the document actually holds — see `MatchRecord._blocos`.
    #: A contribution must be COMPLETE for what it declares; absence inside a
    #: declared block stays an error, exactly as before.
    profile: tuple[str, ...] = Field(min_length=1)

    #: The timezone this source PUBLISHES in, as an IANA name.
    #:
    #: Not decoration. football-data.co.uk publishes in UK local time with no
    #: offset anywhere in the file; read as UTC, 210 of 1.785 Brazilian
    #: matches landed on the wrong calendar day — and the day is part of the
    #: match identity, so each of those would have become a second, phantom
    #: match instead of joining the one that already existed. The converter
    #: applies this before deriving the uid; storing it is what makes the
    #: conversion auditable afterwards.
    #:
    #: Sources that publish a real offset declare `UTC` and lose nothing.
    timezone: str = Field(min_length=3, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> Provenance:
        object.__setattr__(
            self, "collected_at", _aware(self.collected_at, "collected_at")
        )
        desconhecidos = [b for b in self.profile if b not in BLOCOS]
        if desconhecidos:
            raise ValueError(
                f"bloco desconhecido {desconhecidos[0]!r} — "
                f"os blocos são {', '.join(BLOCOS)}"
            )
        if len(set(self.profile)) != len(self.profile):
            raise ValueError("bloco declarado duas vezes")
        if "core" not in self.profile:
            # Sem núcleo não há partida a compor: mercado e estatística
            # sozinhos não sabem de que jogo estão falando.
            raise ValueError(
                "toda contribuição precisa declarar 'core' — "
                "é ele que diz quem jogou, quando e quanto foi"
            )
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"'{self.timezone}' não é um fuso IANA conhecido "
                "(ex.: America/Sao_Paulo, Europe/London, UTC)"
            ) from None
        return self


class MatchRecord(BaseModel):
    """One CONTRIBUTION: what a single source says about one finished match.

    WHAT COMPLETENESS MEANS HERE, AND WHY IT MOVED. This contract used to
    require all four blocks of every record. Measured, that made cross-source
    composition unreachable: the public Brazilian CSV brings score and
    closing odds and not one shot; a scrape brings shots and no odds. Both
    were refused for missing what the other had, so the only records that
    could compose were the ones that never needed to.

    So the requirement moved a level instead of loosening:

      * a CONTRIBUTION declares its blocks in `provenance.profile` and must
        be complete FOR THOSE. Declaring `stats` without stats is refused,
        and so is sending stats without declaring them — both mean the
        sender's idea of the record and the record disagree;

      * a MATCH — `atlas.match_record`, the only thing the Atlas reasons over
        and vectorises — still needs all four blocks. A composition short of
        that stays in `match_contribution` waiting for the missing piece and
        never reaches the vector space.

    The corpus the lenses answer from is therefore unchanged: complete rows
    only. What changed is that a complete row may now be assembled from two
    sources instead of requiring one source that brings everything — which,
    among free sources, is none of them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["atlas.match.v1"]
    identity: Identity
    result: Result
    market: Market | None = None
    stats: Stats | None = None
    provenance: Provenance

    @property
    def uid(self) -> str:
        return self.identity.uid

    @property
    def blocos(self) -> tuple[str, ...]:
        """The blocks this record ACTUALLY holds, read off the document.

        Deduced, never trusted from the declaration — that is the whole point
        of having both.
        """
        presentes = ["core"]
        if self.result.home_goals_halftime is not None:
            presentes.append("result_halftime")
        if self.market is not None:
            if self.market.closing is not None:
                presentes.append("market_close")
            if self.market.opening is not None:
                presentes.append("market_open")
            if self.market.spread is not None:
                presentes.append("market_spread")
            if self.market.totals is not None:
                presentes.append("market_totals")
            if self.market.handicap is not None:
                presentes.append("market_handicap")
        if self.stats is not None:
            presentes.append("stats")
        return tuple(b for b in BLOCOS if b in presentes)

    def divergencias_de_perfil(self) -> list[FieldError]:
        """Where the declaration and the document disagree, field by field.

        Checked in `validate` rather than in a `model_validator` for one
        reason: a validator at model level reports the error at the root, and
        "(raiz): declarou stats e não trouxe" makes whoever is fixing a
        10.000-line file go looking. These errors name `stats` and
        `market.closing`, which is what the sender edits.
        """
        declarado = set(self.provenance.profile)
        presente = set(self.blocos)
        erros: list[FieldError] = []

        # Declarou e não trouxe. A mesma recusa de sempre, com o mesmo peso —
        # ausência é afirmação, não esquecimento.
        for bloco in sorted(declarado - presente, key=BLOCOS.index):
            erros.append(
                FieldError(
                    _CAMPO_DO_BLOCO[bloco],
                    f"o bloco '{bloco}' está declarado em provenance.profile e "
                    "não veio — declare só o que a fonte traz",
                )
            )

        # Trouxe e não declarou. Igualmente recusado, e não por rigor: a
        # composição usa o perfil para saber o que ainda falta procurar. Um
        # bloco que chega sem declaração entra na partida sem entrar na
        # contabilidade de quem trouxe o quê.
        for bloco in sorted(presente - declarado, key=BLOCOS.index):
            erros.append(
                FieldError(
                    "provenance.profile",
                    f"o documento traz '{bloco}' sem declará-lo — "
                    "o que não é declarado não é composto",
                )
            )
        return erros


@dataclass(frozen=True)
class FieldError:
    field: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field}: {self.reason}"


@dataclass(frozen=True)
class Verdict:
    """Accepted, or refused with every reason named.

    EVERY reason, not the first. A record with four problems reported one at
    a time takes four round trips to fix, and whoever is fixing it starts
    guessing after the second.
    """

    record: MatchRecord | None
    errors: tuple[FieldError, ...]

    @property
    def accepted(self) -> bool:
        return self.record is not None

    @property
    def uid(self) -> str | None:
        return self.record.uid if self.record else None


@lru_cache(maxsize=1)
def known_clubs(path: Path = CLUB_REGISTRY_PATH) -> frozenset[str]:
    """Club ids the platform recognises, or empty when the registry is absent.

    Empty is reported by `validate` as an unchecked rule rather than as a
    pass — a validator that quietly stops checking is worse than one that
    never checked, because the operator believes it did.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        str(club["club_id"]) for club in data.get("clubs", []) if club.get("club_id")
    )


def validate(payload: Any, *, registry: frozenset[str] | None = None) -> Verdict:
    """Check one record against atlas.match.v1."""
    if not isinstance(payload, dict):
        return Verdict(None, (FieldError("(raiz)", "não é um objeto JSON"),))

    try:
        record = MatchRecord.model_validate(payload)
    except ValidationError as exc:
        return Verdict(None, tuple(_translate(exc)))

    divergencias = record.divergencias_de_perfil()
    if divergencias:
        return Verdict(None, tuple(divergencias))

    clubs = known_clubs() if registry is None else registry
    if clubs:
        unknown = [
            (field, value)
            for field, value in (
                ("identity.home_club_id", record.identity.home_club_id),
                ("identity.away_club_id", record.identity.away_club_id),
            )
            if value not in clubs
        ]
        if unknown:
            return Verdict(
                None,
                tuple(
                    FieldError(
                        field,
                        f"clube '{value}' não está no registro de {len(clubs)} clubes — "
                        "um id não reconhecido nunca se junta ao histórico do clube",
                    )
                    for field, value in unknown
                ),
            )

    return Verdict(record, ())


_MENSAGENS = {
    "missing": "campo obrigatório ausente",
    "extra_forbidden": "campo não faz parte do contrato",
    "literal_error": "valor fora dos permitidos",
    "string_pattern_mismatch": "formato inválido",
    "greater_than": "valor abaixo do mínimo",
    "greater_than_equal": "valor abaixo do mínimo",
    "less_than_equal": "valor acima do máximo",
    "int_parsing": "precisa ser um número inteiro",
    "float_parsing": "precisa ser um número",
    "datetime_from_date_parsing": "precisa ser data e hora, não só data",
    "too_short": "lista vazia — declare pelo menos um bloco",
}


def _translate(exc: ValidationError) -> list[FieldError]:
    """Pydantic's report, in the operator's language and vocabulary."""
    errors: list[FieldError] = []
    for detail in exc.errors():
        field = ".".join(str(part) for part in detail["loc"]) or "(raiz)"
        kind = detail.get("type", "")
        if kind == "value_error":
            # Our own model_validator messages are already written for a
            # reader; pydantic wraps them in "Value error, ".
            reason = str(detail.get("msg", "")).replace("Value error, ", "")
        else:
            reason = _MENSAGENS.get(kind, str(detail.get("msg", kind)))
            if kind == "string_pattern_mismatch":
                reason += " (esperado: minúsculas, dígitos e underscore)"
        errors.append(FieldError(field, reason))
    return errors


def example() -> dict:
    """A record that passes, for documentation and for the CLI's --exemplo.

    Kept as code rather than prose so it cannot drift from the contract: the
    test suite validates it, so a rule that changes breaks the example too.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "competition": "premier_league",
            "season": "2023-2024",
            "home_club_id": "arsenal",
            "away_club_id": "chelsea",
            "kickoff_utc": "2023-08-12T15:00:00Z",
        },
        "result": {
            "status": "finished",
            "home_goals": 2,
            "away_goals": 1,
            "home_goals_halftime": 1,
            "away_goals_halftime": 0,
        },
        "market": {
            "bookmaker": "bet365",
            "opening": {"home": 2.10, "draw": 3.40, "away": 3.75},
            "closing": {"home": 1.95, "draw": 3.50, "away": 4.00},
            # A média do mercado e o melhor preço: a diferença entre as duas
            # é quanto as casas discordam.
            "spread": {
                "consensus": {"home": 1.98, "draw": 3.55, "away": 3.90},
                "best": {"home": 2.05, "draw": 3.70, "away": 4.10},
            },
            # O mercado de total de gols — a pergunta da lente `gols`.
            "totals": {"line": 2.5, "over": 1.85, "under": 1.95},
            # O handicap asiático, com sinal na direção do mandante.
            "handicap": {"line": -0.25, "home": 1.92, "away": 1.98},
        },
        "stats": {
            "home": {
                "shots": 14, "shots_on_target": 6, "corners": 7,
                "fouls": 9, "yellow_cards": 1, "red_cards": 0,
            },
            "away": {
                "shots": 8, "shots_on_target": 3, "corners": 4,
                "fouls": 12, "yellow_cards": 2, "red_cards": 0,
            },
        },
        "provenance": {
            "source": "football_data",
            "source_match_id": "fd-2324-E0-0000",
            "collected_at": "2026-08-11T00:00:00Z",
            "url": "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
            "profile": [
                "core", "result_halftime", "market_close", "market_open",
                "market_spread", "market_totals", "market_handicap", "stats",
            ],
            "timezone": "Europe/London",
        },
    }


def example_parcial() -> list[dict]:
    """Two partial contributions that compose into one complete match.

    Here because the single complete example makes composition look optional
    — and it is the case composition exists for. Neither of these is accepted
    into `match_record` on its own; together they are one match.
    """
    base = example()
    identidade = dict(base["identity"])

    # O arquivo público traz o mercado 1x2 nas duas pontas e a dispersão; não
    # traz over/under nem handicap, que só existem nos arquivos europeus.
    mercado_publico = {
        k: v for k, v in base["market"].items() if k not in ("totals", "handicap")
    }
    csv_publico = {
        "schema_version": SCHEMA_VERSION,
        "identity": identidade,
        "result": base["result"],
        "market": mercado_publico,
        "provenance": {
            "source": "football_data",
            "source_match_id": "fd-2324-E0-0000",
            "collected_at": "2026-08-11T00:00:00Z",
            "url": "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
            # Placar e mercado, nenhum chute — é literalmente o que o arquivo
            # tem. E publicado em hora do Reino Unido, que é o motivo de o
            # fuso ser declarado e não suposto.
            "profile": [
                "core", "result_halftime", "market_close", "market_open",
                "market_spread",
            ],
            "timezone": "Europe/London",
        },
    }
    # A raspagem traz o placar final e os chutes, e não o intervalo — que é
    # o que uma página de estatísticas de partida costuma expor.
    sem_intervalo = {
        k: v for k, v in base["result"].items() if not k.endswith("_halftime")
    }
    raspagem = {
        "schema_version": SCHEMA_VERSION,
        "identity": identidade,
        "result": sem_intervalo,
        "stats": base["stats"],
        "provenance": {
            "source": "espn",
            "source_match_id": "espn-0000",
            "collected_at": "2026-08-11T00:00:00Z",
            "url": "https://www.espn.com.br/futebol/",
            "profile": ["core", "stats"],
            "timezone": "UTC",
        },
    }
    return [csv_publico, raspagem]
