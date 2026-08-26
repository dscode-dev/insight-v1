"""`engine normalize ...` — as MESMAS seis etapas, pelo terminal.

NENHUMA REGRA É REIMPLEMENTADA AQUI. A CLI monta o mesmo grafo e chama os mesmos
casos de uso: ajustar pelo terminal e ajustar pelo console produzem os mesmos
números, com a mesma conferência e a mesma trilha.

AS SEIS ETAPAS SÃO SEIS COMANDOS, e não um. `fit` deixa o ajuste em `BUILDING`;
`validate-artifacts` dá o veredito e publica; `build` termina em `VALIDATING`;
`validate` confere; `publish` exige `--reason`. Um comando único que ajustasse e
publicasse não teria onde conferir — e conferir é o que separa «publicado» de
«gravado».

A FRONTEIRA NÃO É PEDIDA EM COMANDO NENHUM. Ela vem da versão CRUA, que já a
declarou na `spec`: perguntá-la de novo abriria a porta para um ajuste cortado
numa data diferente da divisão — que é o vazamento silencioso do §30.
"""

from __future__ import annotations

import asyncio
import getpass
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
)
from sports_intelligence.domain.features.normalized.versions import (
    DEFAULT_NORMALIZED_DATASET_NAME,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError
from sports_intelligence.domain.shared.versioning import DatasetVersion

app = typer.Typer(
    name="normalize",
    help="Ajuste causal e dataset normalizado: ajustar, conferir, construir, publicar.",
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


async def _normalizado_para_crua(contêiner: Any, raw_version_id: str) -> Any:
    """O grafo montado sob a fronteira DAQUELA versão crua.

    ELE NÃO É UM CAMPO DO CONTÊINER, e o motivo é o §89 do PR-05.1: o corte do
    ajuste é parte da identidade do plano. Montar o grafo antes de saber qual
    versão será normalizada obrigaria a escolher uma fronteira no escuro.
    """
    crua = await contêiner.feature_dataset.datasets.version_by_id(raw_version_id)
    if crua is None:
        console.print(f"[red]a versão crua {raw_version_id} não existe[/red]")
        raise typer.Exit(code=1)
    return contêiner.normalized_dataset(reference_end_exclusive=crua.spec.reference_end_exclusive)


async def _normalizado_para_versao(contêiner: Any, version_id: str) -> tuple[Any, Any]:
    """O grafo e a versão normalizada, a partir do id dela."""
    # O REGISTRO É LIDO SEM O GRAFO. Montar o grafo exigiria a fronteira, e a
    # fronteira é o que esta função está indo buscar.
    versao = await contêiner.normalized_versions.version_by_id(version_id)
    if versao is None:
        console.print(f"[red]a versão normalizada {version_id} não existe[/red]")
        raise typer.Exit(code=1)
    grafo = await _normalizado_para_crua(contêiner, versao.source_version_id)
    return grafo, versao


# ------------------------------------------------------------------ ajustar --


@app.command("fit")
def fit(
    source_version_id: Annotated[
        str, typer.Argument(help="A versão PUBLICADA do dataset cru de features")
    ],
    raw_dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Ajusta mediana e IQR sobre a REFERÊNCIA. Termina em `BUILDING`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo = await _normalizado_para_crua(contêiner, source_version_id)
        return await grafo.fit.execute(
            source_version_id=source_version_id,
            raw_dataset_name=raw_dataset,
            actor=ator,
            batch_rows=grafo.fit_batch_rows,
        )

    saida = _executar(acao)
    console.print(
        f"[green]ajustado[/green] [dim]{saida.artifact_set.id}[/dim] · "
        f"{saida.competitions} competições · {saida.artifacts:_} artefatos"
    )
    console.print(
        f"[dim]referência {saida.reference_rows:_} linhas · "
        f"impressão {saida.fingerprint[:16]}…[/dim]"
    )
    console.print(
        f"[dim]ajustados {saida.fitted:_} · amostra insuficiente "
        f"{saida.insufficient:_} · sem dispersão {saida.degenerate:_}[/dim]"
    )


# --------------------------------------------------------- conferir o ajuste --


@app.command("validate-artifacts")
def validate_artifacts(
    artifact_set_id: Annotated[str, typer.Argument(help="O conjunto em BUILDING")],
    reason: Annotated[str, typer.Option(help="Por que ESTA escala")] = "",
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Confere o ajuste e o publica. REPROVAR derruba o conjunto para `FAILED`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo = contêiner.normalized_dataset(reference_end_exclusive=contêiner.clock.now())
        return await grafo.validate_artifacts.execute(
            artifact_set_id=artifact_set_id, actor=ator, reason=reason
        )

    relatorio = _executar(acao)
    tabela = Table(title=f"ajuste · {artifact_set_id[:8]}")
    tabela.add_column("conferência")
    tabela.add_column("resultado", justify="right")
    tabela.add_row("competições", f"{relatorio.competitions:_}")
    tabela.add_row("artefatos", f"{relatorio.artifacts:_}")
    tabela.add_row("ajustados", f"{relatorio.fitted:_}")
    tabela.add_row("amostra insuficiente", f"{relatorio.insufficient:_}")
    tabela.add_row("sem dispersão", f"{relatorio.degenerate:_}")
    console.print(tabela)
    if relatorio.passed:
        console.print(f"[green]aprovado[/green] · {relatorio.fingerprint[:16]}…")
        return
    for problema in relatorio.divergences:
        console.print(f"[red]·[/red] {problema}")
    raise typer.Exit(code=1)


# -------------------------------------------------------------------- criar --


@app.command("create")
def create(
    source_version_id: Annotated[str, typer.Argument(help="A versão crua publicada")],
    artifact_set_id: Annotated[str, typer.Argument(help="O ajuste publicado")],
    version: Annotated[str, typer.Option(help="A versão a criar, ex. 1.0")] = "1.0",
    dataset: Annotated[str, typer.Option()] = DEFAULT_NORMALIZED_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Cria a versão normalizada em `DRAFT`, com a representação congelada."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo = await _normalizado_para_crua(contêiner, source_version_id)
        return await grafo.create_version.execute(
            version=_versao(version),
            source_version_id=source_version_id,
            artifact_set_id=artifact_set_id,
            dataset_name=dataset,
            actor=ator,
        )

    criada = _executar(acao)
    console.print(
        f"[green]versão[/green] {criada.version} [dim]{criada.id}[/dim] em {criada.status}"
    )
    console.print(
        f"[dim]representação {criada.representation_fingerprint[:16]}… · "
        f"origem {criada.source_row_count:_} linhas[/dim]"
    )


# ---------------------------------------------------------------- construir --


@app.command("build")
def build(
    version_id: Annotated[str, typer.Argument(help="A versão normalizada em DRAFT")],
    dataset: Annotated[str, typer.Option()] = DEFAULT_NORMALIZED_DATASET_NAME,
    raw_dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Transforma as linhas, 1:1. Termina em `VALIDATING`, e NUNCA em `READY`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo, _ = await _normalizado_para_versao(contêiner, version_id)
        return await grafo.build_version.execute(
            version_id=version_id,
            dataset_name=dataset,
            raw_dataset_name=raw_dataset,
            actor=ator,
            part_rows=grafo.part_rows,
            max_pending_rows=grafo.max_pending_rows,
            batch_rows=grafo.build_batch_rows,
        )

    saida = _executar(acao)
    console.print(
        f"[green]construída[/green] {saida.version.version} · "
        f"{saida.matches:_} partidas · {saida.rows_written:_} linhas"
    )
    console.print(
        f"[dim]objetos {len(saida.objects)} · {saida.bytes / 1_048_576:.1f} MB · "
        f"impressão {saida.fingerprint[:16]}…[/dim]"
    )
    console.print(
        f"[dim]referência {saida.reference_fingerprint[:16]}… · "
        f"avaliação {saida.evaluation_fingerprint[:16]}…[/dim]"
    )
    sem_escala = saida.availability.artifact_unavailable
    if sem_escala:
        console.print(
            f"[yellow]{sem_escala:_} célula(s) sem escala[/yellow] — o ajuste não "
            "encontrou dispersão ou amostra nessas competições"
        )


# ------------------------------------------------------------------ validar --


@app.command("validate")
def validate(
    version_id: Annotated[str, typer.Argument(help="A versão em VALIDATING")],
    raw_dataset: Annotated[str, typer.Option()] = DEFAULT_FEATURE_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Relê os arquivos e confere. REPROVAR derruba a versão para `FAILED`."""
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo, _ = await _normalizado_para_versao(contêiner, version_id)
        return await grafo.validate_version.execute(
            version_id=version_id, raw_dataset_name=raw_dataset, actor=ator
        )

    relatorio = _executar(acao)
    tabela = Table(title=f"validação · {version_id[:8]}")
    tabela.add_column("conferência")
    tabela.add_column("resultado", justify="right")
    tabela.add_row("objetos conferidos", f"{relatorio.objects:_}")
    tabela.add_row("linhas conferidas", f"{relatorio.rows:_}")
    tabela.add_row("linhas cruas", f"{relatorio.source_rows:_}")
    console.print(tabela)
    if relatorio.passed:
        console.print("[green]aprovada[/green]")
        return
    for problema in relatorio.failures:
        console.print(f"[red]·[/red] {problema}")
    raise typer.Exit(code=1)


# ----------------------------------------------------------------- publicar --


@app.command("publish")
def publish(
    version_id: Annotated[str, typer.Argument(help="A versão conferida")],
    reason: Annotated[str, typer.Option(help="Por que ESTA representação, e agora")] = "",
    dataset: Annotated[str, typer.Option()] = DEFAULT_NORMALIZED_DATASET_NAME,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """De `VALIDATING` para `READY`. Exige motivo: publicar é uma decisão."""
    if not reason.strip():
        console.print(
            "[red]--reason é obrigatório[/red]: a partir daqui esta representação é a "
            "base sob a qual duas partidas são comparáveis, e «por que esta» precisa "
            "ter resposta depois."
        )
        raise typer.Exit(code=1)
    ator = _ator(actor)

    async def acao(contêiner: Any) -> Any:
        grafo, _ = await _normalizado_para_versao(contêiner, version_id)
        return await grafo.publish_version.execute(
            version_id=version_id, dataset_name=dataset, actor=ator, reason=reason
        )

    publicada = _executar(acao)
    console.print(
        f"[green]publicada[/green] {publicada.version} · "
        f"{publicada.row_count:_} linhas · {publicada.status}"
    )


# -------------------------------------------------------------------- ver --


@app.command("show")
def show(
    dataset: Annotated[str, typer.Option()] = DEFAULT_NORMALIZED_DATASET_NAME,
) -> None:
    """As versões normalizadas, com as impressões que respondem «é a mesma base?».

    A COLUNA DE REFERÊNCIA É A QUE IMPORTA. Duas versões com a MESMA impressão
    de referência foram normalizadas sobre a mesma base estatística — ainda que
    a avaliação de uma tenha o dobro de partidas da outra.
    """

    async def acao(contêiner: Any) -> Any:
        identidade = await contêiner.normalized_versions.dataset_by_name(dataset)
        if identidade is None:
            console.print(f"[yellow]nenhum dataset chamado {dataset!r}[/yellow]")
            raise typer.Exit(code=0)
        return await contêiner.normalized_versions.list_versions(identidade.id, limit=50)

    versoes = _executar(acao)
    tabela = Table(title=f"versões normalizadas de {dataset}")
    tabela.add_column("versão")
    tabela.add_column("estado")
    tabela.add_column("linhas", justify="right")
    tabela.add_column("representação", style="dim")
    tabela.add_column("referência", style="dim")
    for versao in versoes:
        tabela.add_row(
            str(versao.version),
            versao.status.value,
            f"{versao.row_count:_}",
            versao.representation_fingerprint[:16],
            ""
            if versao.normalized_reference_content_fingerprint is None
            else versao.normalized_reference_content_fingerprint.value[:16],
        )
    console.print(tabela)
