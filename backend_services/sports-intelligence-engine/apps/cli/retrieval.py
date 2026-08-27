"""`engine retrieval ...` — o oráculo pelo terminal.

DOIS COMANDOS, e a separação é a mesma do caso de uso:

    universe   quem PODERIA ser candidato, e quantos eixos a liga tem
    exact      o top-K, com a contabilidade que o justifica

`universe` NÃO CALCULA DISTÂNCIA NENHUMA. «Quantos candidatos esta query tem?»
é a pergunta que se faz ANTES de pagar a varredura, e respondê-la rodando a
recuperação inteira faria o diagnóstico custar o mesmo que o resultado.

A SAÍDA NÃO MOSTRA DESFECHO. Nem resultado final, nem gol seguinte, nem
tendência: este PR entrega vizinhos históricos, e um relatório que insinuasse o
contrário convidaria alguém a ler um top-K como previsão.

A QUERY VEM DO DATASET, e não da linha de comando. A V1 só aceita uma linha de
AVALIAÇÃO que já existe na versão normalizada — construir features ao vivo é
outro caminho, e ele não existe ainda.
"""

from __future__ import annotations

import asyncio
import getpass
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import EngineError

app = typer.Typer(
    name="retrieval",
    help="Recuperação histórica exata: universo de candidatos e top-K.",
    no_args_is_help=True,
)
console = Console()


def _ator(informado: str | None) -> Actor:
    try:
        return Actor(id=informado or getpass.getuser(), kind=ActorKind.CLI)
    except EngineError as erro:
        console.print(f"[red]{erro.message}[/red]")
        raise typer.Exit(code=1) from erro


def _chave(texto: str) -> HistoricalFeatureSnapshotKey:
    """`<match_id>#<grid_index>` — a mesma forma que o resultado imprime.

    ELA É A FORMA CANÔNICA DA CHAVE, e não um par de opções separadas: quem
    copia um vizinho de um resultado anterior para consultá-lo cola exatamente
    este texto.
    """
    if "#" not in texto:
        console.print(
            f"[red]chave inválida: {texto!r}[/red] — use "
            "[bold]<match_id>#<grid_index>[/bold], como o resultado imprime."
        )
        raise typer.Exit(code=1)
    partida, indice = texto.rsplit("#", 1)
    try:
        return HistoricalFeatureSnapshotKey(match_key=partida, grid_index=int(indice))
    except (ValueError, EngineError) as erro:
        console.print(f"[red]chave inválida: {texto!r}[/red]")
        raise typer.Exit(code=1) from erro


def _executar(acao: Any, *, version_id: str) -> Any:
    """Monta o grafo sob a fronteira DA VERSÃO consultada.

    A FRONTEIRA NÃO É UMA OPÇÃO DA LINHA DE COMANDO, e não pode ser: ela entra
    na identidade do plano, e deixar alguém digitá-la abriria a porta para
    consultar um dataset sob um plano que não é o dele. Ela é lida da versão
    crua de origem, que a declarou na `spec`.
    """

    async def _com_pool() -> Any:
        from apps.composition import build_container

        contêiner = build_container()
        await contêiner.database.connect()
        try:
            versao = await contêiner.normalized_versions.version_by_id(version_id)
            if versao is None:
                console.print(f"[red]versão normalizada {version_id} não existe[/red]")
                raise typer.Exit(code=1)
            crua = await contêiner.feature_dataset.datasets.version_by_id(versao.source_version_id)
            if crua is None:
                console.print(f"[red]a versão crua {versao.source_version_id} não existe[/red]")
                raise typer.Exit(code=1)
            grafo = contêiner.retrieval(reference_end_exclusive=crua.spec.reference_end_exclusive)
            return await acao(grafo)
        finally:
            await contêiner.database.close()

    try:
        return asyncio.run(_com_pool())
    except EngineError as erro:
        console.print(f"[red]{erro.category}[/red] {erro.message}")
        if erro.context:
            console.print(f"[dim]{erro.context}[/dim]")
        raise typer.Exit(code=1) from erro


# ---------------------------------------------------------------- universo --


@app.command("universe")
def universe(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Quem poderia ser candidato — sem calcular distância nenhuma."""
    _ator(actor)
    chave = _chave(query_snapshot)

    async def acao(grafo: Any) -> Any:
        return await grafo.describe.execute(version_id=dataset_version, key=chave)

    descricao = _executar(acao, version_id=dataset_version)
    tabela = Table(title=f"universo · {query_snapshot}")
    tabela.add_column("o quê")
    tabela.add_column("valor", justify="right")
    tabela.add_row("competição", str(descricao["competition"]))
    tabela.add_row("instante", str(descricao["position"]))
    tabela.add_row("candidatos", f"{descricao['universe_count']:_}")
    tabela.add_row("eixos do perfil", f"{descricao['axis_count']}")
    tabela.add_row("query comparável", "sim" if descricao["query_comparable"] else "não")
    console.print(tabela)
    faltando = descricao["query_missing_axes"]
    if faltando:
        console.print(
            f"[yellow]a query não tem {len(faltando)} eixo(s) do perfil[/yellow]: "
            f"{', '.join(faltando[:5])}"
        )
    console.print(f"[dim]perfil {descricao['profile_fingerprint'][:16]}[/dim]")


# -------------------------------------------------------------------- exato --


@app.command("exact")
def exact(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 10,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """O top-K EXATO, depois de examinar todo o universo elegível."""
    _ator(actor)
    chave = _chave(query_snapshot)

    async def acao(grafo: Any) -> Any:
        return await grafo.retrieve.execute(version_id=dataset_version, key=chave, k=k)

    resultado = _executar(acao, version_id=dataset_version)

    cabecalho = Table(title=f"recuperação exata · {resultado.query_key.text}")
    cabecalho.add_column("o quê")
    cabecalho.add_column("valor", justify="right")
    cabecalho.add_row("competição", resultado.competition)
    cabecalho.add_row("universo", f"{resultado.universe_count:_}")
    cabecalho.add_row(
        "comparáveis",
        f"{resultado.comparable_count:_} ({resultado.comparable_ratio:.1%})",
    )
    cabecalho.add_row("K", f"{resultado.returned_k}/{resultado.requested_k}")
    cabecalho.add_row("eixos", f"{resultado.axis_count}")
    console.print(cabecalho)

    for motivo, contagem in sorted(resultado.ineligible.items()):
        console.print(f"[yellow]inelegível[/yellow] {motivo}: {contagem:_}")

    if resultado.is_empty:
        console.print(
            "[yellow]nenhum vizinho comparável[/yellow] — e isto é um resultado, e "
            "não uma falha: a competição não tem candidato completo neste instante."
        )
    else:
        vizinhos = Table(title="vizinhos")
        vizinhos.add_column("#", justify="right")
        vizinhos.add_column("candidato")
        vizinhos.add_column("temporada")
        # O RÓTULO DIZ `d²`, e não «distância». Ele é L2 AO QUADRADO, e um
        # cabeçalho que omitisse isso convidaria à comparação com limiares
        # euclidianos que não valem (§110).
        vizinhos.add_column("d²", justify="right")
        for vizinho in resultado.neighbors:
            vizinhos.add_row(
                str(vizinho.rank),
                vizinho.key.text,
                vizinho.season,
                distance_text(vizinho.squared_distance),
            )
        console.print(vizinhos)

    console.print(
        f"[dim]perfil {resultado.resolved_profile_fingerprint[:16]} · "
        f"distância {resultado.distance_definition_fingerprint[:16]}[/dim]"
    )
    console.print(
        f"[dim]universo {resultado.candidate_universe_fingerprint[:16]} · "
        f"resultado {resultado.fingerprint[:16]}[/dim]"
    )
    console.print(
        "[dim]baseline DIAGNÓSTICO: eixos robustos ajustados, caso completo, "
        "pesos iguais. Não é a similaridade final do Insight.[/dim]"
    )


# ------------------------------------------------- ciente de disponibilidade --


@app.command("availability-aware")
def availability_aware(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 10,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """O top-K sob o piso de cobertura e a penalidade por ausência (PR-06.2).

    A SAÍDA ABRE A CONTA DE CADA VIZINHO, e não só o total. `D = 0,4` pode ser
    discrepância pura sobre o perfil inteiro ou incerteza pura sobre metade
    dele, e as duas coisas dizem coisas opostas sobre o vizinho — mostrar só o
    total apagaria a diferença que este PR existe para medir.
    """
    _ator(actor)
    chave = _chave(query_snapshot)

    async def acao(grafo: Any) -> Any:
        return await grafo.retrieve_aware.execute(version_id=dataset_version, key=chave, k=k)

    resultado = _executar(acao, version_id=dataset_version)

    cabecalho = Table(title=f"recuperação ciente de disponibilidade · {resultado.query_key.text}")
    cabecalho.add_column("o quê")
    cabecalho.add_column("valor", justify="right")
    cabecalho.add_row("competição", resultado.competition)
    cabecalho.add_row("eixos do perfil", f"{resultado.axis_count}")
    cabecalho.add_row(
        "cobertura da query",
        f"{resultado.query_available_count}/{resultado.axis_count} "
        f"({resultado.query_coverage:.1%})",
    )
    cabecalho.add_row("universo", f"{resultado.universe_count:_}")
    cabecalho.add_row(
        "elegíveis",
        f"{resultado.coverage_eligible_count:_} ({resultado.eligible_ratio:.1%})",
    )
    cabecalho.add_row("recusados por cobertura", f"{resultado.coverage_ineligible_count:_}")
    cabecalho.add_row("recusados por estrutura", f"{resultado.structural_ineligible_count:_}")
    cabecalho.add_row("K", f"{resultado.returned_k}/{resultado.requested_k}")
    cabecalho.add_row("no piso de cobertura", f"{resultado.floor_pressure}")
    console.print(cabecalho)

    for motivo, contagem in sorted(resultado.ineligible.items()):
        console.print(f"[yellow]inelegível[/yellow] {motivo}: {contagem:_}")

    if resultado.is_empty:
        console.print(
            "[yellow]nenhum vizinho com evidência bastante[/yellow] — e isto é um "
            "resultado, e não uma falha: nenhum candidato desta competição alcançou "
            "o piso de cobertura neste instante."
        )
    else:
        vizinhos = Table(title="vizinhos")
        vizinhos.add_column("#", justify="right")
        vizinhos.add_column("candidato")
        # O RÓTULO DIZ `D`, e NÃO `d²`. Ela é a média sobre o perfil FIXO com a
        # incerteza dentro — comparar este número com um `d²` do PR-06.1 é
        # comparar grandezas diferentes.
        vizinhos.add_column("D", justify="right")
        vizinhos.add_column("eixos", justify="right")
        vizinhos.add_column("cobertura", justify="right")
        vizinhos.add_column("observado", justify="right")
        vizinhos.add_column("incerteza", justify="right")
        vizinhos.add_column("% incerto", justify="right")
        for vizinho in resultado.neighbors:
            parcela = vizinho.penalty_share
            vizinhos.add_row(
                str(vizinho.rank),
                vizinho.key.text,
                distance_text(vizinho.dissimilarity),
                f"{vizinho.shared_count}/{resultado.axis_count}",
                f"{vizinho.shared_coverage:.0%}",
                distance_text(vizinho.evidence.observed_squared_sum),
                distance_text(vizinho.evidence.missing_penalty_sum),
                "-" if parcela is None else f"{parcela:.0%}",
            )
        console.print(vizinhos)

    console.print(
        f"[dim]perfil {resultado.resolved_profile_fingerprint[:16]} · "
        f"cobertura {resultado.coverage_policy_fingerprint[:16]} · "
        f"distância {resultado.distance_definition_fingerprint[:16]}[/dim]"
    )
    console.print(
        f"[dim]universo {resultado.candidate_universe_fingerprint[:16]} · "
        f"resultado {resultado.fingerprint[:16]}[/dim]"
    )
    console.print(
        "[dim]a AUSÊNCIA é penalizada, e nunca preenchida: cada eixo não "
        "compartilhado custa 1/m em unidade de IQR². Não é confiança, e não é "
        "a similaridade final do Insight.[/dim]"
    )


# ------------------------------------------------------------- a comparação --


@app.command("compare")
def compare(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 10,
    actor: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Caso completo contra cobertura compartilhada, sobre o MESMO universo.

    O NÚMERO QUE IMPORTA É A DIFERENÇA, e ela só significa alguma coisa porque
    os dois lados leem o mesmo universo na mesma execução.

    `recuperação` É UMA CONTAGEM, e não uma melhoria: mais candidatos medidos
    não é o mesmo que melhores vizinhos, e não há rótulo com que afirmar a
    segunda coisa antes do PR-06.5.
    """
    _ator(actor)
    chave = _chave(query_snapshot)

    async def acao(grafo: Any) -> Any:
        return await grafo.compare.execute(version_id=dataset_version, key=chave, k=k)

    comparacao = _executar(acao, version_id=dataset_version)

    tabela = Table(title=f"caso completo contra cobertura · {comparacao.key.text}")
    tabela.add_column("o quê")
    tabela.add_column("caso completo", justify="right")
    tabela.add_column("ciente de disp.", justify="right")
    tabela.add_row(
        "query comparável",
        "não" if comparacao.complete_case_rejected else "sim",
        "não" if comparacao.availability_aware_rejected else "sim",
    )
    tabela.add_row(
        "candidatos medidos",
        f"{comparacao.complete_case_comparable:_}",
        f"{comparacao.availability_aware_eligible:_}",
    )
    tabela.add_row(
        "vizinhos devolvidos",
        f"{comparacao.complete_case_returned}",
        f"{comparacao.availability_aware_returned}",
    )
    console.print(tabela)

    relativa = comparacao.relative_recovery
    console.print(
        f"universo {comparacao.universe_count:_} · eixos {comparacao.axis_count} · "
        f"recuperação [bold]{comparacao.candidate_recovery:+_}[/bold] candidato(s)"
        + ("" if relativa is None else f" ({relativa:+.1%})")
    )
    if comparacao.recovered_from_zero:
        console.print("[green]esta query não tinha vizinho nenhum sob o caso completo[/green]")
    sobreposicao = comparacao.top_k_overlap
    console.print(
        "sobreposição do top-K  "
        + ("-" if sobreposicao is None else f"{sobreposicao:.0%}")
        + "  [dim](diagnóstico — uma sobreposição baixa é o comportamento "
        "pretendido, e não um erro)[/dim]"
    )
