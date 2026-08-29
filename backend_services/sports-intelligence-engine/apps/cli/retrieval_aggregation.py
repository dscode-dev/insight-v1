"""A agregação de vizinhos na linha de comando.

ELA SE PENDURA NO GRUPO `retrieval` que já existe, e não cria um grupo novo: o
que estes comandos fazem é a continuação do top-K, não uma segunda família de
operações. `engine retrieval aggregate-state` fica ao lado de
`engine retrieval availability-aware`, que é onde alguém procuraria.

## O vocabulário é o do contrato, e isso não é preciosismo (§73)

    peso relativo    o que a distância atribui
    N_eff            a concentração desses pesos

    NÃO probabilidade. NÃO chance. NÃO confiança. NÃO previsão.

UMA COLUNA CHAMADA «chance» SERIA LIDA COMO CHANCE por quem olhar a saída, e
nenhuma nota de rodapé desfaz um cabeçalho. O peso do vizinho mais próximo ser
0,115 não diz que algo tem 11,5% de acontecer: diz que aquele vizinho responde
por 11,5% da massa comparativa do conjunto recuperado.

## E ela não fala com adapter nenhum (§70)

A lição do PR-06.4, aplicada de novo: os três componentes da projeção vêm da
composição, e a agregação vem do caso de uso. Uma CLI que instanciasse
`PostgresRetrievalProjectionReader` seria o app escolhendo infraestrutura por
conta própria — e no dia do segundo armazenamento ela ficaria para trás sem que
nada quebrasse alto.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from sports_intelligence.domain.retrieval.aggregation.aggregate import AggregationStatus
from sports_intelligence.domain.retrieval.distance import distance_text

console = Console()


def _cabecalho(saida: Any, *, rotulo: str, chave_texto: str) -> Table:
    """O que a execução resolveu — com o `lambda` À VISTA (§13, §82).

    NENHUMA EXECUÇÃO PODE ESCONDER QUAL `lambda` USOU. Dois agregados sob
    `lambda` diferentes não se comparam, e quem lê a saída precisa saber sob
    qual régua os pesos foram atribuídos sem ter de abrir o código.
    """
    agregado = saida.aggregation
    politica = saida.policy

    tabela = Table(title=f"{rotulo} · {chave_texto}")
    tabela.add_column("o quê")
    tabela.add_column("valor", justify="right")
    tabela.add_row("tipo de recuperação", agregado.kind.value)
    tabela.add_row("estado", agregado.status.value)
    tabela.add_row("política", politica.identity)
    tabela.add_row("núcleo", politica.kernel)
    tabela.add_row("lambda", f"{politica.lam:g}")
    tabela.add_row("normalização", politica.normalization)
    tabela.add_row("impressão da política", politica.fingerprint[:16])
    tabela.add_row("régua de distância", politica.distance_definition_fingerprint[:16])
    tabela.add_row("K", f"{agregado.neighbor_count}/{agregado.requested_k}")
    tabela.add_row("linhas lidas da projeção", f"{saida.universe_rows:_}")

    efetivo = agregado.effective_sample_size
    # N_eff NÃO É CONFIANÇA e não é número de partidas (§17, §82). O rótulo diz
    # «tamanho efetivo» porque é isso que a definição de ESS mede: a
    # concentração dos pesos, expressa na escala de observações equiponderadas.
    tabela.add_row("N_eff (tamanho efetivo)", "—" if efetivo is None else f"{efetivo:.4f}")
    media = agregado.weighted_mean_dissimilarity
    tabela.add_row(
        "dissimilaridade média ponderada",
        "—" if media is None else distance_text(media),
    )
    minima = agregado.minimum_dissimilarity
    tabela.add_row("dissimilaridade mínima", "—" if minima is None else distance_text(minima))
    maxima = agregado.maximum_dissimilarity
    tabela.add_row("dissimilaridade máxima", "—" if maxima is None else distance_text(maxima))
    maior = agregado.max_neighbor_weight
    tabela.add_row("maior peso relativo", "—" if maior is None else f"{maior:.6f}")
    topo = agregado.top3_weight_mass
    tabela.add_row("massa dos 3 maiores", "—" if topo is None else f"{topo:.6f}")
    tabela.add_row("impressão do agregado", agregado.fingerprint[:16])
    tabela.add_row("impressão da recuperação", agregado.retrieval_fingerprint[:16])
    tabela.add_row("agregação pura", f"{saida.aggregate_ms:.3f} ms")
    return tabela


def _vizinhos(saida: Any, *, coluna_de_distancia: str) -> Table:
    tabela = Table(title="vizinhos e MASSA RELATIVA (não é probabilidade)")
    tabela.add_column("#", justify="right")
    tabela.add_column("candidato")
    tabela.add_column(coluna_de_distancia, justify="right")
    tabela.add_column("peso", justify="right")
    tabela.add_column("evidência")
    for vizinho in saida.aggregation.weighted_neighbors:
        tabela.add_row(
            str(vizinho.retrieval_rank),
            vizinho.identity,
            distance_text(vizinho.dissimilarity),
            f"{vizinho.normalized_weight:.6f}",
            vizinho.evidence_fingerprint[:12],
        )
    return tabela


def _resumo(saida: Any) -> Table | None:
    """A evidência agregada — DESCRITIVA, e nunca multiplicada no peso (§49)."""
    resumo = saida.aggregation.evidence_summary
    if not resumo:
        return None
    tabela = Table(title="evidência do conjunto (descritiva — não altera peso)")
    tabela.add_column("o quê")
    tabela.add_column("valor", justify="right")
    for nome in sorted(resumo):
        valor = resumo[nome]
        if valor is None:
            texto = "—"
        elif isinstance(valor, float):
            texto = f"{valor:.6f}"
        else:
            texto = str(valor)
        tabela.add_row(nome, texto)
    return tabela


def _imprimir(saida: Any, *, rotulo: str, chave_texto: str, coluna: str) -> None:
    console.print(_cabecalho(saida, rotulo=rotulo, chave_texto=chave_texto))
    if saida.aggregation.status is AggregationStatus.NO_NEIGHBORS:
        # §74 — a ausência é DITA, e não desenhada como uma tabela vazia.
        console.print(
            "[yellow]NO_NEIGHBORS[/yellow] — a recuperação não devolveu vizinho "
            "elegível. Não há massa a distribuir, e `N_eff` fica indefinido: um "
            "zero aqui pareceria medição onde houve ausência."
        )
        return
    console.print(_vizinhos(saida, coluna_de_distancia=coluna))
    resumo = _resumo(saida)
    if resumo is not None:
        console.print(resumo)


def _validar(k: int, lam: float | None) -> None:
    """As recusas que NÃO precisam de infraestrutura para acontecer.

    ELAS VÊM ANTES DE ABRIR O POOL. Um `--k 0` que só falha depois de conectar
    ao PostgreSQL, montar o grafo e recuperar o universo gasta tudo isso para
    dizer o que já dava para dizer na primeira linha — e o erro chega embrulhado
    numa `ValidationError` de domínio, longe do argumento que o causou.
    """
    if k < 1:
        console.print(
            f"[red]K = {k}[/red] — a agregação distribui massa sobre um conjunto, "
            "e um conjunto vazio pedido de propósito não é uma pergunta."
        )
        raise typer.Exit(code=1)
    if lam is not None and (lam <= 0.0 or lam != lam or lam in (float("inf"), float("-inf"))):
        console.print(
            f"[red]lambda = {lam!r}[/red] — o núcleo exige `lambda > 0` e finito: "
            "com zero todos os pesos ficam iguais, e com negativo o vizinho mais "
            "DISTANTE passaria a pesar mais."
        )
        raise typer.Exit(code=1)


def registrar(app: typer.Typer) -> None:
    """Pendura `aggregate-state` e `aggregate-trajectory` no grupo `retrieval`.

    A MONTAGEM DO GRAFO É A DA PROJEÇÃO, e reusá-la é o ponto: a agregação roda
    sobre o MESMO caminho projetado do PR-06.4. Uma cópia da montagem aqui
    continuaria montando o grafo antigo no dia em que a original mudasse, e
    calada — que é o pior jeito de descobrir uma divergência de composição.
    """
    from apps.cli.retrieval_projection import (
        chave_de_snapshot as chave_de,
    )
    from apps.cli.retrieval_projection import (
        executar_sob_versao as executar,
    )
    from apps.cli.retrieval_projection import (
        projecao_da_composicao as projecao_de,
    )

    @app.command("aggregate-state")
    def aggregate_state_cmd(
        dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
        query_snapshot: Annotated[
            str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
        ],
        k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 20,
        lam: Annotated[
            float | None,
            typer.Option(
                "--lambda",
                help="Sobrepõe o lambda SELECIONADO (8.0). Muda a identidade da política.",
            ),
        ] = None,
    ) -> None:
        """Pondera o top-K de ESTADO pela dissimilaridade exata.

        O PESO NÃO É PROBABILIDADE e `N_eff` não é confiança. O comando
        descreve a concentração da evidência histórica recuperada, e não diz
        nada sobre o que vai acontecer na partida consultada.
        """
        from sports_intelligence.application.use_cases.neighbor_aggregation import (
            AggregateProjectedStateNeighbors,
        )
        from sports_intelligence.application.use_cases.projected_retrieval import (
            RetrieveProjectedStateHistoricalNeighbors,
        )
        from sports_intelligence.domain.retrieval.projection.contract import (
            RetrievalProjectionKind,
        )

        _validar(k, lam)
        chave = chave_de(query_snapshot)

        async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
            repo, _, leitor = projecao_de(grafo)
            publicada = await repo.latest_ready(
                dataset_version_id=versao.id, kind=RetrievalProjectionKind.STATE
            )
            return await AggregateProjectedStateNeighbors(
                RetrieveProjectedStateHistoricalNeighbors(aware=grafo.retrieve_aware, reader=leitor)
            ).execute(
                projection_version=publicada,
                version_id=versao.id,
                key=chave,
                k=k,
                lam=lam,
            )

        saida = executar(acao, version_id=dataset_version)
        _imprimir(saida, rotulo="estado agregado", chave_texto=chave.text, coluna="D")

    @app.command("aggregate-trajectory")
    def aggregate_trajectory_cmd(
        dataset_version: Annotated[str, typer.Argument(help="A versão normalizada PUBLICADA")],
        query_snapshot: Annotated[
            str, typer.Argument(help="A linha de AVALIAÇÃO: <match_id>#<grid_index>")
        ],
        k: Annotated[int, typer.Option(help="Quantos vizinhos")] = 20,
        lam: Annotated[
            float | None,
            typer.Option(
                "--lambda",
                help="Sobrepõe o lambda SELECIONADO (16.0). Muda a identidade da política.",
            ),
        ] = None,
    ) -> None:
        """Pondera o top-K de TRAJETÓRIA pela `D_T` exata.

        A POLÍTICA É OUTRA, e não por simetria: a escala de `D_T` difere da de
        `D`, e o mesmo `lambda` produziria concentrações diferentes nos dois
        caminhos por acidente de escala.
        """
        from sports_intelligence.application.use_cases.neighbor_aggregation import (
            AggregateProjectedTrajectoryNeighbors,
        )
        from sports_intelligence.application.use_cases.projected_trajectory_retrieval import (
            RetrieveProjectedTrajectoryHistoricalNeighbors,
        )
        from sports_intelligence.domain.retrieval.projection.contract import (
            RetrievalProjectionKind,
        )

        _validar(k, lam)
        chave = chave_de(query_snapshot)

        async def acao(conteiner: Any, grafo: Any, versao: Any) -> Any:
            repo, _, leitor = projecao_de(grafo)
            publicada = await repo.latest_ready(
                dataset_version_id=versao.id, kind=RetrievalProjectionKind.TRAJECTORY
            )
            return await AggregateProjectedTrajectoryNeighbors(
                RetrieveProjectedTrajectoryHistoricalNeighbors(
                    trajectory=grafo.retrieve_trajectory, reader=leitor
                )
            ).execute(
                projection_version=publicada,
                version_id=versao.id,
                key=chave,
                k=k,
                lam=lam,
            )

        saida = executar(acao, version_id=dataset_version)
        # O RÓTULO DIZ `D_T`, e nunca `D`: são grandezas diferentes.
        _imprimir(saida, rotulo="trajetória agregada", chave_texto=chave.text, coluna="D_T")
