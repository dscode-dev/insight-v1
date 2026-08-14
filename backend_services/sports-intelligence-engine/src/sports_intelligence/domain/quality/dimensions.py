"""Qualidade histórica em seis eixos — e por que nenhum deles é «o score».

O QUE ESTE MÓDULO EXISTE PARA IMPEDIR. Um número só — `quality = 0.87` —
responde «confio?» e não responde «o que faço a respeito?», que é a única
pergunta operacional. Pior: ele deixa um eixo em 0,1 ser mascarado por cinco
em 0,95, e um fato de identidade duvidosa não fica bom por estar completo.

SEIS E NÃO QUATRO. O `DataQuality` do PR-00 tem quatro eixos e continua sendo
o contrato POR REGISTRO. A avaliação histórica precisa de dois que aquele não
tem, e a diferença é de propósito:

    integrity           as referências existem e apontam para coisas reais
    consistency         os fatos não se contradizem entre si
    completeness        os fatos ESPERADOS para este tipo de registro estão lá
    identity_confidence a identidade foi PROVADA, e com quanta força
    temporal_integrity  as datas fecham: janela, ordem, vínculo na data
    provenance_quality  dá para chegar do valor canônico ao byte bruto

`freshness` DO PR-00 NÃO ENTRA. Ele mede quanto o dado envelheceu, que é a
pergunta certa para o caminho ao vivo e a pergunta errada para um corpus
histórico: uma partida de 2019 não fica pior por ser de 2019. Confundir os
dois faria todo histórico antigo parecer degradado.

`integrity` E `provenance_quality` SÃO NOVOS porque o PR-04 é o primeiro que
promove dado a fato canônico. Antes disso, uma referência quebrada era um
problema de leitura; aqui ela seria um fato histórico apontando para uma
entidade que não existe — e ninguém descobriria depois, porque tudo continua
somando.

O ELO MAIS FRACO GOVERNA, e não a média (§83). É a mesma decisão do PR-00 e
pela mesma razão: média esconde blocker. A diferença é que aqui a política diz
QUAIS eixos são críticos, em vez de tratar os seis como iguais.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import ValidationError


class QualityDimension(StrEnum):
    """Os seis eixos. Nomeados porque são consultados por nome na política.

    UM `StrEnum` E NÃO ATRIBUTOS SOLTOS: a política precisa dizer «estes três
    são críticos» sem repetir os nomes como strings livres, e o relatório
    precisa iterá-los numa ordem estável.
    """

    INTEGRITY = "INTEGRITY"
    CONSISTENCY = "CONSISTENCY"
    COMPLETENESS = "COMPLETENESS"
    IDENTITY_CONFIDENCE = "IDENTITY_CONFIDENCE"
    TEMPORAL_INTEGRITY = "TEMPORAL_INTEGRITY"
    PROVENANCE_QUALITY = "PROVENANCE_QUALITY"


#: A ordem canônica dos eixos. Ela entra na impressão determinística do
#: manifesto, então mudá-la re-chaveia toda versão histórica já publicada.
DIMENSION_ORDER: Final[tuple[QualityDimension, ...]] = (
    QualityDimension.INTEGRITY,
    QualityDimension.CONSISTENCY,
    QualityDimension.COMPLETENESS,
    QualityDimension.IDENTITY_CONFIDENCE,
    QualityDimension.TEMPORAL_INTEGRITY,
    QualityDimension.PROVENANCE_QUALITY,
)


def _unidade(nome: str, valor: float) -> float:
    if not 0.0 <= valor <= 1.0:
        raise ValidationError(
            f"{nome} = {valor!r} fora de [0,1]: os eixos de qualidade são frações, "
            "e um valor fora da faixa costuma ser uma contagem que escapou"
        )
    return float(valor)


@final
@dataclass(frozen=True, slots=True)
class QualityVector:
    """Os seis eixos de um registro histórico avaliado.

    IMUTÁVEL, como tudo que vira evidência. Uma avaliação que pudesse ser
    ajustada depois seria indistinguível de uma avaliação inventada — e é
    justamente a auditabilidade que faz este PR existir.
    """

    integrity: float
    consistency: float
    completeness: float
    identity_confidence: float
    temporal_integrity: float
    provenance_quality: float

    def __post_init__(self) -> None:
        for dimensao in DIMENSION_ORDER:
            _unidade(dimensao.value.lower(), self[dimensao])

    def __getitem__(self, dimension: QualityDimension) -> float:
        return float(getattr(self, dimension.value.lower()))

    @classmethod
    def perfect(cls) -> Self:
        """Todos os eixos em 1,0. Existe para o teste e para o caso trivial.

        NÃO É O PADRÃO DE NENHUM CONSTRUTOR. Um default perfeito faria um
        avaliador esquecido produzir dado impecável por omissão, que é o pior
        tipo de erro: silencioso e favorável.
        """
        return cls(
            integrity=1.0,
            consistency=1.0,
            completeness=1.0,
            identity_confidence=1.0,
            temporal_integrity=1.0,
            provenance_quality=1.0,
        )

    def weakest(
        self, among: frozenset[QualityDimension] | None = None
    ) -> tuple[QualityDimension, float]:
        """O eixo mais fraco e o valor dele — o que governa a decisão (§83).

        `among` RESTRINGE AOS EIXOS QUE A POLÍTICA CONSIDERA CRÍTICOS. Sem
        essa restrição, uma completude baixa — que é cobertura disfarçada e
        raramente é blocker — derrubaria um registro cuja identidade e
        linhagem estão perfeitas.

        EMPATE RESOLVE PELA ORDEM CANÔNICA, e não pela ordem do `frozenset`:
        conjuntos não têm ordem, e sem o desempate o mesmo vetor apontaria
        eixos diferentes em execuções diferentes.
        """
        considerados = [d for d in DIMENSION_ORDER if among is None or d in among]
        if not considerados:
            raise ValidationError(
                "nenhuma dimensão a considerar: uma política sem eixos críticos "
                "não consegue reprovar nada, e uma avaliação que nunca reprova "
                "não é uma avaliação"
            )
        return min(((d, self[d]) for d in considerados), key=lambda p: (p[1], p[0].value))

    def as_canonical(self) -> dict[str, float]:
        """A forma determinística, para a impressão do manifesto."""
        return {d.value: round(self[d], 6) for d in DIMENSION_ORDER}

    def __str__(self) -> str:
        eixo, valor = self.weakest()
        return f"qualidade · elo mais fraco {eixo} = {valor:.2f}"
