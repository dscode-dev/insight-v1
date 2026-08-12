"""A CLI do motor. Dois comandos, os dois fazendo trabalho real.

`doctor` É O COMANDO QUE JUSTIFICA A CLI NO PR-00. Ele responde a pergunta que
todo mundo faz ao clonar o repositório e que nenhum README responde com
precisão: o que está configurado aqui, e o que falta.

E ele responde SEM EXIGIR a infraestrutura. Um `doctor` que morre porque não
há Postgres é inútil justamente quando é mais necessário — antes de haver
Postgres. Cada dependência é tentada em separado, e a ausência é relatada como
estado, não como falha.

NENHUM COMANDO PLACEHOLDER. Um comando que imprime "não implementado" é pior
que a ausência dele: ele aparece no `--help`, alguém tenta usar, e descobre
tarde. Os comandos dos PRs seguintes entram com os PRs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.table import Table

from sports_intelligence.config.settings import (
    AppSettings,
    ClickHouseSettings,
    ObjectStoreSettings,
    ObservabilitySettings,
    PostgresSettings,
    RedisSettings,
    SecuritySettings,
)

app = typer.Typer(
    name="engine",
    help="Insight Sports Intelligence Engine",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


class Estado(StrEnum):
    CONFIGURADO = "configurado"
    AUSENTE = "não configurado"
    INVALIDO = "inválido"

    @property
    def cor(self) -> str:
        return {
            Estado.CONFIGURADO: "green",
            Estado.AUSENTE: "yellow",
            Estado.INVALIDO: "red",
        }[self]


#: As dependências que o `doctor` sabe verificar. Nome → classe de settings.
#:
#: `AppSettings` fica de fora: ela não é opcional. Se ela não construir, o
#: processo não sobe, e o `doctor` falha antes de chegar na tabela.
_DEPENDENCIAS: Final = {
    "postgres": PostgresSettings,
    "clickhouse": ClickHouseSettings,
    "redis": RedisSettings,
    "object_store": ObjectStoreSettings,
    "observability": ObservabilitySettings,
    "security": SecuritySettings,
}

#: Do que o PR-00 realmente depende para rodar. O resto é declarado e ainda
#: não usado — dizer isso é a diferença entre "faltam seis coisas" e "está
#: pronto para o que existe hoje".
_EXIGIDAS_AGORA: Final = frozenset({"security"})


@app.command()
def version() -> None:
    """Versão e ambiente deste processo."""
    settings = AppSettings()
    console.print(
        f"[bold]{settings.service_name}[/bold] "
        f"[cyan]{settings.version}[/cyan] "
        f"({settings.environment.value})"
    )


@app.command()
def doctor() -> None:
    """O que está configurado, o que falta, e o que ainda não é exigido."""
    try:
        settings = AppSettings()
    except PydanticValidationError as erro:
        console.print("[red]A configuração básica da aplicação é inválida.[/red]")
        for problema in erro.errors():
            campo = ".".join(str(p) for p in problema["loc"])
            console.print(f"  [red]{campo}[/red]: {problema['msg']}")
        raise typer.Exit(code=1) from erro

    console.print(
        f"\n[bold]{settings.service_name}[/bold] {settings.version} "
        f"· ambiente [cyan]{settings.environment.value}[/cyan]\n"
    )

    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("dependência")
    tabela.add_column("estado")
    tabela.add_column("exigida agora")
    tabela.add_column("detalhe")

    faltando_exigida = False
    for nome, classe in _DEPENDENCIAS.items():
        estado, detalhe = _verificar(classe)
        exigida = nome in _EXIGIDAS_AGORA
        if exigida and estado is not Estado.CONFIGURADO:
            faltando_exigida = True
        tabela.add_row(
            nome,
            f"[{estado.cor}]{estado.value}[/{estado.cor}]",
            "sim" if exigida else "não",
            detalhe,
        )

    console.print(tabela)
    console.print(
        "\n[dim]As não exigidas estão declaradas nos ADRs e entram no PR que as usar.[/dim]"
    )

    if faltando_exigida:
        console.print("\n[red]Falta configuração exigida para este estágio.[/red]")
        raise typer.Exit(code=1)
    console.print("\n[green]Pronto para o que existe hoje.[/green]")


def _verificar(classe: type) -> tuple[Estado, str]:
    """Tenta construir um grupo de settings e traduz o resultado.

    DISTINGUE AUSENTE DE INVÁLIDO, e a distinção é acionável: ausente quer
    dizer "ninguém configurou ainda"; inválido quer dizer "alguém configurou
    errado", e o segundo caso é o que se conserta agora.
    """
    try:
        classe()
    except PydanticValidationError as erro:
        problemas = erro.errors()
        faltando = [p for p in problemas if p["type"] == "missing"]
        if len(faltando) == len(problemas):
            campos = ", ".join(".".join(str(p) for p in x["loc"]) for x in faltando)
            return Estado.AUSENTE, f"faltam: {campos}"
        primeiro = next(p for p in problemas if p["type"] != "missing")
        campo = ".".join(str(p) for p in primeiro["loc"])
        return Estado.INVALIDO, f"{campo}: {primeiro['msg']}"
    except Exception as erro:  # noqa: BLE001 — o doctor nunca deve derrubar
        return Estado.INVALIDO, str(erro)
    return Estado.CONFIGURADO, ""


if __name__ == "__main__":
    app()
