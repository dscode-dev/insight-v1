"""O conteúdo como identidade: SHA-256 e a chave de objeto que sai dele.

O QUE O HASH RESOLVE. Três perguntas que aparecem no primeiro dia de operação
manual e que nenhum nome de arquivo responde:

    o operador reenviou o mesmo arquivo?          mesmo hash
    ele renomeou e reenviou?                      mesmo hash, nome diferente
    ele corrigiu o arquivo e manteve o nome?      mesmo nome, hash diferente

Sem hash, o primeiro caso duplica, o segundo duplica, e o terceiro sobrescreve
em silêncio — que é o pior dos três, porque destrói a evidência anterior sem
deixar rastro.

O QUE O HASH NÃO É. Ele não é o `DatasetId`. Um dataset é uma unidade lógica
declarada pelo operador — "Premier League, temporadas 2019 a 2024, do
football-data" — e ela continua sendo a mesma coisa quando um arquivo é
acrescentado. Amarrar a identidade do dataset ao conteúdo faria acrescentar
uma linha criar outro dataset, e o histórico de decisões sobre ele se perderia
a cada correção.

Nem é identidade de linha. Duas linhas idênticas em fontes diferentes podem
descrever a mesma partida ou duas partidas distintas, e decidir isso é
resolução de identidade — PR-03, com confiança, conflito e fila de revisão.
Aqui o hash identifica BYTES, e só.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: 64 caracteres hexadecimais, minúsculos. A forma canônica é uma só para que
#: o mesmo conteúdo não vire duas chaves por diferença de caixa.
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: Tamanho do bloco de leitura. 1 MiB é grande o bastante para não pagar
#: syscall por byte e pequeno o bastante para o pico de memória não depender
#: do tamanho do arquivo — que é a regra inteira deste PR.
CHUNK_SIZE: Final[int] = 1024 * 1024


@final
@dataclass(frozen=True, slots=True)
class ContentHash:
    """O SHA-256 dos bytes exatos recebidos.

    DOS BYTES RECEBIDOS, e não do conteúdo lógico. Um CSV com CRLF e o mesmo
    CSV com LF são conteúdos lógicos idênticos e bytes diferentes, e este
    hash os distingue. É o comportamento certo para uma camada cuja função é
    provar o que chegou: normalizar antes de hashear seria afirmar que
    recebemos algo que não recebemos.
    """

    value: str

    def __post_init__(self) -> None:
        texto = self.value.strip().lower()
        if not _HEX_SHA256.match(texto):
            raise ValidationError(
                f"{self.value!r} não é um SHA-256: são 64 caracteres hexadecimais"
            )
        object.__setattr__(self, "value", texto)

    @classmethod
    def of(cls, data: bytes) -> Self:
        """Para conteúdo que já está inteiro em memória — testes e blocos
        pequenos. Arquivo de operador NUNCA passa por aqui: ele vem por
        stream, e o hash é acumulado durante a leitura."""
        return cls(hashlib.sha256(data).hexdigest())

    @property
    def short(self) -> str:
        """Os 12 primeiros. Para log e para a tabela da CLI, onde 64
        caracteres quebram a linha e ninguém lê mesmo assim."""
        return self.value[:12]

    def __str__(self) -> str:
        return self.value


#: Prefixo do arquivo bruto. Um só, no topo, porque uma chave montada em três
#: lugares diverge no dia em que alguém ajusta um deles.
RAW_PREFIX: Final[str] = "datasets/raw"


def build_object_key(
    *,
    dataset_id: DatasetId,
    version: DatasetVersion,
    content_hash: ContentHash,
    safe_filename: str,
) -> str:
    """A chave determinística de um arquivo bruto.

        datasets/raw/dataset=<uuid>/version=v1.0/sha256=<hash>/<nome-limpo>

    TRÊS PROPRIEDADES, E CADA UMA PAGA UM CUSTO ESPECÍFICO.

    DETERMINÍSTICA: a mesma entrada produz a mesma chave, sempre. É o que
    torna o retry idempotente no object store — reenviar os mesmos bytes
    escreve no mesmo lugar o mesmo conteúdo, e não cria um segundo objeto.

    ENDEREÇADA POR CONTEÚDO: o hash está no caminho, então dois arquivos
    diferentes nunca disputam a mesma chave, e o mesmo arquivo com dois nomes
    ocupa um lugar só dentro da versão.

    SEGURA POR CONSTRUÇÃO: todo componente que decide o CAMINHO é gerado por
    nós — uuid, versão, hash hexadecimal. O único componente que vem de fora
    é o nome, e ele entra já sanitizado e apenas como folha, onde não pode
    redirecionar nada. Mesmo assim, é conferido de novo aqui: uma função que
    confia no chamador para a própria segurança não é segura, é conveniente.

    O nome sobrevive na folha porque um bucket em que todo objeto se chama
    `sha256=ab3f.../data` é ilegível para quem opera — e a legibilidade do
    arquivo bruto é o que faz alguém conseguir auditá-lo dois anos depois.
    """
    if "/" in safe_filename or "\\" in safe_filename:
        raise ValidationError(
            f"nome {safe_filename!r} contém separador de caminho — "
            "ele deveria ter passado por sanitize_filename antes"
        )
    if safe_filename in ("", ".", ".."):
        raise ValidationError(f"nome de arquivo inválido para chave: {safe_filename!r}")
    return (
        f"{RAW_PREFIX}/dataset={dataset_id}/version={version}/sha256={content_hash}/{safe_filename}"
    )


def dataset_key_prefix(dataset_id: DatasetId, version: DatasetVersion | None = None) -> str:
    """O prefixo de tudo que pertence a um dataset — e opcionalmente a uma
    versão. É o que permite listar o que existe fisicamente e confrontar com
    o que o banco diz existir, que é a reconciliação do ADR-0017."""
    base = f"{RAW_PREFIX}/dataset={dataset_id}"
    return base if version is None else f"{base}/version={version}"
