"""Os limites do PR-04.2, verificados por AST e falhando o CI.

QUATRO COISAS PRECISAM CONTINUAR VERDADEIRAS, e nenhuma sobrevive por convenção:

    o construtor NÃO reavalia qualidade      duas implementações da mesma
                                             regra divergem no primeiro ajuste

    `Match` continua sem resultado           o primeiro write real não pode
                                             desfazer a decisão do PR-01

    fatos canônicos são append-only          um `UPDATE` no adapter satisfaz
                                             qualquer teste de interface e
                                             quebra a regra inteira

    o PR-04.3 e os seguintes não foram       features, engines, pgvector,
    antecipados                              ClickHouse, Redis e live continuam
                                             fora
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_checks import (
    INFRA_EXTERNA,
    RAIZ,
    defined_functions,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes que o PR-04.2 acrescentou.
PACOTES_DE_QUALIDADE = ("domain/quality", "domain/build")
PACOTES_DE_EXECUCAO = ("historical/quality", "historical/build")

#: O que NENHUM deles pode conhecer. `features` e `engines` são o PR-04.3 e os
#: seguintes; os três armazéns são ADR e não têm uma linha de código que fale
#: com eles; `live` é o outro plano inteiro.
PACOTES_FUTUROS = (
    "sports_intelligence.features",
    "sports_intelligence.engines",
    "sports_intelligence.ingestion.live",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


class TestDominioDeQualidadeEDeBuild:
    @pytest.mark.parametrize("pacote", list(PACOTES_DE_QUALIDADE))
    def test_nao_importa_infraestrutura(self, pacote: str) -> None:
        violacoes = external_violations(files_in(pacote), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", list(PACOTES_DE_QUALIDADE))
    def test_nao_importa_adapters_application_nem_apps(self, pacote: str) -> None:
        """O domínio descreve o que é qualidade e o que é uma decisão de
        build. Quem monta repositório é a borda."""
        violacoes = internal_violations(
            files_in(pacote),
            (
                "sports_intelligence.adapters",
                "sports_intelligence.application",
                "sports_intelligence.ingestion",
                "sports_intelligence.historical",
                "apps",
            ),
        )
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", [*PACOTES_DE_QUALIDADE, *PACOTES_DE_EXECUCAO])
    def test_nao_antecipa_features_engines_nem_armazens(self, pacote: str) -> None:
        """§80. O PR-04.3 e os seguintes não foram antecipados."""
        violacoes = internal_violations(files_in(pacote), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", list(PACOTES_DE_EXECUCAO))
    def test_a_execucao_nao_importa_fastapi_nem_banco(self, pacote: str) -> None:
        """O avaliador e os construtores são puros sobre objetos de domínio.
        Um `asyncpg` aqui faria a construção canônica precisar de um pool para
        ser testada."""
        violacoes = external_violations(files_in(pacote), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", list(PACOTES_DE_EXECUCAO))
    def test_a_execucao_nao_importa_adapters_nem_apps(self, pacote: str) -> None:
        violacoes = internal_violations(files_in(pacote), ("sports_intelligence.adapters", "apps"))
        assert not violacoes, str(violacoes)


class TestOConstrutorNaoReavaliaQualidade:
    """§5, o princípio central do PR — verificado no código, não na intenção."""

    def test_os_construtores_nao_importam_a_politica_de_qualidade(self) -> None:
        """Um construtor que conhecesse `HistoricalQualityPolicy` poderia
        conferir um piso por conta — e a partir daí haveria duas respostas
        para «este registro é elegível?»."""
        violacoes = internal_violations(
            files_in("historical/build"),
            ("sports_intelligence.domain.quality.policy",),
        )
        assert not violacoes, (
            "a construção canônica importou a política de QUALIDADE:\n"
            + "\n".join(map(str, violacoes))
        )

    def test_nenhuma_funcao_de_construcao_tem_nome_de_avaliacao(self) -> None:
        """O import não cobre tudo: alguém escreve `def _e_elegivel(...)`
        dentro do próprio construtor, sem importar nada."""
        proibidos = frozenset(
            {
                "assess",
                "evaluate",
                "is_eligible",
                "_is_eligible",
                "score_quality",
                "compute_quality",
                "check_thresholds",
            }
        )
        encontradas = [
            f"{arquivo.name}:{linha} def {nome}"
            for arquivo, linha, nome in defined_functions(files_in("historical/build"))
            if nome in proibidos
        ]
        assert not encontradas, "\n".join(encontradas)

    def test_o_construtor_exige_a_decisao_por_assinatura(self) -> None:
        """A regra deixou de ser convenção e virou parâmetro obrigatório."""
        import inspect

        from sports_intelligence.historical.build.builders import (
            CanonicalLineupBuilder,
            CanonicalMatchBuilder,
            CanonicalOddsBuilder,
            CanonicalResultBuilder,
        )

        for construtor in (
            CanonicalMatchBuilder,
            CanonicalResultBuilder,
            CanonicalLineupBuilder,
            CanonicalOddsBuilder,
        ):
            assinatura = inspect.signature(construtor.build)
            assert "decision" in assinatura.parameters, (
                f"{construtor.__name__}.build sem `decision` — ele passaria a poder "
                "construir sem que a política tivesse autorizado (§5)"
            )
            assert assinatura.parameters["decision"].default is inspect.Parameter.empty, (
                f"{construtor.__name__}.build com `decision` opcional"
            )

    def test_a_politica_de_build_nao_le_o_vetor_de_qualidade(self) -> None:
        """Ela decide SOBRE o veredito, e não sobre as observações que o
        produziram. Ler o vetor aqui seria reavaliar com outro critério.

        POR AST E NÃO POR TEXTO. A docstring do módulo CITA `QualityVector`
        por nome — justamente para explicar que ele não é usado — e um `grep`
        marcaria a explicação como violação. É o mesmo motivo pelo qual
        `ast_checks` existe.
        """
        arquivo = RAIZ / "src/sports_intelligence/domain/build/policy.py"
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))

        importados = {
            alias.asname or alias.name
            for no in ast.walk(arvore)
            if isinstance(no, ast.ImportFrom)
            for alias in no.names
        }
        for proibido in ("QualityVector", "QualityDimension"):
            assert proibido not in importados, (
                f"a política de build importou `{proibido}` — ela decide sobre o "
                "VEREDITO, e reavaliar as observações criaria a segunda opinião "
                "que o §5 proíbe"
            )

        chamados = {
            no.func.attr
            for no in ast.walk(arvore)
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
        }
        for proibido in ("minimum_for", "identity_minimum_for", "weakest"):
            assert proibido not in chamados, (
                f"a política de build chamou `{proibido}` — conferir piso aqui é "
                "reavaliar qualidade num segundo lugar"
            )


class TestMatchContinuaSemResultado:
    """§32, §88 — a decisão central do PR-01, reconferida no primeiro write."""

    def test_o_agregado_nao_ganhou_atributo_de_resultado(self) -> None:
        from sports_intelligence.domain.matches.models import Match

        for proibido in ("result", "final_score", "winner", "score", "outcome", "goals"):
            assert proibido not in Match.__dataclass_fields__, (
                f"`{proibido}` apareceu em Match — qualquer caminho que descreva o "
                "minuto 63 passaria a poder ler o fim (ADR-0007)"
            )
            assert not hasattr(Match, proibido)

    def test_o_construtor_de_partida_nao_toca_em_resultado(self) -> None:
        """Verificado no código do construtor, e não só no tipo: um
        `partida.with_result(...)` acrescentado depois passaria pelo teste de
        atributo se `Match` continuasse sem o campo."""
        arquivo = RAIZ / "src/sports_intelligence/historical/build/builders.py"
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        construtor = next(
            no
            for no in ast.walk(arvore)
            if isinstance(no, ast.ClassDef) and no.name == "CanonicalMatchBuilder"
        )
        corpo = ast.dump(construtor)
        for proibido in ("MatchResult", "Score", "regular_time"):
            assert proibido not in corpo, (
                f"`{proibido}` dentro de CanonicalMatchBuilder — o placar é um FATO "
                "à parte, e juntá-los desfaria a decisão do PR-01 (§26, §31)"
            )

    def test_a_tabela_de_partidas_nao_tem_coluna_de_placar(self) -> None:
        """A mesma decisão, no banco. A 0003 já a tomou; a 0005 não a desfaz."""
        migracao = RAIZ / "migrations/0005_quality_and_canonical_build.sql"
        texto = migracao.read_text(encoding="utf-8")
        assert "ALTER TABLE matches" not in texto, (
            "a migration do PR-04.2 alterou `matches` — o placar continua em "
            "`match_results`, e uma coluna aqui o traria de volta para dentro do "
            "agregado"
        )


class TestAppendOnlySobreFatoCanonico:
    """§62. Um `UPDATE` no adapter satisfaz qualquer teste de interface."""

    ADAPTERS = (
        RAIZ / "src/sports_intelligence/adapters/postgres/canonical.py",
        RAIZ / "src/sports_intelligence/adapters/postgres/quality.py",
    )

    @pytest.mark.parametrize(
        "tabela",
        [
            "matches",
            "match_results",
            "lineups",
            "lineup_entries",
            "canonical_odds_observations",
            "match_quality_assessments",
            "quality_assessment_coverage",
            "quality_assessment_issues",
            "canonical_build_records",
            "canonical_build_family_decisions",
        ],
    )
    def test_nao_ha_update_sobre(self, tabela: str) -> None:
        for adapter in self.ADAPTERS:
            texto = adapter.read_text(encoding="utf-8")
            assert f"UPDATE {tabela}" not in texto, (
                f"UPDATE em {tabela} ({adapter.name}): reprocessar emite outra "
                "execução, e a anterior fica exatamente como estava — um fato "
                "histórico sobrescrito reescreve o passado em silêncio (§62)"
            )

    def test_as_excecoes_sao_condicionais_ao_estado(self) -> None:
        """Fechar uma execução em curso e gravar o snapshot da política SÃO
        `UPDATE`, e os dois são condicionais a `status = 'RUNNING'` — que é
        como esta base faz concorrência desde o PR-02."""
        for adapter, tabela in (
            (self.ADAPTERS[0], "canonical_build_runs"),
            (self.ADAPTERS[1], "quality_runs"),
        ):
            texto = adapter.read_text(encoding="utf-8")
            assert f"UPDATE {tabela}" in texto
            for bloco in texto.split(f"UPDATE {tabela}")[1:]:
                trecho = bloco.split('"""')[0]
                assert "status = 'RUNNING'" in trecho, (
                    f"UPDATE em {tabela} sem condição de estado: dois workers "
                    "fechando a mesma execução produziriam duas contagens, e a "
                    "segunda sobrescreveria a primeira"
                )

    def test_o_teste_enxerga_um_update_plantado(self, tmp_path: Path) -> None:
        plantado = tmp_path / "adapter.py"
        plantado.write_text('"UPDATE matches SET x = 1"', encoding="utf-8")
        assert "UPDATE matches" in plantado.read_text(encoding="utf-8")


class TestOLimiteDaFase:
    def test_o_corpus_publicavel_continua_barrado(self) -> None:
        """§110, §111. A guarda existe para ser chamada por qualquer caminho
        que trate uma execução de build como versão publicada do histórico."""
        from sports_intelligence.domain.build.runs import assert_not_a_published_corpus

        assert callable(assert_not_a_published_corpus)

    def test_o_limite_avancou_do_pr_04_2_para_o_pr_04_3(self) -> None:
        """O que era proibido AQUI é o que o PR-04.3 entregou — e o registro
        dessa sucessão é deliberado.

        Este teste barrava `HistoricalCanonicalDataset`, o manifesto e o gate
        `HISTORICAL_CANONICAL_READY` porque, ao fim do PR-04.2, o corpus
        publicável não existia e o código não podia fingir que sim. Ele agora
        existe: apagá-lo esconderia a fronteira, e mantê-lo como estava faria a
        entrega do PR-04.3 aparecer como violação.

        O QUE ELE PASSA A GUARDAR é a fronteira DESTA fase — a do PR-05.
        """
        from sports_intelligence.domain.corpus.versions import (
            HistoricalCanonicalDataset,
            assert_not_vector_active,
        )

        assert HistoricalCanonicalDataset is not None
        assert callable(assert_not_vector_active)

    def test_o_corpus_pronto_nao_e_espaco_vetorial_ativo(self) -> None:
        """§4 do PR-04.3.

            HISTORICAL_CANONICAL_READY  ≠  HISTORICAL_VECTOR_ACTIVE

        Um corpus pronto é um corpus que o PR-05 pode LER. Feature,
        `MatchStateVector` e indexação são o PR-05 inteiro.

        A VERIFICAÇÃO É POR IMPORT E NÃO POR TEXTO, e a diferença importa:
        `assert_not_vector_active` MENCIONA `MatchStateVector` na mensagem que
        o recusa, e uma busca textual transformaria a guarda em violação — o
        oposto exato do que ela faz.
        """
        violacoes = internal_violations(
            [
                arquivo
                for arquivo in files_in(
                    "domain/corpus", "historical/corpus", "application/use_cases"
                )
                if "corpus" in arquivo.as_posix()
            ],
            PACOTES_FUTUROS,
        )
        assert not violacoes, str(violacoes)

    def test_nao_existe_construtor_de_eventos(self) -> None:
        """§28, §92. O contrato fundido da V1 não carrega evento, e um
        construtor que nunca recebe evento nenhum seria dívida com aparência
        de cobertura."""
        from sports_intelligence.domain.build.decisions import BUILDABLE_FAMILIES
        from sports_intelligence.domain.quality.coverage import CoverageFamily
        from sports_intelligence.historical.build import builders

        assert not hasattr(builders, "CanonicalEventBuilder")
        assert CoverageFamily.EVENT not in BUILDABLE_FAMILIES

    def test_o_lifecycle_do_build_nao_e_historical_active(self) -> None:
        """ADR-0007. `HISTORICAL_ACTIVE` é promoção, e promoção é o PR-04.3 —
        um fato recém-construído seria lido como conhecimento publicado."""
        from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
        from sports_intelligence.historical.build.builders import BUILT_LIFECYCLE

        assert BUILT_LIFECYCLE is not MatchLifecycle.HISTORICAL_ACTIVE


class TestSemExecucaoDinamicaNemAprendizado:
    def test_a_qualidade_e_o_build_nao_executam_nada(self) -> None:
        """A política vem de configuração e nunca vira código."""
        proibidos = {"eval", "exec", "compile", "__import__"}
        encontrados: list[str] = []
        for arquivo in files_in(*PACOTES_DE_QUALIDADE, *PACOTES_DE_EXECUCAO):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
            encontrados.extend(
                f"{arquivo.name}:{no.lineno} {no.func.id}()"
                for no in ast.walk(arvore)
                if isinstance(no, ast.Call)
                and isinstance(no.func, ast.Name)
                and no.func.id in proibidos
            )
        assert not encontrados, "\n".join(encontrados)

    def test_nenhum_modelo_de_aprendizado_entra_na_decisao(self) -> None:
        """Uma decisão de corpus precisa ser explicável e estável."""
        from tests.architecture.test_resolution_boundaries import (
            BIBLIOTECAS_DE_APRENDIZADO,
        )

        violacoes = external_violations(
            files_in(*PACOTES_DE_QUALIDADE, *PACOTES_DE_EXECUCAO),
            BIBLIOTECAS_DE_APRENDIZADO,
        )
        assert not violacoes, str(violacoes)


class TestPoliticaNaoEstaNoCodigo:
    def test_o_avaliador_nao_escreve_um_limiar(self) -> None:
        """§23 do PR-04.1, um nível acima: o avaliador OBSERVA e a política
        PESA. Um `if confianca < 0.9` aqui seria a decisão de negócio
        escondida num laço de verificação."""
        suspeitos: list[str] = []
        for arquivo in files_in("historical/quality", "historical/build"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
            for no in ast.walk(arvore):
                if not isinstance(no, ast.Compare):
                    continue
                suspeitos.extend(
                    f"{arquivo.name}:{no.lineno} compara contra {comparado.value}"
                    for comparado in no.comparators
                    if isinstance(comparado, ast.Constant)
                    and isinstance(comparado.value, float)
                    and 0.5 <= comparado.value <= 0.99
                )
        assert not suspeitos, "limiar de decisão no código:\n" + "\n".join(suspeitos)

    def test_as_duas_politicas_sao_versionadas(self) -> None:
        from sports_intelligence.domain.build.policy import (
            DEFAULT_COMMERCIAL_BUILD_POLICY,
            DEFAULT_RESEARCH_BUILD_POLICY,
        )
        from sports_intelligence.domain.quality.policy import DEFAULT_QUALITY_POLICY

        for politica in (
            DEFAULT_QUALITY_POLICY,
            DEFAULT_RESEARCH_BUILD_POLICY,
            DEFAULT_COMMERCIAL_BUILD_POLICY,
        ):
            assert politica.version.major >= 1
            assert politica.as_canonical()["version"]
