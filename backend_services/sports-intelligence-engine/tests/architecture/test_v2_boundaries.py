"""As fronteiras do PR-05.4 — contexto, mercado e normalização.

O QUE ESTE ARQUIVO PROTEGE (§194 ao §199):

    contexto     lê o corpus publicado, e nunca bruto/fusão/resolução
    mercado      lê o `OddsState`, e nunca o banco
    normalizador domínio puro — sem infraestrutura, sem NumPy, sem scikit
    V1           imutável: nada a reescreve, e a impressão dourada prova
    V2           estende sem mutar

O PERIGO NOVO DESTA FASE É O NORMALIZADOR. Ele é o primeiro módulo do motor que
calcula estatística sobre uma população, e a tentação de instalar NumPy «só
para os quartis» é forte e razoável. Ela custaria: a implementação padrão do
`numpy.percentile` é uma escolha de método que muda com a versão da biblioteca,
e o motor perderia o controle sobre a identidade das escalas que publica.
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

#: Os pacotes novos deste PR.
CONTEXTO = "domain/features/prematch"
MERCADO = "domain/features/market"
NORMALIZACAO = "domain/features/fitting"
QUANTIS = "domain/features"

#: Por onde o dado bruto voltaria a entrar no cálculo (§9, §194).
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

PACOTES_FUTUROS = (
    "sports_intelligence.engines",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)

#: As bibliotecas de estatística e ML que o PR proíbe (§195, §196, §197).
BIBLIOTECAS_PROIBIDAS = frozenset(
    {"numpy", "pandas", "polars", "scipy", "sklearn", "scikit_learn", "statsmodels"}
)


def texto(pacote: str) -> list[tuple[str, str]]:
    """O CÓDIGO de cada arquivo do pacote — sem docstring nem comentário.

    Esta base explica por extenso o que NÃO faz: as docstrings citam `epsilon`,
    `winsor` e `overround` pelo nome para registrar a decisão de não tê-los.
    Varrer o arquivo cru marcaria a explicação como violação (§194).
    """
    return [(arquivo.name, code_only(arquivo)) for arquivo in files_in(pacote)]


def proibir(pacote: str, termos: tuple[str, ...]) -> list[str]:
    return [
        f"{nome}: {termo}"
        for nome, conteudo in texto(pacote)
        for termo in termos
        if termo in conteudo
    ]


class TestOContexto:
    """§9, §194, §199."""

    def test_o_pacote_existe_e_foi_varrido(self) -> None:
        assert len(files_in(CONTEXTO)) >= 2

    def test_nao_importa_infraestrutura(self) -> None:
        assert not external_violations(files_in(CONTEXTO), INFRA_EXTERNA)

    def test_nao_importa_bruto_fusao_nem_resolucao(self) -> None:
        violacoes = internal_violations(files_in(CONTEXTO), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_io_no_dominio_do_contexto(self) -> None:
        assert not proibir(
            CONTEXTO, ("open(", "datetime.now", "time.time", "utcnow", "random.")
        )

    def test_o_dominio_do_contexto_nao_carrega_resultado(self) -> None:
        """§11, §166 — medimos calendário, e o tipo não tem por onde medir forma."""
        assert not proibir(CONTEXTO, ("matchresult", "score", "goals_for", "points"))

    def test_nao_ha_forma_nem_forca_de_time(self) -> None:
        """§11 — Elo, pontos recentes e confronto direto ficam fora."""
        assert not proibir(
            CONTEXTO,
            ("def elo", "win_rate", "def form", "power_score", "head_to_head", "def h2h"),
        )

    def test_o_adaptador_le_pela_pertinencia_da_versao(self) -> None:
        """§40, §41 — o passado é o da VERSÃO, e não o da tabela global."""
        adaptador = FONTE / "adapters" / "postgres" / "feature_context.py"
        conteudo = code_only(adaptador)
        assert conteudo.count("historical_canonical_members") >= 2

    def test_o_port_nao_vaza_tipo_de_banco(self) -> None:
        port = FONTE / "ports" / "repositories" / "feature_context.py"
        modulos = {imp.module for imp in imports_of(port)}
        assert not {
            m
            for m in modulos
            if m.startswith(("asyncpg", "sports_intelligence.adapters"))
        }


class TestOMercado:
    """§43, §44, §72, §194."""

    def test_o_pacote_existe_e_foi_varrido(self) -> None:
        assert len(files_in(MERCADO)) >= 2

    def test_nao_importa_infraestrutura(self) -> None:
        assert not external_violations(files_in(MERCADO), INFRA_EXTERNA)

    def test_nao_importa_bruto_adaptador_nem_aplicacao(self) -> None:
        """§43 — a extração de mercado NÃO acessa banco."""
        violacoes = internal_violations(files_in(MERCADO), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_importa_repositorio_de_odds(self) -> None:
        """§44 — a autoridade é o `OddsState`, e não uma segunda leitura."""
        violacoes = internal_violations(
            files_in(MERCADO), ("sports_intelligence.ports.repositories",)
        )
        assert not violacoes, str(violacoes)

    def test_nao_reimplementa_filtro_temporal(self) -> None:
        """§44 — uma segunda regra temporal divergiria da primeira."""
        assert not proibir(
            MERCADO, ("observed_at <", "knowledge_cutoff", "leakageguard", "as_of.knows")
        )

    def test_nao_ha_probabilidade_implicita_nem_overround(self) -> None:
        """§74, §75."""
        assert not proibir(
            MERCADO, ("implied_prob", "overround", "def vig", "1 / odds", "1/odds")
        )

    def test_nao_ha_movimento_de_linha(self) -> None:
        """§76, §77 — exige quatro decisões que ninguém tomou."""
        assert not proibir(
            MERCADO,
            ("def movement", "def drift", "def steam", "velocity", "acceleration", "opening_"),
        )

    def test_nao_ha_peso_por_casa_de_aposta(self) -> None:
        """§73 — todas pesam 1 na V1."""
        assert not proibir(
            MERCADO, ("bookmaker_weight", "bookmaker_quality", "weighted_median")
        )

    def test_a_casa_de_aposta_nao_e_dimensao(self) -> None:
        """§45, §72 — a dimensão do espaço não pode seguir o provedor."""
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            match_state_raw_space_v2,
        )

        chaves = match_state_raw_space_v2().keys
        assert not [k for k in chaves if "bookmaker" in k]

    def test_o_handicap_nao_foi_improvisado(self) -> None:
        """§49, §211 — ele não entra na V2, e não há alias textual."""
        from sports_intelligence.domain.features.market.specs import MARKET_SPECS_V1
        from sports_intelligence.domain.odds.models import OddsMarket

        assert OddsMarket.ASIAN_HANDICAP not in {s.market for s in MARKET_SPECS_V1}


class TestONormalizador:
    """§115, §117, §195 ao §198."""

    def test_o_pacote_existe_e_foi_varrido(self) -> None:
        assert len(files_in(NORMALIZACAO)) >= 4

    def test_nao_importa_infraestrutura(self) -> None:
        """§198 — domínio puro."""
        assert not external_violations(files_in(NORMALIZACAO), INFRA_EXTERNA)

    def test_nao_importa_numpy_pandas_scipy_nem_sklearn(self) -> None:
        """§195, §196, §197 — o método de quantil é NOSSO e é versionado."""
        violacoes = external_violations(files_in(NORMALIZACAO), BIBLIOTECAS_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_o_modulo_de_quantis_tambem_nao_as_importa(self) -> None:
        quantis = FONTE / "domain" / "features" / "quantiles.py"
        modulos = {imp.module.split(".")[0] for imp in imports_of(quantis)}
        assert not modulos & BIBLIOTECAS_PROIBIDAS

    def test_nao_importa_banco_nem_aplicacao(self) -> None:
        """§117 — o ajustador é puro."""
        violacoes = internal_violations(files_in(NORMALIZACAO), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_epsilon_escondido(self) -> None:
        """§125 — `max(iqr, 1e-6)` inventaria uma escala."""
        assert not proibir(
            NORMALIZACAO, ("1e-6", "1e-9", "epsilon", "+ 1e", "max(iqr")
        )

    def test_nao_ha_fallback_para_media_e_desvio(self) -> None:
        """§127 — trocar de método sem versionar seria outra escala."""
        assert not proibir(
            NORMALIZACAO, ("stdev", "std_dev", "def mean", "statistics.mean", "variance")
        )

    def test_nao_ha_clipping_winsorizacao_nem_log(self) -> None:
        """§136, §137, §138."""
        assert not proibir(
            NORMALIZACAO, ("def clip", "winsor", "math.log", "log1p", "def clamp")
        )

    def test_nao_ha_mediana_aproximada(self) -> None:
        """§183, §185 — o ajuste da V1 é EXATO."""
        assert not proibir(
            NORMALIZACAO, ("tdigest", "t_digest", "sketch", "approx", "reservoir")
        )

    def test_nao_ha_ml_nem_selecao_automatica(self) -> None:
        """§2 — nada de PCA, clustering ou pesos aprendidos."""
        assert not proibir(
            NORMALIZACAO,
            (
                "def pca",
                "kmeans",
                "def cluster",
                "learned_weight",
                "def fit_transform",
            ),
        )

    def test_nao_antecipa_vetor_nem_similaridade(self) -> None:
        assert not proibir(
            NORMALIZACAO, ("cosine", "euclidean", "knn", "hnsw", "def to_vector")
        )

    def test_nao_ha_persistencia_de_artefato(self) -> None:
        """§200, §201 — a materialização é o PR-05.5."""
        assert not proibir(
            NORMALIZACAO, ("insert into", "def save", "def persist", "create table")
        )

    def test_nao_antecipa_pgvector_clickhouse_nem_cache(self) -> None:
        violacoes = internal_violations(files_in(NORMALIZACAO), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)


class TestAV1PermaneceImutavel:
    """§3, §5, §90, §194, §219."""

    def test_a_impressao_dourada_da_v1_esta_no_arnes(self) -> None:
        """Se alguém mudar a V1, este teste do PR-05.3 falha — e é o ponto."""
        from sports_intelligence.domain.features.extraction.catalog import (
            match_state_raw_space_v1,
        )
        from tests.unit.test_feature_catalog import GOLDEN_SPACE

        assert match_state_raw_space_v1().fingerprint == GOLDEN_SPACE

    def test_o_catalogo_da_v1_nao_importa_o_da_v2(self) -> None:
        """A seta tem um sentido: a V2 conhece a V1, e nunca o contrário."""
        v1 = FONTE / "domain" / "features" / "extraction" / "catalog.py"
        modulos = {imp.module for imp in imports_of(v1)}
        assert "sports_intelligence.domain.features.extraction.catalog_v2" not in modulos

    def test_o_extrator_da_v1_nao_importa_o_da_v2(self) -> None:
        v1 = FONTE / "domain" / "features" / "extraction" / "extractor.py"
        modulos = {imp.module for imp in imports_of(v1)}
        assert (
            "sports_intelligence.domain.features.extraction.extractor_v2" not in modulos
        )

    def test_a_v1_nao_conhece_contexto_nem_mercado(self) -> None:
        """As features novas são da V2; a V1 não pode passar a exigi-las."""
        violacoes = internal_violations(
            [
                FONTE / "domain" / "features" / "extraction" / "catalog.py",
                FONTE / "domain" / "features" / "extraction" / "extractor.py",
            ],
            (
                "sports_intelligence.domain.features.prematch",
                "sports_intelligence.domain.features.market",
                "sports_intelligence.domain.features.fitting",
            ),
        )
        assert not violacoes, str(violacoes)


class TestAV2NaoAntecipa:
    """§2 — o espaço estendido continua cru."""

    def test_o_espaco_v2_nao_declara_normalizador(self) -> None:
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            extended_feature_catalog,
        )

        assert not [
            d.key
            for d in extended_feature_catalog().definitions
            if d.normalizer_key is not None
        ]

    def test_nao_existe_espaco_normalizado_de_producao(self) -> None:
        """§96 — a população científica de ajuste é o PR-05.5."""
        nomes = [
            arquivo.name
            for arquivo in files_in("domain/features")
            if "match_state_normalized" in code_only(arquivo)
        ]
        assert nomes == []

    def test_o_extrator_v2_nao_normaliza(self) -> None:
        """§152, §153 — normalização é um segundo passo explícito."""
        extrator = FONTE / "domain" / "features" / "extraction" / "extractor_v2.py"
        modulos = {imp.module for imp in imports_of(extrator)}
        assert "sports_intelligence.domain.features.fitting.transformer" not in modulos
        assert "sports_intelligence.domain.features.fitting.fitter" not in modulos

    def test_este_pr_nao_traz_migracao(self) -> None:
        """§200 — as partidas anteriores já existem no corpus."""
        migracoes = sorted(
            p.name for p in (FONTE.parent.parent / "migrations").glob("*.sql")
        )
        assert migracoes[-1] == "0011_event_corpus_membership.sql", migracoes[-3:]
