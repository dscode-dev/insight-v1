"""A projeção de recuperação na linha de comando.

ELA NÃO FALA SQL. Todo comando aqui passa pelos casos de uso da aplicação — os
mesmos que o E2E exercita —, e é isso que impede a CLI de virar um segundo
caminho com regras próprias.

E ELA NÃO FALA DE ANN. Não há `ef_search`, orçamento, distância proxy nem
recall: o caminho de produção da V1 é exato, e o vocabulário da CLI é o do
caminho que existe. O experimento está nos documentos, e não nos comandos.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.features.dataset.rows import HistoricalFeatureSnapshotKey
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.shared.errors import EngineError

app = typer.Typer(
    name="retrieval-projection",
    help="A projeção operacional dos candidatos históricos em PostgreSQL.",
    no_args_is_help=True,
)
console = Console()


def _tipo(texto: str) -> Any:
    """`STATE` ou `TRAJECTORY`, e um terceiro valor é recusado COM a lista.

    O CATÁLOGO CRU LEVANTARIA `ValueError` com um traceback. Quem digitou o
    nome errado precisa das opções, e não da pilha de chamadas.
    """
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionKind,
    )

    try:
        return RetrievalProjectionKind(texto.upper())
    except ValueError:
        validos = ", ".join(t.value for t in RetrievalProjectionKind)
        console.print(f"[red]tipo de projeção inválido: {texto!r}[/red] — use {validos}")
        raise typer.Exit(code=1) from None


def _chave(texto: str) -> HistoricalFeatureSnapshotKey:
    """`<match_id>#<grid_index>` — a forma canônica, a mesma que o topo imprime."""
    if "#" not in texto:
        console.print("[red]a chave tem a forma <match_id>#<grid_index>[/red]")
        raise typer.Exit(code=1)
    match_key, _, indice = texto.rpartition("#")
    if not indice.isdigit():
        console.print("[red]o índice da grade precisa ser numérico[/red]")
        raise typer.Exit(code=1)
    return HistoricalFeatureSnapshotKey(match_key=match_key, grid_index=int(indice))


def _executar(acao: Any, *, version_id: str) -> Any:
    """Monta o grafo sob a fronteira DA VERSÃO consultada.

    A FRONTEIRA NÃO É OPÇÃO DE LINHA DE COMANDO: ela entra na identidade do
    plano, e deixar alguém digitá-la abriria a porta para consultar um dataset
    sob um plano que não é o dele.
    """

    async def _com_pool() -> Any:
        from apps.composition import build_container

        conteiner = build_container()
        await conteiner.database.connect()
        try:
            versao = await conteiner.normalized_versions.version_by_id(version_id)
            if versao is None:
                console.print(f"[red]versão normalizada {version_id} não existe[/red]")
                raise typer.Exit(code=1)
            crua = await conteiner.feature_dataset.datasets.version_by_id(versao.source_version_id)
            if crua is None:
                console.print(f"[red]a versão crua {versao.source_version_id} não existe[/red]")
                raise typer.Exit(code=1)
            grafo = conteiner.retrieval(reference_end_exclusive=crua.spec.reference_end_exclusive)
            return await acao(conteiner, grafo, versao)
        finally:
            await conteiner.database.close()

    try:
        return asyncio.run(_com_pool())
    except EngineError as erro:
        console.print(f"[red]{erro.category}[/red] {erro.message}")
        if erro.context:
            console.print(f"[dim]{erro.context}[/dim]")
        raise typer.Exit(code=1) from erro


def _projecao(grafo: Any) -> tuple[Any, Any, Any]:
    """Os três componentes da projeção, VINDOS DA COMPOSIÇÃO.

    A CLI NÃO INSTANCIA O ADAPTER. Instanciá-lo aqui seria o app escolhendo a
    infraestrutura por conta própria — e a guarda arquitetural do repositório
    recusa isso por um motivo concreto: no dia em que houver um segundo
    armazenamento, quem importou o adapter direto fica para trás sem que nada
    quebre alto.
    """
    return (grafo.projection_repository, grafo.projection_writer, grafo.projection_reader)


def _amarra(conteiner: Any, grafo: Any, versao: Any, *, kind: Any) -> Any:
    from sports_intelligence.domain.features.normalized.plan import normalization_plan_v1
    from sports_intelligence.domain.retrieval.candidate_policy import (
        DEFAULT_CANDIDATE_POLICY,
    )
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionBinding,
        RetrievalProjectionKind,
    )
    from sports_intelligence.domain.retrieval.projection.payload import (
        EXACT_FLOAT64_LE_PAYLOAD_V1,
    )
    from sports_intelligence.domain.retrieval.trajectory_coverage import (
        DEFAULT_TRAJECTORY_COVERAGE,
    )
    from sports_intelligence.domain.retrieval.trajectory_profile import (
        DEFAULT_TRAJECTORY_PROFILE,
    )
    from sports_intelligence.domain.retrieval.trajectory_window import (
        DEFAULT_TRAJECTORY_WINDOW,
    )

    plano = normalization_plan_v1()
    referencia = grafo.retrieve.reference_fingerprint(versao)
    comum = {
        "source_dataset_version_id": versao.id,
        "source_dataset_version": str(versao.version),
        "source_reference_fingerprint": referencia,
        "normalization_plan_fingerprint": plano.fingerprint,
        "artifact_set_fingerprint": referencia,
        "candidate_policy_fingerprint": DEFAULT_CANDIDATE_POLICY.fingerprint,
        "exact_payload_encoding": EXACT_FLOAT64_LE_PAYLOAD_V1,
    }
    if kind is RetrievalProjectionKind.TRAJECTORY:
        return RetrievalProjectionBinding(
            **comum,
            trajectory_window_fingerprint=DEFAULT_TRAJECTORY_WINDOW.fingerprint,
            trajectory_profile_fingerprint=DEFAULT_TRAJECTORY_PROFILE.fingerprint,
            trajectory_coverage_fingerprint=DEFAULT_TRAJECTORY_COVERAGE.fingerprint,
        )
    return RetrievalProjectionBinding(**comum)


# ------------------------------------------------------------------ build --


@app.command("build")
def build(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    kind: Annotated[str, typer.Option(help="STATE ou TRAJECTORY")] = "STATE",
    name: Annotated[str, typer.Option(help="O nome da projeção")] = "default",
) -> None:
    """Constrói a projeção a partir do dataset normalizado READY.

    ELA JÁ SAI VALIDADA E PUBLICADA. Construir sem validar deixaria uma versão
    em `BUILDING` que ninguém pode consultar e ninguém sabe se presta; o ciclo
    inteiro num comando é o que torna o estado final sempre conclusivo.
    """
    from sports_intelligence.application.use_cases.projection_build import (
        BuildStateProjection,
        BuildTrajectoryProjection,
        ValidateAndPublishProjection,
    )
    from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID
    from sports_intelligence.domain.features.normalized.plan import normalization_plan_v1
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionKind,
    )
    from sports_intelligence.domain.retrieval.trajectory_profile import (
        DEFAULT_TRAJECTORY_PROFILE,
    )
    from sports_intelligence.domain.retrieval.trajectory_window import (
        DEFAULT_TRAJECTORY_WINDOW,
    )

    tipo = _tipo(kind)

    async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
        repo, escritor, leitor = _projecao(grafo)
        eixos = normalization_plan_v1().robust_keys
        amarra = _amarra(conteiner, grafo, versao, kind=tipo)
        if tipo is RetrievalProjectionKind.STATE:
            construtor = BuildStateProjection(source=grafo.source, repository=repo, writer=escritor)
            saida = await construtor.execute(
                projection_name=name,
                dataset_name="match-state-normalized",
                version_id=versao.id,
                version_text=str(versao.version),
                binding=amarra,
                axis_keys=eixos,
            )
        else:
            construtor_t = BuildTrajectoryProjection(
                source=grafo.source,
                repository=repo,
                writer=escritor,
                window=DEFAULT_TRAJECTORY_WINDOW,
                grid=DEFAULT_SNAPSHOT_GRID,
            )
            saida = await construtor_t.execute(
                projection_name=name,
                dataset_name="match-state-normalized",
                version_id=versao.id,
                version_text=str(versao.version),
                binding=amarra,
                axis_keys=eixos,
                horizons=DEFAULT_TRAJECTORY_WINDOW.horizons,
                profile_fingerprint=DEFAULT_TRAJECTORY_PROFILE.fingerprint,
            )
        publicada = await ValidateAndPublishProjection(repository=repo, reader=leitor).execute(
            outcome=saida, expected_rows=saida.rows_written
        )
        return saida, publicada

    saida, publicada = _executar(acao, version_id=dataset_version)

    tabela = Table(title=f"projeção {publicada.kind.value}")
    tabela.add_column("o quê")
    tabela.add_column("valor", justify="right")
    tabela.add_row("versão", publicada.version_id)
    tabela.add_row("estado", publicada.status.value)
    tabela.add_row("dataset de origem", publicada.binding.source_dataset_version_id)
    tabela.add_row("linhas", f"{publicada.row_count:_}")
    tabela.add_row("eixos canônicos", str(publicada.axis_count))
    tabela.add_row("duração", f"{saida.duration_s:.1f}s")
    tabela.add_row("linhas/s", f"{saida.rows_per_second:,.0f}")
    if saida.not_applicable:
        tabela.add_row("âncoras não aplicáveis", f"{saida.not_applicable:_}")
    tabela.add_row("impressão do conteúdo", publicada.content_fingerprint[:16])
    tabela.add_row("impressão da versão", publicada.fingerprint[:16])
    console.print(tabela)
    recusadas = dict(saida.accounting.rejected)
    if recusadas:
        for motivo, quantas in sorted(recusadas.items()):
            console.print(f"[yellow]recusadas[/yellow] {motivo}: {quantas:_}")


# ------------------------------------------------------------------- show --


@app.command("show")
def show(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    kind: Annotated[str, typer.Option(help="STATE ou TRAJECTORY")] = "STATE",
) -> None:
    """A projeção READY daquele dataset, com a linhagem inteira."""
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionKind,
    )

    tipo = _tipo(kind)

    async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
        repo, _, _ = _projecao(grafo)
        publicada = await repo.latest_ready(dataset_version_id=versao.id, kind=tipo)
        tamanhos = await repo.sizes(tipo)
        return publicada, tamanhos

    publicada, tamanhos = _executar(acao, version_id=dataset_version)
    amarra = publicada.binding

    tabela = Table(title=f"projeção {publicada.kind.value}")
    tabela.add_column("o quê")
    tabela.add_column("valor", justify="right")
    tabela.add_row("versão", publicada.version_id)
    tabela.add_row("estado", publicada.status.value)
    tabela.add_row("linhas", f"{publicada.row_count:_}")
    tabela.add_row("eixos canônicos", str(publicada.axis_count))
    tabela.add_row("payload", amarra.exact_payload_encoding)
    tabela.add_row("dataset de origem", amarra.source_dataset_version_id)
    tabela.add_row("referência", amarra.source_reference_fingerprint[:16])
    tabela.add_row("plano", amarra.normalization_plan_fingerprint[:16])
    tabela.add_row("artefatos", amarra.artifact_set_fingerprint[:16])
    tabela.add_row("universo", amarra.candidate_policy_fingerprint[:16])
    if publicada.kind is RetrievalProjectionKind.TRAJECTORY:
        tabela.add_row("janela", amarra.trajectory_window_fingerprint[:16])
        tabela.add_row("perfil", amarra.trajectory_profile_fingerprint[:16])
        tabela.add_row("cobertura", amarra.trajectory_coverage_fingerprint[:16])
    tabela.add_row("conteúdo", publicada.content_fingerprint[:16])
    tabela.add_row("tabela", f"{tamanhos['heap_bytes']:_} B")
    tabela.add_row("com índices", f"{tamanhos['total_bytes']:_} B")
    console.print(tabela)


# --------------------------------------------------------- as consultas --


def _tempos(tempos: Any) -> Table:
    tabela = Table(title="onde o tempo foi")
    tabela.add_column("etapa")
    tabela.add_column("ms", justify="right")
    mapa = tempos.as_mapping()
    for rotulo, chave in (
        ("resolver a query", "resolve_ms"),
        ("ler o universo (SQL)", "lookup_ms"),
        ("decodificar", "decode_ms"),
        ("cálculo exato", "compute_ms"),
        ("total", "total_ms"),
    ):
        tabela.add_row(rotulo, f"{mapa[chave]:.2f}")
    return tabela


@app.command("state")
def projected_state(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 10,
) -> None:
    """O top-K de ESTADO lendo o universo da projeção. Distância EXATA."""
    from sports_intelligence.application.use_cases.projected_retrieval import (
        RetrieveProjectedStateHistoricalNeighbors,
    )
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionKind,
    )

    chave = _chave(query_snapshot)

    async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
        repo, _, leitor = _projecao(grafo)
        publicada = await repo.latest_ready(
            dataset_version_id=versao.id, kind=RetrievalProjectionKind.STATE
        )
        return await RetrieveProjectedStateHistoricalNeighbors(
            aware=grafo.retrieve_aware, reader=leitor
        ).execute(
            projection_version=publicada,
            version_id=versao.id,
            key=chave,
            k=k,
        )

    saida = _executar(acao, version_id=dataset_version)
    resultado = saida.result

    cabecalho = Table(title=f"estado projetado · {chave.text}")
    cabecalho.add_column("o quê")
    cabecalho.add_column("valor", justify="right")
    cabecalho.add_row("competição", resultado.competition)
    cabecalho.add_row("universo", f"{resultado.universe_count:_}")
    cabecalho.add_row("linhas lidas da projeção", f"{saida.universe_rows:_}")
    cabecalho.add_row("comparáveis", f"{resultado.coverage_eligible_count:_}")
    cabecalho.add_row("K", f"{resultado.returned_k}/{resultado.requested_k}")
    console.print(cabecalho)

    vizinhos = Table(title="vizinhos por NÍVEL")
    vizinhos.add_column("#", justify="right")
    vizinhos.add_column("candidato")
    vizinhos.add_column("D", justify="right")
    vizinhos.add_column("eixos", justify="right")
    for vizinho in resultado.neighbors:
        vizinhos.add_row(
            str(vizinho.rank),
            vizinho.key.text,
            distance_text(vizinho.dissimilarity),
            str(vizinho.evidence.shared_count),
        )
    console.print(vizinhos)
    console.print(_tempos(saida.timings))


@app.command("trajectory")
def projected_trajectory(
    dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
    query_snapshot: Annotated[
        str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
    ],
    k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 10,
) -> None:
    """O top-K de TRAJETÓRIA lendo o universo da projeção. `D_T` EXATA."""
    from sports_intelligence.application.use_cases.projected_trajectory_retrieval import (
        RetrieveProjectedTrajectoryHistoricalNeighbors,
    )
    from sports_intelligence.domain.retrieval.projection.contract import (
        RetrievalProjectionKind,
    )

    chave = _chave(query_snapshot)

    async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
        repo, _, leitor = _projecao(grafo)
        publicada = await repo.latest_ready(
            dataset_version_id=versao.id, kind=RetrievalProjectionKind.TRAJECTORY
        )
        return await RetrieveProjectedTrajectoryHistoricalNeighbors(
            trajectory=grafo.retrieve_trajectory, reader=leitor
        ).execute(
            projection_version=publicada,
            version_id=versao.id,
            key=chave,
            k=k,
        )

    saida = _executar(acao, version_id=dataset_version)
    resultado = saida.result

    cabecalho = Table(title=f"trajetória projetada · {chave.text}")
    cabecalho.add_column("o quê")
    cabecalho.add_column("valor", justify="right")
    cabecalho.add_row("competição", resultado.competition)
    cabecalho.add_row("universo", f"{resultado.universe_count:_}")
    cabecalho.add_row("linhas lidas da projeção", f"{saida.universe_rows:_}")
    cabecalho.add_row("elegíveis", f"{resultado.trajectory_eligible_count:_}")
    cabecalho.add_row("K", f"{resultado.returned_k}/{resultado.requested_k}")
    console.print(cabecalho)

    vizinhos = Table(title="vizinhos por MOVIMENTO")
    vizinhos.add_column("#", justify="right")
    vizinhos.add_column("candidato")
    # O RÓTULO DIZ `D_T`, e nunca `D`: são grandezas diferentes.
    vizinhos.add_column("D_T", justify="right")
    vizinhos.add_column("células", justify="right")
    vizinhos.add_column("horiz.", justify="right")
    for vizinho in resultado.neighbors:
        vizinhos.add_row(
            str(vizinho.rank),
            vizinho.anchor_key.text,
            distance_text(vizinho.trajectory_dissimilarity),
            str(vizinho.shared_cells),
            str(vizinho.shared_horizons),
        )
    console.print(vizinhos)
    console.print(_tempos(saida.timings))


# ------------------------------------------- reusado pela agregação (PR-06.5) --
#
# A AGREGAÇÃO RODA SOBRE EXATAMENTE ESTE GRAFO. `engine retrieval aggregate-state`
# recupera pelo caminho projetado e só depois pondera; reimplementar a montagem
# do contêiner lá criaria um segundo caminho de composição, e no dia em que este
# mudasse o outro continuaria montando o grafo antigo, calado.
executar_sob_versao = _executar
chave_de_snapshot = _chave
projecao_da_composicao = _projecao
