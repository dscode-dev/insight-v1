"""O catálogo fechado da V1, e por que ele é fechado.

CINCO COMPETIÇÕES, E SÓ ELAS. Um motor que aceita qualquer competição por
string aceita `"premier leage"` na segunda-feira e passa a ter duas Premier
Leagues, cada uma com metade do histórico. Nada falha; os números só ficam
errados — e a descoberta acontece quando alguém estranha um retrospecto.

O DOMÍNIO É EXTENSÍVEL, O CATÁLOGO ATIVO NÃO É. Acrescentar competição é
editar este arquivo, com o código estável escolhido de propósito. É trabalho
de minutos e é exatamente o ponto: a decisão fica registrada num diff em vez
de acontecer por um typo em runtime.

O CÓDIGO É A AUTORIDADE, NÃO O NOME. `Manchester City`, `Man City` e
`Manchester City FC` são a mesma coisa; `PREMIER_LEAGUE` é uma só grafia por
construção. Por isso a identidade canônica de uma competição é derivada do
CÓDIGO — que é imutável — e nunca do nome, que muda com patrocinador,
tradução e capricho de fonte.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId


class CompetitionCode(StrEnum):
    """As cinco da V1. Códigos estáveis: mudá-los re-chaveia o histórico."""

    BRA_SERIE_A = "BRA_SERIE_A"
    CONMEBOL_LIBERTADORES = "CONMEBOL_LIBERTADORES"
    PREMIER_LEAGUE = "PREMIER_LEAGUE"
    UEFA_CHAMPIONS_LEAGUE = "UEFA_CHAMPIONS_LEAGUE"
    LA_LIGA = "LA_LIGA"


class CompetitionType(StrEnum):
    """Liga nacional ou torneio continental de clubes.

    A distinção não é rótulo: ela governa a estrutura de fases. Uma liga tem
    rodadas e uma tabela; um torneio continental tem grupos, mata-mata e
    partidas em campo neutro.
    """

    DOMESTIC_LEAGUE = "DOMESTIC_LEAGUE"
    CONTINENTAL_CLUB = "CONTINENTAL_CLUB"

    @property
    def has_league_table(self) -> bool:
        return self is CompetitionType.DOMESTIC_LEAGUE


@final
@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """O que a V1 sabe sobre uma competição antes de qualquer dado chegar."""

    code: CompetitionCode
    name: str
    region: str
    competition_type: CompetitionType

    @property
    def id(self) -> CompetitionId:
        """A identidade canônica, derivada do CÓDIGO.

        Do código e não do nome: o nome de uma competição muda com
        patrocinador e tradução, e uma identidade derivada dele mudaria junto
        — re-chaveando todo o histórico sem que ninguém tenha decidido isso.
        """
        return CompetitionId.derive(self.code.value)


#: O catálogo. Fonte única — quem quiser saber quais competições existem
#: pergunta aqui, e não a um banco que pode estar desatualizado.
CATALOG: Final[dict[CompetitionCode, CatalogEntry]] = {
    entry.code: entry
    for entry in (
        CatalogEntry(
            code=CompetitionCode.BRA_SERIE_A,
            name="Campeonato Brasileiro Série A",
            region="BR",
            competition_type=CompetitionType.DOMESTIC_LEAGUE,
        ),
        CatalogEntry(
            code=CompetitionCode.CONMEBOL_LIBERTADORES,
            name="CONMEBOL Libertadores",
            region="CONMEBOL",
            competition_type=CompetitionType.CONTINENTAL_CLUB,
        ),
        CatalogEntry(
            code=CompetitionCode.PREMIER_LEAGUE,
            name="Premier League",
            region="EN",
            competition_type=CompetitionType.DOMESTIC_LEAGUE,
        ),
        CatalogEntry(
            code=CompetitionCode.UEFA_CHAMPIONS_LEAGUE,
            name="UEFA Champions League",
            region="UEFA",
            competition_type=CompetitionType.CONTINENTAL_CLUB,
        ),
        CatalogEntry(
            code=CompetitionCode.LA_LIGA,
            name="LaLiga",
            region="ES",
            competition_type=CompetitionType.DOMESTIC_LEAGUE,
        ),
    )
}


def resolve_code(raw: str) -> CompetitionCode:
    """Texto → código, ou recusa listando o que existe.

    O ÚNICO CAMINHO DE ENTRADA para competição vinda de fora. Recusa com a
    lista completa porque "competição inválida" manda quem lê adivinhar, e a
    lista resolve na mesma linha.
    """
    texto = raw.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return CompetitionCode(texto)
    except ValueError as erro:
        raise ValidationError(
            f"competição {raw!r} não está no catálogo da V1",
            context={"supported": sorted(c.value for c in CompetitionCode)},
        ) from erro


def entry_for(code: CompetitionCode) -> CatalogEntry:
    return CATALOG[code]
