"""A fronteira do EXTRATOR — o gate do §185.

O PERIGO ESPECÍFICO DESTA FASE. O PR-05.3 é o primeiro que produz números que
parecem prontos para usar. `shots_home_5m = 4` é um número; dividi-lo por
`shots_away_5m` daria uma «dominância»; padronizá-lo contra a competição daria
um z-score; a distância entre dois vetores desses daria uma «similaridade».
Cada um desses passos é uma decisão de modelagem com população, versão e
normalizador declarados — e nenhum deles foi tomado.

A tentação não é escrever isso de propósito: é escrever `mean()` numa função
auxiliar porque «já que os números estão aqui». Este arquivo torna esse
acidente uma falha de CI.

O QUE ELE PROTEGE:

    extração é DOMÍNIO PURO      nada de asyncpg, PyArrow, MinIO, FastAPI
    extração lê ESTADO + FATOS   nunca bruto, resolução, fusão ou `MatchResult`
    nada de NORMALIZAÇÃO         o contrato existe desde o PR-05.1 e continua
                                 sem execução
    nada de VETOR                nem NumPy, nem lista posicional para distância
    nada de SIMILARIDADE         cosseno, euclidiana, KNN, HNSW: é PR-06
    nada de ML                   pesos aprendidos, treino, predição
    nada de PERSISTÊNCIA         snapshot não tem tabela nem Parquet
"""

from __future__ import annotations

import pytest

from tests.support.ast_checks import (
    FONTE,
    INFRA_EXTERNA,
    external_violations,
    files_in,
    imports_of,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: O pacote da extração. Subpacote de `domain/features`, então já herda as
#: proibições do PR-05.1 e do PR-05.2 — o que este arquivo acrescenta é o que
#: só faz sentido depois que existem features de verdade.
EXTRACAO = "domain/features/extraction"

#: Por onde o dado bruto voltaria a entrar no cálculo (§4, §185).
FONTES_PROIBIDAS = (
    "sports_intelligence.ingestion",
    "sports_intelligence.adapters",
    "sports_intelligence.application",
    "sports_intelligence.domain.sources",
    "sports_intelligence.domain.resolution",
    "sports_intelligence.domain.fusion",
    "sports_intelligence.archival",
    "apps.",
)

#: O futuro que este PR não antecipa (§2, §185, §187).
PACOTES_FUTUROS = (
    "sports_intelligence.engines",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


def texto_da_extracao() -> list[tuple[str, str]]:
    return [
        (arquivo.name, arquivo.read_text(encoding="utf-8").lower())
        for arquivo in files_in(EXTRACAO)
    ]


def proibir(termos: tuple[str, ...]) -> list[str]:
    return [
        f"{nome}: {termo}"
        for nome, texto in texto_da_extracao()
        for termo in termos
        if termo in texto
    ]


class TestAExtracaoEDominioPuro:
    def test_o_pacote_existe_e_foi_varrido(self) -> None:
        """Uma varredura de zero arquivo passa sempre — e não prova nada."""
        assert len(files_in(EXTRACAO)) >= 4

    def test_nao_importa_infraestrutura(self) -> None:
        violacoes = external_violations(files_in(EXTRACAO), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    def test_nao_importa_adaptador_aplicacao_nem_bruto(self) -> None:
        violacoes = internal_violations(files_in(EXTRACAO), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_io_nem_relogio_nem_sorteio(self) -> None:
        """Um extrator que consultasse o relógio deixaria de ser função dos
        seus insumos, e duas extrações do mesmo corte dariam impressões
        diferentes pelo segundo em que rodaram."""
        assert not proibir(("open(", "datetime.now", "time.time", "utcnow", "random."))


class TestAAutoridadeDaEntrada:
    """§4 — só `HistoricalMatchState` e a projeção efetiva alimentam feature."""

    def test_a_extracao_nao_importa_o_resultado_da_partida(self) -> None:
        """§185 — `MatchResult` não é insumo de feature em fase nenhuma.

        O estado já o usou para conferência pós-jogo, e o registrou como
        problema tipado quando divergiu. A feature nunca o vê.
        """
        violacoes = internal_violations(
            files_in(EXTRACAO), ("sports_intelligence.domain.matches.result",)
        )
        assert not violacoes, str(violacoes)

    def test_a_extracao_nao_importa_odds(self) -> None:
        """§98, §99 — nenhuma feature de odds nesta fase."""
        violacoes = internal_violations(
            files_in(EXTRACAO), ("sports_intelligence.domain.odds",)
        )
        assert not violacoes, str(violacoes)

    def test_o_extrator_recebe_contexto_e_nada_mais(self) -> None:
        """§88 — a assinatura é o contrato inteiro."""
        import inspect

        from sports_intelligence.domain.features.extraction.extractor import (
            MatchStateFeatureExtractor,
        )

        assinatura = inspect.signature(MatchStateFeatureExtractor.extract)
        assert set(assinatura.parameters) == {"self", "context"}

    def test_o_extrator_nao_reconstroi_estado(self) -> None:
        """§90 — ele RECEBE o estado; chamar o construtor dobraria o custo e
        abriria a porta para dois estados no mesmo snapshot."""
        extrator = FONTE / "domain" / "features" / "extraction" / "extractor.py"
        texto = extrator.read_text(encoding="utf-8")
        assert "HistoricalMatchStateBuilder" not in texto

    def test_o_extrator_nao_reprojeta_eventos(self) -> None:
        """§5, §91 — uma projeção só, e ela chega pronta."""
        extrator = FONTE / "domain" / "features" / "extraction" / "extractor.py"
        modulos = {imp.module for imp in imports_of(extrator)}
        assert "sports_intelligence.domain.features.projection" not in modulos


class TestNadaDeNormalizacao:
    """§100 ao §105, §189, §190."""

    def test_nao_ha_normalizacao_executada(self) -> None:
        assert not proibir(
            ("def normalize", "z_score", "zscore", "standard_scaler", "def fit(")
        )

    def test_nao_ha_estatistica_de_populacao(self) -> None:
        """Média, mediana e IQR sobre população são o ajuste do normalizador."""
        assert not proibir(("statistics.mean", "statistics.median", "def iqr", "percentile"))

    def test_nao_ha_clipping_nem_transformacao(self) -> None:
        """§103, §104 — nada de clipar extremo nem de log."""
        assert not proibir(("def clip", "np.clip", "math.log", "log1p"))

    def test_nao_ha_imputacao(self) -> None:
        """§102 — indisponível continua indisponível."""
        assert not proibir(("fillna", "def impute", "forward_fill", "or 0.0", "or 0)"))

    def test_a_extracao_nao_importa_o_modulo_de_normalizacao(self) -> None:
        """O contrato pode ser REFERENCIADO em texto; importar seria executar."""
        violacoes = internal_violations(
            files_in(EXTRACAO), ("sports_intelligence.domain.features.normalization",)
        )
        assert not violacoes, str(violacoes)


class TestNadaDeVetorNemSimilaridade:
    """§2, §186, §187, §188."""

    def test_nao_importa_numpy_nem_dataframe(self) -> None:
        assert not proibir(
            ("import numpy", "from numpy", "import polars", "import pandas")
        )

    def test_nao_ha_similaridade_nem_distancia(self) -> None:
        assert not proibir(
            ("cosine", "euclidean", "knn", "hnsw", "nearest_neighbor", "def distance")
        )

    def test_nao_antecipa_pgvector_clickhouse_nem_cache(self) -> None:
        violacoes = internal_violations(files_in(EXTRACAO), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_vetor_posicional(self) -> None:
        """§187, §188 — a ordem do espaço basta; o vetor vem depois."""
        assert not proibir(("def to_vector", "def as_vector", "matchstatevector"))


class TestNadaDeComposicaoNemML:
    """§2, §57, §58 — o evento existir não autoriza a métrica."""

    def test_nao_ha_pressao_momentum_nem_field_tilt(self) -> None:
        assert not proibir(
            (
                "def pressure",
                "def momentum",
                "def field_tilt",
                "def acceleration",
                "def derivative",
            )
        )

    def test_nao_ha_forca_de_time_nem_influencia_de_jogador(self) -> None:
        assert not proibir(
            ("def elo", "def team_strength", "def player_influence", "def tactical_graph")
        )

    def test_nao_ha_peso_aprendido_nem_predicao(self) -> None:
        assert not proibir(("def train", "def predict", "learned_weight", "def loss"))

    def test_nao_ha_recovery_rate(self) -> None:
        """§58 — ainda fora."""
        assert not proibir(("recovery_rate", "def recovery"))


class TestNadaDePersistencia:
    """§183, §184 — o snapshot é reconstruído, e nunca gravado."""

    def test_nao_ha_escrita_no_pacote_de_extracao(self) -> None:
        assert not proibir(("insert into", "def save", "def persist", "def store"))

    def test_este_pr_nao_traz_migracao(self) -> None:
        """§73, §147 — features são definidas em código, e não em tabela."""
        migracoes = sorted(
            p.name for p in (FONTE.parent.parent / "migrations").glob("*.sql")
        )
        assert migracoes[-1] == "0011_event_corpus_membership.sql", migracoes[-3:]

    def test_nao_ha_dataset_parquet_de_feature(self) -> None:
        """§184 — a materialização é fase posterior."""
        assert not proibir(("parquet", "to_arrow", "write_table"))


class TestASetaTemUmSentido:
    def test_o_estado_nao_importa_a_extracao(self) -> None:
        """O estado é insumo da feature, e não o contrário (§3)."""
        violacoes = internal_violations(
            files_in("domain/features/state"),
            ("sports_intelligence.domain.features.extraction",),
        )
        assert not violacoes, str(violacoes)

    def test_o_corpus_nao_importa_a_extracao(self) -> None:
        violacoes = internal_violations(
            files_in("domain/corpus", "historical/corpus", "domain/events"),
            ("sports_intelligence.domain.features",),
        )
        assert not violacoes, str(violacoes)


class TestOContratoEExecutavel:
    def test_o_catalogo_de_producao_tem_o_tamanho_declarado(self) -> None:
        from sports_intelligence.domain.features.extraction.catalog import (
            production_feature_catalog,
        )

        assert production_feature_catalog().size == 75

    def test_o_registro_de_producao_e_construivel(self) -> None:
        """§139 — únicas, resolvíveis, sem ciclo: o construtor prova."""
        from sports_intelligence.domain.features.extraction.catalog import (
            production_feature_registry,
        )

        assert len(production_feature_registry()) == 75

    def test_a_extracao_nao_acrescenta_port_de_leitura(self) -> None:
        """§94, §179 — ela consome o que o estado já carregou."""
        violacoes = internal_violations(
            files_in(EXTRACAO), ("sports_intelligence.ports.repositories",)
        )
        assert not violacoes, str(violacoes)
