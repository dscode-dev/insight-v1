"""Quanto vale uma lente NESTA competição — medido, gravado, e lido de volta.

O NÚMERO QUE VIAJA EM TODA RESPOSTA. O Atlas devolve descrições, e uma
descrição que descreve tem exatamente a mesma forma de uma que não descreve.
A única coisa que as separa é a medida: "os vizinhos desta lente terminaram
como esta partida X pontos acima da taxa base". Sem ela, quem lê não tem como
saber; com ela errada, é pior, porque agora acredita.

POR QUE POR COMPETIÇÃO. Os números eram um por lente, escritos à mão. Sobre
o corpus de 15.628 partidas isso deixou de ser escrevível:

    lente             Europa    Brasileirão   Argentina
    resultado         +10,9%       -4,8%        +0,9%
    desempenho_time    +7,2%       -0,8%        -0,8%
    gols               +5,6%       -4,1%        -4,5%

"+10,9%" mente sobre o Brasileirão; a média do corpus mente sobre a Premier
League. A validade nunca foi propriedade da lente — é propriedade da lente
NAQUELE corpus, e o corpus tem competições diferentes dentro.

AUSÊNCIA DE MEDIDA É UM ESTADO. Competição não medida faz a resposta dizer
isso, com todas as letras. Cair para um número global seria o mesmo defeito
com um passo a mais.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Abaixo disto a medida existe mas não sustenta afirmação nenhuma — é a
#: mesma ideia do mínimo de vizinhos, um nível acima.
MINIMO_AVALIADAS = 100


@dataclass(frozen=True)
class Medida:
    """O que a régua apurou sobre uma lente numa competição."""

    lente: str
    competicao: str
    concordancia: float
    taxa_base: float
    ganho: float
    margem: float
    avaliadas: int
    corpus: int
    medida_em: datetime
    versao_espaco: str

    @property
    def suficiente(self) -> bool:
        return self.avaliadas >= MINIMO_AVALIADAS

    @property
    def conclusiva(self) -> bool:
        """O ganho sai da margem de 95%?

        Amostra pequena demais nunca é conclusiva, por mais extremo que o
        ganho pareça — a margem já cresce com ela, e isto fecha a borda.
        """
        return self.suficiente and abs(self.ganho) > self.margem

    @property
    def pior_que_a_base(self) -> bool:
        """Conclusivamente PIOR que responder o desfecho mais comum.

        Não é o mesmo que "não demonstrada". Uma lente aqui está
        ativamente descrevendo errado, e a resposta não pode apresentá-la
        como descrição de desfecho.
        """
        return self.conclusiva and self.ganho < 0

    @property
    def descreve_desfecho(self) -> bool:
        return self.conclusiva and self.ganho > 0

    @property
    def leitura(self) -> str:
        """A frase, GERADA dos números.

        Escrita à mão ela envelhece separada deles: os textos antigos ainda
        diziam "a lente mais forte das cinco" depois de a lente virar
        negativa. Gerada, não tem como divergir.
        """
        pontos = abs(self.ganho) * 100
        base = f"{self.taxa_base:.1%}".replace(".", ",")
        onde = f"em {self.competicao}, sobre {self.avaliadas} consultas"

        if not self.suficiente:
            return (
                f"{onde}: amostra pequena demais para afirmar qualquer coisa "
                f"(mínimo {MINIMO_AVALIADAS})"
            )
        if not self.conclusiva:
            return (
                f"{onde}: a diferença para a taxa base ({base}) cabe dentro da "
                f"margem de erro — esta lente NÃO foi demonstrada aqui, nem a "
                f"favor nem contra"
            )
        if self.ganho < 0:
            return (
                f"{onde}: a vizinhança desta lente concorda com o desfecho "
                f"{pontos:.1f} pontos ABAIXO de simplesmente responder o "
                f"resultado mais comum ({base}) — ela descreve pior que o "
                f"palpite trivial, e a descrição de desfecho fica retida"
            ).replace(".", ",", 1)
        return (
            f"{onde}: a vizinhança desta lente concorda com o desfecho "
            f"{pontos:.1f} pontos acima de responder o resultado mais comum "
            f"({base})"
        ).replace(".", ",", 1)

    def as_dict(self) -> dict:
        return {
            "competicao": self.competicao,
            "ganho": round(self.ganho, 4),
            "margem": round(self.margem, 4),
            "taxa_base": round(self.taxa_base, 4),
            "concordancia": round(self.concordancia, 4),
            "avaliadas": self.avaliadas,
            "corpus": self.corpus,
            "conclusiva": self.conclusiva,
            "descreve_desfecho": self.descreve_desfecho,
            "pior_que_a_base": self.pior_que_a_base,
            "medida_em": self.medida_em.isoformat(),
            "versao_espaco": self.versao_espaco,
            "leitura": self.leitura,
        }


def nao_medida(lente: str, competicao: str) -> dict:
    """A resposta quando não existe medida para esta competição.

    Um bloco com a mesma forma do medido, dizendo que não há medida — e não
    a AUSÊNCIA do bloco, que quem consome leria como "sem ressalvas".
    """
    return {
        "competicao": competicao,
        "ganho": None,
        "margem": None,
        "conclusiva": False,
        "descreve_desfecho": False,
        "pior_que_a_base": False,
        "leitura": (
            f"a lente '{lente}' nunca foi medida em {competicao}. A descrição "
            "abaixo é da vizinhança encontrada, e não há nada apurado sobre "
            "ela descrever ou não o que costuma acontecer nesta competição"
        ),
    }
