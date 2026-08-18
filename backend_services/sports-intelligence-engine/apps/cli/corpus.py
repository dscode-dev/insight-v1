"""`engine corpus ...` — os MESMOS casos de uso da Control API (§78).

NENHUMA REGRA É REIMPLEMENTADA AQUI. A CLI monta o mesmo grafo e chama os
mesmos objetos: publicar pelo terminal e publicar pelo console produzem a mesma
versão, com a mesma conferência e a mesma trilha. Uma orquestração própria por
porta faria uma delas ganhar uma verificação que a outra não tem — e a
diferença apareceria em produção como «pela CLI funciona».

O GATE CONTINUA SENDO O GATE. `engine corpus build` termina em `VALIDATING`, e
publicar é um comando separado que exige `--reason`. Um comando único que
compõe e publica não teria onde conferir, e conferir é o que separa
«publicado» de «gravado» (§12, §67).

O ATOR VEM DE `--actor` OU DO USUÁRIO DO SISTEMA, com `ActorKind.CLI`. Publicar
é decisão administrativa, e a trilha registra quem decidiu — nunca um
`system`/`root` embutido no código (PR-04.2 §75).
"""

from __future__ import annotations

import asyncio
import getpass
import json
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError
from sports_intelligence.domain.shared.identity import CompetitionId, SeasonId
from sports_intelligence.domain.shared.versioning import DatasetVersion

app = typer.Typer(
    name="corpus",
    help="Corpus histórico canônico: datasets, versões, manifesto.",
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


# --------------------------------------------------------------- dataset --


@app.command("create-dataset")
def create_dataset(
    name: Annotated[str, typer.Argument(help="Nome estável do corpus")],
    description: Annotated[str | None, typer.Option()] = None,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Declara a identidade lógica do corpus. Não cria conteúdo nenhum."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.create_dataset.execute(
            actor=ator, name=name, description=description
        )

    criado = _executar(acao)
    console.print(f"[green]dataset[/green] {criado.name} [dim]{criado.id}[/dim]")


@app.command("list-datasets")
def list_datasets() -> None:
    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.datasets.list_datasets(limit=100)

    encontrados, total = _executar(acao)
    tabela = Table(title=f"datasets históricos ({total})")
    tabela.add_column("nome")
    tabela.add_column("id", style="dim")
    tabela.add_column("criado em")
    for dataset in encontrados:
        tabela.add_row(dataset.name, dataset.id, dataset.created_at.isoformat())
    console.print(tabela)


# ---------------------------------------------------------------- versão --


@app.command("build")
def build_version(
    dataset_id: Annotated[str, typer.Argument()],
    version: Annotated[str, typer.Option(help="Ex.: 1.0")],
    usage: Annotated[UsageScope, typer.Option()] = UsageScope.RESEARCH,
    build_run: Annotated[list[str] | None, typer.Option(help="id de build")] = None,
    quality_run: Annotated[str | None, typer.Option()] = None,
    scope: Annotated[
        list[str] | None,
        typer.Option(help="COMPETICAO:TEMPORADA:competition_id:season_id (repetível)"),
    ] = None,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Compõe a versão. Ela termina em VALIDATING e NÃO publicada (§12)."""
    ator = _ator(actor)
    if not build_run:
        console.print("[red]--build-run é obrigatório[/red]")
        raise typer.Exit(code=1)
    if not scope:
        console.print(
            "[red]--scope é obrigatório[/red]: o escopo é DECLARADO e não "
            "descoberto a partir do que os builds produziram (§65)"
        )
        raise typer.Exit(code=1)

    escopo = CorpusScope.of(*(_entrada_de_escopo(s) for s in scope), usage=usage)
    entradas = VersionInputs(
        build_run_ids=tuple(build_run),
        quality_run_ids=() if quality_run is None else (quality_run,),
    )

    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.build_version.execute(
            actor=ator,
            dataset_id=dataset_id,
            version=_versao(version),
            scope=escopo,
            inputs=entradas,
            quality_run_id=quality_run,
        )

    saida = _executar(acao)
    console.print(
        f"[green]composta[/green] {saida.version.version} "
        f"[{saida.version.status}] · {saida.members_written} partida(s) · "
        f"{saida.objects_written} objeto(s)"
    )
    console.print(f"impressão: [bold]{saida.manifest.corpus_fingerprint.value}[/bold]")
    console.print(
        "[dim]a versão NÃO está publicada. `engine corpus publish` confere e congela.[/dim]"
    )


@app.command("publish")
def publish_version(
    version_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option(help="Por que publicar. Obrigatório.")],
    supersede_previous: Annotated[bool, typer.Option()] = True,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """O GATE: confere contagem, impressão e manifesto, e congela a versão."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.publish_version.execute(
            actor=ator,
            version_id=version_id,
            reason=reason,
            supersede_previous=supersede_previous,
        )

    publicada = _executar(acao)
    console.print(
        f"[green]HISTORICAL_CANONICAL_READY[/green] {publicada.version} "
        f"[{publicada.usage.value}] · {publicada.match_count} partida(s)"
    )
    console.print(
        "[dim]pronto para ser LIDO. Não é espaço vetorial ativo — isso é o PR-05 (§4).[/dim]"
    )


@app.command("versions")
def list_versions(
    dataset_id: Annotated[str, typer.Argument()],
    status: Annotated[DatasetVersionStatus | None, typer.Option()] = None,
    usage: Annotated[UsageScope | None, typer.Option()] = None,
) -> None:
    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.datasets.list_versions(
            dataset_id, status=status, usage=usage, limit=100
        )

    encontradas, total = _executar(acao)
    tabela = Table(title=f"versões ({total})")
    tabela.add_column("versão")
    tabela.add_column("escopo")
    tabela.add_column("estado")
    tabela.add_column("partidas", justify="right")
    tabela.add_column("impressão", style="dim")
    for versao in encontradas:
        tabela.add_row(
            str(versao.version),
            versao.usage.value,
            versao.status.value,
            str(versao.match_count),
            (versao.corpus_fingerprint.value[:16] if versao.corpus_fingerprint else "—"),
        )
    console.print(tabela)


@app.command("manifest")
def show_manifest(version_id: Annotated[str, typer.Argument()]) -> None:
    """O manifesto da versão, como JSON canônico."""

    async def acao(contêiner: Any) -> Any:
        return await contêiner.corpus.manifests.by_version(version_id)

    manifesto = _executar(acao)
    if manifesto is None:
        console.print(f"[yellow]versão {version_id} sem manifesto[/yellow]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(manifesto.as_canonical(), ensure_ascii=False))


# ----------------------------------------------------------------- apoio --


def _versao(texto: str) -> DatasetVersion:
    maior, _, menor = texto.partition(".")
    try:
        return DatasetVersion(major=int(maior), minor=int(menor or 0))
    except ValueError as erro:
        console.print(f"[red]versão {texto!r} inválida — use MAIOR.MENOR[/red]")
        raise typer.Exit(code=1) from erro


def _entrada_de_escopo(bruto: str) -> ScopeEntry:
    """`COMPETICAO:TEMPORADA:competition_id:season_id`.

    OS IDS SÃO EXIGIDOS e não descobertos por nome (§65): casar competição e
    temporada por texto é como um fato da temporada A entra na temporada B.
    """
    import uuid

    partes = bruto.split(":")
    if len(partes) != 4:
        console.print(
            f"[red]escopo {bruto!r} inválido[/red] — use "
            "COMPETICAO:TEMPORADA:competition_id:season_id"
        )
        raise typer.Exit(code=1)
    competicao, temporada, competition_id, season_id = partes
    try:
        return ScopeEntry(
            competition=CompetitionCode(competicao),
            season_label=temporada,
            competition_id=CompetitionId(uuid.UUID(competition_id)),
            season_id=SeasonId(uuid.UUID(season_id)),
        )
    except (ValueError, EngineError) as erro:
        console.print(f"[red]escopo {bruto!r} inválido:[/red] {erro}")
        raise typer.Exit(code=1) from erro
