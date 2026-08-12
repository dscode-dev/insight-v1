"""Where accepted matches — and refused ones — are written.

Backed by the same async session factory every other Atlas repository uses.
Raw SQL rather than an ORM model here on purpose: the row is mostly one
JSONB document plus projections of it, and a mapped class would invite
someone to add a column and forget the document, which is the copy the
audit depends on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.intake.composition import Contribuicao, compor, exigencia, perfil_de
from atlas.intake.contract import FieldError, MatchRecord


@dataclass(frozen=True)
class Gravacao:
    """O que a escrita de uma contribuição produziu.

    Três desfechos, não dois. Antes bastava "existia ou não", porque toda
    contribuição virava uma partida. Com composição existe um terceiro caso —
    contribuição gravada, partida ainda incompleta — e ele precisa de nome
    próprio: sem isso o relatório diria "aceito, delta 0", que é exatamente o
    que uma reingestão de algo já existente também diz.
    """

    existia: bool
    #: Blocos que a composição ainda não tem. Vazio quando a partida foi
    #: derivada. É a lista do que procurar em outra fonte.
    faltando: tuple[str, ...] = ()

    @property
    def derivou(self) -> bool:
        return not self.faltando

#: O que ESTA fonte disse. Reingerir a mesma fonte substitui a contribuição
#: dela e só ela — nunca o que as outras trouxeram.
_CONTRIBUICAO = text(
    """
    INSERT INTO atlas.match_contribution (
        uid, source, profile, document, competition, season, kickoff_utc,
        ingested_via, ingested_by
    ) VALUES (
        :uid, :source, :profile, CAST(:document AS JSONB), :competition,
        :season, :kickoff, :ingested_via, :ingested_by
    )
    ON CONFLICT (uid, source) DO UPDATE SET
        profile      = EXCLUDED.profile,
        document     = EXCLUDED.document,
        ingested_via = EXCLUDED.ingested_via,
        ingested_by  = EXCLUDED.ingested_by,
        updated_at   = now()
    """
)

_CONFLITO = text(
    """
    INSERT INTO atlas.match_conflict (
        uid, field, winning_source, winning_value, losing_source, losing_value
    ) VALUES (
        :uid, :field, :winning_source, :winning_value,
        :losing_source, :losing_value
    )
    """
)

_UPSERT = text(
    """
    INSERT INTO atlas.match_record (
        uid, schema_version, competition, season,
        home_club_id, away_club_id, kickoff_utc,
        home_goals, away_goals,
        source, source_match_id, ingested_via, ingested_by, document,
        contributing_sources
    ) VALUES (
        :uid, :schema_version, :competition, :season,
        :home_club_id, :away_club_id, :kickoff_utc,
        :home_goals, :away_goals,
        :source, :source_match_id, :ingested_via, :ingested_by,
        CAST(:document AS JSONB), :contributing_sources
    )
    ON CONFLICT (uid) DO UPDATE SET
        schema_version  = EXCLUDED.schema_version,
        competition     = EXCLUDED.competition,
        season          = EXCLUDED.season,
        home_club_id    = EXCLUDED.home_club_id,
        away_club_id    = EXCLUDED.away_club_id,
        kickoff_utc     = EXCLUDED.kickoff_utc,
        home_goals      = EXCLUDED.home_goals,
        away_goals      = EXCLUDED.away_goals,
        source          = EXCLUDED.source,
        source_match_id = EXCLUDED.source_match_id,
        ingested_via    = EXCLUDED.ingested_via,
        ingested_by     = EXCLUDED.ingested_by,
        updated_at      = now(),
        document        = EXCLUDED.document,
        contributing_sources = EXCLUDED.contributing_sources
    """
)

_REJECT = text(
    """
    INSERT INTO atlas.match_rejection (
        ingested_via, ingested_by, competition, season, source_match_id,
        errors, document
    ) VALUES (
        :ingested_via, :ingested_by, :competition, :season, :source_match_id,
        CAST(:errors AS JSONB), CAST(:document AS JSONB)
    )
    """
)


class IntakeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def count(self) -> int:
        async with self._sf() as session:
            result = await session.execute(
                text("SELECT count(*) FROM atlas.match_record")
            )
            return int(result.scalar_one())

    async def upsert(self, record: MatchRecord, *, via: str, by: str) -> Gravacao:
        """Grava a contribuição desta fonte e recompõe a partida.

        SUBSTITUIU A ESCRITA DIRETA. Antes, `match_record` era escrita com
        `document = EXCLUDED.document`: a segunda fonte trocava o documento
        inteiro e apagava o bloco que a primeira trouxe — sem erro, com a
        linha continuando a parecer completa. Agora o que se grava é a
        contribuição de cada fonte, e a partida é derivada da composição.

        Devolve o que aconteceu: se a partida já existia, e que blocos ainda
        faltam para que a composição possa ser derivada.
        """
        composicao, existia = await self._contribuir(record, via=via, by=by)
        exigidos = exigencia(record.identity.competition)
        if composicao is None:
            return Gravacao(existia, exigidos)

        faltando = tuple(b for b in exigidos if b not in composicao.perfil)

        # O CONTRATO DA PARTIDA, que não é o da contribuição. Uma fonte pode
        # trazer só o que tem; `match_record` continua exigindo os quatro
        # blocos, porque é dela que sai o vetor — e meia partida vetorizada
        # responderia consultas com uma dimensão inventada em vez de ausente.
        # A composição incompleta fica em `match_contribution` esperando a
        # peça que falta, e uma ingestão futura a completa sem nada se perder.
        if not faltando:
            await self._gravar_composicao(record, composicao, via=via, by=by)
        await self._gravar_conflitos(record.uid, composicao)
        return Gravacao(existia, faltando)

    async def _contribuir(self, record: MatchRecord, *, via: str, by: str):
        """Grava o que esta fonte disse e devolve a composição de todas."""
        identity = record.identity
        documento = json.loads(record.model_dump_json())
        async with self._sf() as session:
            anterior = await session.execute(
                text("SELECT 1 FROM atlas.match_record WHERE uid = :uid"),
                {"uid": record.uid},
            )
            existia = anterior.first() is not None

            await session.execute(
                _CONTRIBUICAO,
                {
                    "uid": record.uid,
                    "source": record.provenance.source,
                    "profile": ",".join(perfil_de(documento)),
                    "document": record.model_dump_json(),
                    "competition": identity.competition,
                    "season": identity.season,
                    "kickoff": identity.kickoff_utc,
                    "ingested_via": via,
                    "ingested_by": by,
                },
            )
            await session.commit()

            linhas = await session.execute(
                text(
                    "SELECT source, profile, document "
                    "FROM atlas.match_contribution WHERE uid = :uid"
                ),
                {"uid": record.uid},
            )
            contribuicoes = [
                Contribuicao(
                    source=str(linha[0]),
                    profile=tuple(str(linha[1]).split(",")) if linha[1] else (),
                    document=linha[2],
                )
                for linha in linhas.fetchall()
            ]
        return compor(contribuicoes), existia

    async def _gravar_composicao(
        self, record: MatchRecord, composicao, *, via: str, by: str
    ) -> None:
        documento = composicao.document
        identidade = documento["identity"]
        resultado = documento["result"]
        procedencia = documento["provenance"]
        async with self._sf() as session:
            await session.execute(
                _UPSERT,
                {
                    "uid": record.uid,
                    "schema_version": (
                        documento.get("schema_version") or record.schema_version
                    ),
                    "competition": identidade["competition"],
                    "season": identidade["season"],
                    "home_club_id": identidade["home_club_id"],
                    "away_club_id": identidade["away_club_id"],
                    # Do registro validado, não do JSON: aqui é um datetime,
                    # e o driver espera timestamptz.
                    "kickoff_utc": record.identity.kickoff_utc,
                    "home_goals": resultado["home_goals"],
                    "away_goals": resultado["away_goals"],
                    # A fonte da LINHA é a que venceu o núcleo — foi ela que
                    # respondeu quem jogou e quanto foi.
                    "source": composicao.origem.get("core", procedencia["source"]),
                    "source_match_id": procedencia["source_match_id"],
                    "ingested_via": via,
                    "ingested_by": by,
                    "document": json.dumps(documento, ensure_ascii=False, default=str),
                    "contributing_sources": len(composicao.fontes),
                },
            )
            await session.commit()

    async def _gravar_conflitos(self, uid: str, composicao) -> None:
        """Desacordo entre fontes fica registrado mesmo com a precedência já
        tendo decidido. Uma fonte que discorda com frequência é uma fonte
        para revisar, e sem registro isso só apareceria quando alguém
        desconfiasse de um número."""
        async with self._sf() as session:
            # Recompor invalida os conflitos anteriores: eles descrevem uma
            # composição que não existe mais.
            await session.execute(
                text("DELETE FROM atlas.match_conflict WHERE uid = :uid"),
                {"uid": uid},
            )
            for conflito in composicao.conflitos:
                await session.execute(
                    _CONFLITO,
                    {
                        "uid": uid,
                        "field": conflito.field,
                        "winning_source": conflito.winning_source,
                        "winning_value": str(conflito.winning_value)[:200],
                        "losing_source": conflito.losing_source,
                        "losing_value": str(conflito.losing_value)[:200],
                    },
                )
            await session.commit()

    async def conflitos_recentes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Desacordos entre fontes, do mais recente. É o que torna possível
        rever uma fonte antes de ela contaminar uma temporada inteira."""
        async with self._sf() as session:
            resultado = await session.execute(
                text(
                    "SELECT c.uid, c.field, c.winning_source, c.winning_value, "
                    "       c.losing_source, c.losing_value, c.detected_at, "
                    "       m.competition, m.season, m.home_club_id, m.away_club_id "
                    "  FROM atlas.match_conflict c "
                    "  LEFT JOIN atlas.match_record m ON m.uid = c.uid "
                    " ORDER BY c.detected_at DESC LIMIT :limit"
                ),
                {"limit": max(1, min(limit, 500))},
            )
            return [
                {
                    "uid": str(linha[0]),
                    "field": linha[1],
                    "winning_source": linha[2],
                    "winning_value": linha[3],
                    "losing_source": linha[4],
                    "losing_value": linha[5],
                    "detected_at": linha[6].isoformat(),
                    "competition": linha[7],
                    "season": linha[8],
                    "match": f"{linha[9]} x {linha[10]}" if linha[9] else None,
                }
                for linha in resultado.fetchall()
            ]

    async def record_rejection(
        self,
        *,
        payload: Any,
        errors: Sequence[FieldError],
        via: str,
        by: str,
    ) -> None:
        """Keep the refusal. A caller that ignores the response would
        otherwise leave no trace of what failed to get in."""
        identity = payload.get("identity") if isinstance(payload, dict) else None
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        async with self._sf() as session:
            await session.execute(
                _REJECT,
                {
                    "ingested_via": via,
                    "ingested_by": by,
                    "competition": _short(identity, "competition", 64),
                    "season": _short(identity, "season", 16),
                    "source_match_id": _short(provenance, "source_match_id", 128),
                    "errors": json.dumps(
                        [{"field": e.field, "reason": e.reason} for e in errors],
                        ensure_ascii=False,
                    ),
                    "document": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
            await session.commit()

    async def coverage(self) -> list[dict[str, Any]]:
        """Matches held, by competition and season. What the console shows."""
        async with self._sf() as session:
            result = await session.execute(
                text(
                    "SELECT competition, season, count(*) AS matches, "
                    "       min(kickoff_utc) AS first_match, "
                    "       max(kickoff_utc) AS last_match, "
                    "       count(DISTINCT source) AS sources "
                    "  FROM atlas.match_record "
                    " GROUP BY competition, season "
                    " ORDER BY competition, season"
                )
            )
            return [
                {
                    "competition": row[0],
                    "season": row[1],
                    "matches": int(row[2]),
                    "first_match": row[3].isoformat() if row[3] else None,
                    "last_match": row[4].isoformat() if row[4] else None,
                    "sources": int(row[5]),
                }
                for row in result.fetchall()
            ]

    async def recent_rejections(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(
                text(
                    "SELECT rejected_at, ingested_via, ingested_by, competition, "
                    "       season, source_match_id, errors "
                    "  FROM atlas.match_rejection "
                    " ORDER BY rejected_at DESC LIMIT :limit"
                ),
                {"limit": max(1, min(limit, 500))},
            )
            return [
                {
                    "rejected_at": row[0].isoformat(),
                    "via": row[1],
                    "by": row[2],
                    "competition": row[3],
                    "season": row[4],
                    "source_match_id": row[5],
                    "errors": row[6],
                }
                for row in result.fetchall()
            ]

    async def iter_documents(self) -> Iterable[dict[str, Any]]:
        """Every stored match, oldest kickoff first.

        The order is not cosmetic: the feature projection is walk-forward, so
        reading out of order would compute a rating from matches that had not
        happened yet.
        """
        async with self._sf() as session:
            result = await session.execute(
                text(
                    "SELECT document FROM atlas.match_record "
                    "ORDER BY kickoff_utc, uid"
                )
            )
            return [row[0] for row in result.fetchall()]


def _short(source: Any, key: str, limit: int) -> str | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if value is None:
        return None
    return str(value)[:limit]
