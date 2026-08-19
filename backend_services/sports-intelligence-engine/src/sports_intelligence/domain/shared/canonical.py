"""A serialização canônica — as primitivas que TODA impressão do motor usa.

POR QUE ELAS SAÍRAM DO MÓDULO DE IMPRESSÃO DO CORPUS (PR-04.4.2). Elas
nasceram lá porque o corpus foi o primeiro a precisar delas. Agora o registro
canônico de eventos precisa das mesmas — para comparar dois eventos com a
MESMA identidade derivada e decidir se são o mesmo fato ou um conflito — e um
adapter de evento importando `domain.corpus` seria a camada de baixo puxando a
de cima.

A ALTERNATIVA ERA COPIAR, e copiar é o defeito: duas serializações
«canônicas» divergem no primeiro tipo novo, e a divergência aparece como duas
impressões diferentes sobre o mesmo fato — sem nada que denuncie qual das duas
está certa.

O QUE ELAS GARANTEM:

    canonical_json   chaves ordenadas, separador fixo, UTF-8. Bytes iguais
                     para conteúdo igual, sempre
    uuid_text        UMA forma de UUID: minúsculas, com hífens
    instant_text     UTC, ISO-8601, microssegundo SEMPRE presente
    decimal_text     texto normalizado, nunca `float`
    frame            enquadramento por tamanho, para concatenação não ambígua
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

#: Quantos bytes o prefixo de tamanho ocupa em `frame`. Oito é folgado para
#: sempre, e um tamanho FIXO é o que torna o enquadramento não ambíguo.
_TAMANHO_DO_PREFIXO: Final[int] = 8


def frame(tag: bytes, payload: bytes) -> bytes:
    """Enquadra um pedaço com rótulo e tamanho explícitos.

    SEM ISSO, A CONCATENAÇÃO É AMBÍGUA: `"AB" + "C"` e `"A" + "BC"` produzem a
    mesma cadeia, e dois conteúdos diferentes produziriam a mesma impressão. O
    prefixo de tamanho torna a fronteira entre pedaços impossível de mover.
    """
    return (
        len(tag).to_bytes(2, "big")
        + tag
        + len(payload).to_bytes(_TAMANHO_DO_PREFIXO, "big")
        + payload
    )


def canonical_json(payload: object) -> bytes:
    """A serialização determinística de um pedaço.

    Chaves ordenadas, separador fixo, UTF-8, `ensure_ascii=False`. O que ela
    NÃO faz é resolver tipos — `uuid_text`, `instant_text` e `decimal_text`
    existem para isso, e nenhum valor chega aqui como objeto.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def uuid_text(value: UUID | str) -> str:
    """UUID em forma canônica: minúsculas, com hífens.

    UMA FORMA SÓ, DECIDIDA AQUI. `str(UUID)` já produz isto, mas o texto que
    chega do banco pode vir de outro caminho — normalizar num lugar é o que
    impede duas representações do mesmo id produzirem impressões diferentes.
    """
    return str(UUID(str(value)))


def instant_text(value: datetime) -> str:
    """Instante em UTC, ISO-8601, com precisão de MICROSSEGUNDO fixa.

    `datetime.isoformat()` OMITE os microssegundos quando eles são zero, então
    `20:00:00` e `20:00:00.000000` — o mesmo instante — produziriam cadeias
    diferentes conforme o caminho que trouxe o valor. A precisão fixa fecha
    isso; o fuso normalizado fecha a outra metade.
    """
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def decimal_text(value: Decimal | None) -> str | None:
    """Decimal como TEXTO normalizado, nunca float.

    `2.00` e `2.0` são a mesma odd escrita de dois jeitos, e
    `float(Decimal("2.05"))` não é 2.05. A normalização escolhe uma forma; o
    expoente positivo volta a inteiro porque `normalize()` transforma 100 em
    `1E+2`.
    """
    if value is None:
        return None
    normalizado = value.normalize()
    if normalizado == normalizado.to_integral_value():
        normalizado = normalizado.quantize(Decimal(1))
    return format(normalizado, "f")
