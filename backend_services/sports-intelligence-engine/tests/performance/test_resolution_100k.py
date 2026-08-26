"""Cem mil registros pelo caminho operacional inteiro, contra PostgreSQL real.

O QUE ESTE ARQUIVO TRANSFORMA EM MEDIDA. Até o PR-03, «a resolução escala por
lote» era uma afirmação sobre a ASSINATURA dos ports. Aqui ela vira número:
quantos registros por segundo, quantas consultas, quanto de pico de memória, e
como cada um deles se comporta quando o tamanho do lote muda.

O QUE ELE NÃO AFIRMA. Nenhum SLO comercial (§50). Os números dependem da
máquina, do disco e do que mais estiver rodando; virar asserção produziria uma
suíte que falha por ruído e que passa a ser ignorada. As asserções aqui são
sobre PROPRIEDADES que sobrevivem à troca de máquina:

    consultas crescem por LOTE, não por registro
    pico de memória não cresce com o tamanho do arquivo
    o resultado NÃO muda quando o tamanho do lote muda

Os tempos são REPORTADOS — para `docs/performance/PR03_RESOLUTION_BASELINE.md`
e para a próxima execução ter contra o que comparar.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.resolution.decisions import ResolutionStatus, SubjectType
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.sources.mapping import SourceFieldMapping
from sports_intelligence.domain.sources.semantics import SemanticRole
from tests.support.corpus import DISTRIBUICAO, Corpus, csv_bytes
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.pipeline import Pipeline

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: O volume que o PR-03.1 existe para provar (§4).
REGISTROS = 100_000
#: O volume dos testes comparativos. Dez mil bastam para ver a curva de
#: consultas e de memória, e rodar três tamanhos de lote sobre cem mil
#: custaria meia hora sem responder nada que estes não respondam.
REGISTROS_COMPARATIVOS = 10_000

PROVEDOR = ProviderId("benchmark_source")

CAMPOS: tuple[SourceFieldMapping, ...] = (
    SourceFieldMapping(column="Competition", role=SemanticRole.COMPETITION_NAME),
    SourceFieldMapping(column="Season", role=SemanticRole.SEASON_LABEL),
    SourceFieldMapping(column="Date", role=SemanticRole.KICKOFF_DATE, date_format="%Y-%m-%d"),
    SourceFieldMapping(column="Kickoff", role=SemanticRole.KICKOFF),
    SourceFieldMapping(column="Round", role=SemanticRole.ROUND_NUMBER),
    SourceFieldMapping(column="HomeTeam", role=SemanticRole.HOME_TEAM_NAME),
    SourceFieldMapping(column="AwayTeam", role=SemanticRole.AWAY_TEAM_NAME),
    SourceFieldMapping(column="FTHG", role=SemanticRole.HOME_SCORE),
    SourceFieldMapping(column="FTAG", role=SemanticRole.AWAY_SCORE),
    SourceFieldMapping(column="HS", role=SemanticRole.HOME_SHOTS),
    SourceFieldMapping(column="AS", role=SemanticRole.AWAY_SHOTS),
)


def _relatar(titulo: str, linhas: Sequence[str]) -> None:
    """Imprime o bloco que vai para o documento de baseline (§32).

    Vai para `stdout` e não para um arquivo versionado gerado: um artefato
    escrito pelo próprio teste entraria no `git` a cada execução com números
    diferentes, e o diff passaria a ser ruído permanente. O documento é
    escrito por gente, com o contexto de hardware junto.
    """
    print(f"\n┌─ {titulo}")
    for linha in linhas:
        print(f"│  {linha}")
    print("└" + "─" * (len(titulo) + 2))


async def _assinatura_da_execucao(
    database: Database, run_id: str, *, com_alternativas: bool = False
) -> list[tuple[Any, ...]]:
    """O que uma execução decidiu, em forma comparável.

    LIDA POR `SQL` E NÃO PELO CASO DE USO. `ListResolutionDecisions` pagina em
    500 e não carrega alternativas — ele existe para a tela do operador, não
    para conferir vinte mil decisões. Ler a tabela direto é o que permite
    comparar a execução INTEIRA, que é o que o teste afirma.

    O ID DA DECISÃO FICA DE FORA de propósito: ele é sorteado por construção,
    e compará-lo faria o teste falhar sempre sem provar nada. O ID DO DATASET
    também: comparar duas execuções sobre arquivos idênticos em datasets
    diferentes é o caso de uso desta função, e o `uuid` do dataset difere por
    construção. O que identifica a linha entre os dois é o NÚMERO dela.
    """
    import uuid as _uuid

    async with database.acquire() as conexao:
        linhas = await conexao.fetch(
            """
            SELECT split_part(d.record_ref, ':', 3)::int AS linha,
                   d.subject_type, d.source_normalized, d.status,
                   d.method, d.confidence, d.canonical_entity_id,
                   coalesce(
                       (SELECT string_agg(
                                  a.canonical_entity_id::text || ':' || a.score::text,
                                  ',' ORDER BY a.ordinal)
                        FROM resolution_alternatives a WHERE a.decision_id = d.id),
                       ''
                   ) AS alternativas
            FROM resolution_decisions d
            WHERE d.run_id = $1
            ORDER BY 1, d.subject_type, d.source_normalized
            """,
            _uuid.UUID(run_id),
        )
    return [tuple(linha) if com_alternativas else tuple(linha)[:-1] for linha in linhas]


async def _preparar(
    database: Database,
    object_store: Any,
    corpus: Corpus,
    *,
    registros: int,
    nome: str,
    batch_size: int,
) -> tuple[Pipeline, Any]:
    pipeline = Pipeline(database, object_store, batch_size=batch_size)
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()
    dataset = await pipeline.stage(
        name=nome, content=csv_bytes(corpus, total=registros), provider=PROVEDOR
    )
    await pipeline.map_source(dataset, provider=PROVEDOR, fields=CAMPOS)
    return pipeline, dataset


class TestResolucaoEmVolume:
    async def test_cem_mil_registros_pelo_caminho_operacional(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """A medida principal: cem mil linhas, do object store à decisão.

        MEDE O CAMINHO INTEIRO e não a função pura do resolver (§7). O que
        derruba um pipeline de ingestão não é comparar strings — é a ida ao
        banco, a serialização da decisão e o `INSERT` das evidências. Um
        benchmark que chamasse `TeamResolver.resolve` num laço mediria a
        parte que já se sabe barata.
        """
        pipeline, dataset = await _preparar(
            banco_semeado,
            object_store,
            corpus,
            registros=REGISTROS,
            nome="benchmark-100k",
            batch_size=1_000,
        )

        # PRIMEIRA EXECUÇÃO — FRIA: nada nos buffers do PostgreSQL sobre estas
        # tabelas, nada no cache de página do sistema.
        async with contando_consultas(banco_semeado) as consultas:
            with medindo("fria") as fria:
                saida = await pipeline.resolve(dataset.id)

        # SEGUNDA — QUENTE: mesmo dataset, execução nova (reprocessar produz
        # execução nova, nunca reescreve — ADR-0019). A diferença entre as
        # duas é o que o cache do banco e do sistema operacional dão.
        with medindo("quente") as quente:
            segunda = await pipeline.resolve(dataset.id)

        contagens = saida.run.counts
        total = contagens.total
        lotes = -(-REGISTROS // 1_000)

        _relatar(
            f"resolução · {REGISTROS:_} registros · lote 1.000",
            [
                f"corpus            {corpus.size}",
                f"decisões          {saida.decisions:_} em {total:_} sujeitos",
                f"fila de revisão   {saida.review_items:_}",
                "",
                f"fria              {fria.segundos:.1f}s · "
                f"{fria.por_segundo(REGISTROS):.0f} reg/s · pico {fria.pico_mb:.0f} MB",
                f"quente            {quente.segundos:.1f}s · "
                f"{quente.por_segundo(REGISTROS):.0f} reg/s · pico {quente.pico_mb:.0f} MB",
                "",
                f"consultas         {consultas.total:_} em {lotes} lotes "
                f"({consultas.total / lotes:.1f} por lote, "
                f"{consultas.total / REGISTROS:.4f} por registro)",
                f"por verbo         {consultas.por_verbo}",
                f"alvos             {consultas.mais_frequentes}",
                "",
                f"RESOLVED          {contagens.resolved:_}",
                f"REVIEW_REQUIRED   {contagens.review_required:_}",
                f"AMBIGUOUS         {contagens.ambiguous:_}",
                f"UNRESOLVED        {contagens.unresolved:_}",
                f"REJECTED          {contagens.rejected:_}",
                "",
                f"distribuição      {[(c.value, f) for c, f in DISTRIBUICAO]}",
            ],
        )

        assert total > 0
        assert saida.run.id != segunda.run.id
        # A EXECUÇÃO ANTERIOR CONTINUA INTACTA (§28). Reprocessar produz
        # execução nova; se a segunda reescrevesse a primeira, comparar
        # resolver novo com resolver velho seria comparar contra si mesmo.
        anterior = await pipeline.resolution.get_resolution_run.execute(saida.run.id)
        assert anterior.counts.total == total

    async def test_consultas_crescem_por_lote_e_nao_por_registro(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """A prova de execução contra o N+1 (§9, §38).

        O CAMINHO INGÊNUO produziria da ordem de sete consultas por registro —
        setecentas mil para cem mil linhas. O caminho em lote produz um punhado
        por lote. Os dois números diferem por ordens de grandeza, e é por isso
        que a asserção não precisa de um limite ajustado com precisão: ela
        pega a regressão grosseira, que é a que acontece.

        DEZ VEZES MAIS REGISTROS COM O MESMO LOTE devem multiplicar as
        consultas por perto de dez — porque são dez vezes mais LOTES —, e não
        por cem.
        """
        medidas: list[tuple[int, int, int]] = []
        for registros in (1_000, 10_000):
            pipeline, dataset = await _preparar(
                banco_semeado,
                object_store,
                corpus,
                registros=registros,
                nome=f"benchmark-n1-{registros}",
                batch_size=1_000,
            )
            async with contando_consultas(banco_semeado) as consultas:
                await pipeline.resolve(dataset.id)
            medidas.append((registros, -(-registros // 1_000), consultas.total))

        _relatar(
            "escalonamento de consultas · lote 1.000",
            [
                f"{r:_} registros · {lotes} lote(s) · {q:_} consultas · "
                f"{q / lotes:.1f} por lote · {q / r:.4f} por registro"
                for r, lotes, q in medidas
            ],
        )

        (r_pequeno, lotes_pequeno, q_pequeno), (r_grande, lotes_grande, q_grande) = medidas
        por_registro_pequeno = q_pequeno / r_pequeno
        por_registro_grande = q_grande / r_grande

        # A PROPRIEDADE: consultas POR REGISTRO caem quando o volume cresce,
        # porque o custo fixo do lote se dilui. Num N+1 elas seriam constantes
        # — e é exatamente essa constância que denuncia o defeito.
        assert por_registro_grande < por_registro_pequeno
        assert por_registro_grande < 0.5, (
            f"{por_registro_grande:.3f} consultas por registro: perto de 1 significa "
            "que alguém pôs um `for` em volta de uma chamada em massa"
        )
        # E o crescimento acompanha os LOTES, com folga para as consultas
        # legítimas de persistência, que crescem com o volume.
        assert q_grande < q_pequeno * (lotes_grande / lotes_pequeno) * 3

    @pytest.mark.parametrize("lote", [250, 1_000, 5_000])
    async def test_tamanho_de_lote(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus, lote: int
    ) -> None:
        """Três tamanhos, e a troca que cada um faz (§10).

        NÃO ESCOLHE O MAIOR AUTOMATICAMENTE. Um lote maior reduz idas ao banco
        e aumenta o pico de memória e o tamanho dos arrays que a consulta de
        confrontos carrega. O ponto certo depende da máquina, e o que este
        teste faz é MOSTRAR a troca — a escolha fica no documento de baseline.
        """
        pipeline, dataset = await _preparar(
            banco_semeado,
            object_store,
            corpus,
            registros=REGISTROS_COMPARATIVOS,
            nome=f"benchmark-lote-{lote}",
            batch_size=lote,
        )
        async with contando_consultas(banco_semeado) as consultas:
            with medindo(f"lote {lote}") as medida:
                saida = await pipeline.resolve(dataset.id)

        lotes = -(-REGISTROS_COMPARATIVOS // lote)
        _relatar(
            f"lote {lote} · {REGISTROS_COMPARATIVOS:_} registros",
            [
                f"tempo        {medida.segundos:.2f}s "
                f"({medida.por_segundo(REGISTROS_COMPARATIVOS):.0f} reg/s)",
                f"pico         {medida.pico_mb:.1f} MB",
                f"consultas    {consultas.total:_} em {lotes} lote(s) "
                f"({consultas.total / lotes:.1f} por lote)",
                f"decisões     {saida.decisions:_}",
            ],
        )
        assert saida.run.counts.total > 0

    async def test_pico_de_memoria_nao_acompanha_o_arquivo(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """Memória limitada pelo LOTE, não pelo arquivo (§37).

        A ASSERÇÃO É RELATIVA, não absoluta. «Menos de 200 MB» seria um número
        arbitrário que muda com a versão do Python. «Vinte vezes mais linhas
        não custam vinte vezes mais memória» é a propriedade de verdade, e ela
        sobrevive à troca de máquina.
        """
        picos: dict[int, float] = {}
        for registros in (2_500, 50_000):
            pipeline, dataset = await _preparar(
                banco_semeado,
                object_store,
                corpus,
                registros=registros,
                nome=f"benchmark-memoria-{registros}",
                batch_size=1_000,
            )
            with medindo(f"{registros}") as medida:
                await pipeline.resolve(dataset.id)
            picos[registros] = medida.pico_mb

        fator_de_dado = 50_000 / 2_500
        fator_de_pico = picos[50_000] / max(picos[2_500], 0.001)
        _relatar(
            "pico de memória por volume · lote 1.000",
            [
                f"2.500 registros   pico {picos[2_500]:.1f} MB",
                f"50.000 registros  pico {picos[50_000]:.1f} MB",
                f"dado x{fator_de_dado:.0f} · pico x{fator_de_pico:.1f}",
            ],
        )
        assert fator_de_pico < fator_de_dado / 2, (
            f"o pico cresceu x{fator_de_pico:.1f} para x{fator_de_dado:.0f} de dado: "
            "alguma coisa está acumulando o arquivo inteiro em memória"
        )


class TestBatchingNaoMudaSemantica:
    async def test_lotes_diferentes_decidem_exatamente_igual(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§37, §39: o critério é ZERO diferença — não «menos de 1%».

        O QUE O PR-03.1 MEDIU E O PR-03.2 FECHOU. Com o universo de
        candidatos vindo do que o lote tinha carregado, 2,7% das listas de
        alternativas mudavam entre lote 250 e lote 5.000. Nenhuma decisão
        `RESOLVED` mudava — e mesmo assim era uma violação: a lista de
        alternativas é o que o operador vê na fila de revisão, e ela passava a
        depender de um parâmetro de I/O.

        Agora o universo vem de uma busca POR NOME, então o tamanho do lote
        controla o que ele deve controlar — idas ao banco, memória, tamanho de
        transação — e mais nada.

        A COMPARAÇÃO INCLUI AS ALTERNATIVAS E A ORDEM DELAS (§31, §38).
        Comparar só `RESOLVED vs RESOLVED` teria passado antes da correção.
        """
        assinaturas: dict[int, list[tuple[Any, ...]]] = {}
        for lote in (250, 1_000, 5_000):
            pipeline, dataset = await _preparar(
                banco_semeado,
                object_store,
                corpus,
                registros=2_000,
                nome=f"benchmark-semantica-{lote}",
                batch_size=lote,
            )
            saida = await pipeline.resolve(dataset.id)
            assinaturas[lote] = await _assinatura_da_execucao(
                banco_semeado, saida.run.id, com_alternativas=True
            )

        assert assinaturas[250], "a execução não produziu decisão nenhuma"
        divergentes = {
            lote: sum(1 for a, b in zip(assinaturas[250], assinaturas[lote], strict=True) if a != b)
            for lote in (1_000, 5_000)
        }
        _relatar(
            "determinismo sob lotes diferentes · 2.000 registros",
            [
                f"decisões por execução   {len(assinaturas[250]):_}",
                f"250 vs 1.000            {divergentes[1_000]} divergência(s)",
                f"250 vs 5.000            {divergentes[5_000]} divergência(s)",
                "",
                "inclui status, método, confiança, entidade e a ORDEM das",
                "alternativas — que é onde a dependência de lote aparecia",
            ],
        )
        assert assinaturas[250] == assinaturas[1_000]
        assert assinaturas[250] == assinaturas[5_000]

    async def test_reexecutar_produz_a_mesma_decisao(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """Duas execuções da mesma entrada decidem igual, na mesma ordem (§46).

        A ORDEM DAS ALTERNATIVAS É DO DESEMPATE, não da leitura. É ela que o
        operador vê na fila de revisão, e uma ordem que mudasse a cada
        execução faria «o primeiro candidato» significar coisas diferentes em
        dois dias seguidos.
        """
        pipeline, dataset = await _preparar(
            banco_semeado,
            object_store,
            corpus,
            registros=2_000,
            nome="benchmark-ordem",
            batch_size=500,
        )
        primeira = await pipeline.resolve(dataset.id)
        segunda = await pipeline.resolve(dataset.id)

        assert primeira.run.id != segunda.run.id
        de_a = await _assinatura_da_execucao(banco_semeado, primeira.run.id)
        de_b = await _assinatura_da_execucao(banco_semeado, segunda.run.id)
        assert de_a, "a execução não produziu decisão nenhuma"
        assert de_a == de_b


class TestDistribuicaoDoCenario:
    async def test_o_cenario_exercita_os_quatro_caminhos(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """O benchmark só vale se o dado exercitar mais de um caminho (§5).

        SEM ESTE TESTE, uma mudança no gerador que fizesse tudo resolver por
        chave exata deixaria o throughput ótimo e o número sem sentido — e
        ninguém notaria, porque o benchmark não falha.
        """
        pipeline, dataset = await _preparar(
            banco_semeado,
            object_store,
            corpus,
            registros=5_000,
            nome="benchmark-distribuicao",
            batch_size=1_000,
        )
        import uuid as _uuid

        saida = await pipeline.resolve(dataset.id)
        async with banco_semeado.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT subject_type, method, status, count(*) AS quantas
                FROM resolution_decisions WHERE run_id = $1
                GROUP BY subject_type, method, status ORDER BY 1, 4 DESC
                """,
                _uuid.UUID(saida.run.id),
            )

        _relatar(
            "caminhos exercitados · 5.000 registros",
            [
                f"{linha['subject_type']:<12} {linha['method']:<24} "
                f"{linha['status']:<16} {linha['quantas']:_}"
                for linha in linhas
            ],
        )

        de_time = [linha for linha in linhas if linha["subject_type"] == SubjectType.TEAM.value]
        resolvidas = sum(
            linha["quantas"]
            for linha in de_time
            if linha["status"] == ResolutionStatus.RESOLVED.value
        )
        total_de_time = sum(linha["quantas"] for linha in de_time)
        assert resolvidas > 0, "nenhum time resolveu: o cenário não tem lado canônico"
        assert resolvidas < total_de_time, (
            "todos os times resolveram: o cenário não exercita busca de candidato "
            "nem a fila de revisão, e o número mediria um `dict.get`"
        )
        metodos = {linha["method"] for linha in de_time}
        assert len(metodos) > 1, f"um caminho só ({metodos}): a distribuição não pegou"
