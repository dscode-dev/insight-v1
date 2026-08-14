"""A leitura de rótulos de temporada — sem adivinhar o que a fonte não disse.

QUATRO ESCRITAS PARA A MESMA COISA, e uma para coisas diferentes:

    2023/24     2023-24     2023-2024      a mesma temporada cruzada
    2024        a temporada de 2024 numa liga de ano civil
                OU 2023/24 numa fonte de liga cruzada
                OU 2024/25 noutra fonte da mesma liga

O ÚLTIMO CASO É O PROBLEMA INTEIRO (§15). `2024` sozinho não determina
temporada: depende da liga e da convenção do publicador. Resolvê-lo
universalmente para `2023/24` erraria o Brasileirão sempre; para `2024`,
erraria metade das fontes de Premier League.

A SAÍDA É NÃO DECIDIR AQUI. Este módulo devolve o que o rótulo PERMITE
concluir — um ano inicial, talvez um final, e se ele é ambíguo — e a decisão
sai da combinação com a convenção declarada pela fonte e com a data da
partida. Sem nenhuma das duas, o resolver manda para revisão.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.sources.mapping import SeasonConvention

#: `2023/24`, `2023-24`, `2023/2024`, `2023-2024`. O traço longo (U+2013)
#: entra escapado: fontes que exportam de planilha o produzem por
#: autocorreção, e recusar por causa dele seria recusar um rótulo válido.
_CRUZADA = re.compile(r"^(\d{4})\s*[/\u2013-]\s*(\d{2}|\d{4})$")
#: `2024`
_ANO = re.compile(r"^(\d{4})$")
#: `24/25` — ano de dois dígitos dos dois lados. Aceito e marcado como
#: incerto: `24` pode ser 1924 ou 2024, e a janela da temporada desempata.
_CURTA = re.compile(r"^(\d{2})\s*[/\u2013-]\s*(\d{2})$")

#: A partir de qual ano de dois dígitos assumimos o século 20. Fixado e não
#: relativo ao ano corrente: um limiar móvel faria o mesmo rótulo ser lido de
#: um jeito hoje e de outro em 2031 — e o reprocessamento deixaria de
#: reproduzir.
_CORTE_DE_SECULO: Final[int] = 50


@final
@dataclass(frozen=True, slots=True)
class SeasonHint:
    """O que um rótulo de temporada permite concluir. Nada além disso."""

    raw: str
    start_year: int | None
    end_year: int | None
    #: `True` quando o rótulo é um ano só e a convenção não foi declarada —
    #: ou seja, quando ele pode significar duas temporadas diferentes.
    ambiguous: bool
    #: `True` quando o rótulo não é reconhecível como temporada.
    unparseable: bool = False

    @property
    def is_split_year(self) -> bool:
        return self.end_year is not None and self.end_year != self.start_year

    def compatible_with(self, other: SeasonHint) -> bool:
        """Se os dois rótulos PODEM descrever a mesma temporada.

        DELIBERADAMENTE PERMISSIVA. Ela filtra candidatos impossíveis — anos
        que não se tocam —, e não decide. Decidir é da política, com a
        margem e o limiar; uma compatibilidade estrita aqui descartaria o
        candidato certo antes de ele ser pontuado.
        """
        if self.unparseable or other.unparseable:
            return False
        if self.start_year is None or other.start_year is None:
            return False
        anos_a = {self.start_year, self.end_year or self.start_year}
        anos_b = {other.start_year, other.end_year or other.start_year}
        return bool(anos_a & anos_b)

    def agreement_with(self, other: SeasonHint) -> float:
        """Quão bem os dois rótulos concordam, em [0,1].

            1,00   mesmo início e mesmo fim
            0,70   mesmo início, um deles sem fim declarado
            0,45   os anos se tocam, mas em posições diferentes
            0,00   incompatíveis
        """
        if not self.compatible_with(other):
            return 0.0
        if self.start_year == other.start_year and self.end_year == other.end_year:
            return 1.0
        if self.start_year == other.start_year:
            return 0.7
        return 0.45

    def __str__(self) -> str:
        if self.unparseable:
            return f"{self.raw!r} (irreconhecível)"
        faixa = (
            f"{self.start_year}/{self.end_year}" if self.is_split_year else str(self.start_year)
        )
        return f"{faixa}{' (ambíguo)' if self.ambiguous else ''}"


def parse_season_label(
    raw: str, *, convention: SeasonConvention = SeasonConvention.UNDECLARED
) -> SeasonHint:
    """Lê um rótulo de temporada. NÃO resolve para uma temporada.

    A CONVENÇÃO DECLARADA É O QUE DESAMBIGUA `2024`:

        CALENDAR_YEAR   `2024` é a temporada de 2024        (Brasileirão)
        SPLIT_YEAR      `2024` é 2024/25                    (Premier League)
        UNDECLARED      `2024` fica AMBÍGUO, e sobe assim

    O terceiro caso é o importante. Escolher um dos dois como default seria
    escolher errar metade das fontes em silêncio; marcar como ambíguo faz a
    data da partida — ou a fila de revisão — decidir.
    """
    texto = raw.strip()
    if not texto:
        return SeasonHint(
            raw=raw, start_year=None, end_year=None, ambiguous=False, unparseable=True
        )

    cruzada = _CRUZADA.match(texto)
    if cruzada:
        inicio = int(cruzada.group(1))
        bruto_fim = cruzada.group(2)
        fim = int(bruto_fim) if len(bruto_fim) == 4 else _completar_seculo(inicio, int(bruto_fim))
        return SeasonHint(raw=raw, start_year=inicio, end_year=fim, ambiguous=False)

    curta = _CURTA.match(texto)
    if curta:
        inicio = _expandir_ano(int(curta.group(1)))
        fim = _completar_seculo(inicio, int(curta.group(2)))
        return SeasonHint(raw=raw, start_year=inicio, end_year=fim, ambiguous=False)

    ano = _ANO.match(texto)
    if ano:
        valor = int(ano.group(1))
        if convention is SeasonConvention.CALENDAR_YEAR:
            return SeasonHint(raw=raw, start_year=valor, end_year=valor, ambiguous=False)
        if convention is SeasonConvention.SPLIT_YEAR:
            return SeasonHint(raw=raw, start_year=valor, end_year=valor + 1, ambiguous=False)
        # A FONTE NÃO DECLAROU. O rótulo fica com o ano e o fim em aberto, e
        # a marca de ambiguidade viaja até a política.
        return SeasonHint(raw=raw, start_year=valor, end_year=None, ambiguous=True)

    return SeasonHint(raw=raw, start_year=None, end_year=None, ambiguous=False, unparseable=True)


def _expandir_ano(dois_digitos: int) -> int:
    return 2000 + dois_digitos if dois_digitos < _CORTE_DE_SECULO else 1900 + dois_digitos


def _completar_seculo(inicio: int, dois_digitos: int) -> int:
    """`2023/24` → 2024; `1999/00` → 2000.

    A VIRADA DE SÉCULO É O CASO QUE UM `inicio // 100 * 100 + dois` ERRARIA:
    `1999/00` viraria 1900. Somar um ao século quando o fim é menor que o
    início resolve, e é a única forma de o rótulo fazer sentido.
    """
    candidato = (inicio // 100) * 100 + dois_digitos
    return candidato + 100 if candidato < inicio else candidato
