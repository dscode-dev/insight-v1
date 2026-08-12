"""The one place a match becomes part of the Atlas.

The HTTP endpoint and the CLI are two doors onto this function. Neither
validates, neither writes, neither counts — they parse their own input,
call `ingest`, and render the same report. That is the whole reason this
module exists: two write paths that each know the rules will eventually
disagree about them, and the disagreement will be silent.

WHAT AN OPERATOR GETS BACK. Not "ok". Per line: accepted or refused, and
for a refusal every field that was wrong with the reason in words. Plus
the difference the batch actually made — how many matches the Atlas held
before, how many after, how many were updates rather than new. "Deu certo"
without a measured difference is the failure this rebuild started from.

REFUSALS ARE STORED, NOT JUST REPORTED. A caller that ignores the response
would otherwise leave no trace of what did not get in, and "the Atlas does
not have that match" would stay a mystery instead of being a query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from atlas.intake.contract import FieldError, Verdict, validate

Door = Literal["api", "cli"]


@dataclass(frozen=True)
class LineResult:
    """What happened to one submitted record."""

    index: int
    accepted: bool
    uid: str | None
    #: True when the uid already existed — the record was updated, not added.
    replaced: bool
    errors: tuple[FieldError, ...]
    #: How the record identified itself, for a human scanning the report.
    label: str
    #: Blocks the composition still lacks. Non-empty means the contribution
    #: was stored and the match was NOT derived — it is waiting for another
    #: source, and this names exactly what to go find.
    missing_blocks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "accepted": self.accepted,
            "uid": self.uid,
            "replaced": self.replaced,
            "label": self.label,
            "missing_blocks": list(self.missing_blocks),
            "errors": [{"field": e.field, "reason": e.reason} for e in self.errors],
        }


@dataclass
class IngestReport:
    submitted: int = 0
    accepted: int = 0
    added: int = 0
    replaced: int = 0
    rejected: int = 0
    #: Aceitas, gravadas, e ainda não são partidas — falta bloco que outra
    #: fonte precisa trazer. Nem `added` nem `replaced`, porque nenhuma das
    #: duas aconteceu; sem esta linha o relatório diria "aceito, delta 0",
    #: que é o que uma reingestão de algo já existente também diz.
    pending: int = 0
    #: Matches held by the Atlas before and after this batch. The difference
    #: is the only honest answer to "did it work".
    total_before: int = 0
    total_after: int = 0
    lines: list[LineResult] = field(default_factory=list)
    #: field -> how many records failed on it. Turns 400 refusals into one
    #: sentence about what is wrong with the file.
    by_field: dict[str, int] = field(default_factory=dict)
    #: bloco -> quantas composições estão esperando por ele. Diz qual fonte
    #: buscar em seguida, em vez de deixar isso para inspeção linha a linha.
    missing_blocks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "accepted": self.accepted,
            "added": self.added,
            "replaced": self.replaced,
            "pending": self.pending,
            "rejected": self.rejected,
            "total_before": self.total_before,
            "total_after": self.total_after,
            "delta": self.total_after - self.total_before,
            "by_field": dict(
                sorted(self.by_field.items(), key=lambda kv: -kv[1])
            ),
            "missing_blocks": dict(
                sorted(self.missing_blocks.items(), key=lambda kv: -kv[1])
            ),
            "lines": [line.as_dict() for line in self.lines],
        }


def _label(payload: Any) -> str:
    """Enough to find the record in the file the operator submitted.

    Best effort on purpose: a record refused for having no identity still
    has to be findable, so this reads whatever is there rather than
    requiring the fields to be valid.
    """
    if not isinstance(payload, dict):
        return "(não é um objeto)"
    identity = payload.get("identity")
    if isinstance(identity, dict):
        home = identity.get("home_club_id") or "?"
        away = identity.get("away_club_id") or "?"
        when = str(identity.get("kickoff_utc") or "?")[:10]
        comp = identity.get("competition") or "?"
        return f"{comp} {when} {home} x {away}"
    provenance = payload.get("provenance")
    if isinstance(provenance, dict) and provenance.get("source_match_id"):
        return f"(sem identidade) {provenance['source_match_id']}"
    return "(sem identidade)"


async def ingest(
    payloads: Iterable[Any],
    repository,
    *,
    via: Door,
    by: str,
    registry: frozenset[str] | None = None,
) -> IngestReport:
    """Validate a batch, store what passes, record what does not.

    ONE TRANSACTION PER RECORD, NOT PER BATCH. A file of 5.000 matches with
    one bad line should land 4.999, not zero — the operator can fix one line
    far more easily than they can work out which of 5.000 broke an all-or-
    nothing load. The report is what makes that safe: nothing is lost
    quietly, because the refusal is both returned and stored.
    """
    report = IngestReport()
    report.total_before = await repository.count()

    for index, payload in enumerate(payloads):
        report.submitted += 1
        label = _label(payload)

        if isinstance(payload, MalformedLine):
            errors = (FieldError("(linha)", f"não é JSON válido — {payload.reason}"),)
            report.rejected += 1
            report.by_field["(linha)"] = report.by_field.get("(linha)", 0) + 1
            await repository.record_rejection(
                payload={"raw": payload.raw}, errors=errors, via=via, by=by
            )
            report.lines.append(
                LineResult(index, False, None, False, errors, "(linha ilegível)")
            )
            continue

        verdict: Verdict = validate(payload, registry=registry)

        if not verdict.accepted:
            report.rejected += 1
            for error in verdict.errors:
                report.by_field[error.field] = report.by_field.get(error.field, 0) + 1
            await repository.record_rejection(
                payload=payload, errors=verdict.errors, via=via, by=by
            )
            report.lines.append(
                LineResult(index, False, None, False, verdict.errors, label)
            )
            continue

        record = verdict.record
        gravacao = await repository.upsert(record, via=via, by=by)
        report.accepted += 1
        if gravacao.faltando:
            # Aceita e guardada, mas ainda não é uma partida. Contada à parte
            # de `added`/`replaced`: as duas dizem que `match_record` mudou, e
            # aqui ela não mudou.
            report.pending += 1
            for bloco in gravacao.faltando:
                report.missing_blocks[bloco] = report.missing_blocks.get(bloco, 0) + 1
        elif gravacao.existia:
            report.replaced += 1
        else:
            report.added += 1
        report.lines.append(
            LineResult(
                index,
                True,
                record.uid,
                gravacao.existia,
                (),
                label,
                gravacao.faltando,
            )
        )

    report.total_after = await repository.count()
    return report


class SimulacaoRepository:
    """Valida tudo, grava nada. UMA implementação, usada pelas duas portas.

    Era duas — uma na rota HTTP, uma no CLI — e as duas tinham de mudar juntas
    toda vez que o repositório real mudasse de interface. Não mudaram: três
    vezes o repositório ganhou algo e um dos falsos ficou para trás. A última
    estourou na frente do operador, com `'bool' object has no attribute
    'faltando'`, porque `--simular` do CLI não tinha teste e a rota tinha.

    Duas cópias da mesma coisa não se mantêm sincronizadas por disciplina.
    """

    def __init__(self, total: int) -> None:
        self._total = total

    async def count(self) -> int:
        return self._total

    async def upsert(self, record, *, via: str, by: str):
        # Simular não compõe: que blocos faltariam depende do que as outras
        # fontes já gravaram, e responder isso exigiria ler a base que a
        # simulação promete não tocar. `faltando` vazio diz "esta contribuição
        # é válida", que é o que a simulação de fato apurou.
        from atlas.intake.repository import Gravacao

        return Gravacao(existia=False)

    async def record_rejection(self, **_: object) -> None:
        # Uma recusa simulada não é uma recusa: gravá-la encheria a trilha de
        # auditoria com tentativas que ninguém chegou a fazer.
        return None


@dataclass(frozen=True)
class MalformedLine:
    """A line that is not JSON at all.

    Carried through as a value rather than raised, so a file whose line 300
    is truncated still reports on the other 4.999 — and names line 300. It is
    a distinct type, not a dict with a magic key, so `ingest` can refuse it
    with "não é JSON válido" instead of listing every required field as
    missing, which is what a sentinel dict would have produced.
    """

    raw: str
    reason: str


def read_jsonl(text: str) -> list[Any]:
    """Parse JSONL. Broken lines come back as `MalformedLine`."""
    records: list[Any] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            records.append(MalformedLine(raw=raw[:200], reason=str(exc)))
    return records


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
