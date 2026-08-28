"""O codec EXATO do payload projetado — `float64`, byte a byte.

ELE EXISTE PARA QUE A PROJEÇÃO NÃO SEJA UMA SEGUNDA VERDADE. `D_state` e
`D_trajectory` são definidas sobre os números do dataset normalizado; se a
travessia pelo PostgreSQL perdesse um bit, a distância calculada a partir da
projeção seria PARECIDA com a do oráculo — e parecida é o pior resultado
possível, porque passa despercebida.

    origem  ->  encode  ->  bytea  ->  decode  ->  domínio

    e os `float64` das duas pontas são IGUAIS, sem tolerância

POR QUE `bytes` E NÃO JSON NEM `float8[]`. Foi medido nesta instalação: vinte e
nove `float64` ocupam 236 bytes em `bytea` contra 256 em `double precision[]`, e
JSON custaria mais que os dois somados mais o parser no caminho quente. O que
decidiu, porém, não foi o tamanho — foi o CONTROLE: aqui a ordem dos bytes é
declarada, e o mesmo vetor produz a mesma sequência em qualquer máquina.

NÃO HÁ CONVERSÃO PARA `float32` NESTE ARQUIVO. Houve, enquanto o PR-06.4
avaliava um índice ANN: o vetor do pgvector é `binary32` e perde bits, o que
tornava obrigatório um payload exato ao lado dele. O experimento foi concluído
e o ANN não foi adotado; o payload exato ficou, porque ele é o que a projeção
sempre foi. O registro da avaliação está em
`docs/retrieval/ANN_FEASIBILITY_EXPERIMENT_V1.md`.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Final

from sports_intelligence.domain.shared.errors import ValidationError

#: A codificação exata da V1.
IEEE754_FLOAT64_LE_PAYLOAD_V1: Final[str] = "IEEE754_FLOAT64_LE_PAYLOAD_V1"


def encode_exact_float64(values: Sequence[float]) -> bytes:
    """O payload EXATO, em `binary64` little-endian, sem cabeçalho.

    POR QUE `bytes` E NÃO JSON (§50). Foi medido nesta instalação: vinte e nove
    `float64` ocupam 236 bytes em `bytea` contra 256 em `double precision[]`, e
    JSON custaria o dobro disso mais o parser no caminho quente. O que decidiu,
    porém, não foi o tamanho — foi o CONTROLE: aqui a ordem dos bytes é
    declarada, e o mesmo vetor produz a mesma sequência em qualquer máquina.

    `<` FIXA O ENDIANESS. Sem ele `struct` usaria a ordem nativa, e o mesmo
    dataset indexado num ARM e lido num x86 daria digestos diferentes para
    conteúdo idêntico.

    NÃO-FINITO É RECUSADO AQUI TAMBÉM, e pelo mesmo motivo do proxy: um `NaN`
    no payload exato não é ausência, é um valor que compara falso consigo
    mesmo — e a ausência já tem uma máscara para representá-la.
    """
    for v in values:
        if not math.isfinite(v):
            raise ValidationError(
                f"valor não finito no payload exato: {v!r}. A ausência viaja na "
                "máscara, e nunca dentro do número"
            )
    return struct.pack(f"<{len(values)}d", *values)


def decode_exact_float64(payload: bytes, *, count: int) -> tuple[float, ...]:
    """De volta ao `float64`, bit a bit. `count` é conferido, e não inferido.

    INFERIR O TAMANHO PELO COMPRIMENTO ESCONDERIA O ERRO QUE IMPORTA: um
    payload de outro espaço de eixos teria comprimento diferente e seria
    decodificado sem reclamar, produzindo um vetor de tamanho errado que só
    falharia mais adiante — ou pior, não falharia.
    """
    esperado = count * 8
    if len(payload) != esperado:
        raise ValidationError(
            f"payload de {len(payload)} bytes para {count} valores: esperados "
            f"{esperado}. Um payload de outro espaço de eixos decodificaria em "
            "silêncio e produziria uma distância sobre dimensões erradas"
        )
    return tuple(struct.unpack(f"<{count}d", payload))


def encode_mask(mask: Sequence[bool]) -> bytes:
    """A máscara como um byte por posição — `b"\\x01"` presente, `b"\\x00"` ausente.

    UM BYTE POR EIXO, E NÃO UM BIT. Vinte e nove bits caberiam em quatro bytes,
    e a economia de vinte e cinco bytes por linha não paga o que ela custa: o
    empacotamento em bits exige declarar ordem de bits além de ordem de bytes,
    e é uma segunda convenção para errar. A máscara já é pequena perto dos
    duzentos e trinta e seis bytes dos valores.
    """
    return bytes(1 if bit else 0 for bit in mask)


def decode_mask(payload: bytes, *, count: int) -> tuple[bool, ...]:
    if len(payload) != count:
        raise ValidationError(f"máscara de {len(payload)} bytes para {count} eixos")
    for byte in payload:
        if byte not in (0, 1):
            raise ValidationError(
                f"byte {byte} na máscara: ela é booleana, e um terceiro valor "
                "significaria um estado de disponibilidade que o contrato não tem"
            )
    return tuple(byte == 1 for byte in payload)
