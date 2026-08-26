"""O verificador de fronteiras, num lugar só.

POR QUE EXTRAÍDO. O PR-02 acrescentou um segundo arquivo de testes de
arquitetura, e ele precisa das mesmas funções. Copiá-las criaria dois
verificadores que divergem na primeira vez que alguém ajustar um — e o pior
resultado disso não é falha, é um dos dois deixar de enxergar em silêncio,
com a suíte continuando verde.

POR QUE AST E NÃO GREP. `grep -r "import fastapi"` não distingue um import
real de uma menção em docstring — e esta base tem docstrings longas que citam
FastAPI, Redis, boto3 e `resolve_team` por nome, justamente para explicar por
que o domínio não os usa. Um grep marcaria cada explicação como violação.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FONTE = RAIZ / "src" / "sports_intelligence"
APPS = RAIZ / "apps"

#: Pacotes que o domínio, features e engines não podem conhecer.
INFRA_EXTERNA = frozenset(
    {
        "fastapi",
        "starlette",
        "uvicorn",
        "sqlalchemy",
        "asyncpg",
        "psycopg",
        "psycopg2",
        "redis",
        "aioredis",
        "clickhouse_driver",
        "clickhouse_connect",
        "boto3",
        "botocore",
        "minio",
        "aioboto3",
        "aiobotocore",
        "pgvector",
        "typer",
        "rich",
        "httpx",
        "requests",
        "aiohttp",
        # Bibliotecas de dataframe: um domínio que as importa tem um
        # dataframe no modelo, e o modelo passa a ser desenhado pelo que é
        # fácil de ler em vez de pelo que é verdade sobre o dado.
        "polars",
        "pyarrow",
        "pandas",
        "numpy",
    }
)


@dataclass(frozen=True)
class Import:
    """Um import real, com onde está — para que a falha seja acionável."""

    module: str
    file: Path
    line: int

    def __str__(self) -> str:
        return f"{self.file.relative_to(RAIZ)}:{self.line} importa {self.module!r}"


def imports_of(caminho: Path) -> list[Import]:
    """Os imports de um arquivo, lidos da árvore sintática."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
    achados: list[Import] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            achados.extend(Import(alias.name, caminho, no.lineno) for alias in no.names)
        # `level > 0` é import relativo; o ruff já os proíbe (TID252).
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            achados.append(Import(no.module, caminho, no.lineno))
    return achados


def files_in(*pacotes: str) -> list[Path]:
    saida: list[Path] = []
    for pacote in pacotes:
        base = FONTE / pacote
        if base.exists():
            saida.extend(sorted(base.rglob("*.py")))
    return saida


def root_module(module: str) -> str:
    return module.split(".", 1)[0]


def external_violations(arquivos: list[Path], proibidos: frozenset[str]) -> list[Import]:
    return [
        imp
        for arquivo in arquivos
        for imp in imports_of(arquivo)
        if root_module(imp.module) in proibidos
    ]


def internal_violations(arquivos: list[Path], prefixos: tuple[str, ...]) -> list[Import]:
    return [
        imp
        for arquivo in arquivos
        for imp in imports_of(arquivo)
        if imp.module.startswith(prefixos)
    ]


def code_only(caminho: Path) -> str:
    """O arquivo SEM comentários e SEM docstrings, em minúsculas.

    POR QUE ISTO EXISTE (PR-05.4). As guardas textuais procuram construções
    proibidas — `epsilon`, `winsor`, `overround`, `1 / odds`. O problema é que
    esta base EXPLICA por extenso o que não faz: as docstrings citam cada uma
    dessas coisas pelo nome, justamente para registrar a decisão de não
    tê-las. Uma varredura ingênua marca a explicação como violação, e a saída
    natural — reescrever a prosa para escapar do grep — deixaria o código pior
    e a guarda igualmente cega.

    O que sobra depois desta função é CÓDIGO. Uma menção numa docstring passa;
    uma chamada de função, não.
    """
    fonte = caminho.read_text(encoding="utf-8")
    arvore = ast.parse(fonte, filename=str(caminho))
    linhas = fonte.splitlines()
    apagar: set[int] = set()
    for no in ast.walk(arvore):
        # Docstrings são `Expr(Constant(str))` — em módulo, classe ou função.
        if (
            isinstance(no, ast.Expr)
            and isinstance(no.value, ast.Constant)
            and isinstance(no.value.value, str)
            and no.end_lineno is not None
        ):
            apagar.update(range(no.lineno - 1, no.end_lineno))
    mantidas = ["" if n in apagar else linha.split("#", 1)[0] for n, linha in enumerate(linhas)]
    return "\n".join(mantidas).lower()


def defined_functions(arquivos: list[Path]) -> list[tuple[Path, int, str]]:
    """(arquivo, linha, nome) de cada função definida.

    Existe para a proibição que o import não cobre: alguém escreve
    `def resolve_team(...)` dentro do próprio validador, sem importar nada de
    fora, e nenhuma verificação de dependência a enxerga.
    """
    encontradas: list[tuple[Path, int, str]] = []
    for arquivo in arquivos:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        encontradas.extend(
            (arquivo, no.lineno, no.name)
            for no in ast.walk(arvore)
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return encontradas
