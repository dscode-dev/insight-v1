"""Do que o evento ao vivo sabe para o que o corpus histórico entende.

    evento do provedor  →  IdentidadeDaPartida  →  atlas.match_vector

O PROBLEMA, E ELE NÃO É DE MAPEAMENTO. Existem duas regras de identidade no
Atlas, e elas não podem concordar:

                      match_uid (corpus)          canonical_match_id (ao vivo)
    namespace         ...a71a5dee                 6f1c2d34...
    competição        slug: premier_league        UUID
    clubes            club_id: arsenal            nome normalizado
    tempo             dia UTC                     hora arredondada
    temporada         presente                    ausente

Não é um bug: as duas respondem perguntas diferentes. `canonical_match_id`
identifica uma partida AO VIVO entre provedores que a chamam de nomes
diferentes; `match_uid` identifica um REGISTRO histórico entre fontes que a
publicam com ids diferentes. Unificá-las exigiria mudar a cunhagem
compartilhada com o Hub em Go, que existe para os dois serviços concordarem.

ENTÃO A PONTE NÃO É ENTRE OS DOIS IDS — É PELOS CAMPOS. O evento ao vivo
chega com os nomes dos times e o instante do pontapé; o resolvedor de
identidade os recebe e os descarta ao cunhar o UUID. Este módulo os aproveita
antes disso e produz o que a consulta ao corpus precisa.

NADA AQUI ADIVINHA. A temporada não é derivada por regra — europeias
atravessam dois anos, sul-americanas cabem em um, e o futebol argentino mudou
de formato quase todo ano. Ela é PROCURADA: qual temporada desta competição
contém esta data, segundo as partidas que o Atlas já tem. Não achando,
devolve `None` com o motivo, em vez de um palpite que faria a consulta
responder sobre outro campeonato.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.intake.contract import known_clubs
from atlas.match_identity import match_uid_from


@dataclass(frozen=True)
class IdentidadeDaPartida:
    """O que a consulta ao corpus precisa, e nada além."""

    competition: str
    season: str
    home_club_id: str
    away_club_id: str
    kickoff_utc: datetime

    @property
    def uid(self) -> str:
        """O `match_uid` desta partida — a MESMA regra do corpus.

        Existe para que uma partida ao vivo que já esteja no histórico seja
        reconhecida como a mesma linha, e não como uma vizinha de si própria.
        """
        return match_uid_from(
            self.competition,
            self.season,
            self.home_club_id,
            self.away_club_id,
            self.kickoff_utc,
        )


@dataclass(frozen=True)
class Falha:
    """Por que a identidade não pôde ser montada.

    Um valor e não uma exceção: a sonda roda por tick, e o caminho ao vivo
    não deve cair porque um provedor mandou um nome novo. O campo `motivo`
    entra no log e diz o que consertar.
    """

    campo: str
    motivo: str

    def __str__(self) -> str:
        return f"{self.campo}: {self.motivo}"


class ResolvedorAoVivo:
    """Resolve a identidade usando o MESMO registro e a MESMA regra do corpus.

    Um segundo resolvedor de clubes aqui produziria um segundo entendimento
    de "que clube é este" — que é exatamente a classe de defeito que colocou
    352 partidas do Arsenal de Sarandí no histórico do Arsenal de Londres.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._apelidos: dict[str, str] | None = None

    async def _indice_de_apelidos(self) -> dict[str, str]:
        """Nome normalizado → club_id, do registro compartilhado.

        Só casamento EXATO sobre o nome normalizado. Sem fallback por
        subconjunto de tokens: foi ele que fez `Olimpo Bahia Blanca` virar o
        Bahia de Salvador, e no caminho ao vivo o erro seria pior — a partida
        seria descrita com o histórico de outro clube, em tempo real.
        """
        if self._apelidos is not None:
            return self._apelidos
        indice: dict[str, str] = {}
        for club_id in known_clubs():
            indice[_normalizar(club_id.replace("_", " "))] = club_id
        self._apelidos = indice
        return indice

    async def resolver(
        self,
        *,
        competition: str | None,
        home_name: str | None,
        away_name: str | None,
        kickoff: datetime | None,
    ) -> IdentidadeDaPartida | Falha:
        if not competition:
            return Falha("competition", "o evento não trouxe a competição")
        if not kickoff:
            return Falha("kickoff", "sem instante não há como achar a temporada")

        indice = await self._indice_de_apelidos()
        casa = indice.get(_normalizar(home_name or ""))
        fora = indice.get(_normalizar(away_name or ""))
        if casa is None:
            return Falha("home_club_id", f"clube não reconhecido: {home_name!r}")
        if fora is None:
            return Falha("away_club_id", f"clube não reconhecido: {away_name!r}")

        temporada = await self._temporada(competition, kickoff)
        if temporada is None:
            return Falha(
                "season",
                f"nenhuma temporada de {competition} no corpus contém "
                f"{kickoff.date().isoformat()}",
            )

        return IdentidadeDaPartida(
            competition=competition,
            season=temporada,
            home_club_id=casa,
            away_club_id=fora,
            kickoff_utc=kickoff,
        )

    async def _temporada(self, competition: str, kickoff: datetime) -> str | None:
        """Qual temporada desta competição contém esta data.

        PROCURADA, não derivada. Uma regra do tipo "julho a junho" acerta a
        Europa e erra o Brasil; uma do tipo "ano civil" faz o inverso. O
        corpus já sabe as janelas reais, então a pergunta é para ele.
        """
        async with self._sf() as sessao:
            linha = (
                await sessao.execute(
                    text(
                        """
                        SELECT season
                        FROM atlas.match_record
                        WHERE competition = :competicao
                        GROUP BY season
                        HAVING min(kickoff_utc) - interval '30 days' <= :quando
                           AND max(kickoff_utc) + interval '30 days' >= :quando
                        ORDER BY min(kickoff_utc) DESC
                        LIMIT 1
                        """
                    ),
                    {"competicao": competition, "quando": kickoff},
                )
            ).first()
        return str(linha[0]) if linha else None


def _normalizar(nome: str) -> str:
    """Minúsculas, sem acento, só alfanumérico.

    A mesma dobra que `atlas.identity.normalize` usa, para que os dois lados
    do caminho ao vivo comparem nomes do mesmo jeito.
    """
    import unicodedata

    decomposto = unicodedata.normalize("NFKD", (nome or "").strip().lower())
    return "".join(c for c in decomposto if c.isalnum() and ord(c) < 128)
