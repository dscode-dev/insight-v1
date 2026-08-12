from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StreamPartitioning:
    """
    Determina em qual partição de stream um match será publicado.

    O particionamento usa SHA1 do UUID para garantir:
    - distribuição uniforme
    - estabilidade entre processos
    - estabilidade entre linguagens (Go, Python, JS, etc)

    Exemplo de streams:

        insight:stream:events:odds:p0
        insight:stream:events:odds:p1
        insight:stream:events:odds:p2
        ...

    Se partitions == 1, retorna apenas base_key.
    """

    base_key: str
    partitions: int

    def key_for_match(self, match_id: UUID) -> str:
        """
        Retorna a stream correta para um match.

        O hash é calculado usando SHA1 do UUID string para garantir
        estabilidade cross-process e cross-language.
        """

        if self.partitions <= 1:
            return self.base_key

        # hash estável
        h = hashlib.sha1(str(match_id).encode("utf-8")).digest()

        # usa primeiros 4 bytes
        bucket = int.from_bytes(h[:4], byteorder="big", signed=False) % self.partitions

        return f"{self.base_key}:p{bucket}"

    def all_stream_keys(self) -> list[str]:
        """
        Retorna todas as streams existentes.
        """

        if self.partitions <= 1:
            return [self.base_key]

        return [f"{self.base_key}:p{i}" for i in range(self.partitions)]