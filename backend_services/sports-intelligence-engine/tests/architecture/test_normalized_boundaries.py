"""As fronteiras do PR-05.5.2 — o plano, o ajuste e a representação normalizada.

O QUE ESTE ARQUIVO PROTEGE:

    o domínio normalizado   puro: sem pyarrow, sem banco, sem object store
    o plano                 é EXPLÍCITO: nenhuma decisão sai do dtype
    a transformação         só PASS_THROUGH e MEDIAN_IQR — sem z-score, sem
                            min-max, sem log, sem winsorização, sem clipping
    o artefato degenerado   NÃO cai para pass-through, e não ganha epsilon
    a ausência              NÃO vira zero
    a identidade do ajuste  NÃO enxerga a impressão crua global
    o PR                    NÃO vetoriza: sem similaridade, sem pgvector, sem
                            KNN, sem embedding
    o materializador        é a ÚNICA fronteira nova que conhece pyarrow

O PERIGO CENTRAL DESTA FASE É O FALLBACK. Um eixo classificado `ROBUST` cuja
competição não tem dispersão produz uma célula vazia, e a tentação de «pelo
menos devolver o valor cru» é enorme — ela faz o dataset parecer mais completo e
mistura unidades na mesma coluna, de forma que nenhuma leitura denuncia.

O SEGUNDO PERIGO É O EPSILON. `max(iqr, 1e-6)` faz o código parar de produzir
ausências e inventa uma escala: uma distribuição sem dispersão passa a produzir
valores normalizados enormes, e eles parecem sinal.

O TERCEIRO É A IMPRESSÃO ERRADA NA IDENTIDADE. Se `raw_content_fingerprint` — que
cobre as duas metades — entrasse na identidade do conjunto de artefatos,
acrescentar uma partida à AVALIAÇÃO mudaria o ajuste sem que número nenhum
mudasse, e o PR inteiro deixaria de valer.
"""

from __future__ import annotations

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


def _sql_sem_comentarios(nome: str) -> str:
    """O SQL sem as linhas de `--`, em minúsculas.

    ELE É O `code_only` DAS MIGRATIONS, e existe pelo mesmo motivo: estes
    arquivos EXPLICAM por extenso o que não fazem — «e não `double precision`»,
    «sem epsilon» —, e uma varredura ingênua marcaria a explicação como
    violação. A saída natural seria reescrever a prosa para escapar do grep,
    deixando o arquivo pior e a guarda igualmente cega.
    """
    bruto = (RAIZ / "migrations" / nome).read_text(encoding="utf-8")
    linhas = [linha.split("--", 1)[0] for linha in bruto.splitlines()]
    return chr(10).join(linhas).lower()


NORMALIZADO = "domain/features/normalized"

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

#: Os pacotes que só existem no PR-06 e adiante. Importá-los aqui seria
#: antecipar uma decisão que ainda não foi tomada.
PACOTES_FUTUROS = (
    "sports_intelligence.engines",
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
    }
)


class TestODominioNormalizadoEhPuro:
    """§146 — nenhuma infraestrutura, nenhuma camada de cima."""

    def test_nao_importa_biblioteca_numerica_nem_de_io(self) -> None:
        violacoes = external_violations(files_in(NORMALIZADO), BIBLIOTECAS_PROIBIDAS)
        assert not violacoes, (
            "o domínio normalizado é `Decimal` e `float` do interpretador: uma "
            f"dependência numérica aqui muda a conta sem mudar o código — {violacoes}"
        )

    def test_nao_importa_camada_de_cima(self) -> None:
        assert not internal_violations(files_in(NORMALIZADO), FONTES_PROIBIDAS)

    def test_nao_antecipa_o_pr06(self) -> None:
        assert not internal_violations(files_in(NORMALIZADO), PACOTES_FUTUROS)


class TestOPlanoEhExplicito:
    """§13 — nenhuma decisão de normalização sai do tipo do dado."""

    def test_a_classificacao_nao_olha_para_dtype(self) -> None:
        """`if dtype == float: normalize()` é a forma proibida.

        ELA PARECE RAZOÁVEL e é falsa: `market_1x2_home_median` e
        `market_1x2_home_bookmakers` são os dois `float` no arquivo, e um é uma
        cotação e o outro é uma contagem de casas de apostas. Normalizar os dois
        por serem do mesmo tipo reescalaria a contagem.
        """
        plano = code_only(FONTE / "domain/features/normalized/plan.py")
        for termo in ("dtype", "np.floating", "is_numeric", "isinstance(valor, float)"):
            assert termo not in plano, termo

    def test_a_classificacao_e_por_metadado_do_catalogo(self) -> None:
        # `code_only` DEVOLVE MINÚSCULAS — ele existe para varrer construções
        # proibidas, e o casamento é sempre em caixa baixa.
        plano = code_only(FONTE / "domain/features/normalized/plan.py")
        # A CLASSIFICAÇÃO OLHA PARA O QUE A FEATURE É, e não para como ela é
        # guardada: família, tipo de contexto, tipo de mercado.
        for termo in ("rollingfamily", "contextfeaturekind", "marketfeaturekind"):
            assert termo in plano, termo

    def test_o_plano_cobre_o_espaco_inteiro(self) -> None:
        from sports_intelligence.domain.features.normalized.plan import (
            normalization_plan_v1,
        )

        plano = normalization_plan_v1()
        assert plano.size == 105
        assert len(plano.robust_keys) + len(plano.pass_through_keys) == plano.size


class TestSoDuasTransformacoes:
    """§14 — o catálogo de estratégias é FECHADO."""

    def test_o_catalogo_tem_exatamente_duas(self) -> None:
        from sports_intelligence.domain.features.normalized.plan import (
            TransformStrategy,
        )

        assert {e.name for e in TransformStrategy} == {
            "PASS_THROUGH",
            "ROBUST_MEDIAN_IQR",
        }

    def test_nao_ha_metodo_nao_declarado_no_pacote(self) -> None:
        """As formas proibidas, por nome (§15).

        ELAS NÃO ESTÃO NO CATÁLOGO e não podem aparecer no código: uma delas
        implementada «só para este eixo» produziria uma coluna cuja escala o
        manifesto descreve errado.
        """
        proibidos = (
            "z_score",
            "zscore",
            "min_max",
            "minmax",
            "winsor",
            "boxcox",
            "box_cox",
            "quantile_transform",
            "log1p",
            "np.log",
            "math.log",
            "clip(",
        )
        for arquivo in files_in(NORMALIZADO):
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"


class TestNaoHaFallbackNemEpsilon:
    """§88, ADR-0035 — a ausência de escala é uma AUSÊNCIA, e não um número."""

    def test_a_transformacao_nao_tem_epsilon(self) -> None:
        corpo = code_only(FONTE / "domain/features/normalized/transform.py")
        for termo in ("epsilon", "1e-6", "1e-9", "max(iqr", "or 1.0", "_eps"):
            assert termo not in corpo, termo

    def test_um_eixo_robusto_nunca_vira_pass_through_em_execucao(self) -> None:
        """A estratégia da célula sai do PLANO, e nunca do estado do artefato.

        A FORMA PROIBIDA É `if artefato.status is not FITTED: strategy =
        PASS_THROUGH`. Ela faria a mesma coluna ter unidades diferentes em
        competições diferentes — gols normalizados numa, gols crus na outra.
        """
        corpo = code_only(FONTE / "domain/features/normalized/transform.py")
        atribuicoes = [
            linha
            for linha in corpo.splitlines()
            if "transformstrategy.pass_through" in linha and "=" in linha
        ]
        assert not atribuicoes, (
            "a estratégia está sendo ATRIBUÍDA em execução: ela é do plano, e "
            f"trocá-la aqui mistura unidades na mesma coluna — {atribuicoes}"
        )

    def test_a_ausencia_nunca_vira_zero(self) -> None:
        for arquivo in files_in(NORMALIZADO):
            corpo = code_only(arquivo)
            for termo in ("or 0.0", "or 0)", "fillna", "nan_to_num", ", 0.0)"):
                assert termo not in corpo, f"{arquivo.name}: {termo}"


class TestAIdentidadeDoAjusteNaoEnxergaAAvaliacao:
    """§4, §46 — a invariante central, protegida no código e não só em teste."""

    def test_a_forma_canonica_do_conjunto_nao_cita_a_impressao_crua(self) -> None:
        from sports_intelligence.domain.features.normalized.artifacts import (
            NormalizerArtifactSet,
        )

        campos = set(
            NormalizerArtifactSet.as_canonical.__doc__ or ""
        )  # só para garantir que a docstring existe
        assert campos
        corpo = code_only(FONTE / "domain/features/normalized/artifacts.py")
        canonica = corpo.split("def as_canonical")[-1].split("def ")[0]
        for proibido in (
            "source_raw_content_fingerprint",
            "source_version_id",
            "created_at",
            "self.id",
        ):
            assert proibido not in canonica, (
                f"{proibido} entrou na identidade semântica do conjunto: ele muda sem "
                "o ajuste mudar, e dois deles carregam a avaliação dentro"
            )

    def test_a_linhagem_existe_e_e_separada(self) -> None:
        from sports_intelligence.domain.features.normalized.artifacts import (
            NormalizerArtifactSet,
        )

        assert hasattr(NormalizerArtifactSet, "lineage")

    def test_o_ajuste_le_somente_a_referencia(self) -> None:
        corpo = code_only(FONTE / "domain/features/normalized/fit.py")
        assert "datasetsplit.reference" in corpo
        # A RECUSA É EXPLÍCITA, e não um filtro: ignorar em silêncio faria um
        # leitor mal configurado produzir um ajuste plausível sobre a população
        # errada.
        assert "is not datasetsplit.reference" in corpo


class TestNaoVetorizaNemBusca:
    """O PR-06 não começou. Nenhum vestígio dele aqui."""

    def test_sem_similaridade_sem_vetor_sem_indice(self) -> None:
        proibidos = (
            "cosine",
            "euclidean",
            "knn",
            "hnsw",
            "ivfflat",
            "pgvector",
            "embedding",
            "nearest_neighbor",
            "similarity",
        )
        alvos = [
            *files_in(NORMALIZADO),
            FONTE / "application/use_cases/normalized_dataset.py",
            FONTE / "historical/normalized/materializer.py",
            FONTE / "historical/normalized/reader.py",
        ]
        for arquivo in alvos:
            corpo = code_only(arquivo).lower()
            for termo in proibidos:
                assert termo not in corpo, f"{arquivo.name}: {termo}"

    def test_nao_ha_treino_de_modelo(self) -> None:
        for arquivo in files_in(NORMALIZADO):
            corpo = code_only(arquivo).lower()
            for termo in ("model.fit", "train(", "gradient", "loss", "epoch"):
                assert termo not in corpo, f"{arquivo.name}: {termo}"


class TestOMaterializadorEAUnicaFronteiraNovaComPyarrow:
    """§147 — pyarrow mora no adaptador, e em nenhum lugar acima."""

    def test_so_o_leitor_e_o_materializador_importam_pyarrow(self) -> None:
        for arquivo in (
            FONTE / "application/use_cases/normalized_dataset.py",
            *files_in(NORMALIZADO),
        ):
            modulos = {i.module for i in imports_of(arquivo)}
            assert not {m for m in modulos if m.startswith("pyarrow")}, arquivo.name

    def test_o_caso_de_uso_nao_conhece_adaptador_nem_driver(self) -> None:
        modulos = {
            i.module for i in imports_of(FONTE / "application/use_cases/normalized_dataset.py")
        }
        assert not {
            m
            for m in modulos
            if m.startswith(("pyarrow", "asyncpg", "sports_intelligence.adapters"))
        }

    def test_o_adaptador_nao_guarda_linha_normalizada(self) -> None:
        """O banco guarda ponteiros e a ESCALA; as linhas moram no Parquet."""
        adaptador = code_only(FONTE / "adapters/postgres/normalized_dataset.py")
        for termo in (
            "n_shots",
            "insert into normalized_feature_rows",
            "normalizedcell",
        ):
            assert termo not in adaptador, termo


class TestAEscalaEhDecimalNoBanco:
    """A mediana e o IQR não passam por ponto flutuante na persistência."""

    def test_a_migration_declara_numeric(self) -> None:
        # OS COMENTÁRIOS SÃO REMOVIDOS antes da varredura, pelo mesmo motivo de
        # `code_only`: esta migration EXPLICA por extenso por que não usa
        # `double precision`, e uma busca ingênua marcaria a explicação como
        # violação.
        sql = _sql_sem_comentarios("0013_normalized_feature_dataset.sql")
        for coluna in ("median", "q1", "q3", "iqr"):
            assert f"{coluna} numeric" in " ".join(sql.split()), coluna
        assert "double precision" not in sql, (
            "uma coluna de escala em `double precision` faria a normalização de uma "
            "competição depender do arredondamento do driver"
        )

    def test_o_adaptador_recusa_float_vindo_do_banco(self) -> None:
        adaptador = code_only(FONTE / "adapters/postgres/normalizer_artifacts.py")
        assert "isinstance(valor, decimal)" in adaptador


class TestAMigrationNovaNaoTocaAsAnteriores:
    def test_a_0013_existe_e_vem_depois_da_0012(self) -> None:
        nomes = sorted(m.name for m in (RAIZ / "migrations").glob("*.sql"))
        assert "0013_normalized_feature_dataset.sql" in nomes
        posicao = nomes.index("0013_normalized_feature_dataset.sql")
        assert nomes[posicao - 1] == "0012_historical_feature_dataset.sql"

    def test_ela_cria_as_tabelas_declaradas(self) -> None:
        sql = _sql_sem_comentarios("0013_normalized_feature_dataset.sql")
        for tabela in (
            "normalizer_artifact_sets",
            "normalizer_artifact_bundles",
            "normalizer_fit_artifacts",
            "normalized_feature_datasets",
            "normalized_feature_dataset_versions",
            "normalized_feature_dataset_manifests",
            "normalized_feature_dataset_build_runs",
            "normalized_feature_objects",
        ):
            assert f"create table {tabela}" in sql, tabela

    def test_ela_nao_altera_tabela_do_dataset_cru(self) -> None:
        sql = _sql_sem_comentarios("0013_normalized_feature_dataset.sql")
        for proibido in (
            "alter table historical_feature_dataset_versions",
            "drop table",
            "alter table historical_feature_objects",
        ):
            assert proibido not in sql, proibido


class TestOsTiposDoDatasetCruContinuamIntocados:
    """`FeatureValue` continua `float`. Este PR não redesenhou o de baixo."""

    def test_feature_value_continua_float(self) -> None:
        corpo = code_only(FONTE / "domain/features/values.py")
        assert "def numeric(self) -> float | none" in corpo
        # `decimal_text` CONTINUA IMPORTADO — ele formata o texto canônico e
        # não muda o tipo do valor. O que este teste recusa é a ANOTAÇÃO: um
        # campo ou retorno `Decimal` seria o redesenho que este PR declarou não
        # fazer, e a travessia acontece no ajuste (bridge.py), uma vez só.
        for proibido in (": decimal", "-> decimal", "decimal | none"):
            assert proibido not in corpo, proibido

    def test_o_dataset_cru_nao_ganhou_coluna_normalizada(self) -> None:
        corpo = code_only(FONTE / "historical/features/materializer.py")
        for termo in ("normalized_prefix", "normalizedfeaturerow", '"n_"'):
            assert termo not in corpo, termo
