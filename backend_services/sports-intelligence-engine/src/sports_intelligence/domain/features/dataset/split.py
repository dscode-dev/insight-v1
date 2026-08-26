"""A divisão do dataset — temporal, atômica por partida, e declarada.

O DEFEITO QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§40 ao §47). A divisão óbvia é
sortear linhas: 80% para uma metade, 20% para a outra. Sobre um dataset de
snapshots ela produz um vazamento perfeito e invisível:

    o minuto 62 do jogo X cai em REFERENCE
    o minuto 63 do MESMO jogo cai em EVALUATION

As duas linhas descrevem quase o mesmo estado. A avaliação passa a medir a
capacidade de reencontrar um vizinho que é literalmente o mesmo jogo um minuto
depois — e o número que sai disso é excelente e não significa nada.

DUAS REGRAS, E AS DUAS SÃO NECESSÁRIAS:

    ATÔMICA POR PARTIDA   todas as 91 linhas de uma partida na mesma metade
    TEMPORAL              a fronteira é um instante, e não uma proporção

A atômica sozinha não basta: dois jogos da mesma rodada, um em cada metade,
ainda compartilham contexto de calendário e mercado formado com a mesma
informação. A temporal sozinha não basta: sem atomicidade, um jogo que cruza a
meia-noite da fronteira teria minutos dos dois lados.

A FRONTEIRA É DECLARADA PELO OPERADOR, e não derivada de percentil (§45). Um
percentil faz a fronteira MUDAR quando o corpus cresce — e dois datasets
«80/20» construídos com um mês de diferença passariam a ter fronteiras
diferentes sob o mesmo nome. O instante é o que torna a divisão reproduzível.

    REFERENCE    kickoff <  reference_end_exclusive
    EVALUATION   kickoff >= reference_end_exclusive

`REFERENCE` E NÃO `TRAIN` (§43). Nada é treinado aqui: a metade de referência é
a população que o motor consulta — a base de vizinhos, e a base sobre a qual
escalas serão ajustadas num PR futuro. `train` traria consigo a expectativa de
gradiente, época e validação, e nenhuma delas existe.

NÃO EXISTE `VALIDATION` NEM `TEST`. Uma terceira metade exige uma segunda
fronteira e uma decisão sobre o que ela serve — e as duas seriam inventadas
aqui sem que ninguém precisasse delas ainda.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Self, final

from sports_intelligence.domain.shared.canonical import canonical_json, instant_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant, instant

#: O nome da política. Ele carrega as duas propriedades que a definem, porque
#: são elas que alguém precisa contestar para mudá-la.
TEMPORAL_MATCH_ATOMIC_SPLIT_V1: Final[str] = "TEMPORAL_MATCH_ATOMIC_SPLIT_V1"


@final
class DatasetSplit(StrEnum):
    """A metade a que uma partida — e portanto todas as linhas dela — pertence."""

    #: A população consultável. Vizinhos, e a base de ajuste futuro de escala.
    REFERENCE = "REFERENCE"
    #: O conjunto reservado. Nada é ajustado sobre ele, por definição.
    EVALUATION = "EVALUATION"

    @property
    def is_fittable(self) -> bool:
        """Se esta metade pode alimentar ajuste de escala (PR-05.5.2).

        A PERGUNTA JÁ TEM RESPOSTA AQUI para que o PR que ajusta normalizador
        não precise reinventá-la — e para que a resposta seja a mesma nos dois
        lugares onde ela importa.
        """
        return self is DatasetSplit.REFERENCE


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetSplitPolicy:
    """A fronteira temporal, versionada e impressa.

    ELA NÃO SORTEIA NADA. Não há semente, não há proporção, e o tipo não tem
    onde guardá-las — o que torna a propriedade estrutural em vez de
    disciplinar.
    """

    reference_end_exclusive: Instant
    name: str = TEMPORAL_MATCH_ATOMIC_SPLIT_V1
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de divisão sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de divisão inválida: {self.version}")
        if self.reference_end_exclusive.tzinfo is None:
            raise ValidationError(
                "fronteira de divisão sem fuso: «01/06 às 00:00» é um instante "
                "diferente em cada fuso, e a divisão mudaria conforme onde o build "
                "rodasse"
            )

    def assign(self, *, kickoff: Instant) -> DatasetSplit:
        """A metade daquela partida. A DECISÃO É POR PARTIDA, nunca por linha.

        A assinatura é o que sustenta a atomicidade: quem recebe um `kickoff` e
        devolve uma metade não consegue dar respostas diferentes para dois
        minutos do mesmo jogo.
        """
        if kickoff.tzinfo is None:
            raise ValidationError(
                "pontapé sem fuso na divisão: a comparação com a fronteira seria "
                "entre um instante e uma leitura local dele"
            )
        if kickoff < self.reference_end_exclusive:
            return DatasetSplit.REFERENCE
        return DatasetSplit.EVALUATION

    def as_canonical(self) -> dict[str, object]:
        return {
            "boundary_is_exclusive": True,
            "name": self.name,
            "reference_end_exclusive": instant_text(self.reference_end_exclusive),
            "splits": [s.value for s in DatasetSplit],
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @classmethod
    def from_canonical(cls, forma: Mapping[str, Any]) -> Self:
        """A política de volta, da forma canônica que a versão guardou.

        A FRONTEIRA É O MOTIVO. Ela não tem padrão nenhum — é declarada pelo
        operador —, então reconstruir por nome e versão produziria uma política
        sem fronteira, que é uma política sem divisão.
        """
        from datetime import datetime

        momento = datetime.fromisoformat(str(forma["reference_end_exclusive"]))
        return cls(
            reference_end_exclusive=instant(momento),
            name=str(forma["name"]),
            version=int(forma["version"]),
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} (< {instant_text(self.reference_end_exclusive)})"


@final
@dataclass(frozen=True, slots=True)
class SplitCounts:
    """Quantas partidas e quantas linhas caíram de cada lado.

    ELAS SÃO CONTADAS, NUNCA ESTIMADAS. Um dataset cuja avaliação ficou vazia
    porque a fronteira caiu depois do último jogo é um erro que precisa ser
    visível no manifesto, e não uma proporção plausível calculada de antemão.
    """

    reference_matches: int = 0
    evaluation_matches: int = 0
    reference_rows: int = 0
    evaluation_rows: int = 0

    def with_match(self, split: DatasetSplit, *, rows: int) -> SplitCounts:
        if split is DatasetSplit.REFERENCE:
            return SplitCounts(
                reference_matches=self.reference_matches + 1,
                evaluation_matches=self.evaluation_matches,
                reference_rows=self.reference_rows + rows,
                evaluation_rows=self.evaluation_rows,
            )
        return SplitCounts(
            reference_matches=self.reference_matches,
            evaluation_matches=self.evaluation_matches + 1,
            reference_rows=self.reference_rows,
            evaluation_rows=self.evaluation_rows + rows,
        )

    @property
    def matches(self) -> int:
        return self.reference_matches + self.evaluation_matches

    @property
    def rows(self) -> int:
        return self.reference_rows + self.evaluation_rows

    def as_canonical(self) -> dict[str, object]:
        return {
            "evaluation_matches": self.evaluation_matches,
            "evaluation_rows": self.evaluation_rows,
            "reference_matches": self.reference_matches,
            "reference_rows": self.reference_rows,
        }
