"""O espaço vetorial: como um conjunto de features vira um vetor comparável.

UMA VERSÃO SÓ. `atlas-memory-embedding-v1` (32 dims) e `-v2` (37) conviviam,
e nada dizia qual era a boa. Aqui existe uma, `atlas.vector.v1`, e trocá-la é
reconstruir tudo — o que é honesto, porque um vetor codificado com regras
diferentes não é comparável com outro por definição.

PADRONIZAR É O CONSERTO MEDIDO. As duas versões antigas guardavam todo
componente em [0, 1] mais um termo de viés fixo, o que põe cada vetor no
mesmo octante positivo: o ângulo entre dois deles já nasce pequeno e o
cosseno não tem para onde se espalhar. Medido sobre os 7.261 vetores de
produção, dois jogos sorteados ao acaso davam 0,807 de similaridade e os 25
vizinhos mais próximos cabiam numa faixa de 0,008. Centrando cada dimensão, a
mediana dos pares aleatórios foi para ~0 e a dispersão triplicou.

POR QUE OS PARÂMETROS SÃO GRAVADOS, E NÃO RECALCULADOS. Padronizar exige a
média e o desvio DO CORPUS. Uma consulta ao vivo precisa das mesmas duas
constantes, ou o vetor da consulta cai num espaço diferente do dos vetores
guardados e a similaridade compara coisas que não estão na mesma régua — sem
erro em lugar nenhum, com números plausíveis. Por isso o espaço é um artefato
persistido, com data e contagem, e não uma conta refeita a cada chamada.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import Sequence

from atlas.vector.features import NOMES

VERSAO = "atlas.vector.v1"


@dataclass(frozen=True)
class EspacoVetorial:
    """Média e desvio por dimensão, mais de onde vieram."""

    versao: str
    dimensoes: tuple[str, ...]
    medias: tuple[float, ...]
    desvios: tuple[float, ...]
    partidas: int

    @property
    def tamanho(self) -> int:
        return len(self.dimensoes)

    def transformar(self, features: dict[str, float]) -> tuple[float, ...]:
        """Um conjunto de features vira um vetor unitário neste espaço.

        Uma feature ausente entra como a MÉDIA do corpus, que padroniza para
        zero — ou seja, "não informa nada", que é a única leitura honesta de
        um dado que não existe. Entrar como 0.0 cru diria "valor baixo", que
        é uma afirmação que ninguém fez.
        """
        bruto = [
            (features.get(nome, self.medias[indice]) - self.medias[indice])
            / self.desvios[indice]
            for indice, nome in enumerate(self.dimensoes)
        ]
        return _unitario(bruto)

    def as_dict(self) -> dict:
        return {
            "versao": self.versao,
            "dimensoes": list(self.dimensoes),
            "medias": [round(v, 8) for v in self.medias],
            "desvios": [round(v, 8) for v in self.desvios],
            "partidas": self.partidas,
        }

    @staticmethod
    def from_dict(dados: dict) -> EspacoVetorial:
        return EspacoVetorial(
            versao=str(dados["versao"]),
            dimensoes=tuple(dados["dimensoes"]),
            medias=tuple(float(v) for v in dados["medias"]),
            desvios=tuple(float(v) for v in dados["desvios"]),
            partidas=int(dados["partidas"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False)


def ajustar(
    conjuntos: Sequence[dict[str, float]], *, dimensoes: tuple[str, ...] = NOMES
) -> EspacoVetorial:
    """Calcula média e desvio de cada dimensão sobre o corpus inteiro."""
    if not conjuntos:
        raise ValueError("corpus vazio: não há de que tirar média e desvio")

    medias: list[float] = []
    desvios: list[float] = []
    for nome in dimensoes:
        # SÓ AS PARTIDAS QUE TÊM A DIMENSÃO. Contar a ausência como 0,0 —
        # como esta função fazia — puxaria a média para baixo e inflaria o
        # desvio na proporção de quanto falta: com 11.830 partidas
        # sul-americanas sem estatística e 3.801 europeias com ela, a régua
        # de `home_shots_rate` seria calculada sobre três quartos de zeros
        # inventados, e as partidas que DE FATO têm chutes seriam
        # padronizadas contra ela.
        coluna = [
            float(item[nome])
            for item in conjuntos
            if item.get(nome) is not None
        ]
        if not coluna:
            # Ninguém tem esta dimensão. Média 0 e desvio 1 a deixam
            # exatamente neutra, que é o que ela vale — e a régua a reporta
            # como constante, então ela aparece na próxima revisão em vez de
            # sumir.
            medias.append(0.0)
            desvios.append(1.0)
            continue
        media = sum(coluna) / len(coluna)
        desvio = statistics.pstdev(coluna)
        medias.append(media)
        # Desvio zero significa que a dimensão não distingue nada neste
        # corpus. Dividir por ele explodiria; usar 1.0 a deixa em zero
        # constante depois de centrar, que é exatamente o que ela vale.
        # A régua reporta a dimensão como constante e ela sai na próxima
        # revisão — silenciosamente virar NaN esconderia o problema.
        desvios.append(desvio if desvio > 1e-9 else 1.0)

    return EspacoVetorial(
        versao=VERSAO,
        dimensoes=tuple(dimensoes),
        medias=tuple(medias),
        desvios=tuple(desvios),
        partidas=len(conjuntos),
    )


def _unitario(valores: list[float]) -> tuple[float, ...]:
    norma = math.sqrt(sum(v * v for v in valores))
    if norma <= 1e-12:
        return tuple(valores)
    return tuple(round(v / norma, 8) for v in valores)
