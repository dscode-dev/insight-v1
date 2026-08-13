"""O que o arquivo É, contra o que ele DIZ ser — antes de qualquer parser.

A ORDEM É A DEFESA. Todo parser é uma superfície de ataque: ele aceita bytes
arbitrários e faz alocação, recursão e decodificação com base neles. Chamar o
parser primeiro e perguntar depois inverte a proteção — o dano já aconteceu
dentro da biblioteca quando descobrimos que o arquivo não era daquele tipo.

Então aqui, sobre os primeiros bytes e nada mais:

    é compactado?          recusa (zip bomb não chega ao descompressor)
    é do formato certo?    recusa (o parser errado nunca é chamado)
    o texto decodifica?    recusa (nenhum decodificador roda sobre o resto)

Só depois disso um parser vê o arquivo.

ENCODING. UTF-8 é o esperado, e BOM é aceito porque metade das exportações de
planilha o inclui. Latin-1 NÃO é adivinhado: qualquer sequência de bytes é
Latin-1 válida, então "detectar" Latin-1 é sempre dizer sim — e o resultado é
um `Ã§` no lugar de `ç` percorrendo o pipeline inteiro sem nenhum erro. Um
arquivo que não é UTF-8 é recusado com o nome do problema, e quem o enviou
converte na origem, que é onde se sabe qual era o encoding de verdade.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.datasets.formats import (
    PARQUET_MAGIC,
    DatasetFormat,
    detect_compression,
)

#: Quanto se lê para decidir. 64 KiB pega o cabeçalho e algumas linhas de
#: qualquer CSV real sem materializar o arquivo.
PROBE_BYTES: Final[int] = 64 * 1024

#: BOMs que aparecem em exportação de planilha. UTF-16 é reconhecido para ser
#: RECUSADO com o nome certo — sem isso ele viraria "bytes ilegíveis".
_BOMS: Final[tuple[tuple[bytes, str], ...]] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


@final
@dataclass(frozen=True, slots=True)
class Probe:
    """O que os primeiros bytes revelaram."""

    declared: DatasetFormat
    size_bytes: int
    compression: str | None
    #: `None` quando não foi possível decidir — o que é diferente de "está
    #: errado". Um CSV é texto com vírgulas, e texto com vírgulas não tem
    #: assinatura; a ausência de prova não é prova de ausência.
    looks_like: DatasetFormat | None
    encoding: str | None
    encoding_error: str | None

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0

    @property
    def format_conflicts(self) -> bool:
        """Se o conteúdo CONTRADIZ a declaração.

        Contradiz, não "difere de". `looks_like is None` significa que não
        conseguimos decidir, e recusar por não ter conseguido decidir
        rejeitaria todo CSV do mundo.
        """
        return self.looks_like is not None and self.looks_like is not self.declared


def probe(head: bytes, *, declared: DatasetFormat, size_bytes: int) -> Probe:
    """Examina os primeiros bytes. Não chama parser nenhum."""
    compressao = detect_compression(head)
    parece = _sniff(head)

    encoding: str | None = None
    erro_encoding: str | None = None
    if not declared.is_binary and compressao is None and head:
        encoding, erro_encoding = _sniff_encoding(head)

    return Probe(
        declared=declared,
        size_bytes=size_bytes,
        compression=compressao,
        looks_like=parece,
        encoding=encoding,
        encoding_error=erro_encoding,
    )


def _sniff(head: bytes) -> DatasetFormat | None:
    """O formato que os bytes sugerem, ou `None` se não dá para dizer.

    SÓ O PARQUET É DECIDÍVEL AQUI, e é honesto que seja assim: ele tem
    assinatura, CSV e JSONL não têm. Distinguir CSV de JSONL exige olhar a
    estrutura da primeira linha, e isso é trabalho do inspetor de cada
    formato — que já tem o arquivo aberto e sabe o que procura.
    """
    if head.startswith(PARQUET_MAGIC):
        return DatasetFormat.PARQUET
    return None


def _sniff_encoding(head: bytes) -> tuple[str | None, str | None]:
    """(encoding, motivo da recusa). Um dos dois é sempre `None`."""
    for bom, nome in _BOMS:
        if head.startswith(bom):
            if nome == "utf-8-sig":
                return "utf-8-sig", None
            return None, (
                f"o arquivo declara {nome.upper()} pelo BOM; o motor lê UTF-8. "
                "Converta na origem, onde o encoding real é conhecido."
            )

    try:
        head.decode("utf-8")
    except UnicodeDecodeError as erro:
        # O último bloco pode cortar um caractere multibyte ao meio, e isso
        # não é erro de encoding — é o corte da amostra. Só conta como falha
        # quando o problema está longe do fim.
        if erro.start < len(head) - 4:
            return None, (
                f"byte inválido para UTF-8 na posição {erro.start} ({erro.reason}). "
                "Latin-1 não é adivinhado de propósito: toda sequência de bytes é "
                "Latin-1 válida, e supor isso produziria acentos errados sem nenhum erro."
            )
    return "utf-8", None


def looks_like_jsonl(first_line: str) -> bool:
    """Se a primeira linha parece um objeto JSON.

    A HEURÍSTICA É DELIBERADAMENTE FRACA — só a chave de abertura. Ela existe
    para pegar o caso grosseiro (um CSV declarado como JSONL) e não para
    validar JSON, que é trabalho do parser com todas as suas defesas. Uma
    heurística forte aqui duplicaria o parser e divergiria dele.
    """
    limpa = first_line.lstrip()
    return limpa.startswith("{")


def looks_like_csv_header(first_line: str, *, delimiter: str = ",") -> bool:
    """Se a primeira linha parece um cabeçalho de CSV com mais de uma coluna.

    UMA COLUNA SÓ É SUSPEITO E NÃO ERRADO: existe CSV de coluna única. Mas
    quando o arquivo tem muitas linhas e uma coluna só, quase sempre o
    delimitador é outro — ponto e vírgula, tabulação — e é isso que o
    inspetor investiga com esta resposta na mão.
    """
    return delimiter in first_line
