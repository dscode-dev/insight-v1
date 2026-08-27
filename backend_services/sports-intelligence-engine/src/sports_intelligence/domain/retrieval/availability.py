"""Quais eixos um lado REALMENTE tem — a máscara, e o que ela recusa.

    Q = { i ∈ A : q_i utilizável }
    C = { i ∈ A : c_i utilizável }
    S = Q ∩ C

TRÊS CONDIÇÕES PARA «UTILIZÁVEL», E AS TRÊS SÃO NECESSÁRIAS:

    disponibilidade = AVAILABLE     a normalização afirma que o número existe
    valor presente                  ele está lá
    valor finito                    e é um número

FALHA FECHADA NA INCONSISTÊNCIA (§15). Uma célula que se declara `AVAILABLE` e
não traz valor — ou traz `NaN` — não é «um eixo ausente»: é o dataset
normalizado contradizendo a si mesmo, e o construtor de `NormalizedCell` o
proíbe na escrita (ADR-0040). Tratar isso como ausência esconderia um
invariante quebrado atrás de uma penalidade que parece normal, e a atrição
medida sairia inflada por um defeito de escrita.

    isto é diferente de `vector_for` do PR-06.1, e a diferença é deliberada.
    Lá a ausência e a inconsistência caem no mesmo `None`, porque o caso
    completo recusa o par de qualquer jeito e a distinção não mudava nada.
    Aqui ela muda: a inconsistência vira penalidade silenciosa se não parar.

A MÁSCARA É UMA TUPLA ORDENADA PELO PERFIL, e não um conjunto de nomes. A
ordem é a mesma da soma da distância, e é o que garante que a posição `i` da
máscara e a posição `i` do vetor falam do mesmo eixo. Um `set[str]` obrigaria
cada consumidor a reordenar, e a impressão passaria a depender da ordem de
iteração de um `dict`.

NADA DE VALOR CRU (§16). Se o valor normalizado não existe, o eixo está
ausente — ponto. Buscar o valor cru, o canônico, o do provedor ou o da linha
anterior traria um número de OUTRA grandeza para dentro de uma soma de
desvios robustos, e ele pareceria um vizinho próximo por acidente de escala.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Final

from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
)
from sports_intelligence.domain.shared.errors import DataQualityError

#: O motivo tipado da inconsistência entre máscara e valor.
AVAILABILITY_VALUE_INCONSISTENCY: Final[str] = "AVAILABILITY_VALUE_INCONSISTENCY"


class AvailabilityInconsistencyError(DataQualityError):
    """A célula declara `AVAILABLE` e não entrega um número finito.

    ELA É ESTRUTURAL, e não ausência. O dataset normalizado garante
    `AVAILABLE ⟺ valor finito presente` na escrita; uma linha que chega aqui
    violando isso foi escrita por um caminho que não é o do PR-05.5.2, ou foi
    corrompida depois — e as duas coisas param a recuperação em vez de virarem
    um eixo penalizado.
    """

    def __init__(self, *, owner: str, axis: str, availability: str, value: float | None) -> None:
        super().__init__(
            f"{AVAILABILITY_VALUE_INCONSISTENCY}: {owner} declara {availability} no "
            f"eixo {axis!r} e entrega {value!r}. O dataset normalizado garante que "
            "AVAILABLE implica número finito (ADR-0040); tratar isto como ausência "
            "esconderia um invariante quebrado atrás de uma penalidade normal",
            context={
                "availability": availability,
                "axis": axis,
                "owner": owner,
                "reason": AVAILABILITY_VALUE_INCONSISTENCY,
                "value": repr(value),
            },
        )
        self.axis = axis
        self.owner = owner

    @property
    def reason(self) -> str:
        return AVAILABILITY_VALUE_INCONSISTENCY


def availability_mask(
    *,
    feature_keys: Sequence[str],
    values: Mapping[str, float | None],
    availabilities: Mapping[str, str],
    owner: str,
) -> tuple[bool, ...]:
    """Quais eixos do perfil este lado tem, na ORDEM do perfil.

    `owner` É SÓ PARA A MENSAGEM — a chave da linha, para que a falha diga
    qual delas contradiz a si mesma em vez de «uma linha qualquer».
    """
    mascara: list[bool] = []
    for chave in feature_keys:
        declarada = availabilities.get(chave)
        valor = values.get(chave)
        disponivel = declarada == NormalizationAvailability.AVAILABLE.value
        if not disponivel:
            # UM VALOR SOBRANDO NUMA CÉLULA INDISPONÍVEL também é contradição,
            # e ele é o mais perigoso dos dois: o número está lá, e um leitor
            # distraído o usaria.
            if valor is not None:
                raise AvailabilityInconsistencyError(
                    owner=owner,
                    axis=chave,
                    availability=str(declarada),
                    value=valor,
                )
            mascara.append(False)
            continue
        if valor is None or not math.isfinite(valor):
            raise AvailabilityInconsistencyError(
                owner=owner,
                axis=chave,
                availability=NormalizationAvailability.AVAILABLE.value,
                value=valor,
            )
        mascara.append(True)
    return tuple(mascara)


def shared_mask(query: Sequence[bool], candidate: Sequence[bool]) -> tuple[bool, ...]:
    """`S = Q ∩ C`, posição a posição.

    OS DOIS LADOS PRECISAM SER DO MESMO PERFIL, e o `strict=True` do `zip` é a
    guarda: máscaras de tamanhos diferentes descrevem espaços diferentes, e
    intersectá-las produziria uma máscara curta que a soma percorreria sem
    reclamar.
    """
    return tuple(q and c for q, c in zip(query, candidate, strict=True))


def mask_text(mask: Sequence[bool]) -> str:
    """A máscara como texto determinístico — `1` presente, `0` ausente.

    ELA ENTRA NA IMPRESSÃO DA EVIDÊNCIA nesta forma. Um `list[bool]` em JSON
    canônico funcionaria; o texto é mais curto, é legível no relatório, e —
    principalmente — não depende de como o serializador escreve `true`.
    """
    return "".join("1" if bit else "0" for bit in mask)


def selected(feature_keys: Sequence[str], mask: Sequence[bool]) -> tuple[str, ...]:
    """Os nomes dos eixos marcados, na ordem do perfil."""
    return tuple(chave for chave, bit in zip(feature_keys, mask, strict=True) if bit)


def unselected(feature_keys: Sequence[str], mask: Sequence[bool]) -> tuple[str, ...]:
    """Os nomes dos eixos NÃO marcados, na ordem do perfil."""
    return tuple(chave for chave, bit in zip(feature_keys, mask, strict=True) if not bit)


def count(mask: Sequence[bool]) -> int:
    return sum(1 for bit in mask if bit)
