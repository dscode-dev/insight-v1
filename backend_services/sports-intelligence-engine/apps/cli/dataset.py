"""`engine dataset ...` — o mesmo fluxo da API, pelos mesmos casos de uso.

NENHUMA REGRA É REIMPLEMENTADA AQUI. A CLI monta o mesmo contêiner que a
Control API monta e chama os mesmos objetos. É o que garante que promover um
dataset pelo terminal e promovê-lo pela API façam exatamente a mesma coisa —
inclusive as validações, a trilha de auditoria e os eventos.

O caminho oposto é o comum e é caro: a CLI fala direto com o banco "porque é
mais simples", e seis meses depois ela permite uma transição que a API recusa.
Ninguém descobre até um dataset aparecer num estado que o grafo não prevê.

O UPLOAD TAMBÉM É EM BLOCOS AQUI, e não por simetria: o limite de memória de
um laptop é menor que o do servidor, não maior. Um `Path.read_bytes()` num
dump de 2 GB derruba o terminal de quem opera.

O ATOR É QUEM ESTÁ RODANDO. Vem de `--actor` ou do usuário do sistema
operacional, e a trilha registra `ActorKind.CLI` — distinto de
`HUMAN_OPERATOR`, porque "aprovou pelo console" e "rodou um comando local" são
fatos diferentes numa investigação.
"""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.formats import resolve_declared_format
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.models import DatasetFilter, Page
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import IssueSeverity
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import parse_instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ingestion.historical.upload import chunks_from_path

app = typer.Typer(
    name="dataset",
    help="Registro e ingestão manual de datasets históricos.",
    no_args_is_help=True,
)
console = Console()

_CORES_DE_SEVERIDADE = {
    IssueSeverity.INFO: "dim",
    IssueSeverity.WARNING: "yellow",
    IssueSeverity.ERROR: "red",
    IssueSeverity.BLOCKING: "bold red",
}


def _ator(informado: str | None) -> Actor:
    """Quem está rodando. NUNCA um padrão genérico.

    `getpass.getuser()` e não `"cli"`: um `created_by = "cli"` na trilha
    responde "por onde" quando a pergunta é "quem", e a diferença só aparece
    quando alguém precisa da resposta.

    DENTRO DE CONTÊINER o usuário costuma ser `root`, que o domínio recusa
    pelo mesmo motivo. A recusa é traduzida aqui na ação que resolve — em vez
    de deixar a mensagem do domínio, correta e sem saída, chegar ao terminal.
    """
    try:
        return Actor(id=informado or getpass.getuser(), kind=ActorKind.CLI)
    except EngineError as erro:
        console.print(f"[red]{erro.message}[/red]")
        console.print(
            "\nUse [bold]--actor SEU_USUARIO[/bold]. "
            "Toda operação administrativa tem autor, e ele vai para a trilha."
        )
        raise typer.Exit(code=1) from erro


def _contêiner() -> Any:
    """Monta o mesmo grafo da API. Import tardio, de propósito.

    `engine dataset --help` não deve exigir PostgreSQL configurado. Com o
    import no topo, construir o módulo já tentaria ler as settings, e o
    `--help` morreria com erro de configuração — que é a pior primeira
    experiência possível com uma ferramenta.
    """
    from apps.composition import build_container

    return build_container()


def _executar(corrotina: Any) -> Any:
    """Roda a corrotina abrindo e fechando o pool, e traduz erro de domínio.

    O ERRO SAI COMO MENSAGEM E CÓDIGO DE SAÍDA, não como traceback. Um
    traceback de 40 linhas para dizer "esse dataset não existe" esconde a
    frase que importa no meio do ruído.
    """

    async def _com_pool() -> Any:
        contêiner = _contêiner()
        await contêiner.database.connect()
        try:
            return await corrotina(contêiner)
        finally:
            await contêiner.database.close()

    try:
        return asyncio.run(_com_pool())
    except EngineError as erro:
        console.print(f"[red]{erro.category}[/red] {erro.message}")
        if erro.context:
            console.print(f"[dim]{erro.context}[/dim]")
        raise typer.Exit(code=1) from erro


@app.command("create")
def criar(
    name: Annotated[str, typer.Option(help="Slug do dataset: minúsculas e hífen.")],
    source_name: Annotated[str, typer.Option(help="Nome da fonte.")],
    license_class: Annotated[LicenseClass, typer.Option()],
    retrieved_at: Annotated[str, typer.Option(help="ISO-8601 COM fuso: 2026-08-01T10:00:00Z")],
    competition: Annotated[list[CompetitionCode], typer.Option(help="Repetível.")],
    version: Annotated[str, typer.Option()] = "v1.0",
    source_type: Annotated[SourceType, typer.Option()] = SourceType.OPEN_DATA,
    provider_id: Annotated[str | None, typer.Option()] = None,
    source_url: Annotated[str | None, typer.Option()] = None,
    publisher: Annotated[str | None, typer.Option()] = None,
    season: Annotated[list[str] | None, typer.Option(help="Rótulos, repetível.")] = None,
    description: Annotated[str | None, typer.Option()] = None,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Registra um dataset. Repetir o comando não cria um segundo."""
    fonte = DatasetSource(
        source_name=source_name,
        source_type=source_type,
        license_class=license_class,
        retrieved_at=parse_instant(retrieved_at),
        source_url=source_url,
        publisher=publisher,
        provider_id=ProviderId(provider_id) if provider_id else None,
    )

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.register.execute(
            actor=_ator(actor),
            name=name,
            version=DatasetVersion.parse(version),
            source=fonte,
            declared_competitions=frozenset(competition),
            declared_seasons=tuple(season or ()),
            description=description,
        )

    dataset, criado = _executar(_acao)
    marca = "[green]criado[/green]" if criado else "[yellow]já existia[/yellow]"
    console.print(f"{marca} [bold]{dataset.name}[/bold]@{dataset.version}")
    console.print(f"  id        {dataset.id}")
    console.print(f"  estado    {dataset.lifecycle}")
    if dataset.needs_license_review:
        console.print(
            f"  [yellow]licença {dataset.source.license_class}: guardar e validar é "
            "legítimo; promover a uso comercial exige decisão humana.[/yellow]"
        )


@app.command("list")
def listar(
    lifecycle: Annotated[DatasetLifecycle | None, typer.Option()] = None,
    competition: Annotated[CompetitionCode | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option(min=1, max=Page.MAX_LIMIT)] = 25,
    offset: Annotated[int, typer.Option(min=0)] = 0,
) -> None:
    """Lista os datasets registrados."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.listing.execute(
            filters=DatasetFilter(lifecycle=lifecycle, competition=competition),
            page=Page(limit=limit, offset=offset),
        )

    itens, total = _executar(_acao)
    tabela = Table(show_header=True, header_style="bold")
    for coluna in ("nome", "versão", "estado", "fonte", "licença", "arquivos", "bytes"):
        tabela.add_column(coluna)
    for resumo in itens:
        tabela.add_row(
            resumo.name,
            str(resumo.version),
            resumo.lifecycle.value,
            resumo.source_name,
            resumo.license_class,
            str(resumo.file_count),
            f"{resumo.total_bytes:,}".replace(",", "."),
        )
    console.print(tabela)
    console.print(f"[dim]{len(itens)} de {total}[/dim]")


@app.command("show")
def mostrar(dataset_id: str) -> None:
    """Detalha um dataset, com os arquivos e o histórico de estados."""

    async def _acao(contêiner: Any) -> Any:
        identificador = DatasetId.parse(dataset_id)
        dataset = await contêiner.get.execute(identificador)
        return dataset, await contêiner.get.datasets.transitions_of(identificador)

    dataset, transicoes = _executar(_acao)
    console.print(f"\n[bold]{dataset.name}[/bold]@{dataset.version}  {dataset.id}")
    console.print(f"estado       {dataset.lifecycle}")
    console.print(
        f"fonte        {dataset.source.source_name} "
        f"({dataset.source.source_type}, {dataset.source.license_class})"
    )
    console.print(
        f"declara      {', '.join(sorted(c.value for c in dataset.declared_competitions))}"
    )
    if dataset.declared_seasons:
        console.print(f"temporadas   {', '.join(dataset.declared_seasons)}")
    # `intelligence_ready` DITO SEMPRE, inclusive em STAGED. É a linha que
    # impede alguém de ler "STAGED" e concluir que o dado está em uso.
    console.print("pronto p/ IA [red]não[/red]  [dim](STAGED ≠ HISTORICAL_ACTIVE)[/dim]")

    if dataset.files:
        tabela = Table(show_header=True, header_style="bold", title="arquivos")
        for coluna in ("arquivo", "formato", "sha256", "bytes", "estado", "linhas"):
            tabela.add_column(coluna)
        for arquivo in dataset.files:
            cor = "green" if arquivo.staging_state.counts_as_present else "yellow"
            tabela.add_row(
                arquivo.safe_filename,
                arquivo.format.value,
                arquivo.content_hash.short,
                f"{arquivo.size_bytes:,}".replace(",", "."),
                f"[{cor}]{arquivo.staging_state.value}[/{cor}]",
                str(arquivo.row_count) if arquivo.row_count is not None else "—",
            )
        console.print(tabela)

    if transicoes:
        console.print("\n[bold]histórico[/bold]")
        for de, para, motivo, quando in transicoes:
            console.print(f"  {quando}  {de} → {para}  [dim]{motivo}[/dim]")


@app.command("upload")
def enviar(
    dataset_id: str,
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    file_format: Annotated[
        str | None, typer.Option("--format", help="PARQUET | CSV | JSONL")
    ] = None,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Envia um arquivo, em blocos, calculando o SHA-256 durante a leitura."""
    # A extensão só serve como SUGESTÃO quando o operador não declara nada, e
    # é dito na mensagem. Ela nunca substitui a conferência contra os bytes,
    # que acontece na validação.
    declarado = file_format or path.suffix.lstrip(".")
    if not file_format:
        console.print(
            f"[dim]formato não declarado; supondo {declarado.upper()} pela extensão — "
            "os bytes são conferidos na validação[/dim]"
        )
    formato = resolve_declared_format(declarado)
    tamanho = path.stat().st_size
    console.print(
        f"enviando [bold]{path.name}[/bold] · {tamanho:,} bytes · {formato}".replace(",", ".")
    )

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.attach.execute(
            actor=_ator(actor),
            dataset_id=DatasetId.parse(dataset_id),
            filename=path.name,
            file_format=formato,
            stream=chunks_from_path(str(path)),
        )

    resultado = _executar(_acao)
    arquivo = resultado.file
    console.print(f"  sha256    {arquivo.content_hash}")
    console.print(f"  bytes     {arquivo.size_bytes:,}".replace(",", "."))
    console.print(f"  chave     [dim]{arquivo.object_key}[/dim]")
    if resultado.was_duplicate:
        console.print(
            "  [yellow]estes bytes já estavam registrados neste dataset — "
            "nada foi gravado de novo[/yellow]"
        )
    else:
        console.print("  [green]gravado e conferido[/green]")


@app.command("validate")
def validar(
    dataset_id: str,
    required: Annotated[
        list[str] | None, typer.Option(help="Coluna obrigatória, repetível.")
    ] = None,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Roda a validação estrutural e imprime o relatório."""
    from sports_intelligence.domain.datasets.schema import DatasetSchemaContract

    contrato = DatasetSchemaContract(required_columns=frozenset(required)) if required else None

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.validate.execute(
            actor=_ator(actor),
            dataset_id=DatasetId.parse(dataset_id),
            contract=contrato,
        )

    _imprimir_relatorio(_executar(_acao))


@app.command("validation")
def relatorio(
    dataset_id: str,
    report_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Mostra o relatório de validação mais recente, ou um específico."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.validation.execute(DatasetId.parse(dataset_id), report_id=report_id)

    _imprimir_relatorio(_executar(_acao))


@app.command("manifest")
def manifesto(dataset_id: str) -> None:
    """Mostra o manifesto congelado e sua impressão."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.manifest.execute(DatasetId.parse(dataset_id))

    m = _executar(_acao)
    console.print(f"\n[bold]impressão[/bold] {m.fingerprint}")
    console.print(f"validação  {m.validation_id} · {m.validation_status}")
    console.print(f"arquivos   {len(m.files)} · {m.total_bytes:,} bytes".replace(",", "."))
    for arquivo in m.files:
        console.print(
            f"  {arquivo.sha256.short}  {arquivo.filename}  "
            f"{arquivo.row_count if arquivo.row_count is not None else '—'} linha(s)"
        )


@app.command("stage")
def promover(
    dataset_id: str,
    reason: Annotated[str, typer.Option(help="Por que este dataset pode seguir.")],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Promove para `STAGED`. Exige motivo — é decisão humana."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.stage.execute(
            actor=_ator(actor), dataset_id=DatasetId.parse(dataset_id), reason=reason
        )

    dataset = _executar(_acao)
    console.print(f"[green]STAGED[/green] {dataset.name}@{dataset.version}")
    console.print(
        "[dim]STAGED significa: bruto preservado e estruturalmente apto a ENTRAR em "
        "resolução de identidade e fusão.\nNÃO significa apto a alimentar "
        "inteligência — isso é o PR-03 mais a barreira do ADR-0007.[/dim]"
    )


def _imprimir_relatorio(r: Any) -> None:
    cor = "green" if not r.has_blocking_issues else "red"
    console.print(f"\n[{cor}]{r.status}[/{cor}]  [dim]{r.id}[/dim]")
    console.print(
        f"{r.files_checked} arquivo(s) · {r.rows_observed:,} linha(s) · "
        f"{r.issue_count} achado(s)".replace(",", ".")
        + (f"  [yellow](amostrados {len(r.issues)})[/yellow]" if r.truncated else "")
    )
    console.print(f"validador  {r.validator_version}")

    if r.issues:
        tabela = Table(show_header=True, header_style="bold")
        for coluna in ("sev", "código", "onde", "mensagem"):
            tabela.add_column(coluna)
        for issue in r.issues:
            cor_sev = _CORES_DE_SEVERIDADE[issue.severity]
            tabela.add_row(
                f"[{cor_sev}]{issue.severity}[/{cor_sev}]",
                issue.code.value,
                issue.location or "—",
                issue.message[:90],
            )
        console.print(tabela)

    for observacao in r.schema_observations:
        colunas = ", ".join(c.name for c in observacao.columns[:12])
        extra = f" (+{observacao.column_count - 12})" if observacao.column_count > 12 else ""
        console.print(f"[dim]{observacao.row_count} linhas · {colunas}{extra}[/dim]")

    if r.has_blocking_issues:
        console.print("\n[red]há impeditivos: este dataset não pode ir para STAGED.[/red]")
    else:
        console.print("\n[green]sem impeditivos: pode ir para STAGED.[/green]")
