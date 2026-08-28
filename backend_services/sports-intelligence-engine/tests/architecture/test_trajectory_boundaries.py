"""As fronteiras do PR-06.3 — o que a trajetória pode e o que ela não pode.

O NOVO É PERIGOSO DE TRÊS JEITOS ESPECÍFICOS, e nenhum deles falha alto:

    §213  olhar para o FUTURO       a distância sai plausível, e é vazamento
    §214  atravessar o INTERVALO    a trajetória mede quinze minutos de
                                    vestiário como se fossem minutos de jogo
    §215  PREENCHER a ausência      `Δ = 0` é estabilidade inventada, e ela
    §216                            parece calma

E MAIS UM, que é o do PR inteiro:

    §217  SOMAR estado e trajetória num float só

Este módulo guarda os quatro, e o que o PR-06.1 e o PR-06.2 já guardavam
continua valendo — as guardas deles varrem `domain/retrieval` inteiro.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from tests.support.ast_checks import (
    FONTE,
    RAIZ,
    code_only,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

RETRIEVAL = FONTE / "domain" / "retrieval"

#: Os módulos que o PR-06.3 acrescentou ao domínio.
DO_PR_06_3: tuple[str, ...] = (
    "trajectory.py",
    "trajectory_coverage.py",
    "trajectory_distance.py",
    "trajectory_evidence.py",
    "trajectory_exact.py",
    "trajectory_profile.py",
    "trajectory_result.py",
    "trajectory_window.py",
)

FORA_DO_DOMINIO: tuple[str, ...] = (
    "application/use_cases/trajectory_retrieval.py",
    "historical/retrieval/trajectory_reader.py",
    "ports/object_store/trajectory.py",
)


def _novos() -> list[Path]:
    return [RETRIEVAL / nome for nome in DO_PR_06_3]


def _alvos() -> list[Path]:
    return [*_novos(), *(FONTE / caminho for caminho in FORA_DO_DOMINIO)]


def _sem_identificador(arquivos: list[Path], termos: tuple[str, ...]) -> None:
    """Nenhum dos termos aparece como IDENTIFICADOR.

    A FRONTEIRA DE PALAVRA NÃO É DETALHE — ver o módulo do PR-06.2: uma
    varredura por substring acusa `breakdown` de conter «break». Uma guarda que
    produz falso positivo é desligada, e uma guarda desligada não guarda nada.
    """
    for arquivo in arquivos:
        corpo = code_only(arquivo)
        for termo in termos:
            achado = re.search(rf"\b{re.escape(termo)}\b", corpo)
            assert achado is None, (
                f"{arquivo.name}: {termo!r} em "
                f"{corpo[max(0, achado.start() - 40) : achado.end() + 20]!r}"
            )


def _sem_trecho(arquivos: list[Path], termos: tuple[str, ...]) -> None:
    for arquivo in arquivos:
        corpo = code_only(arquivo)
        for termo in termos:
            assert termo not in corpo, f"{arquivo.name}: {termo}"


class TestOsModulosNovosExistem:
    """Uma guarda contra o teste que passa porque não olha nada."""

    def test_os_oito_modulos_estao_no_lugar(self) -> None:
        ausentes = [c.name for c in _novos() if not c.is_file()]
        assert not ausentes, f"módulos do PR-06.3 ausentes: {ausentes}"

    def test_e_os_tres_de_fora_tambem(self) -> None:
        ausentes = [c for c in FORA_DO_DOMINIO if not (FONTE / c).is_file()]
        assert not ausentes


class TestODominioContinuaPuro:
    """§212 — nenhuma infraestrutura entrou junto com a trajetória."""

    def test_nao_importa_biblioteca_de_io_nem_de_indice(self) -> None:
        proibidas = (
            "pyarrow",
            "minio",
            "boto3",
            "asyncpg",
            "psycopg",
            "fastapi",
            "starlette",
            "redis",
            "clickhouse",
            "pgvector",
            "numpy",
            "pandas",
            "scipy",
            "sklearn",
            "faiss",
        )
        violacoes = external_violations(_novos(), frozenset(proibidas))
        assert not violacoes, f"o domínio da trajetória é `int`, `float` e `heapq` — {violacoes}"

    def test_nao_importa_camada_de_cima(self) -> None:
        proibidas = (
            "sports_intelligence.adapters",
            "sports_intelligence.application",
            "sports_intelligence.historical",
            "sports_intelligence.ingestion",
            "sports_intelligence.api",
            "apps.",
        )
        assert not internal_violations(_novos(), proibidas)

    def test_nao_importa_desfecho_nem_evento(self) -> None:
        """§219 — a trajetória não volta ao corpus."""
        proibidos = (
            "sports_intelligence.domain.events",
            "sports_intelligence.domain.odds",
            "sports_intelligence.domain.matches.result",
            "sports_intelligence.domain.results",
            "sports_intelligence.domain.lineups",
            "sports_intelligence.domain.corpus",
        )
        assert not internal_violations(_novos(), proibidos)


class TestNaoOlhaParaOFuturo:
    """§213, §254 — a guarda mais importante deste PR."""

    def test_o_catalogo_de_direcao_tem_UM_membro(self) -> None:
        from sports_intelligence.domain.retrieval.trajectory_window import (
            TrajectoryDirection,
        )

        assert {d.value for d in TrajectoryDirection} == {"BACKWARD"}
        assert "FORWARD" not in {d.name for d in TrajectoryDirection}

    def test_a_aritmetica_da_janela_SUBTRAI(self) -> None:
        """A forma da expressão: `minuto - horizonte`, e nunca `+`.

        A GUARDA LÊ A EXPRESSÃO porque trocar o sinal é uma edição de UM
        caractere que não quebra nenhum tipo, não falha nenhum tipo de
        checagem, e transforma a trajetória num vazamento do futuro.
        """
        corpo = code_only(RETRIEVAL / "trajectory_window.py")
        assert "alvo = anchor.minute - horizonte" in corpo
        assert "anchor.minute + horizonte" not in corpo

    def test_sem_vocabulario_de_futuro(self) -> None:
        _sem_identificador(
            _alvos(),
            (
                "lookahead",
                "look_ahead",
                "forward_horizon",
                "future_snapshot",
                "next_snapshot",
                "peek",
            ),
        )

    def test_o_construtor_da_trajetoria_recusa_alvo_nao_anterior(self) -> None:
        """A guarda de execução, e não só a de forma."""
        corpo = code_only(RETRIEVAL / "trajectory.py")
        assert "slot.target >= self.anchor_position" in corpo


class TestNaoAtravessaOPeriodo:
    """§214, §18 — o intervalo não é um minuto de jogo."""

    def test_o_catalogo_de_cruzamento_tem_UM_membro(self) -> None:
        from sports_intelligence.domain.retrieval.trajectory_window import (
            PeriodCrossingPolicy,
        )

        assert {p.value for p in PeriodCrossingPolicy} == {"STOP_AT_PERIOD_START"}
        assert "ALLOW" not in {p.name for p in PeriodCrossingPolicy}

    def test_a_janela_compara_contra_o_comeco_do_periodo(self) -> None:
        corpo = code_only(RETRIEVAL / "trajectory_window.py")
        assert "if alvo < inicio:" in corpo
        # `code_only` DEVOLVE MINÚSCULAS — ver o utilitário.
        assert "outside_period_lookback" in corpo

    def test_os_limites_vem_da_GRADE(self) -> None:
        """§20 — e não de constantes locais que divergiriam dela."""
        corpo = code_only(RETRIEVAL / "trajectory_window.py")
        assert "grid.first_half_last_minute" in corpo
        assert "grid.second_half_last_minute" in corpo

    def test_o_construtor_recusa_alvo_de_outro_periodo(self) -> None:
        corpo = code_only(RETRIEVAL / "trajectory.py")
        assert "slot.target.period is not self.anchor_position.period" in corpo

    def test_sem_relogio_de_parede(self) -> None:
        """§19 — nada de `kickoff + minuto` nem de duração de intervalo."""
        _sem_identificador(
            _novos(),
            (
                "kickoff",
                "wall_clock",
                "timedelta",
                "datetime",
                "elapsed_match_minutes",
                "halftime_duration",
            ),
        )


class TestNaoPreencheNemInterpola:
    """§215, §216, §102, §103 — o blocker mais perigoso deste PR."""

    def test_sem_padrao_de_preenchimento(self) -> None:
        _sem_identificador(
            _alvos(),
            (
                "fillna",
                "fill_null",
                "nan_to_num",
                "impute",
                "coalesce",
                "mean_fill",
                "zero_fill",
            ),
        )
        _sem_trecho(_alvos(), ("or 0.0", "or 0)", "or 0,", "default=0.0"))

    def test_sem_interpolacao_nem_vizinho_mais_proximo(self) -> None:
        """§29, §216."""
        _sem_identificador(
            _alvos(),
            (
                "interpolate",
                "interpolation",
                "forward_fill",
                "backward_fill",
                "ffill",
                "bfill",
                "nearest",
                "nearest_row",
                "resample",
                "dtw",
            ),
        )

    def test_o_deslocamento_exige_OS_DOIS_extremos(self) -> None:
        """§159 — a forma da guarda, e não só o comportamento."""
        corpo = code_only(RETRIEVAL / "trajectory.py")
        assert "if not (mascara_da_ancora[indice] and mascara_do_slot[indice]):" in corpo

    def test_o_denominador_e_o_ESPACO_e_nao_a_intersecao(self) -> None:
        """§44, §95 — trocar o denominador é uma edição de uma palavra."""
        corpo = code_only(RETRIEVAL / "trajectory_distance.py")
        valor = corpo[corpo.index("def value(self)") :]
        corpo_do_valor = valor[: valor.index("def observed_mse")]
        assert "/ self.cell_count" in corpo_do_valor
        assert "shared_cells" not in corpo_do_valor


class TestNaoCombinaEstadoComTrajetoria:
    """§4, §217, §258 — o PR entrega DOIS sinais, e não um."""

    def test_sem_peso_nem_score_combinado(self) -> None:
        _sem_identificador(
            _alvos(),
            (
                "alpha",
                "beta",
                "gamma",
                "lambda_",
                "weights",
                "weighted",
                "combined_score",
                "total_score",
                "d_total",
                "blend",
                "ensemble",
            ),
        )

    def test_o_dominio_da_trajetoria_NAO_importa_a_distancia_de_ESTADO(self) -> None:
        """A separação, na direção que importa.

        A trajetória REUSA da régua de estado o que é infraestrutura numérica —
        a semântica de `float`, o piso racional, o valor da penalidade — e
        NUNCA a definição de distância nem o resultado: importá-los seria o
        primeiro passo para somá-los.
        """
        proibidos = ("AvailabilityAwareDistanceDefinition", "AvailabilityAwareRetrievalResult")
        for arquivo in _novos():
            corpo = code_only(arquivo)
            for termo in proibidos:
                assert termo.lower() not in corpo, f"{arquivo.name}: {termo}"

    def test_o_comparador_NAO_soma(self) -> None:
        """§147 — ele apresenta, e não combina."""
        corpo = code_only(FONTE / "application/use_cases/trajectory_retrieval.py")
        comparador = corpo[corpo.index("class comparestateandtrajectory") :]
        assert "0.5" not in comparador
        for termo in ("alpha", "beta", "weight", "combined"):
            assert termo not in comparador


class TestNaoAntecipaOIndice:
    """§118, §218 — continua exaustivo, e sem cache."""

    def test_sem_vestigio_de_ANN(self) -> None:
        _sem_identificador(
            _alvos(),
            (
                "pgvector",
                "hnsw",
                "ivfflat",
                "faiss",
                "scann",
                "annoy",
                "approximate",
                "ef_search",
                "ef_construction",
            ),
        )

    def test_sem_cache(self) -> None:
        """§138."""
        _sem_identificador(_alvos(), ("lru_cache", "cached_property", "redis", "memoize"))
        _sem_trecho(_alvos(), ("@cache",))

    def test_sem_poda_na_varredura_de_candidatos(self) -> None:
        """§118 — o laço não tem `break`."""
        corpo = code_only(RETRIEVAL / "trajectory_exact.py")
        laco = corpo[corpo.index("for candidato in candidates") :]
        corpo_do_laco = laco[: laco.index("descritor = universo.finalize")]
        assert re.search(r"\bbreak\b", corpo_do_laco) is None

    def test_sem_amostragem(self) -> None:
        _sem_identificador(_novos(), ("random", "sample", "reservoir", "seed", "shuffle", "top_n"))


class TestNaoHaLeituraNMaisUm:
    """§127, §129, §245 — a prova de FORMA; a de número está no benchmark."""

    def test_o_leitor_varre_a_particao_UMA_vez_por_objeto(self) -> None:
        """A varredura é por objeto, e o filtro é por CONJUNTO de instantes.

        A GUARDA LÊ A FORMA: se houvesse um laço por horizonte por candidato,
        `_objetos` apareceria dentro dele. Aqui ele é chamado uma vez, e o
        laço interno percorre os objetos daquela partição.
        """
        corpo = code_only(FONTE / "historical/retrieval/trajectory_reader.py")
        varredura = corpo[corpo.index("async def stream_candidate_trajectories") :]
        corpo_da_varredura = varredura[: varredura.index("async def count_trajectory_rows")]
        assert corpo_da_varredura.count("await self._objetos(") == 1
        # E O FILTRO É UM CONJUNTO DE INSTANTES, e não um instante por vez.
        assert "instantes = {anchor, *targets}" in corpo_da_varredura
        assert "if posicao not in instantes:" in corpo

    def test_o_caso_de_uso_chama_o_leitor_UMA_vez(self) -> None:
        corpo = code_only(FONTE / "application/use_cases/trajectory_retrieval.py")
        assert corpo.count("stream_candidate_trajectories(") == 1
        assert corpo.count("load_query_trajectory_rows(") == 1

    def test_o_leitor_conta_as_linhas_de_origem(self) -> None:
        """§204, §210 — sem o contador, a ausência do N+1 seria uma opinião."""
        from sports_intelligence.historical.retrieval.trajectory_reader import (
            ParquetHistoricalTrajectorySource,
        )

        assert hasattr(ParquetHistoricalTrajectorySource, "source_rows_read")


class TestSemMigracao:
    """§137, §223 — nada de novo é persistido."""

    def test_as_migracoes_anteriores_nao_mudaram(self) -> None:
        """A afirmação era FASE-LOCAL, e a fase mudou (PR-06.4).

        O QUE ELA DIZIA: «a última migração é a 0013». Isso era verdade
        enquanto nada da recuperação era persistido — e o PR-06.4 passou a
        persistir a PROJEÇÃO de recuperação, que é justamente o que elimina a
        releitura do Parquet a cada consulta.

        O QUE ELA PASSA A DIZER, e é o invariante que sempre importou: as
        migrações ANTERIORES continuam intactas, e a nova é ADITIVA. Apagar o
        teste teria descartado a proteção junto com a afirmação vencida; o que
        se perde ao mudá-lo é só a data de validade.
        """
        migracoes = sorted(p.name for p in (RAIZ / "migrations").glob("*.sql"))
        assert migracoes[-1] == "0014_historical_retrieval_projection.sql", (
            "a migração do PR-06.4 é a última; uma posterior precisa de "
            f"justificativa explícita — {migracoes[-3:]}"
        )
        # AS ANTERIORES CONTINUAM LÁ, E COM OS MESMOS NOMES. Uma migração
        # renomeada é uma migração reescrita para o aplicador, que guarda o
        # SHA-256 de cada uma e recusa seguir quando o arquivo muda.
        assert migracoes[12] == "0013_normalized_feature_dataset.sql"
        assert len(migracoes) == 14

    def test_a_trajetoria_nao_e_persistida(self) -> None:
        """§134, §135 — ela é derivada na leitura, e reconstruível."""
        _sem_identificador(
            _alvos(),
            ("insert", "insert_into", "persist_trajectory", "materialize_trajectory"),
        )


class TestOsPRsAnterioresContinuamIntactos:
    """§5, §220, §221 — as réguas congeladas."""

    def test_as_impressoes_anteriores_nao_mudaram(self) -> None:
        from sports_intelligence.domain.retrieval.candidate_policy import (
            DEFAULT_CANDIDATE_POLICY,
        )
        from sports_intelligence.domain.retrieval.coverage import DEFAULT_COVERAGE_POLICY
        from sports_intelligence.domain.retrieval.profile import (
            AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
            DEFAULT_RETRIEVAL_PROFILE,
        )

        assert DEFAULT_CANDIDATE_POLICY.fingerprint == (
            "cd0c62f32f4336f686085aa95799d8fca8b472d4cd230bb0bb5690c5cf93bde1"
        )
        assert DEFAULT_RETRIEVAL_PROFILE.fingerprint == (
            "8b71f33612eb22a666bffa64f194d9475bce8e9ab6168c239f5eb1701eec1848"
        )
        assert AVAILABILITY_AWARE_RETRIEVAL_PROFILE.fingerprint == (
            "a37702d20fa87907ff0a385200b2a631e516cbfb888cefe0f11ef930d7cc423c"
        )
        assert DEFAULT_COVERAGE_POLICY.fingerprint == (
            "ed825ca38fc24ce510848f019939dc6edfe60f9e1cd038cdd9f991214959fd69"
        )

    def test_os_dois_recuperadores_anteriores_continuam_no_lugar(self) -> None:
        for nome in (
            "exact.py",
            "distance.py",
            "result.py",
            "neighbor.py",
            "availability_exact.py",
            "availability_distance.py",
            "availability_result.py",
        ):
            assert (RETRIEVAL / nome).is_file()

    def test_eles_NAO_importam_nada_do_PR_06_3(self) -> None:
        """A dependência é de MÃO ÚNICA, e a direção importa.

        O PR-06.3 reusa dos anteriores a política de candidatos, o acumulador
        de universo, o piso racional e a semântica de `float`. O contrário
        faria as réguas dependerem do que elas medem.
        """
        for nome in (
            "exact.py",
            "distance.py",
            "result.py",
            "neighbor.py",
            "availability_exact.py",
            "availability_distance.py",
            "availability_result.py",
            "coverage.py",
            "evidence.py",
        ):
            corpo = code_only(RETRIEVAL / nome)
            for modulo in DO_PR_06_3:
                assert modulo.removesuffix(".py") not in corpo, (
                    f"{nome} importa {modulo}: a régua passaria a depender do que mede"
                )


class TestAsGuardasAnterioresContinuamValendo:
    """As varreduras do PR-06.1 e do PR-06.2 cobrem `domain/retrieval` inteiro."""

    def test_o_pacote_inteiro_continua_sem_ANN(self) -> None:
        _sem_identificador(
            files_in("domain/retrieval"),
            ("pgvector", "hnsw", "ivfflat", "faiss", "scann", "annoy"),
        )

    def test_o_pacote_inteiro_continua_sem_desfecho(self) -> None:
        _sem_identificador(
            files_in("domain/retrieval"),
            (
                "winner",
                "final_score",
                "next_goal",
                "prediction",
                "forecast",
                "result_trend",
                "pressure_trend",
            ),
        )


class TestOPisoNAOPassaPorPontoFlutuante:
    """§12 do adendo — a decisão de cobertura é INTEIRA, e a prova é do AST.

    UMA GUARDA TEXTUAL AQUI SERIA FRÁGIL. `0.6` aparece legitimamente em
    docstrings, e `ceil` aparece no nome `ceil_div`; procurar as palavras no
    fonte produziria falso positivo em ambos. O que este teste faz é olhar a
    ÁRVORE: quais nomes as funções de decisão realmente chamam, e que tipo de
    literal e de operador de divisão elas realmente contêm.
    """

    #: As funções que DECIDEM admissibilidade de cobertura temporal.
    DECISORAS: Final[tuple[str, ...]] = (
        "floors",
        "cell_floors",
        "admits_query",
        "admits_pair",
        "admits_profile",
        "is_evidential_horizon",
        "minimum_part",
        "ceil_div",
        "admits",
    )

    def _funcoes_decisoras(self) -> list[tuple[Path, ast.FunctionDef]]:
        achadas: list[tuple[Path, ast.FunctionDef]] = []
        for caminho in (
            RETRIEVAL / "trajectory_coverage.py",
            RETRIEVAL / "coverage.py",
        ):
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                if isinstance(no, ast.FunctionDef) and no.name in self.DECISORAS:
                    achadas.append((caminho, no))
        return achadas

    def test_o_harnes_encontra_as_funcoes_que_decidem(self) -> None:
        """Uma guarda contra o teste que passa porque não achou nada."""
        nomes = {no.name for _, no in self._funcoes_decisoras()}
        assert nomes >= {
            "floors",
            "cell_floors",
            "admits_query",
            "admits_pair",
            "is_evidential_horizon",
            "minimum_part",
            "ceil_div",
        }, f"o harnes nao localizou as decisoras: achou {sorted(nomes)}"

    def test_nenhuma_decisora_contem_literal_FLOAT(self) -> None:
        """Nem `0.6`, nem `0.5`, nem constante alguma de ponto flutuante."""
        ofensas: list[str] = []
        for caminho, funcao in self._funcoes_decisoras():
            for no in ast.walk(funcao):
                if isinstance(no, ast.Constant) and isinstance(no.value, float):
                    ofensas.append(f"{caminho.name}:{funcao.name} tem o float {no.value}")
        assert not ofensas, ofensas

    def test_nenhuma_decisora_usa_DIVISAO_VERDADEIRA(self) -> None:
        """`/` produz `float` em Python. Só `//` é permitido aqui.

        É ASSIM QUE `ceil(a / b)` ENTRARIA. O teto sobre uma divisão já
        arredondada é o erro que o §4 proíbe, e o operador é o que o denuncia.
        """
        ofensas: list[str] = []
        for caminho, funcao in self._funcoes_decisoras():
            for no in ast.walk(funcao):
                if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Div):
                    ofensas.append(f"{caminho.name}:{funcao.name} usa `/`")
        assert not ofensas, ofensas

    def test_nenhuma_decisora_chama_ceil_round_ou_float(self) -> None:
        """`math.ceil`, `round` e `float` não participam da decisão."""
        proibidas = {"ceil", "floor", "round", "float", "fsum", "trunc"}
        ofensas: list[str] = []
        for caminho, funcao in self._funcoes_decisoras():
            for no in ast.walk(funcao):
                if not isinstance(no, ast.Call):
                    continue
                alvo = no.func
                nome = (
                    alvo.attr
                    if isinstance(alvo, ast.Attribute)
                    else alvo.id
                    if isinstance(alvo, ast.Name)
                    else ""
                )
                if nome in proibidas:
                    ofensas.append(f"{caminho.name}:{funcao.name} chama {nome}()")
        assert not ofensas, ofensas

    def test_a_derivacao_do_piso_e_UMA_SO(self) -> None:
        """§5 do gate — não existe segunda implementação da mesma fórmula.

        A EXPRESSÃO `-((-a) // b)` PODE APARECER UMA VEZ SÓ no domínio de
        produção, dentro de `ceil_div`. Duas cópias é como uma delas passa a
        decidir sozinha depois de uma mudança na outra.
        """
        ocorrencias: list[str] = []
        for caminho in sorted(FONTE.rglob("*.py")):
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                # `-((-x) // y)` é UnaryOp(USub, BinOp(FloorDiv, UnaryOp(USub, _), _))
                if (
                    isinstance(no, ast.UnaryOp)
                    and isinstance(no.op, ast.USub)
                    and isinstance(no.operand, ast.BinOp)
                    and isinstance(no.operand.op, ast.FloorDiv)
                    and isinstance(no.operand.left, ast.UnaryOp)
                    and isinstance(no.operand.left.op, ast.USub)
                ):
                    ocorrencias.append(f"{caminho.name}:{no.lineno}")
        assert len(ocorrencias) == 1, (
            f"o teto inteiro esta escrito em {len(ocorrencias)} lugares: {ocorrencias}"
        )
        assert "coverage.py" in ocorrencias[0]

    def test_a_avaliacao_de_cobertura_NAO_decide_por_fracao(self) -> None:
        """As frações existem para RELATÓRIO, e não para decidir.

        `shared_coverage` devolve `float` de propósito — é um número para o
        operador ler. O que este teste garante é que os predicados `meets_*`
        não o consultam: eles comparam CONTAGENS contra PISOS, os dois `int`.
        """
        arvore = ast.parse((RETRIEVAL / "trajectory_coverage.py").read_text(encoding="utf-8"))
        predicados = {
            "meets_query_cell_floor",
            "meets_shared_cell_floor",
            "meets_horizon_count_floor",
        }
        vistos: set[str] = set()
        for no in ast.walk(arvore):
            if not isinstance(no, ast.FunctionDef) or no.name not in predicados:
                continue
            vistos.add(no.name)
            for interno in ast.walk(no):
                if isinstance(interno, ast.Attribute):
                    assert "coverage" not in interno.attr or interno.attr.endswith("_floor"), (
                        f"{no.name} consulta a fracao {interno.attr}"
                    )
                if isinstance(interno, ast.Constant):
                    assert not isinstance(interno.value, float), no.name
        assert vistos == predicados, f"faltou verificar {predicados - vistos}"
