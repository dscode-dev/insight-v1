"""`engine resolution ...` e `engine fusion ...` — os mesmos casos de uso.

NENHUMA REGRA É REIMPLEMENTADA AQUI, como no PR-02. A CLI monta o mesmo grafo
que a Control API e chama os mesmos objetos: resolver um item da fila pelo
terminal e resolvê-lo pelo console produzem a mesma decisão, com a mesma
evidência e a mesma trilha.

O ATOR É HUMANO NA FILA DE REVISÃO, e o domínio cobra isso: uma decisão com
método `MANUAL_REVIEW` atribuída a um ator de serviço é recusada. Aqui o ator
vem de `--actor` ou do usuário do sistema, com `ActorKind.CLI` — que é humano
por um caminho diferente do console, e a trilha registra a diferença.
"""

from __future__ import annotations

import asyncio
import getpass
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.review import ReviewFilter, ReviewStatus
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError
from sports_intelligence.domain.shared.identity import DatasetId, EntityId
from sports_intelligence.domain.sources.mapping import (
    SourceFieldMapping,
    SourceMappingDefinition,
    ValueTransform,
)
from sports_intelligence.domain.sources.semantics import SemanticRole

app = typer.Typer(
    name="resolution",
    help="Resolução de identidade sobre datasets STAGED.",
    no_args_is_help=True,
)
fusion_app = typer.Typer(
    name="fusion", help="Fusão de fontes já resolvidas.", no_args_is_help=True
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
    """Roda com o pool aberto e traduz erro de domínio em mensagem."""

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


# ------------------------------------------------------------ mapeamento --


@app.command("mapping")
def definir_mapeamento(
    dataset_id: str,
    arquivo: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Registra o mapeamento de fonte a partir de um JSON.

    O ARQUIVO É DECLARATIVO E INERTE (§81). Ele diz que a coluna `HomeTeam`
    carrega `HOME_TEAM_NAME` — uma afirmação sobre o ARQUIVO. Não há campo de
    expressão, não há `eval`: um mapeamento vem de fora, e o que vem de fora
    nunca vira código.

        {
          "provider_id": "football_data",
          "conventions": {"season_convention": "SPLIT_YEAR"},
          "fields": [
            {"column": "Div",      "role": "COMPETITION_NAME"},
            {"column": "Season",   "role": "SEASON_LABEL"},
            {"column": "HomeTeam", "role": "HOME_TEAM_NAME"},
            {"column": "AwayTeam", "role": "AWAY_TEAM_NAME"},
            {"column": "Date",     "role": "KICKOFF_DATE", "date_format": "%d/%m/%Y"}
          ]
        }
    """
    dados = json.loads(arquivo.read_text(encoding="utf-8"))

    async def _acao(contêiner: Any) -> Any:
        from sports_intelligence.domain.shared.identity import ProviderId

        identificador = DatasetId.parse(dataset_id)
        dataset = await contêiner.get.execute(identificador)
        definicao = SourceMappingDefinition.draft(
            dataset_id=identificador,
            dataset_version=dataset.version,
            provider_id=ProviderId(dados["provider_id"]),
            version=int(dados.get("version", 1)),
            fields=tuple(
                SourceFieldMapping(
                    column=f["column"],
                    role=SemanticRole(f["role"]),
                    transform=ValueTransform(f.get("transform", "TRIM")),
                    date_format=f.get("date_format"),
                    timezone=f.get("timezone"),
                )
                for f in dados["fields"]
            ),
            at=contêiner.clock.now(),
            created_by=_ator(actor).id,
            conventions=dados.get("conventions", {}),
            description=dados.get("description"),
        )
        return await contêiner.resolution.register_mapping.execute(
            actor=_ator(actor), dataset_id=identificador, definition=definicao
        )

    gravado = _executar(_acao)
    console.print(f"[green]mapeamento v{gravado.version}[/green] {gravado.provider_id}")
    tabela = Table(show_header=True, header_style="bold")
    for coluna in ("coluna", "papel", "transformação"):
        tabela.add_column(coluna)
    for campo in gravado.fields:
        tabela.add_row(campo.column, campo.role.value, campo.transform.value)
    console.print(tabela)


# ------------------------------------------------------------- execução --


@app.command("run")
def rodar(
    dataset_id: str,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Executa a resolução de identidade sobre um dataset STAGED."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.run_resolution_for_dataset(
            actor=_ator(actor), dataset_id=DatasetId.parse(dataset_id)
        )

    saida = _executar(_acao)
    _imprimir_execucao(saida.run)
    if saida.review_items:
        console.print(
            f"\n[yellow]{saida.review_items} item(ns) na fila de revisão.[/yellow] "
            "Use [bold]engine resolution review list[/bold]."
        )


@app.command("show")
def mostrar(run_id: str) -> None:
    """Detalha uma execução de resolução."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.get_resolution_run.execute(run_id)

    _imprimir_execucao(_executar(_acao))


@app.command("decisions")
def decisoes(
    run_id: str,
    subject: Annotated[SubjectType | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 30,
) -> None:
    """As decisões de uma execução, com evidência e alternativas."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.list_decisions.execute(
            run_id, subject=subject, limit=limit
        )

    itens, total = _executar(_acao)
    tabela = Table(show_header=True, header_style="bold")
    for coluna in ("sujeito", "valor", "status", "método", "conf.", "entidade"):
        tabela.add_column(coluna)
    for d in itens:
        cor = {"RESOLVED": "green", "REJECTED": "red"}.get(d.status.value, "yellow")
        tabela.add_row(
            d.subject_type.value,
            d.source_value.raw[:28],
            f"[{cor}]{d.status.value}[/{cor}]",
            d.method.value,
            f"{d.confidence.value:.2f}",
            str(d.canonical_entity_id)[:12] if d.canonical_entity_id else "—",
        )
    console.print(tabela)
    console.print(f"[dim]{len(itens)} de {total}[/dim]")


# ----------------------------------------------------------- revisão --

review_app = typer.Typer(name="review", help="A fila humana.", no_args_is_help=True)
app.add_typer(review_app)


@review_app.command("list")
def listar_revisao(
    subject: Annotated[SubjectType | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 25,
) -> None:
    """Os itens abertos, mais antigos primeiro."""

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.list_review.execute(
            filters=ReviewFilter(status=ReviewStatus.OPEN, subject_type=subject),
            limit=limit,
        )

    itens, total = _executar(_acao)
    for item in itens:
        console.print(f"\n[bold]{item.id}[/bold]  {item.subject}")
        console.print(f"  motivo    {item.reason_status.value}")
        console.print(f"  registro  [dim]{item.subject.record_ref}[/dim]")
        if not item.candidates:
            console.print("  [dim]sem candidatos — nada a escolher[/dim]")
        for candidato in item.candidates:
            console.print(
                f"    {candidato.score:.3f}  {candidato.canonical_entity_id}  "
                f"{candidato.label or ''}  [dim]{candidato.evidence_summary}[/dim]"
            )
    console.print(f"\n[dim]{len(itens)} de {total} aberto(s)[/dim]")


@review_app.command("resolve")
def resolver_item(
    item_id: str,
    entity_id: Annotated[str, typer.Option(help="O candidato escolhido.")],
    reason: Annotated[str, typer.Option(help="Por que este e não os outros.")],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Escolhe um candidato. Produz decisão, alias e — quando há — mapeamento.

    É O CICLO QUE A FILA EXISTE PARA FECHAR (§88): um humano decide uma vez, o
    alias fica gravado, e a próxima execução resolve sozinha.
    """

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.resolve_review.execute(
            actor=_ator(actor),
            item_id=item_id,
            chosen=EntityId.parse(entity_id),
            reason=reason,
        )

    decisao = _executar(_acao)
    console.print(f"[green]resolvido[/green] {decisao.source_value.raw!r} → {entity_id}")
    console.print(f"  decisão   {decisao.id}")
    console.print(f"  método    {decisao.method.value}")
    console.print(
        "\n[dim]O alias foi gravado: a próxima execução resolve este nome sozinha.[/dim]"
    )


@review_app.command("reject")
def rejeitar_item(
    item_id: str,
    reason: Annotated[str, typer.Option(help="Por que nenhum candidato serve.")],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Recusa todos os candidatos. TAMBÉM produz decisão.

    Sem ela, o item rejeitado seria indistinguível de um que ninguém olhou — e
    a próxima execução o recolocaria na fila.
    """

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.resolve_review.execute(
            actor=_ator(actor), item_id=item_id, chosen=None, reason=reason
        )

    decisao = _executar(_acao)
    console.print(f"[yellow]rejeitado[/yellow] {decisao.source_value.raw!r}")
    console.print(f"  decisão   {decisao.id}")


# ------------------------------------------------------------- fusão --


@fusion_app.command("run")
def rodar_fusao(
    resolution_run: Annotated[list[str], typer.Option(help="Repetível.")],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Funde as saídas de execuções de resolução.

    SÓ IDENTIDADE PROVADA ENTRA. Registros cuja partida ficou `AMBIGUOUS` não
    aparecem em grupo nenhum — e a diferença entre lidos e agrupados é
    reportada.
    """

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.run_fusion_for_runs(
            actor=_ator(actor), resolution_run_ids=resolution_run
        )

    saida = _executar(_acao)
    _imprimir_fusao(saida.run)
    if saida.discarded:
        console.print(
            f"[yellow]{saida.discarded} registro(s) descartado(s)[/yellow] — "
            "duplicata interna de uma fonte, não confirmação."
        )


@fusion_app.command("show")
def mostrar_fusao(run_id: str) -> None:
    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.get_fusion_run.execute(run_id)

    _imprimir_fusao(_executar(_acao))


@fusion_app.command("conflicts")
def conflitos(
    run_id: str, limit: Annotated[int, typer.Option(min=1, max=500)] = 50
) -> None:
    """Os conflitos não resolvidos.

    UM CONFLITO PRESERVADO NÃO É FALHA. É o resultado desejável quando a
    política não sabe decidir: escolher por desempate arbitrário produziria um
    número de aparência decidida que ninguém revisaria.
    """

    async def _acao(contêiner: Any) -> Any:
        return await contêiner.resolution.list_conflicts.execute(run_id, limit=limit)

    achados = _executar(_acao)
    if not achados:
        console.print("[green]nenhum conflito não resolvido.[/green]")
        return
    tabela = Table(show_header=True, header_style="bold")
    for coluna in ("partida", "campo", "valores em conflito"):
        tabela.add_column(coluna)
    for partida, campo, valores in achados:
        tabela.add_row(str(partida)[:12], campo, valores[:70])
    console.print(tabela)


# ---------------------------------------------------------- impressão --


def _imprimir_execucao(run: Any) -> None:
    cor = {"COMPLETED": "green", "FAILED": "red"}.get(run.status.value, "yellow")
    console.print(f"\n[{cor}]{run.status.value}[/{cor}]  [dim]{run.id}[/dim]")
    console.print(f"versões    {run.versions}")
    console.print(f"entrada    [dim]{run.manifest_fingerprint.short}[/dim]")

    tabela = Table(show_header=True, header_style="bold")
    for coluna in ("total", "resolvidos", "revisão", "ambíguos", "sem resolução", "recusados"):
        tabela.add_column(coluna, justify="right")
    tabela.add_row(
        str(run.counts.total),
        f"[green]{run.counts.resolved}[/green]",
        f"[yellow]{run.counts.review_required}[/yellow]",
        f"[yellow]{run.counts.ambiguous}[/yellow]",
        str(run.counts.unresolved),
        str(run.counts.rejected),
    )
    console.print(tabela)
    taxa = run.counts.automatic_rate
    if taxa is not None:
        console.print(f"automático {taxa:.1%}")
    if run.records_per_second:
        console.print(f"velocidade {run.records_per_second:.0f} registros/s")
    console.print(
        "\n[dim]A saída de uma resolução NÃO é conhecimento histórico ativo.\n"
        "Entre ela e o índice histórico estão a fusão, a avaliação de qualidade\n"
        "e a construção canônica — o PR-04 — mais a barreira do ADR-0007.[/dim]"
    )


def _imprimir_fusao(run: Any) -> None:
    cor = {"COMPLETED": "green", "FAILED": "red"}.get(run.status.value, "yellow")
    console.print(f"\n[{cor}]{run.status.value}[/{cor}]  [dim]{run.id}[/dim]")
    console.print(f"política   {run.policy_version}")
    console.print(f"entradas   {', '.join(r[:8] for r in run.input_resolution_run_ids)}")
    console.print(
        f"grupos     {run.counts.groups} ({run.counts.multi_source_groups} multi-fonte)"
    )
    console.print(f"campos     {run.counts.fields_selected}")
    console.print(
        f"conflitos  {run.counts.conflicts} "
        f"([yellow]{run.counts.unresolved_conflicts} não resolvidos[/yellow])"
    )
    if run.output_fingerprint:
        console.print(f"impressão  [dim]{run.output_fingerprint.short}[/dim]")
    console.print(
        "\n[dim]O candidato fundido NÃO é conhecimento histórico ativo: falta a\n"
        "avaliação de qualidade e a construção canônica, que são o PR-04.[/dim]"
    )
