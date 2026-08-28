"""As fronteiras do PR-06.2 — o que a cobertura pode e o que ela não pode.

O PR-06.1 JÁ GUARDA O PACOTE INTEIRO contra ANN, inteligência, trajetória,
amostragem e leitura de fato canônico. Este módulo guarda o que é NOVO, e o
novo é perigoso de um jeito específico: uma política de ausência frouxa não
falha — ela devolve vizinhos plausíveis a mais.

    §129  nenhuma imputação por zero, em lugar nenhum
    §130  o perfil não encolhe em função da query nem do candidato
    §131  o índice aproximado continua fora
    §186  nenhum candidato abaixo do piso recebe distância

E TAMBÉM O QUE O PR-06.2 NÃO PODE TER DESFEITO: as impressões do PR-06.1
precisam continuar byte-idênticas, e o oráculo de caso completo precisa
continuar executável ao lado do novo.
"""

from __future__ import annotations

import re
from pathlib import Path

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

#: Os módulos que o PR-06.2 acrescentou ao domínio.
DO_PR_06_2: tuple[str, ...] = (
    "availability.py",
    "availability_distance.py",
    "availability_exact.py",
    "availability_result.py",
    "coverage.py",
    "evidence.py",
)

FORA_DO_DOMINIO: tuple[str, ...] = (
    "application/use_cases/retrieval.py",
    "historical/retrieval/reader.py",
    "ports/object_store/retrieval.py",
)


def _sem_identificador(arquivos: list[Path], termos: tuple[str, ...]) -> None:
    """Nenhum dos termos aparece como IDENTIFICADOR nos arquivos.

    A FRONTEIRA DE PALAVRA NÃO É DETALHE. Uma varredura por substring acusa
    `AvailabilityAwareDistanceDefinition` de conter «redis» (awa-REDIS-tance) e
    `breakdown` de conter «break» — as duas foram observadas ao escrever este
    módulo. Uma guarda que produz falso positivo é desligada, e uma guarda
    desligada não guarda nada.
    """
    for arquivo in arquivos:
        corpo = code_only(arquivo)
        for termo in termos:
            achado = re.search(rf"{re.escape(termo)}", corpo)
            assert achado is None, (
                f"{arquivo.name}: {termo!r} em "
                f"{corpo[max(0, achado.start() - 40) : achado.end() + 20]!r}"
            )


def _sem_trecho(arquivos: list[Path], termos: tuple[str, ...]) -> None:
    """Nenhum dos trechos literais aparece — para o que não é identificador."""
    for arquivo in arquivos:
        corpo = code_only(arquivo)
        for termo in termos:
            assert termo not in corpo, f"{arquivo.name}: {termo}"


def _novos() -> list[Path]:
    return [RETRIEVAL / nome for nome in DO_PR_06_2]


def _alvos() -> list[Path]:
    return [*files_in("domain/retrieval"), *(FONTE / caminho for caminho in FORA_DO_DOMINIO)]


class TestOsModulosNovosExistem:
    """Uma guarda contra o teste que passa porque não olha nada."""

    def test_os_seis_modulos_estao_no_lugar(self) -> None:
        ausentes = [caminho.name for caminho in _novos() if not caminho.is_file()]
        assert not ausentes, f"módulos do PR-06.2 ausentes: {ausentes}"


class TestODominioContinuaPuro:
    """§127 — nenhuma infraestrutura entrou junto com a cobertura."""

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
        assert not violacoes, (
            f"o domínio da cobertura é `int`, `float` e `heapq` do interpretador — {violacoes}"
        )

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

    def test_nao_le_fato_canonico(self) -> None:
        """§116 — a cobertura não volta ao corpus para completar um eixo."""
        proibidos = (
            "sports_intelligence.domain.events",
            "sports_intelligence.domain.odds",
            "sports_intelligence.domain.matches",
            "sports_intelligence.domain.results",
            "sports_intelligence.domain.lineups",
            "sports_intelligence.domain.corpus",
        )
        assert not internal_violations(_novos(), proibidos)


class TestNaoImputa:
    """§129, §180 — a penalidade é o OPOSTO do preenchimento."""

    def test_sem_padrao_de_preenchimento(self) -> None:
        _sem_identificador(
            _alvos(),
            ("fillna", "fill_null", "nan_to_num", "impute", "coalesce", "mean_fill", "zero_fill"),
        )
        _sem_trecho(_alvos(), ("or 0.0", "or 0)", "or 0,", "default=0.0"))

    def test_o_valor_ausente_nunca_vira_numero(self) -> None:
        """A conta LÊ os valores só nas posições marcadas na máscara.

        A GUARDA É SOBRE A FORMA: o laço da distância pula o que não está
        marcado com `continue`, e o único caminho que lê `query[indice]` está
        depois dessa guarda. Um `else: termos.append(...)` ali seria imputação.
        """
        corpo = code_only(RETRIEVAL / "availability_distance.py")
        laco = corpo[corpo.index("for indice, marcado in enumerate(shared)") :]
        corpo_do_laco = laco[: laco.index("compartilhados = _contar")]
        assert "if not marcado:" in corpo_do_laco
        assert "continue" in corpo_do_laco
        assert "else:" not in corpo_do_laco

    def test_a_penalidade_e_uma_constante_declarada(self) -> None:
        """Ela não é um literal solto no meio de uma expressão."""
        from sports_intelligence.domain.retrieval.availability_distance import (
            MISSING_AXIS_PENALTY,
        )

        assert MISSING_AXIS_PENALTY == 1.0


class TestOPerfilNaoEncolhe:
    """§29, §130 — nenhuma lógica muda o perfil em função da disponibilidade."""

    def test_sem_reducao_dinamica_do_perfil(self) -> None:
        _sem_identificador(
            _novos(),
            ("shrink", "reduced_profile", "effective_profile", "dynamic_profile", "narrow"),
        )
        _sem_trecho(_novos(), ("profile = ", "feature_keys = ["))

    def test_o_denominador_e_o_perfil_no_codigo(self) -> None:
        """A divisão é por `profile_axis_count`, e não por `shared_count`.

        A GUARDA LÊ A EXPRESSÃO. Trocar o denominador é uma edição de uma
        palavra que não quebra nenhum tipo e muda o significado inteiro do
        número — exatamente a classe de defeito que uma guarda pega e uma
        revisão de código não.
        """
        corpo = code_only(RETRIEVAL / "availability_distance.py")
        # A GUARDA É SOBRE A PROPRIEDADE `value`, e não sobre o arquivo:
        # `observed_mse` divide por `shared_count` de propósito, e é outro
        # número — o diagnóstico, e nunca o ranking.
        valor = corpo[corpo.index("def value(self)") :]
        corpo_do_valor = valor[: valor.index("def observed_mse")]
        assert "/ self.profile_axis_count" in corpo_do_valor
        assert "shared_count" not in corpo_do_valor


class TestNaoAntecipaOIndice:
    """§108, §131 — continua exaustivo."""

    def test_sem_vestigio_de_ANN(self) -> None:
        proibidos = (
            "pgvector",
            "hnsw",
            "ivfflat",
            "faiss",
            "scann",
            "annoy",
            "approximate",
            "recall@",
            "ef_search",
            "ef_construction",
        )
        _sem_identificador(_alvos(), proibidos)

    def test_sem_poda_nem_parada_antecipada_na_varredura(self) -> None:
        """§64, §65 — o laço não tem `break`, e a atrição fica exata."""
        corpo = code_only(RETRIEVAL / "availability_exact.py")
        laco = corpo[corpo.index("for candidato in candidates") :]
        corpo_do_laco = laco[: laco.index("descritor = universo.finalize")]
        # `break`, E NÃO A SUBSTRING: o item do heap tem um campo
        # `breakdown`, e uma varredura ingênua o acusaria.
        assert re.search(r"break", corpo_do_laco) is None, (
            "um `break` na varredura é como uma parada antecipada entra — e a "
            "contagem de candidatos recusados por cobertura deixaria de ser exata"
        )

    def test_sem_amostragem(self) -> None:
        _sem_identificador(_novos(), ("random", "sample", "reservoir", "seed", "shuffle", "top_n"))


class TestNaoAntecipaOsPRsSeguintes:
    """§107, §109, §110, §111, §85 — o que ainda não é deste PR."""

    def test_sem_trajetoria(self) -> None:
        proibidos = ("trajectory", "dtw", "time_window", "tolerance", "t_minus")
        _sem_identificador(_novos(), proibidos)

    def test_sem_peso_nem_tamanho_efetivo_de_amostra(self) -> None:
        proibidos = (
            "alpha",
            "beta",
            "gamma",
            "lambda_",
            "weights",
            "weighted",
            "n_eff",
            "effective_sample",
            "decay",
            "kernel",
        )
        _sem_identificador(_novos(), proibidos)

    def test_sem_confianca_nem_probabilidade(self) -> None:
        """§85 — `PenaltyShare` é evidência; convertê-la é do PR-06.7."""
        proibidos = ("confidence", "probability", "likelihood", "certainty")
        _sem_identificador(_novos(), proibidos)

    def test_sem_inteligencia_nem_desfecho(self) -> None:
        """§59, §111 — nada de vencedor, gol seguinte ou tendência."""
        proibidos = (
            "result_trend",
            "pressure_trend",
            "market_trend",
            "goal_timing",
            "winner",
            "final_score",
            "next_goal",
            "outcome",
            "prediction",
            "forecast",
        )
        _sem_identificador(_novos(), proibidos)

    def test_sem_cache(self) -> None:
        """§118 — o caminho exato continua sendo medido sem atalho."""
        _sem_identificador(_novos(), ("lru_cache", "cached_property", "redis", "memoize"))
        _sem_trecho(_novos(), ("@cache",))


class TestSemMigracao:
    """§119, §174 — nada de novo é persistido."""

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

    def test_as_impressoes_do_PR_06_1_nao_mudaram(self) -> None:
        """Os goldens, escritos por extenso.

        ELES SÃO O CONTRATO DO §175. Acrescentar um membro a um catálogo, um
        campo a um contrato ou uma chave a uma forma canônica muda uma
        impressão — e a única forma de saber é fixá-la.
        """
        from sports_intelligence.domain.retrieval.candidate_policy import (
            DEFAULT_CANDIDATE_POLICY,
        )
        from sports_intelligence.domain.retrieval.profile import (
            DEFAULT_RETRIEVAL_PROFILE,
        )

        assert DEFAULT_CANDIDATE_POLICY.fingerprint == (
            "cd0c62f32f4336f686085aa95799d8fca8b472d4cd230bb0bb5690c5cf93bde1"
        )
        assert DEFAULT_RETRIEVAL_PROFILE.fingerprint == (
            "8b71f33612eb22a666bffa64f194d9475bce8e9ab6168c239f5eb1701eec1848"
        )

    def test_o_oraculo_de_caso_completo_continua_no_lugar(self) -> None:
        """§73 — ele não foi substituído."""
        assert (RETRIEVAL / "exact.py").is_file()
        assert (RETRIEVAL / "distance.py").is_file()
        assert (RETRIEVAL / "result.py").is_file()
        assert (RETRIEVAL / "neighbor.py").is_file()

    def test_o_oraculo_nao_importa_nada_do_PR_06_2(self) -> None:
        """A dependência é de MÃO ÚNICA, e a direção importa.

        O PR-06.2 conhece o PR-06.1 — ele reusa a política de candidatos, o
        acumulador de universo e a semântica de `float`. O contrário faria o
        oráculo depender da cobertura, e ele deixaria de ser uma régua estável.
        """
        for nome in ("exact.py", "distance.py", "result.py", "neighbor.py"):
            corpo = code_only(RETRIEVAL / nome)
            for modulo in DO_PR_06_2:
                assert modulo.removesuffix(".py") not in corpo, (
                    f"{nome} importa {modulo}: a régua passaria a depender do que ela mede"
                )
