"""A fronteira do motor de features — a mais importante desde o PR-01.

A REGRA CONSTITUCIONAL (§2, §3, §149, §150):

    FeatureBuilderInput = HistoricalCanonicalDatasetVersion

O motor de features lê o CORPUS PUBLICADO, e nada mais. Não lê arquivo de
provedor, `SourceRecord`, `ResolutionRun`, `FusionRun`, tabela de staging nem
SDK de fonte. Esses continuam alcançáveis pela auditoria — que percorre o
caminho ao contrário —, e nunca pelo caminho de cálculo.

POR QUE ISSO PRECISA DE TESTE E NÃO DE COMBINADO. Ler o bruto é sempre mais
fácil: o dado está lá, sem política de qualidade, sem decisão de licença, sem
recorte de versão. Um `import` de conveniência num sábado à noite contorna três
PRs de decisões — e não quebra nada visível, porque o número calculado continua
parecendo um número.

A SETA TEM UM SENTIDO SÓ (§150):

    Feature  →  contratos públicos do Corpus        permitido
    Corpus   →  qualquer coisa de Feature           proibido

E o motor de features também não conhece o futuro dele mesmo: nada de pgvector,
similaridade, ClickHouse ou Redis (§113, §114).
"""

from __future__ import annotations

import pytest

from tests.support.ast_checks import (
    FONTE,
    INFRA_EXTERNA,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes de feature deste PR. `historical/features` e
#: `application/features` NÃO existem ainda, e a ausência é deliberada (§110):
#: eles só devem nascer quando houver responsabilidade real de I/O, que é o
#: PR-05.2. A lista é filtrada para o que existe, e não fixa.
PACOTES_DE_FEATURE = ("domain/features",)

#: O QUE O MOTOR DE FEATURES NÃO PODE IMPORTAR (§3). Cada entrada é um caminho
#: por onde o dado bruto voltaria a entrar no cálculo.
FONTES_PROIBIDAS = (
    "sports_intelligence.ingestion",
    "sports_intelligence.adapters",
    "sports_intelligence.application",
    "sports_intelligence.domain.sources",
    "sports_intelligence.domain.resolution",
    "sports_intelligence.domain.fusion",
    "sports_intelligence.domain.datasets.files",
    "sports_intelligence.domain.datasets.validation",
    "sports_intelligence.archival",
    "apps.",
)

#: Os casos de uso QUE PUBLICAM O CORPUS. Nomeados um a um: uma varredura de
#: diretório passaria a incluir, sem ninguém decidir, todo caso de uso novo que
#: aparecesse ali — inclusive os que consomem o corpus, que é o sentido
#: permitido da seta.
MODULOS_DE_CORPUS = [
    caminho for caminho in (FONTE / "application" / "use_cases" / "corpus.py",) if caminho.exists()
]

#: O QUE AINDA NÃO EXISTE, e que este PR não pode antecipar (§113, §114).
PACOTES_FUTUROS = (
    "sports_intelligence.engines",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


class TestAEntradaAutorizada:
    """§2, §3. Só o corpus publicado alimenta feature."""

    @pytest.mark.parametrize("pacote", list(PACOTES_DE_FEATURE))
    def test_nao_le_bruto_resolucao_nem_fusao(self, pacote: str) -> None:
        violacoes = internal_violations(files_in(pacote), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_o_dominio_de_features_nao_importa_infraestrutura(self) -> None:
        """§111. Nada de PostgreSQL, PyArrow, FastAPI ou MinIO."""
        violacoes = external_violations(files_in("domain/features"), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    def test_o_dominio_de_features_nao_importa_numpy(self) -> None:
        """§112. O vetor chega depois, e com ele a decisão de como representá-lo.

        Introduzir NumPy agora, só para guardar uma lista de valores, tomaria
        essa decisão por antecipação — e a tomaria errado: o que este PR guarda
        é `ComputedFeature` com máscara e procedência, que não é um array.
        """
        encontrados: list[str] = []
        for arquivo in files_in("domain/features"):
            texto = arquivo.read_text(encoding="utf-8")
            if "import numpy" in texto or "from numpy" in texto:
                encontrados.append(arquivo.name)
        assert not encontrados, str(encontrados)

    def test_o_corpus_e_a_unica_dependencia_historica(self) -> None:
        """A lista de imports do corpus é CURTA e nomeada — se ela crescer, é
        porque alguém abriu uma porta nova, e a mudança precisa ser vista."""
        permitidos = {
            "sports_intelligence.domain.corpus.versions",
            "sports_intelligence.domain.corpus.membership",
            "sports_intelligence.domain.corpus.manifest",
            "sports_intelligence.domain.corpus.scope",
        }
        usados: set[str] = set()
        for arquivo in files_in("domain/features"):
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if "sports_intelligence.domain.corpus" in linha:
                    usados.add(linha.split("import")[0].replace("from", "").strip())
        assert usados <= permitidos, f"import novo de corpus: {sorted(usados - permitidos)}"


class TestONaoAntecipaOFuturo:
    """§113 ao §120. Nada de vetor, similaridade ou materialização."""

    @pytest.mark.parametrize("pacote", list(PACOTES_DE_FEATURE))
    def test_nao_importa_pgvector_clickhouse_nem_redis(self, pacote: str) -> None:
        violacoes = internal_violations(files_in(pacote), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_similaridade_nem_distancia(self) -> None:
        """§114. Isso é PR-06."""
        proibidos = {
            "cosine",
            "euclidean",
            "knn",
            "nearest_neighbor",
            "hnsw",
            "def distance",
        }
        encontrados: list[str] = []
        for arquivo in files_in("domain/features"):
            texto = arquivo.read_text(encoding="utf-8").lower()
            encontrados.extend(f"{arquivo.name}: {n}" for n in proibidos if n in texto)
        assert not encontrados, "\n".join(encontrados)

    def test_nao_ha_feature_de_producao_implementada(self) -> None:
        """§115 ao §119. Nenhuma janela móvel, pressão, força de time ou
        influência de jogador foi calculada neste PR.

        A BUSCA É POR CÁLCULO, e não pela palavra: `rolling` aparece em
        comentário explicando o que NÃO existe. O que não pode aparecer é uma
        função que o produza.
        """
        proibidos = {
            "def shots_last",
            "def xg_last",
            "def pressure",
            "def field_tilt",
            "def elo",
            "def form_index",
            "def player_influence",
            "def tactical_graph",
        }
        encontrados: list[str] = []
        for arquivo in files_in("domain/features"):
            texto = arquivo.read_text(encoding="utf-8").lower()
            encontrados.extend(f"{arquivo.name}: {n}" for n in proibidos if n in texto)
        assert not encontrados, "\n".join(encontrados)

    def test_nao_ha_imputacao(self) -> None:
        """§101. Média, zero, forward-fill: nenhum deles existe, e o dia em que
        existir precisa ser explícito e versionado."""
        proibidos = {"fillna", "def impute", "forward_fill", "mean_imputation"}
        encontrados: list[str] = []
        for arquivo in files_in("domain/features"):
            texto = arquivo.read_text(encoding="utf-8").lower()
            encontrados.extend(f"{arquivo.name}: {n}" for n in proibidos if n in texto)
        assert not encontrados, "\n".join(encontrados)


class TestASetaTemUmSentido:
    """§150. O corpus não conhece feature."""

    def test_o_corpus_nao_importa_feature(self) -> None:
        """A varredura é dos MÓDULOS DE CORPUS, e não do diretório inteiro.

        `application/use_cases` passou a abrigar os dois lados desde o PR-05.2:
        o corpus publica, e a reconstrução de estado consome — e ela PRECISA
        importar feature, porque é feita de feature. Varrer o diretório todo
        confundiria «o corpus não conhece feature» com «ninguém em application
        conhece feature», que é outra regra, e falsa.
        """
        violacoes = internal_violations(
            [*files_in("domain/corpus", "historical/corpus"), *MODULOS_DE_CORPUS],
            ("sports_intelligence.domain.features", "sports_intelligence.features"),
        )
        assert not violacoes, str(violacoes)

    def test_os_eventos_nao_importam_feature(self) -> None:
        """A canonicalização não pode passar a calcular nada — é o §119 do
        PR-04.4.1, visto do outro lado."""
        violacoes = internal_violations(
            files_in("domain/events", "historical/events"),
            ("sports_intelligence.domain.features",),
        )
        assert not violacoes, str(violacoes)


class TestOContratoEExecutavel:
    """As promessas do PR viram asserção, e não parágrafo."""

    def test_o_port_do_calculador_nao_recebe_infraestrutura(self) -> None:
        """§94. A assinatura é o contrato: definição, corte e contexto."""
        import inspect

        from sports_intelligence.ports.features import FeatureCalculator

        assinatura = inspect.signature(FeatureCalculator.compute)
        assert list(assinatura.parameters) == ["self", "context", "as_of"]

    def test_o_espaco_ao_vivo_nao_aceita_verdade_retrospectiva(self) -> None:
        """§80. A guarda é do OBJETO, e não da revisão de código."""
        from sports_intelligence.domain.features.space import FeatureSpaceDefinition
        from sports_intelligence.domain.features.temporal import TemporalMode
        from sports_intelligence.domain.shared.errors import ValidationError
        from sports_intelligence.domain.shared.versioning import FeatureSpaceVersion
        from tests.support.feature_fixtures import definicao_de_teste

        with pytest.raises(ValidationError):
            FeatureSpaceDefinition(
                name="proibido",
                version=FeatureSpaceVersion(major=1, minor=0),
                features=(definicao_de_teste(families=()),),
                temporal_mode=TemporalMode.CANONICAL_FINAL,
                live_comparable=True,
            )

    def test_a_versao_nao_publicada_nao_vira_origem_de_feature(self) -> None:
        """§2. Uma versão em `BUILDING` pode estar pela metade."""
        from sports_intelligence.domain.corpus.versions import DatasetVersionStatus

        legiveis = {e for e in DatasetVersionStatus if e.is_readable_corpus}
        assert legiveis == {DatasetVersionStatus.READY, DatasetVersionStatus.SUPERSEDED}
