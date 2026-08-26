"""As fronteiras do PR-05.5.1 — a grade, a divisão e a materialização.

O QUE ESTE ARQUIVO PROTEGE (§146 ao §149):

    o domínio do dataset   puro: sem pyarrow, sem banco, sem object store
    a grade                não fabrica instante de parede a partir do minuto
    a divisão              não sorteia, não tem semente, não tem proporção
    o dataset              NÃO normaliza: sem `fit`, sem escala, sem z-score
    o dataset              NÃO vetoriza: sem similaridade, sem pgvector
    o materializador       é a ÚNICA fronteira que conhece pyarrow
    o port                 não vaza tipo de banco nem de object store

O PERIGO NOVO DESTA FASE É A NORMALIZAÇÃO. Com a população finalmente
materializada, ajustar a escala «já que estamos aqui» é a coisa mais natural do
mundo — e faria a escala ser ajustada dentro da mesma execução que produz o
conjunto, sem que ninguém tivesse decidido sobre qual metade. É a fronteira que
este arquivo mais protege.

O SEGUNDO PERIGO É O INSTANTE FABRICADO. `kickoff + minuto` parece o carimbo de
parede daquele minuto do jogo e erra por dez a vinte minutos exatamente nos
jogos mais irregulares. Um corte de conhecimento fabricado é pior que corte
nenhum, porque ele parece prova.
"""

from __future__ import annotations

import pytest

from tests.support.ast_checks import (
    FONTE,
    INFRA_EXTERNA,
    code_only,
    external_violations,
    files_in,
    imports_of,
    internal_violations,
)

pytestmark = pytest.mark.architecture

DATASET = "domain/features/dataset"

#: Por onde o dado bruto — ou a infraestrutura — voltaria ao domínio.
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

#: Os pacotes que só existem em PRs futuros. Importá-los aqui seria antecipar
#: uma decisão que ainda não foi tomada.
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
    }
)


def texto(pacote: str) -> list[tuple[str, str]]:
    """O CÓDIGO de cada arquivo — sem docstring nem comentário.

    A base explica por extenso o que NÃO faz: as docstrings citam `fit`,
    `z-score` e `kickoff + minuto` pelo nome para registrar a decisão de não
    tê-los. Varrer o arquivo cru marcaria a explicação como violação.
    """
    return [(arquivo.name, code_only(arquivo)) for arquivo in files_in(pacote)]


def proibir(pacote: str, termos: tuple[str, ...]) -> list[str]:
    return [
        f"{nome}: {termo}"
        for nome, conteudo in texto(pacote)
        for termo in termos
        if termo in conteudo
    ]


class TestODominioDoDataset:
    def test_o_pacote_existe_e_foi_varrido(self) -> None:
        assert len(files_in(DATASET)) >= 5

    def test_nao_importa_infraestrutura(self) -> None:
        assert not external_violations(files_in(DATASET), INFRA_EXTERNA)

    def test_nao_importa_pyarrow(self) -> None:
        """O formato é decisão do adaptador. Um domínio que conhecesse Parquet
        teria a forma dele ditada pelo que o formato aceita."""
        assert not external_violations(files_in(DATASET), BIBLIOTECAS_PROIBIDAS)

    def test_nao_importa_adaptador_aplicacao_nem_bruto(self) -> None:
        violacoes = internal_violations(files_in(DATASET), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_importa_pacote_de_pr_futuro(self) -> None:
        violacoes = internal_violations(files_in(DATASET), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_io_nem_relogio_no_dominio(self) -> None:
        assert not proibir(DATASET, ("open(", "datetime.now", "time.time", "utcnow", "random."))


class TestAGradeNaoFabricaInstante:
    def test_nao_soma_minuto_a_apito(self) -> None:
        """`kickoff + minuto` pareceria prova e erraria por dez a vinte
        minutos nos jogos mais irregulares."""
        assert not proibir(
            DATASET,
            (
                "kickoff + ",
                "kickoff +timedelta",
                "kickoff+timedelta",
                "timedelta(minutes=minute",
                "timedelta(minutes=minuto",
            ),
        )

    def test_nao_estima_duracao_de_acrescimo(self) -> None:
        assert not proibir(
            DATASET,
            ("stoppage_seconds", "estimated_duration", "assumed_stoppage", "avg_stoppage"),
        )

    def test_nao_ha_relogio_continuo_de_partida(self) -> None:
        """Achatar o jogo numa linha contínua exigiria saber quanto durou o
        intervalo, e o corpus não sabe."""
        assert not proibir(
            DATASET, ("absolute_minute", "continuous_clock", "total_elapsed", "match_minute(")
        )


class TestADivisaoNaoSorteia:
    def test_nao_ha_aleatoriedade(self) -> None:
        """Sortear linhas põe o minuto 62 e o 63 do MESMO jogo em metades
        diferentes — vazamento perfeito e invisível."""
        assert not proibir(
            DATASET,
            ("random", "shuffle", "seed", "sample(", "choice(", "train_test_split"),
        )

    def test_nao_ha_proporcao_de_divisao(self) -> None:
        """Um percentual faz a fronteira mudar quando o corpus cresce."""
        assert not proibir(
            DATASET, ("test_size", "train_ratio", "split_ratio", "percentile_split", "0.8")
        )

    def test_nao_existem_metades_de_treino(self) -> None:
        """`train` traria a expectativa de gradiente, época e validação."""
        assert not proibir(DATASET, ("TRAIN", "TEST =", "VALIDATION ="))


class TestONaoNormalizaENaoVetoriza:
    def test_nao_ajusta_escala(self) -> None:
        """A população é justamente o que este PR produz — ajustar aqui seria
        ajustar sobre um conjunto que ainda não existe."""
        assert not proibir(
            DATASET,
            ("def fit", "normalizerfit", "median_iqr", "robustscale", "z_score", "zscore"),
        )

    def test_nao_importa_o_pacote_de_ajuste(self) -> None:
        violacoes = internal_violations(
            files_in(DATASET), ("sports_intelligence.domain.features.fitting",)
        )
        assert not violacoes, str(violacoes)

    def test_nao_ha_vetor_nem_similaridade(self) -> None:
        assert not proibir(
            DATASET,
            ("cosine", "euclidean", "def similarity", "embedding", "nearest", "knn"),
        )

    def test_a_aplicacao_tambem_nao_normaliza(self) -> None:
        """A fronteira vale para o caso de uso tanto quanto para o domínio."""
        caso = code_only(FONTE / "application" / "use_cases" / "feature_dataset.py")
        for termo in ("RobustNormalizerFitter", "NormalizerFitArtifact", "normalized"):
            assert termo not in caso, termo


class TestOMaterializadorEAUnicaFronteiraComPyarrow:
    def test_ele_existe(self) -> None:
        assert (FONTE / "historical" / "features" / "materializer.py").exists()

    def test_o_schema_e_derivado_do_catalogo_e_nunca_inferido(self) -> None:
        conteudo = code_only(FONTE / "historical" / "features" / "materializer.py")
        assert "def feature_schema" in conteudo
        assert "schema=self.schema()" in conteudo
        assert "infer" not in conteudo.lower()

    def test_ele_nao_conhece_o_banco(self) -> None:
        arquivos = files_in("historical/features")
        violacoes = internal_violations(arquivos, ("sports_intelligence.adapters.postgres",))
        assert not violacoes, str(violacoes)

    def test_o_port_nao_vaza_pyarrow_nem_banco(self) -> None:
        port = FONTE / "ports" / "object_store" / "feature_dataset.py"
        modulos = {imp.module for imp in imports_of(port)}
        assert not {
            m
            for m in modulos
            if m.startswith(("pyarrow", "asyncpg", "sports_intelligence.adapters"))
        }

    def test_o_repositorio_nao_guarda_valor_de_feature(self) -> None:
        """O banco guarda ponteiros; o conteúdo mora no Parquet (ADR-0037)."""
        adaptador = code_only(FONTE / "adapters" / "postgres" / "feature_dataset.py")
        for termo in ("feature_value", "f_shots", "INSERT INTO historical_feature_rows"):
            assert termo not in adaptador, termo

    def test_a_migration_nova_existe_e_a_anterior_nao_foi_tocada(self) -> None:
        """A 0012 existe e nada foi acrescentado ENTRE ela e a 0011.

        A VERSÃO ANTERIOR DESTE TESTE EXIGIA QUE A 0012 FOSSE A ÚLTIMA, e isso
        confundia duas coisas: «ninguém editou o passado» — que é a invariante
        de verdade, porque o aplicador guarda o SHA-256 de cada arquivo — com
        «ninguém escreveu o futuro», que é falso por construção: o PR seguinte
        acrescenta a 0013, e o teste passaria a reprovar todo trabalho posterior.
        """
        from tests.support.ast_checks import RAIZ

        nomes = sorted(m.name for m in (RAIZ / "migrations").glob("*.sql"))
        assert "0012_historical_feature_dataset.sql" in nomes
        posicao = nomes.index("0012_historical_feature_dataset.sql")
        assert nomes[posicao - 1].startswith("0011_"), (
            "uma migration foi inserida ENTRE a 0011 e a 0012: o aplicador guarda o "
            "hash de cada arquivo aplicado, e reordenar o passado o faz recusar seguir"
        )

    def test_a_migration_cria_as_quatro_tabelas_declaradas(self) -> None:
        from tests.support.ast_checks import RAIZ

        sql = (RAIZ / "migrations" / "0012_historical_feature_dataset.sql").read_text(
            encoding="utf-8"
        )
        for tabela in (
            "historical_feature_datasets",
            "historical_feature_dataset_versions",
            "historical_feature_dataset_build_runs",
            "historical_feature_objects",
        ):
            assert f"CREATE TABLE {tabela}" in sql, tabela


class TestOEspacoDaV2ContinuaIntocado:
    def test_o_pr_nao_altera_o_catalogo(self) -> None:
        """Materializar não é motivo para mudar o que se mede."""
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            V1_SIZE,
            extended_feature_catalog,
        )

        catalogo = extended_feature_catalog()
        assert catalogo.size == 105
        assert catalogo.inherited == V1_SIZE == 75
