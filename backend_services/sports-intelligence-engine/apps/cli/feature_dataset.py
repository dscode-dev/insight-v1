"""`engine features ...` — as MESMAS quatro fases, pelo terminal.

NENHUMA REGRA É REIMPLEMENTADA AQUI. A CLI monta o mesmo grafo e chama os
mesmos casos de uso: construir pelo terminal e construir pelo console produzem
a mesma versão, com a mesma conferência e a mesma trilha.

AS QUATRO FASES SÃO QUATRO COMANDOS, e não um. `build` termina em `VALIDATING`;
`validate` dá o veredito; `publish` exige `--reason`. Um comando único que
compusesse e publicasse não teria onde conferir — e conferir é o que separa
«publicado» de «gravado».

O ATOR VEM DE `--actor` OU DO USUÁRIO DO SISTEMA, com `ActorKind.CLI`.
"""

from __future__ import annotations

import asyncio
import getpass
from datetime import datetime
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID
from sports_intelligence.domain.features.dataset.split import (
    FeatureDatasetSplitPolicy,
)
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

app = typer.Typer(
    name="features",
    help="Dataset histórico de features: criar, construir, conferir, publicar.",
    no_args_is_help=True,
)
console = Console()


def _ator(informado: str | None) -> Actor:
    try:
        return Actor(id=informado or getpass.getuser(), kind=ActorKind.CLI)
    except EngineError as erro:
        console.print(f"[red]{erro.message}[/red]")
        console.print("\nUse [bold]--actor SEU_USUARIO[/bold].")
        raise typer.Exit(code=1) from erro


def _executar(acao: Any) -> Any:
    async def _com_pool() -> Any:
        from apps.composition import build_container

        contêiner = build_container()
        await contêiner.database.connect()
        try:
            return await acao(contêiner)
        finally:
            await contêiner.database.close()

    try:
        return asyncio.run(_com_pool())
    except EngineError as erro:
        console.print(f"[red]{erro.category}[/red] {erro.message}")
        if erro.context:
            console.print(f"[dim]{erro.context}[/dim]")
        raise typer.Exit(code=1) from erro


def _versao(texto: str) -> DatasetVersion:
    try:
        return DatasetVersion.parse(texto)
    except EngineError as erro:
        console.print(f"[red]{erro.message}[/red]")
        raise typer.Exit(code=1) from erro


def _fronteira(texto: str) -> Any:
    """A fronteira da divisão, exigida com fuso.

    ELA É RECUSADA SEM FUSO aqui e no domínio. «01/06 às 00:00» é um instante
    diferente em cada fuso, e a divisão mudaria conforme onde o comando rodasse.
    """
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError as erro:
        console.print(f"[red]fronteira inválida: {texto!r} — use ISO-8601[/red]")
        raise typer.Exit(code=1) from erro
    if momento.tzinfo is None:
        console.print(
            "[red]fronteira sem fuso[/red] — use, por exemplo, [bold]2026-06-01T00:00:00Z[/bold]"
        )
        raise typer.Exit(code=1)
    return instant(momento)


# ------------------------------------------------------------------ criar --


@app.command("create")
def create(
    source_version_id: Annotated[
        str, typer.Argument(help="A versão PUBLICADA do corpus que alimenta o dataset")
    ],
    version: Annotated[str, typer.Option(help="A versão a criar, ex. 1.0")] = "1.0",
    reference_end: Annotated[
        str, typer.Option(help="Fronteira da divisão, ISO-8601 COM fuso")
    ] = "",
    dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Cria a versão em `DRAFT`, com as políticas já congeladas."""
    if not reference_end:
        console.print(
            "[red]--reference-end é obrigatório[/red]: a fronteira da divisão é "
            "DECLARADA, e não derivada de percentil."
        )
        raise typer.Exit(code=1)
    ator = _ator(actor)
    divisao = FeatureDatasetSplitPolicy(reference_end_exclusive=_fronteira(reference_end))

    async def acao(contêiner: Any) -> Any:
        return await contêiner.feature_dataset.create_version.execute(
            dataset_name=dataset,
            version=_versao(version),
            source_version_id=source_version_id,
            split=divisao,
            grid=DEFAULT_SNAPSHOT_GRID,
            actor=ator,
        )

    criada = _executar(acao)
    console.print(
        f"[green]versão[/green] {criada.version} [dim]{criada.id}[/dim] em {criada.status}"
    )
    console.print(f"[dim]grade   {criada.spec.grid_name} v{criada.spec.grid_version}[/dim]")
    console.print(f"[dim]divisão {criada.spec.split_name} v{criada.spec.split_version}[/dim]")


# -------------------------------------------------------------- construir --


@app.command("build")
def build(
    version_id: Annotated[str, typer.Argument(help="A versão do dataset em DRAFT")],
    dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Materializa a versão. Termina em `VALIDATING`, e NUNCA em `READY`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        versao = await contêiner.feature_dataset.datasets.version_by_id(version_id)
        if versao is None:
            console.print(f"[red]versão {version_id} não existe[/red]")
            raise typer.Exit(code=1)
        origem = await _origem_do_corpus(contêiner, versao)
        return await contêiner.feature_dataset.build_version.execute(
            version_id=version_id,
            source=origem,
            dataset_name=dataset,
            actor=ator,
        )

    saida = _executar(acao)
    console.print(
        f"[green]construída[/green] {saida.version.version} · "
        f"{saida.matches_processed:_} partidas · {saida.rows_written:_} linhas"
    )
    console.print(
        f"[dim]objetos {saida.objects_written} · "
        f"{saida.bytes_written / 1_048_576:.1f} MB · "
        f"impressão {saida.raw_content_fingerprint.value[:16]}…[/dim]"
    )
    console.print(
        f"[dim]referência {saida.counts.reference_matches:_} partidas · "
        f"avaliação {saida.counts.evaluation_matches:_} partidas[/dim]"
    )
    if saida.skipped_count:
        console.print(
            f"[yellow]{saida.skipped_count:_} partida(s) sem insumo[/yellow]: "
            f"{', '.join(saida.skipped_matches[:5])}"
        )


# ---------------------------------------------------------------- validar --


@app.command("validate")
def validate(
    version_id: Annotated[str, typer.Argument(help="A versão em VALIDATING")],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Relê os arquivos e confere. REPROVAR derruba a versão para `FAILED`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        versao = await contêiner.feature_dataset.datasets.version_by_id(version_id)
        if versao is None:
            console.print(f"[red]versão {version_id} não existe[/red]")
            raise typer.Exit(code=1)
        origem = await _origem_do_corpus(contêiner, versao)
        return await contêiner.feature_dataset.validate_version.execute(
            version_id=version_id, source=origem, actor=ator
        )

    relatorio = _executar(acao)
    tabela = Table(title=f"validação · {version_id[:8]}")
    tabela.add_column("conferência")
    tabela.add_column("resultado")
    tabela.add_row("objetos conferidos", f"{relatorio.objects_verified:_}")
    tabela.add_row("linhas conferidas", f"{relatorio.rows_verified:_}")
    tabela.add_row("partidas reconstruídas", f"{relatorio.matches_rebuilt:_}")
    console.print(tabela)
    if relatorio.passed:
        console.print("[green]aprovada[/green]")
        return
    for problema in relatorio.failures():
        console.print(f"[red]·[/red] {problema}")
    raise typer.Exit(code=1)


# --------------------------------------------------------------- publicar --


@app.command("publish")
def publish(
    version_id: Annotated[str, typer.Argument(help="A versão conferida")],
    reason: Annotated[str, typer.Option(help="Por que ESTA população, e agora")] = "",
    dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """De `VALIDATING` para `READY`. Exige motivo: publicar é uma decisão."""
    if not reason.strip():
        console.print(
            "[red]--reason é obrigatório[/red]: a partir daqui esta população é a "
            "base de comparação, e «por que esta» precisa ter resposta depois."
        )
        raise typer.Exit(code=1)
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        return await contêiner.feature_dataset.publish_version.execute(
            version_id=version_id,
            dataset_name=dataset,
            actor=ator,
            reason=reason,
        )

    publicada = _executar(acao)
    console.print(
        f"[green]publicada[/green] {publicada.version} · "
        f"{publicada.row_count:_} linhas · {publicada.status}"
    )


# ----------------------------------------------------------------- listar --


@app.command("list-versions")
def list_versions(
    dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
) -> None:
    """As versões do dataset, com estado, contagens e impressão de conteúdo."""

    async def acao(contêiner: Any) -> Any:
        identidade = await contêiner.feature_dataset.datasets.dataset_by_name(dataset)
        if identidade is None:
            console.print(f"[yellow]nenhum dataset chamado {dataset!r}[/yellow]")
            raise typer.Exit(code=0)
        return await contêiner.feature_dataset.datasets.list_versions(identidade.id, limit=50)

    versoes = _executar(acao)
    tabela = Table(title=f"versões de {dataset}")
    tabela.add_column("versão")
    tabela.add_column("estado")
    tabela.add_column("partidas", justify="right")
    tabela.add_column("linhas", justify="right")
    tabela.add_column("impressão", style="dim")
    for versao in versoes:
        tabela.add_row(
            str(versao.version),
            versao.status.value,
            f"{versao.match_count:_}",
            f"{versao.row_count:_}",
            ""
            if versao.raw_content_fingerprint is None
            else versao.raw_content_fingerprint.value[:16],
        )
    console.print(tabela)


async def _origem_do_corpus(contêiner: Any, versao: Any) -> Any:
    """A `CorpusSource` da versão de corpus que o dataset declarou.

    ELA É RECONSTRUÍDA E CONFERIDA, e não recebida por parâmetro: o caso de uso
    compara id e impressão contra o que a versão declarou, então passar outra
    coisa aqui seria recusado — e este comando não tem por onde a pessoa errar.
    """
    from sports_intelligence.domain.features.context import CorpusSource
    from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState

    corpus = await contêiner.corpus.datasets.version_by_id(versao.source_version_id)
    if corpus is None:
        console.print(f"[red]a versão de corpus {versao.source_version_id} não existe[/red]")
        raise typer.Exit(code=1)
    manifesto = await contêiner.corpus.manifests.by_version(corpus.id)
    familias = (
        frozenset()
        if manifesto is None
        else frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        )
    )
    return CorpusSource.of(corpus, published_families=familias)
