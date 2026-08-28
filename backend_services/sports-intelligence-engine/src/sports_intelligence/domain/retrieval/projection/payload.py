"""O payload EXATO — o que o rerank consome, e o que o proxy não pode ser.

A REGRA DE OURO DO PR (§48): **o vetor do pgvector NÃO é insumo de distância.**
Ele perde bits — foi medido — e uma distância calculada sobre `float32` não é a
distância do PR-06.2 nem a do PR-06.3. Seria uma terceira, parecida com as duas,
e parecida é o pior resultado possível: ela passaria despercebida.

Por isso cada linha indexada carrega DUAS coisas independentes:

    proxy vector      float32   ORDENA candidatos
    exact payload     float64   RESPONDE a pergunta

E o payload exato precisa reconstruir a representação de origem **bit a bit**,
porque é isso que permite a única afirmação que fecha o PR:

    distância a partir do payload indexado
    ==
    distância a partir do oráculo exato

Não «aproximadamente». Igual. Se um bit se perde no caminho, o índice deixou de
ser um acelerador e virou uma segunda fonte de verdade — e o §52 chama isso de
blocker absoluto, com razão.

O QUE VIAJA JUNTO DOS NÚMEROS. Valores e máscara não bastam para reconstruir a
identidade: sem o digesto da linha de origem não há como provar que o payload
veio DAQUELA linha, e sem a impressão da representação não há como recusar um
payload gravado sob outro contrato. Os dois entram.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.retrieval.projection.numeric import (
    decode_exact_float64,
    decode_mask,
    encode_exact_float64,
    encode_mask,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

PAYLOAD_DIGEST_ALGORITHM: Final[str] = "indexed-exact-payload-sha256-v1"

#: A codificação do payload exato da V1.
EXACT_FLOAT64_LE_PAYLOAD_V1: Final[str] = "EXACT_FLOAT64_LE_PAYLOAD_V1"


@final
@dataclass(frozen=True, slots=True)
class ExactStatePayload:
    """Os `float64` de UMA linha de estado, na ordem canônica dos eixos.

    A ORDEM É A DO PROXY, e ela é a mesma do plano. Guardar os valores numa
    ordem e o vetor noutra funcionaria — as duas estruturas são lidas por
    caminhos diferentes — até o dia em que alguém comparasse posição com
    posição.
    """

    axis_keys: tuple[str, ...]
    values: tuple[float, ...]
    mask: tuple[bool, ...]
    row_digest: str
    representation_fingerprint: str
    encoding: str = EXACT_FLOAT64_LE_PAYLOAD_V1

    def __post_init__(self) -> None:
        if not (len(self.axis_keys) == len(self.values) == len(self.mask)):
            raise ValidationError(
                f"payload incoerente: {len(self.axis_keys)} eixos, {len(self.values)} "
                f"valores e {len(self.mask)} posições de máscara"
            )
        if not self.row_digest.strip():
            raise ValidationError(
                "payload exato sem digesto de origem: não haveria como provar de "
                "qual linha do dataset normalizado ele saiu"
            )

    @property
    def usable_count(self) -> int:
        return sum(1 for bit in self.mask if bit)

    def values_by_key(self) -> Mapping[str, float | None]:
        """O mapa que a representação exata consome — ausente é `None`.

        AQUI O ZERO DE ARMAZENAMENTO VIRA `None` DE VOLTA. O payload guarda um
        número em toda posição porque `bytes` não tem buraco; a máscara é o que
        devolve a ausência ao domínio, e é ela que manda.
        """
        return {
            chave: (valor if utilizavel else None)
            for chave, valor, utilizavel in zip(self.axis_keys, self.values, self.mask, strict=True)
        }

    def encode(self) -> tuple[bytes, bytes]:
        """`(valores, máscara)` — dois `bytea`, os dois determinísticos."""
        return encode_exact_float64(self.values), encode_mask(self.mask)

    @property
    def digest(self) -> str:
        """O digesto do CONTEÚDO exato — bytes, e não representação decimal.

        HASHEAR OS BYTES É O PONTO. Um digesto sobre `repr(valor)` mudaria com a
        versão do Python que formata float, e um sobre `round(valor, 12)` não
        distinguiria dois números que a distância exata distingue.
        """
        valores, mascara = self.encode()
        return hashlib.sha256(
            canonical_json(
                {
                    "algorithm": PAYLOAD_DIGEST_ALGORITHM,
                    "axis_keys": list(self.axis_keys),
                    "encoding": self.encoding,
                    "mask": mascara.hex(),
                    "representation_fingerprint": self.representation_fingerprint,
                    "row_digest": self.row_digest,
                    "values": valores.hex(),
                }
            )
        ).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class ExactTrajectoryPayload:
    """Os deslocamentos `float64` de UMA âncora, em ordem `(horizonte, eixo)`.

    A ÂNCORA E A IMPRESSÃO DA TRAJETÓRIA VIAJAM JUNTAS porque a trajetória não é
    uma linha: ela é uma âncora mais os instantes que alcançou. Sem a impressão,
    dois payloads com os mesmos deslocamentos e linhagens diferentes seriam
    indistinguíveis — e a linhagem é o que prova que o `t-5` usado é do mesmo
    período.
    """

    axis_keys: tuple[str, ...]
    horizons: tuple[int, ...]
    displacements: tuple[float, ...]
    mask: tuple[bool, ...]
    anchor_row_digest: str
    trajectory_fingerprint: str
    representation_fingerprint: str
    encoding: str = EXACT_FLOAT64_LE_PAYLOAD_V1

    def __post_init__(self) -> None:
        esperado = len(self.horizons) * len(self.axis_keys)
        if len(self.displacements) != esperado or len(self.mask) != esperado:
            raise ValidationError(
                f"payload de trajetória com {len(self.displacements)} deslocamentos e "
                f"{len(self.mask)} máscaras para {esperado} células"
            )
        if not self.trajectory_fingerprint.strip():
            raise ValidationError(
                "payload de trajetória sem impressão: a linhagem dos instantes "
                "alcançados é o que prova que o lookback não atravessou o intervalo"
            )

    @property
    def cell_count(self) -> int:
        return len(self.displacements)

    @property
    def usable_count(self) -> int:
        return sum(1 for bit in self.mask if bit)

    def displacements_by_cell(self) -> Mapping[tuple[int, str], float | None]:
        saida: dict[tuple[int, str], float | None] = {}
        posicao = 0
        for horizonte in self.horizons:
            for chave in self.axis_keys:
                saida[(horizonte, chave)] = (
                    self.displacements[posicao] if self.mask[posicao] else None
                )
                posicao += 1
        return saida

    def encode(self) -> tuple[bytes, bytes]:
        return encode_exact_float64(self.displacements), encode_mask(self.mask)

    @property
    def digest(self) -> str:
        valores, mascara = self.encode()
        return hashlib.sha256(
            canonical_json(
                {
                    "algorithm": PAYLOAD_DIGEST_ALGORITHM,
                    "anchor_row_digest": self.anchor_row_digest,
                    "axis_keys": list(self.axis_keys),
                    "displacements": valores.hex(),
                    "encoding": self.encoding,
                    "horizons": list(self.horizons),
                    "mask": mascara.hex(),
                    "representation_fingerprint": self.representation_fingerprint,
                    "trajectory_fingerprint": self.trajectory_fingerprint,
                }
            )
        ).hexdigest()


def decode_state_payload(
    *,
    axis_keys: Sequence[str],
    values: bytes,
    mask: bytes,
    row_digest: str,
    representation_fingerprint: str,
) -> ExactStatePayload:
    """De `bytea` de volta ao domínio, sem perder um bit."""
    quantidade = len(axis_keys)
    return ExactStatePayload(
        axis_keys=tuple(axis_keys),
        values=decode_exact_float64(values, count=quantidade),
        mask=decode_mask(mask, count=quantidade),
        row_digest=row_digest,
        representation_fingerprint=representation_fingerprint,
    )


def decode_trajectory_payload(
    *,
    axis_keys: Sequence[str],
    horizons: Sequence[int],
    displacements: bytes,
    mask: bytes,
    anchor_row_digest: str,
    trajectory_fingerprint: str,
    representation_fingerprint: str,
) -> ExactTrajectoryPayload:
    quantidade = len(horizons) * len(axis_keys)
    return ExactTrajectoryPayload(
        axis_keys=tuple(axis_keys),
        horizons=tuple(horizons),
        displacements=decode_exact_float64(displacements, count=quantidade),
        mask=decode_mask(mask, count=quantidade),
        anchor_row_digest=anchor_row_digest,
        trajectory_fingerprint=trajectory_fingerprint,
        representation_fingerprint=representation_fingerprint,
    )
