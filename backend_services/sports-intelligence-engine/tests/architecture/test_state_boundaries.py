"""A fronteira do motor de ESTADO — o gate do §177.

O QUE ELE PROTEGE, e por que cada regra precisa ser executável:

    o estado é DOMÍNIO PURO         nada de asyncpg, PyArrow, MinIO, FastAPI
    o estado lê o CORPUS            e nunca bruto, resolução ou fusão
    o estado NÃO CALCULA FEATURE    janela móvel, pressão, força: é PR-05.3
    o estado NÃO É UM VETOR         nada de NumPy, pgvector, similaridade
    o corpus NÃO CONHECE o estado   a seta tem um sentido só

O PERIGO ESPECÍFICO DESTE PR. `HistoricalMatchState` é a primeira coisa do
motor de features que PARECE útil sozinha: ela tem placar, elenco e cartões.
A tentação natural é pendurar nela uma média móvel — «já que o estado está
aqui» —, e o resultado seria uma feature sem definição, sem versão, sem
população e sem normalizador declarado. É exatamente o que o PR-05.1
construiu contratos para impedir, e o que este arquivo impede de acontecer
por conveniência.

A OUTRA TENTAÇÃO É CACHE. Reconstruir dez mil estados é caro, e guardar o
resultado num Redis parece óbvio. Não é: um estado cacheado é um estado cuja
identidade deixou de depender do corpus e da política, e a primeira
republicação do corpus faria o cache servir um passado que não existe mais
(§92, §93).
"""

from __future__ import annotations

import pytest

from tests.support.ast_checks import (
    FONTE,
    INFRA_EXTERNA,
    files_in,
    imports_of,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: O pacote de estado. Ele é um subpacote de `domain/features`, e por isso já
#: herda as proibições do PR-05.1 — o que este arquivo acrescenta é o que só
#: faz sentido depois que existe estado.
ESTADO = "domain/features/state"

#: O QUE O ESTADO NÃO PODE CONHECER (§177). Cada entrada é um caminho por onde
#: o dado deixaria de vir do corpus publicado.
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

#: O FUTURO QUE ESTE PR NÃO ANTECIPA (§92, §93, §114).
PACOTES_FUTUROS = (
    "sports_intelligence.engines",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


def texto_do_estado() -> list[tuple[str, str]]:
    return [
        (arquivo.name, arquivo.read_text(encoding="utf-8").lower())
        for arquivo in files_in(ESTADO)
    ]


class TestOEstadoEDominioPuro:
    """§73, §76 — ele recebe contratos e devolve estado. Nada mais."""

    def test_o_pacote_de_estado_existe_e_foi_varrido(self) -> None:
        """Uma varredura de zero arquivo passa sempre — e não prova nada."""
        assert len(files_in(ESTADO)) >= 6

    def test_nao_importa_infraestrutura(self) -> None:
        from tests.support.ast_checks import external_violations

        violacoes = external_violations(files_in(ESTADO), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    def test_nao_importa_adaptador_aplicacao_nem_bruto(self) -> None:
        violacoes = internal_violations(files_in(ESTADO), FONTES_PROIBIDAS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_io_no_pacote_de_estado(self) -> None:
        """Sem `open`, sem `await conexao`, sem `datetime.now`.

        `datetime.now()` É A ARMADILHA MAIS SUTIL. Um estado que consultasse o
        relógio da máquina deixaria de ser função dos seus insumos — e duas
        reconstruções do mesmo corte dariam impressões diferentes por causa do
        segundo em que rodaram.
        """
        proibidos = ("open(", "datetime.now", "time.time", "utcnow", "random.")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)


class TestOEstadoNaoCalculaFeature:
    """§115 ao §119 do PR-05.1, aplicados ao lugar mais tentador."""

    def test_nao_ha_janela_movel(self) -> None:
        proibidos = ("rolling_", "def rolling", "last_5", "last_10", "moving_average")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)

    def test_nao_ha_pressao_momentum_nem_forca_de_time(self) -> None:
        proibidos = (
            "def pressure",
            "def momentum",
            "def field_tilt",
            "def elo",
            "def team_strength",
            "def form_index",
            "def player_influence",
            "def tactical_graph",
        )
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)

    def test_nao_ha_normalizacao_executada(self) -> None:
        """§120 — o PR-05.1 DEFINIU normalizador; nenhum PR ainda o executa."""
        proibidos = ("def normalize", "z_score(", "min_max(", "standard_scaler")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)

    def test_o_estado_nao_chama_calculador_de_feature(self) -> None:
        """§169 — a relação é a inversa: o estado alimenta as features."""
        violacoes = internal_violations(
            files_in(ESTADO), ("sports_intelligence.ports.features",)
        )
        assert not violacoes, str(violacoes)


class TestOEstadoNaoEUmVetor:
    """§5, §173 — representação estrutural, e não matemática."""

    def test_nao_importa_numpy_nem_dataframe(self) -> None:
        proibidos = ("import numpy", "from numpy", "import polars", "import pandas")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)

    def test_nao_antecipa_pgvector_clickhouse_nem_cache(self) -> None:
        violacoes = internal_violations(files_in(ESTADO), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_nao_ha_similaridade_nem_distancia(self) -> None:
        proibidos = ("cosine", "euclidean", "knn", "hnsw", "nearest_neighbor")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)

    def test_nao_ha_persistencia_de_estado(self) -> None:
        """§94 — o estado deste PR é reconstruído, e nunca gravado.

        Persistir estado exigiria decidir invalidação, versionamento e
        republicação — três decisões que nenhum PR tomou —, e o resultado seria
        uma tabela cuja verdade envelhece em silêncio.
        """
        proibidos = ("insert into", "def save", "def persist", "def store")
        encontrados = [
            f"{nome}: {termo}"
            for nome, texto in texto_do_estado()
            for termo in proibidos
            if termo in texto
        ]
        assert not encontrados, "\n".join(encontrados)


class TestASetaTemUmSentido:
    """§150 aplicado ao estado: quem publica não conhece quem consome."""

    def test_o_corpus_nao_importa_estado(self) -> None:
        violacoes = internal_violations(
            files_in("domain/corpus", "historical/corpus", "domain/events"),
            ("sports_intelligence.domain.features.state",),
        )
        assert not violacoes, str(violacoes)

    def test_o_adaptador_de_estado_le_pela_pertinencia_da_versao(self) -> None:
        """§78 — o registro canônico é global; a versão publica um recorte.

        Ler `canonical_match_events` sem cruzar com a pertinência traria
        eventos que aquele corpus nunca publicou — e o estado passaria a
        depender de quando o build rodou, e não de qual versão foi pedida.
        """
        adaptador = FONTE / "adapters" / "postgres" / "feature_state.py"
        texto = adaptador.read_text(encoding="utf-8")
        assert "historical_canonical_event_members" in texto
        assert "historical_canonical_members" in texto

    def test_o_dominio_de_estado_nao_conhece_o_port_de_leitura(self) -> None:
        """Quem lê é a aplicação (§74). O domínio nem sabe que existe um port."""
        violacoes = internal_violations(
            files_in(ESTADO), ("sports_intelligence.ports.repositories",)
        )
        assert not violacoes, str(violacoes)


class TestOContratoEExecutavel:
    """As promessas do PR viram asserção, e não parágrafo."""

    def test_o_construtor_recebe_contrato_e_nao_conexao(self) -> None:
        """§76 — a assinatura é o contrato: entrada tipada, corte e origem."""
        import inspect

        from sports_intelligence.domain.features.state.builder import (
            HistoricalMatchStateBuilder,
        )

        assinatura = inspect.signature(HistoricalMatchStateBuilder.build)
        assert set(assinatura.parameters) == {"self", "entrada", "as_of", "source"}

    def test_a_classificacao_estrutural_cobre_a_taxonomia_inteira(self) -> None:
        """§88 — o módulo já falha ao ser importado; aqui isso vira asserção."""
        from sports_intelligence.domain.events.taxonomy import EventType
        from sports_intelligence.domain.features.state.effects import (
            structural_effect_of,
        )

        assert all(structural_effect_of(tipo) is not None for tipo in EventType)

    def test_o_port_de_leitura_nao_vaza_tipo_de_banco(self) -> None:
        """O port é do domínio da aplicação — `Record` de asyncpg não passa."""
        port = FONTE / "ports" / "repositories" / "feature_state.py"
        modulos = {imp.module for imp in imports_of(port)}
        assert not {m for m in modulos if m.startswith(("asyncpg", "sports_intelligence.adapters"))}

    def test_este_pr_nao_traz_migracao(self) -> None:
        """§94, §183 — reconstrução não grava, e por isso não muda o esquema."""
        migracoes = sorted(
            p.name for p in (FONTE.parent.parent / "migrations").glob("*.sql")
        )
        assert migracoes[-1] == "0011_event_corpus_membership.sql", migracoes[-3:]
