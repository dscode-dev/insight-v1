"""Os três formatos da V1, e por que a extensão não prova nada.

`.csv` É UMA AFIRMAÇÃO DO REMETENTE, NÃO UM FATO. Renomear um arquivo é
gratuito, e um Parquet chamado `matches.csv` passa por qualquer verificação
que olhe só o nome — o parser de CSV lê o cabeçalho binário como uma linha,
não falha, e produz um dataframe de uma coluna com lixo dentro. Nada dispara.

Por isso o formato tem duas fontes aqui: o que foi DECLARADO e o que os
primeiros bytes DIZEM. Quando discordam, é impeditivo — não aviso.

XLSX FICOU DE FORA POR DECISÃO. Ele é um zip de XML, o que traz zip bomb,
fórmula, macro e três bibliotecas de superfície ampla para ler o que o
operador pode exportar para CSV em dois cliques.

PARQUET É O PREFERENCIAL INTERNO e não converte nada na entrada. O bruto
recebido permanece exatamente como chegou (ADR-0014); a conversão, quando
existir, produz um artefato derivado ao lado — nunca por cima.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from sports_intelligence.domain.shared.errors import ValidationError


class DatasetFormat(StrEnum):
    """O que o motor sabe ler na V1."""

    PARQUET = "PARQUET"
    CSV = "CSV"
    JSONL = "JSONL"

    @property
    def media_type(self) -> str:
        return _MEDIA_TYPES[self]

    @property
    def is_binary(self) -> bool:
        """Se o conteúdo não é texto. Governa se checar encoding faz sentido."""
        return self is DatasetFormat.PARQUET

    @property
    def canonical_extension(self) -> str:
        return _EXTENSOES[self]


_MEDIA_TYPES: Final[dict[DatasetFormat, str]] = {
    DatasetFormat.PARQUET: "application/vnd.apache.parquet",
    DatasetFormat.CSV: "text/csv",
    DatasetFormat.JSONL: "application/x-ndjson",
}

_EXTENSOES: Final[dict[DatasetFormat, str]] = {
    DatasetFormat.PARQUET: ".parquet",
    DatasetFormat.CSV: ".csv",
    DatasetFormat.JSONL: ".jsonl",
}

#: A assinatura do Parquet: `PAR1` no início E no fim do arquivo. É o único
#: dos três com marca de formato — CSV e JSONL são texto, e nenhum texto tem
#: assinatura. Para eles a detecção é estrutural, não mágica, e mora no
#: validador; aqui fica só o que é fato do formato.
PARQUET_MAGIC: Final[bytes] = b"PAR1"

#: Compactação NÃO é aceita na V1, e a ausência é declarada em vez de
#: silenciosa. Aceitar zip/gzip traria decompression bomb — um arquivo de
#: 4 KB que vira 40 GB ao ser lido, e cujo dano acontece dentro da biblioteca
#: de descompressão, antes de qualquer limite nosso ter chance de agir.
#: Quando entrar, entra com limite de razão de expansão medido durante a
#: leitura, e não depois.
ASSINATURAS_COMPACTADAS: Final[dict[bytes, str]] = {
    b"PK\x03\x04": "ZIP",
    b"\x1f\x8b": "GZIP",
    b"BZh": "BZIP2",
    b"\xfd7zXZ": "XZ",
    b"\x04\x22\x4d\x18": "LZ4",
    b"\x28\xb5\x2f\xfd": "ZSTD",
}


def detect_compression(head: bytes) -> str | None:
    """O nome do compactador, se os primeiros bytes forem de um.

    Existe para que um `.csv.gz` renomeado para `.csv` seja RECUSADO com o
    motivo certo, em vez de virar um CSV de uma coluna com bytes ilegíveis
    que atravessa a validação como dado ruim.
    """
    for assinatura, nome in ASSINATURAS_COMPACTADAS.items():
        if head.startswith(assinatura):
            return nome
    return None


#: O que sobra de um nome de arquivo depois da limpeza. Tudo que não estiver
#: aqui vira `_`.
_CARACTERE_SEGURO = re.compile(r"[^A-Za-z0-9._-]")
_PONTOS_SEGUIDOS = re.compile(r"\.{2,}")

#: Nomes que o Windows reserva. Um arquivo chamado `CON` quebra qualquer
#: extração feita numa máquina Windows, e a falha acontece longe daqui.
_RESERVADOS: Final[frozenset[str]] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

MAX_FILENAME_LENGTH: Final[int] = 120


def sanitize_filename(raw: str) -> str:
    """Devolve um nome seguro, ou recusa.

    ISTO NÃO É PARA ARRUMAR O NOME — é para impedir que um nome escolhido por
    quem envia decida onde os bytes vão parar. `../../etc/passwd`,
    `C:\\Windows\\x`, um nome com `\\x00` no meio e um nome de 4 KB são todos
    entradas plausíveis num endpoint aberto a operador.

    O nome limpo é METADADO, guardado porque o operador precisa reconhecer o
    que enviou. Ele NÃO entra na chave do objeto sozinho: a chave vem do hash
    do conteúdo (ver `object_keys`), e é isso que torna a colisão de nomes
    irrelevante para o armazenamento.
    """
    if not raw or not raw.strip():
        raise ValidationError("nome de arquivo vazio")
    if "\x00" in raw:
        raise ValidationError("nome de arquivo com byte nulo")

    # Só o último componente. Barra e contrabarra somem antes de qualquer
    # outra coisa, então `../../x` vira `x` e não sobra travessia nenhuma.
    ultimo = re.split(r"[/\\]", raw.strip())[-1]
    limpo = _CARACTERE_SEGURO.sub("_", ultimo)
    limpo = _PONTOS_SEGUIDOS.sub(".", limpo).strip("._-")

    if not limpo:
        raise ValidationError(
            f"nome de arquivo {raw!r} não sobrou nada depois da limpeza"
        )
    if limpo.split(".", 1)[0].lower() in _RESERVADOS:
        limpo = f"arquivo_{limpo}"
    if len(limpo) > MAX_FILENAME_LENGTH:
        # Corta pelo começo e preserva a extensão: o começo do nome é o que
        # identifica, e o fim é o que diz o formato.
        raiz, _, extensao = limpo.rpartition(".")
        if raiz and len(extensao) <= 12:
            limpo = raiz[: MAX_FILENAME_LENGTH - len(extensao) - 1] + "." + extensao
        else:
            limpo = limpo[:MAX_FILENAME_LENGTH]
    return limpo


def resolve_declared_format(raw: str) -> DatasetFormat:
    """Traduz o que o operador declarou, com erro que diz as opções."""
    texto = raw.strip().upper().lstrip(".")
    apelidos = {"NDJSON": DatasetFormat.JSONL, "JSON_LINES": DatasetFormat.JSONL}
    if texto in apelidos:
        return apelidos[texto]
    try:
        return DatasetFormat(texto)
    except ValueError as erro:
        aceitos = ", ".join(f.value for f in DatasetFormat)
        raise ValidationError(
            f"formato {raw!r} não é suportado na V1. Aceitos: {aceitos}. "
            "XLSX ficou de fora por decisão — exporte para CSV."
        ) from erro
