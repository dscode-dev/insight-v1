"""As fronteiras do PR-06.1 — o oráculo, e tudo que ele não é.

O QUE ESTE ARQUIVO PROTEGE:

    o domínio de retrieval   puro: sem pyarrow, sem banco, sem object store
    o PR                     NÃO é ANN: sem pgvector, HNSW, IVFFlat, FAISS
    o PR                     NÃO é inteligência: sem rótulo, resultado final,
                             gol seguinte, tendência, probabilidade
    o universo               NÃO amostra: sem semente, sem reservoir, sem teto
    a distância              sem pesos, sem imputação, sem penalidade
    a recuperação            NÃO volta ao corpus: zero leitura de fato canônico
    a trajetória             não existe: a query é UM snapshot

O PERIGO CENTRAL DESTA FASE É O RÓTULO. Com os vizinhos na mão, acrescentar «e
o que aconteceu depois» é a coisa mais natural do mundo — e no dia em que o
`HistoricalNeighbor` carregar o resultado final, alguém vai filtrar candidatos
por ele. O vazamento estaria DENTRO do contrato, e não fora.

O SEGUNDO É A AMOSTRAGEM. Um universo grande convida a «pegar as primeiras dez
mil linhas», e o resultado continua parecendo um top-K. A diferença é que ele
deixa de ser reproduzível e deixa de servir como oráculo — que é a única coisa
que este PR entrega.

O TERCEIRO É A IMPUTAÇÃO. Um candidato sem um eixo é tentador de completar com
zero, com a média, ou com o valor cru. Qualquer uma delas produz uma distância
plausível sobre um número que ninguém mediu.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_checks import (
    FONTE,
    RAIZ,
    code_only,
    external_violations,
    files_in,
    imports_of,
    internal_violations,
)

pytestmark = pytest.mark.architecture

RETRIEVAL = "domain/retrieval"

FONTES_PROIBIDAS = (
    "sports_intelligence.ingestion",
    "sports_intelligence.adapters",
    "sports_intelligence.application",
    "sports_intelligence.historical",
    "sports_intelligence.domain.sources",
    "sports_intelligence.domain.resolution",
    "sports_intelligence.domain.fusion",
    "sports_intelligence.archival",
    "apps.",
)

#: Os pacotes de índice aproximado e de armazenamento vetorial. Nenhum deles
#: existe, e o PR-06.4 é quem decide se algum vai existir.
PACOTES_DE_INDICE = (
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)

BIBLIOTECAS_PROIBIDAS = frozenset(
    {
        "numpy",
        "pandas",
        "polars",
        "scipy",
        "sklearn",
        "scikit_learn",
        "statsmodels",
        "pyarrow",
        "asyncpg",
        "faiss",
        "hnswlib",
        "annoy",
        "pgvector",
        "redis",
    }
)

#: Os arquivos deste PR que ficam fora do domínio. Eles entram nas varreduras
#: de rótulo e de índice — o vazamento não fica mais aceitável por acontecer
#: num adaptador.
FORA_DO_DOMINIO = (
    "application/use_cases/retrieval.py",
    "historical/retrieval/reader.py",
    "ports/object_store/retrieval.py",
)


def _alvos() -> list[Path]:
    return [*files_in(RETRIEVAL), *(FONTE / caminho for caminho in FORA_DO_DOMINIO)]


#: Os módulos do CASO COMPLETO — o oráculo do PR-06.1, e só ele.
#:
#: A LISTA EXISTE DESDE O PR-06.2, e o motivo é que o pacote passou a ter DUAS
#: semânticas de ausência convivendo. As guardas que dizem «aqui não há
#: penalidade nem piso de cobertura» continuam verdadeiras — mas sobre estes
#: quatro arquivos, e não sobre o pacote inteiro. Aplicá-las ao pacote pediria
#: que o PR-06.2 não existisse; removê-las deixaria o oráculo desprotegido.
CASO_COMPLETO: tuple[str, ...] = (
    "distance.py",
    "exact.py",
    "neighbor.py",
    "result.py",
)


def _alvos_do_caso_completo() -> list[Path]:
    return [FONTE / "domain/retrieval" / nome for nome in CASO_COMPLETO]


class TestODominioDeRetrievalEhPuro:
    """§86, §87 — nenhuma infraestrutura, nenhuma camada de cima."""

    def test_nao_importa_biblioteca_de_io_nem_de_indice(self) -> None:
        violacoes = external_violations(files_in(RETRIEVAL), BIBLIOTECAS_PROIBIDAS)
        assert not violacoes, (
            "o domínio de recuperação é `float` e `heapq` do interpretador: uma "
            f"dependência de índice ou de I/O aqui muda o que ele é — {violacoes}"
        )

    def test_nao_importa_camada_de_cima(self) -> None:
        assert not internal_violations(files_in(RETRIEVAL), FONTES_PROIBIDAS)

    def test_nao_antecipa_o_indice_aproximado(self) -> None:
        assert not internal_violations(_alvos(), PACOTES_DE_INDICE)


class TestNaoEhBuscaAproximada:
    """§3, §37, §137 — este PR é o ORÁCULO, e nada além."""

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
            "probe",
        )
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_sem_poda_por_distancia_nem_parada_antecipada(self) -> None:
        """§37 — nenhum `break` que possa mudar o top-K.

        O QUE ELE PROCURA É A FORMA, e não a intenção: um `break` dentro da
        varredura de candidatos é como uma parada antecipada entra. O laço do
        oráculo usa `continue` para pular inelegíveis — que é o oposto: ele
        segue varrendo.
        """
        corpo = code_only(FONTE / "domain/retrieval/exact.py")
        laco = corpo[corpo.index("for candidato in candidates") :]
        corpo_do_laco = laco[: laco.index("descritor =")]
        assert "break" not in corpo_do_laco, (
            "há um `break` na varredura de candidatos: uma parada antecipada faria "
            "o top-K depender de onde a varredura parou, e o resultado continuaria "
            "parecendo exato"
        )

    def test_o_resultado_declara_exaustividade(self) -> None:
        from sports_intelligence.domain.retrieval.result import ExactRetrievalResult

        assert "exhaustive" in ExactRetrievalResult.__dataclass_fields__


class TestNaoEhInteligencia:
    """§2, §35, §88 — sem rótulo, sem resultado, sem tendência."""

    def test_sem_rotulo_nem_desfecho(self) -> None:
        proibidos = (
            "final_score",
            "match_result",
            "matchresult",
            "next_goal",
            "winner",
            "outcome",
            "label",
            "probability",
            "confidence",
            "trend",
            "prediction",
            "effective_sample",
        )
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_o_dominio_nao_importa_resultado_de_partida(self) -> None:
        """§88 — a guarda é sobre o IMPORT, e não sobre o nome."""
        proibidos = (
            "sports_intelligence.domain.matches.result",
            "sports_intelligence.domain.events",
            "sports_intelligence.domain.quality",
        )
        assert not internal_violations(files_in(RETRIEVAL), proibidos)

    def test_o_vizinho_nao_tem_campo_de_futuro(self) -> None:
        from sports_intelligence.domain.retrieval.neighbor import HistoricalNeighbor

        campos = set(HistoricalNeighbor.__dataclass_fields__)
        assert not campos & {
            "result",
            "final_score",
            "winner",
            "next_goal",
            "outcome",
            "weight",
            "confidence",
        }


class TestNaoAmostra:
    """§15, §137 — exato significa TODO candidato elegível."""

    def test_sem_amostragem_no_universo(self) -> None:
        proibidos = (
            "random",
            "sample(",
            "reservoir",
            "seed",
            "shuffle",
            "limit ",
            "head(",
        )
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_o_catalogo_de_amostragem_tem_um_membro(self) -> None:
        from sports_intelligence.domain.retrieval.candidate_policy import (
            CandidateSampling,
        )

        assert {s.value for s in CandidateSampling} == {"NONE"}

    def test_a_politica_nao_tem_teto_de_candidatos(self) -> None:
        from sports_intelligence.domain.retrieval.candidate_policy import (
            DEFAULT_CANDIDATE_POLICY,
        )

        assert DEFAULT_CANDIDATE_POLICY.candidate_cap is None


class TestNaoImputaNemPondera:
    """§57, §58, §115, §116, §117 — pesos iguais, caso completo, e nada mais."""

    def test_sem_peso_por_eixo(self) -> None:
        proibidos = ("alpha", "beta", "gamma", "lambda_", "weights", "weighted")
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_sem_imputacao(self) -> None:
        """Nenhum preenchimento, em lugar nenhum do pacote.

        `penalty` NÃO ESTÁ NESTA LISTA DESDE O PR-06.2, e a distinção é o PR
        inteiro: penalizar a ausência é o OPOSTO de imputá-la. A guarda que
        mantém o oráculo do PR-06.1 livre de penalidade é
        `test_o_oraculo_nao_conhece_penalidade_nem_piso`.
        """
        proibidos = (
            "fillna",
            "nan_to_num",
            "impute",
            "or 0.0",
            "or 0)",
            "mean_fill",
            "zero_fill",
        )
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_o_oraculo_nao_conhece_penalidade_nem_piso(self) -> None:
        """§53, §117 — no CASO COMPLETO, completo é elegível e incompleto não é.

        A GUARDA FICOU MAIS ESTREITA NO PR-06.2 E MAIS FORTE. Antes ela dizia
        «o pacote não tem cobertura»; agora diz «o oráculo não tem» — e é essa
        a afirmação que precisa continuar valendo, porque é ela que faz do
        PR-06.1 uma régua estável contra a qual o PR-06.2 se mede.
        """
        proibidos = (
            "coverage_threshold",
            "min_coverage",
            "shared_axes",
            "coverage =",
            "penalty",
            "shared_mask",
            "availability_mask",
        )
        for arquivo in _alvos_do_caso_completo():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_o_catalogo_de_peso_tem_um_membro(self) -> None:
        """A ponderação continua fechada em `EQUAL` — ela é do PR-06.5."""
        from sports_intelligence.domain.retrieval.profile import (
            MissingPolicy,
            WeightPolicy,
        )

        assert {w.value for w in WeightPolicy} == {"EQUAL"}
        # A AUSÊNCIA GANHOU UM MEMBRO E CONTINUA FECHADA. O que importa é o
        # que NÃO entrou: nenhuma forma de imputação tem nome no catálogo.
        assert {m.value for m in MissingPolicy} == {"COMPLETE_CASE", "AVAILABILITY_AWARE"}
        assert not {m.value for m in MissingPolicy} & {
            "ZERO_FILL",
            "MEAN_FILL",
            "SHARED_DIMENSIONS",
            "IMPUTE",
        }


class TestNaoHaTrajetoria:
    """§20, §120 — a query é UM snapshot."""

    def test_sem_janela_nem_alinhamento_temporal_flexivel(self) -> None:
        proibidos = ("trajectory", "dtw", "time_window", "tolerance", "t_minus")
        for arquivo in _alvos():
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_o_catalogo_de_alinhamento_tem_um_membro(self) -> None:
        from sports_intelligence.domain.retrieval.timepoint import TimeAlignmentPolicy

        assert {a.value for a in TimeAlignmentPolicy} == {"EXACT_MATCH_TIME_POINT_V1"}


class TestNaoVoltaAoCorpus:
    """§5, §6, §132 — a autoridade é o dataset normalizado, e só ele."""

    def test_o_caso_de_uso_nao_conhece_fato_canonico(self) -> None:
        modulos = {i.module for i in imports_of(FONTE / "application/use_cases/retrieval.py")}
        proibidos = {
            m
            for m in modulos
            if m.startswith(
                (
                    "sports_intelligence.ports.repositories.matches",
                    "sports_intelligence.ports.repositories.events",
                    "sports_intelligence.ports.repositories.feature_state",
                    "sports_intelligence.ports.repositories.feature_context",
                    "sports_intelligence.ports.repositories.corpus",
                )
            )
        }
        assert not proibidos, (
            f"a recuperação importa repositório de fato canônico: {proibidos}. Ela "
            "lê o Parquet normalizado, e nada mais"
        )

    def test_o_leitor_so_conhece_o_prefixo_normalizado(self) -> None:
        corpo = code_only(FONTE / "historical/retrieval/reader.py")
        assert '"normalized/' in corpo
        for proibido in ("features/", "corpus/", "canonical"):
            assert proibido not in corpo, proibido

    def test_o_caso_de_uso_nao_conhece_adaptador_nem_driver(self) -> None:
        modulos = {i.module for i in imports_of(FONTE / "application/use_cases/retrieval.py")}
        assert not {
            m
            for m in modulos
            if m.startswith(("pyarrow", "asyncpg", "sports_intelligence.adapters"))
        }

    def test_so_o_leitor_importa_pyarrow(self) -> None:
        for arquivo in (
            FONTE / "application/use_cases/retrieval.py",
            FONTE / "ports/object_store/retrieval.py",
            *files_in(RETRIEVAL),
        ):
            modulos = {i.module for i in imports_of(arquivo)}
            assert not {m for m in modulos if m.startswith("pyarrow")}, arquivo.name


class TestNaoHaPersistenciaNova:
    """§79, §143 — recuperação é computação, e não estado."""

    def test_nenhuma_migration_nova(self) -> None:
        nomes = sorted(m.name for m in (RAIZ / "migrations").glob("*.sql"))
        assert nomes[-1] == "0013_normalized_feature_dataset.sql", (
            "há uma migration depois da 0013: o PR-06.1 não persiste resultado de "
            "query, e uma tabela nova precisa de justificativa arquitetural"
        )

    def test_o_caso_de_uso_nao_escreve(self) -> None:
        corpo = code_only(FONTE / "application/use_cases/retrieval.py").lower()
        for termo in ("insert into", "update ", "delete from", "save(", "record("):
            assert termo not in corpo, termo


class TestOsContratosDoPR05ContinuamIntocados:
    """§138, §139 — nada do PR-05 foi mexido para facilitar recuperação."""

    def test_o_plano_de_normalizacao_nao_mudou(self) -> None:
        from sports_intelligence.domain.features.normalized.plan import (
            normalization_plan_v1,
        )

        plano = normalization_plan_v1()
        assert plano.size == 105
        assert len(plano.robust_keys) == 29
        assert (
            plano.fingerprint == "26b80aa1c7a3143a6634844351a929976ccac73333b2b383339b7ba01b8d73b4"
        )

    def test_o_dataset_normalizado_nao_ganhou_coluna(self) -> None:
        from sports_intelligence.historical.normalized.materializer import (
            COLUNAS_ESPERADAS_NOTA,
        )

        assert COLUNAS_ESPERADAS_NOTA == 15 + 3 * 105

    def test_a_ausencia_continua_sem_epsilon(self) -> None:
        corpo = code_only(FONTE / "domain/features/normalized/transform.py")
        for termo in ("epsilon", "1e-6", "max(iqr"):
            assert termo not in corpo, termo
