"""O catálogo de produção — identidade, ordem e as recusas do registro.

O QUE ESTES TESTES PROVAM (§139, §164, §165). O catálogo é a primeira coisa do
motor que é PURA DECLARAÇÃO: setenta e cinco contratos e uma ordem. Um defeito
aqui não quebra nada visível — as features continuam calculando —, e produz
duas coisas caras:

    identidade instável   a mesma feature com impressão diferente entre
                          execuções faz todo histórico deixar de comparar
    ordem instável        o vetor futuro troca de eixos, e a distância entre
                          dois vetores vira aritmética sobre dimensões
                          diferentes

AS IMPRESSÕES DOURADAS SÃO O ARNÊS (§164, §165). Elas não estão aqui porque o
hash é interessante: estão porque mudá-lo precisa ser uma DECISÃO. Um teste
que falha com «a impressão do espaço mudou» obriga quem mudou a dizer se subiu
a versão.
"""

from __future__ import annotations

from typing import Final

import pytest

from sports_intelligence.domain.features.definitions import (
    FeatureOutputType,
    FeatureScope,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.extraction.catalog import (
    FAMILIAS_MOVEIS,
    MATCH_STATE_RAW_V1_NAME,
    FeatureSide,
    RollingFamily,
    RollingFeatureSpec,
    StateFeatureSpec,
    match_state_raw_space_v1,
    production_feature_catalog,
    production_feature_registry,
    rolling_definition,
)
from sports_intelligence.domain.features.extraction.windows import (
    WINDOWS_V1,
    RollingWindow,
)
from sports_intelligence.domain.features.registry import FeatureDefinitionRegistry
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError

#: A impressão DOURADA do espaço de produção (§165). Ela muda quando qualquer
#: definição muda, quando a ORDEM muda, ou quando uma feature entra ou sai — e
#: qualquer um dos três exige subir a versão do espaço.
GOLDEN_SPACE: Final[str] = (
    "384038f2b11a754873451361e49e76d0f999ca653d6ac744078da30670545172"
)

#: As impressões douradas de definições REPRESENTATIVAS (§164): uma derivada
#: do estado, uma diferença, uma contagem móvel, uma soma decimal móvel e uma
#: móvel de diferença.
GOLDEN_FEATURES: Final[dict[str, str]] = {
    "score_home": "413a2fca3c04f0415bb8de68ad85f2a12a42cfb82e98839c416b2a1872dab2a0",
    "score_difference": "5d01474f15818690ff9e3fcb747f09defdf9adf649147ee69532d74aaff9dc21",
    "shots_home_5m": "aaf71c363ab4366517cc3613a819b2bf40b42709d78841dba75b0297625472b5",
    "xg_away_10m": "2c71af02fad344b8907e32ce7c584c873199107a716e935f162d35caa5d69ff6",
    "shots_on_target_diff_1m": (
        "2ad8ef7ce3a055e62cac489a452fec56a82a613fb9f90c020e9467d14229ac49"
    ),
    "corners_home_3m": "d1a7fe40f73090a074124a5238dc2ec679c14a62f9682d44baef27f2eb5b0e03",
}

#: Quantas definições o catálogo V1 declara (§140). Quinze de estado e sessenta
#: móveis — cinco famílias, três lados, quatro janelas.
TOTAL_V1: Final[int] = 75


class TestOCatalogo:
    def test_o_numero_de_definicoes_e_o_declarado(self) -> None:
        assert production_feature_catalog().size == TOTAL_V1

    def test_quinze_vem_do_estado_e_sessenta_das_janelas(self) -> None:
        specs = production_feature_catalog().specs
        do_estado = [s for s in specs if isinstance(s, StateFeatureSpec)]
        moveis = [s for s in specs if isinstance(s, RollingFeatureSpec)]
        assert len(do_estado) == 15
        assert len(moveis) == len(FAMILIAS_MOVEIS) * 3 * len(WINDOWS_V1) == 60

    def test_toda_definicao_declara_unidade(self) -> None:
        """§66 — a unidade nunca fica implícita."""
        sem_unidade = [
            d.key for d in production_feature_catalog().definitions if not d.unit
        ]
        assert sem_unidade == []

    def test_toda_definicao_e_intra_jogo_causal(self) -> None:
        """§11 — o espaço promete ser comparável ao vivo, e cumpre."""
        classes = {
            d.temporal_class for d in production_feature_catalog().definitions
        }
        assert classes == {FeatureTemporalClass.INTRA_MATCH_CAUSAL}

    def test_nenhuma_definicao_declara_normalizador(self) -> None:
        """§11, §100 — o espaço é CRU; nada aqui é normalizado."""
        com_normalizador = [
            d.key
            for d in production_feature_catalog().definitions
            if d.normalizer_key is not None
        ]
        assert com_normalizador == []

    def test_o_escopo_segue_o_lado(self) -> None:
        catalogo = production_feature_catalog()
        assert catalogo.spec_of("shots_home_5m").definition.scope is FeatureScope.HOME_TEAM
        assert catalogo.spec_of("shots_away_5m").definition.scope is FeatureScope.AWAY_TEAM
        assert catalogo.spec_of("shots_diff_5m").definition.scope is FeatureScope.MATCH

    def test_o_xg_e_decimal_e_as_contagens_sao_inteiras(self) -> None:
        catalogo = production_feature_catalog()
        assert catalogo.spec_of("xg_home_5m").definition.output_type is FeatureOutputType.FLOAT
        assert (
            catalogo.spec_of("shots_home_5m").definition.output_type
            is FeatureOutputType.INTEGER
        )

    def test_o_catalogo_nao_tem_feature_de_passe_nem_de_evento_total(self) -> None:
        """§55, §56 — as duas ausências são decisões registradas."""
        chaves = {d.key for d in production_feature_catalog().definitions}
        proibidas = {"passes_home_5m", "events_home_5m", "pressure_home_5m"}
        assert chaves & proibidas == set()

    def test_o_catalogo_nao_tem_feature_de_odds(self) -> None:
        """§98, §99 — dimensão fixa não pode depender de quantas casas existem."""
        chaves = {d.key for d in production_feature_catalog().definitions}
        assert not [k for k in chaves if "odds" in k]


class TestAsDependencias:
    def test_a_diferenca_declara_os_dois_lados(self) -> None:
        """§135, §136 — a dependência é explícita, e não inferida do nome."""
        catalogo = production_feature_catalog()
        assert catalogo.spec_of("score_difference").definition.depends_on_features == (
            "score_home",
            "score_away",
        )
        assert catalogo.spec_of("xg_diff_10m").definition.depends_on_features == (
            "xg_home_10m",
            "xg_away_10m",
        )

    def test_os_lados_nao_dependem_de_nada(self) -> None:
        catalogo = production_feature_catalog()
        for chave in ("shots_home_5m", "score_home", "players_on_field_away"):
            assert catalogo.spec_of(chave).definition.depends_on_features == ()

    def test_toda_dependencia_esta_no_catalogo(self) -> None:
        """§137 — o espaço recusaria uma dependência ausente; aqui é asserção."""
        chaves = {d.key for d in production_feature_catalog().definitions}
        for definicao in production_feature_catalog().definitions:
            assert set(definicao.depends_on_features) <= chaves


class TestORegistro:
    def test_o_registro_aceita_o_catalogo_inteiro(self) -> None:
        """§139 — únicas, resolvíveis, sem ciclo. O construtor prova tudo."""
        assert len(production_feature_registry()) == TOTAL_V1

    def test_toda_definicao_e_recuperavel_por_chave_e_versao(self) -> None:
        registro = production_feature_registry()
        for definicao in production_feature_catalog().definitions:
            assert registro.get(definicao.key, str(definicao.version)) == definicao

    def test_o_registro_recusa_a_mesma_chave_com_janela_diferente(self) -> None:
        """§71 — a pior ambiguidade: mesmo nome, mesma versão, outra semântica.

        Ela é construída de propósito com uma janela que não está em produção:
        o objetivo é provar que o REGISTRO detecta, e não que o catálogo está
        certo.
        """
        cinco = rolling_definition(
            family=RollingFamily.SHOT,
            side=FeatureSide.HOME,
            window=RollingWindow.of_minutes(5),
        )
        from dataclasses import replace

        impostor = replace(
            cinco,
            parameters={**cinco.parameters, "window_seconds": 600},
        )
        assert impostor.key == cinco.key
        assert impostor.fingerprint != cinco.fingerprint
        with pytest.raises(ValidationError, match="conteúdos diferentes"):
            FeatureDefinitionRegistry.of([cinco, impostor])

    def test_a_janela_entra_na_impressao(self) -> None:
        """§22, §70 — trocar 5 por 10 muda a identidade da feature."""
        impressoes = {
            rolling_definition(
                family=RollingFamily.SHOT, side=FeatureSide.HOME, window=janela
            ).fingerprint
            for janela in WINDOWS_V1
        }
        assert len(impressoes) == len(WINDOWS_V1)

    def test_o_lado_entra_na_impressao(self) -> None:
        impressoes = {
            rolling_definition(
                family=RollingFamily.SHOT,
                side=lado,
                window=RollingWindow.of_minutes(5),
            ).fingerprint
            for lado in FeatureSide
        }
        assert len(impressoes) == 3

    def test_a_familia_entra_na_impressao(self) -> None:
        impressoes = {
            rolling_definition(
                family=familia,
                side=FeatureSide.HOME,
                window=RollingWindow.of_minutes(5),
            ).fingerprint
            for familia in FAMILIAS_MOVEIS
        }
        assert len(impressoes) == len(FAMILIAS_MOVEIS)


class TestOEspaco:
    def test_o_espaco_tem_nome_e_versao_de_producao(self) -> None:
        espaco = match_state_raw_space_v1()
        assert espaco.name == MATCH_STATE_RAW_V1_NAME
        assert str(espaco.version) == "v1.0"
        assert espaco.size == TOTAL_V1

    def test_o_espaco_e_comparavel_ao_vivo_e_causal(self) -> None:
        espaco = match_state_raw_space_v1()
        assert espaco.live_comparable
        assert espaco.temporal_mode is TemporalMode.AS_KNOWN

    def test_o_espaco_declara_o_que_exige_do_corpus(self) -> None:
        """§57 do PR-05.1 — a incompatibilidade aparece antes do cálculo."""
        espaco = match_state_raw_space_v1()
        assert set(espaco.requirement.families) == {
            CoverageFamily.EVENT,
            CoverageFamily.LINEUP,
        }
        with pytest.raises(ValidationError, match="EVENT"):
            espaco.assert_compatible_with(frozenset({CoverageFamily.MATCH}))

    def test_a_ordem_e_a_declarada_e_nao_a_alfabetica(self) -> None:
        """§74, §75 — a ordem é contrato, e não consequência da grafia."""
        chaves = match_state_raw_space_v1().keys
        assert chaves[:3] == ("clock_period_order", "clock_minute", "clock_stoppage")
        assert chaves[3:6] == ("score_home", "score_away", "score_difference")
        assert chaves[15] == "shots_home_1m"
        assert chaves[-1] == "corners_diff_10m"
        assert list(chaves) != sorted(chaves)

    def test_as_janelas_aparecem_agrupadas_e_em_ordem_crescente(self) -> None:
        chaves = match_state_raw_space_v1().keys
        posicoes = [
            next(i for i, k in enumerate(chaves) if k.endswith(f"_{j.label}"))
            for j in WINDOWS_V1
        ]
        assert posicoes == sorted(posicoes)

    def test_a_ordem_muda_a_impressao_do_espaco(self) -> None:
        """§55 do PR-05.1 — a ordem É conteúdo."""
        from dataclasses import replace

        espaco = match_state_raw_space_v1()
        trocado = replace(espaco, features=tuple(reversed(espaco.features)))
        assert trocado.fingerprint != espaco.fingerprint


class TestOsDourados:
    def test_a_impressao_do_espaco_e_a_dourada(self) -> None:
        """§165 — mudar isto exige decidir, e não acontecer."""
        assert match_state_raw_space_v1().fingerprint == GOLDEN_SPACE

    @pytest.mark.parametrize(("chave", "esperada"), sorted(GOLDEN_FEATURES.items()))
    def test_as_impressoes_representativas_sao_as_douradas(
        self, chave: str, esperada: str
    ) -> None:
        assert production_feature_catalog().spec_of(chave).definition.fingerprint == esperada

    def test_a_impressao_e_estavel_entre_construcoes(self) -> None:
        assert match_state_raw_space_v1().fingerprint == match_state_raw_space_v1().fingerprint
