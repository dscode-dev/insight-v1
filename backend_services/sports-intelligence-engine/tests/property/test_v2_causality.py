"""As INVARIANTES do PR-05.4 — o gate do §164 ao §176 e do §214 ao §219.

    §214  Context(M)   = f(partidas da MESMA competição, kickoff < kickoff(M))
    §215  Market_t     = f(cotações elegíveis <= t)
    §216  populações de competições diferentes são disjuntas
    §217  mesma população + mesma declaração + mesmo corte ⇒ mesmo artefato
    §218  normalizar NÃO muta o valor cru
    §219  MATCH_STATE_RAW_V1 é o mesmo antes e depois

A DIFERENÇA ENTRE ESTES E OS DE UNIDADE. Os de unidade conferem números contra
uma tabela; estes provam propriedades sobre CONJUNTOS de entrada: «acrescentar
QUALQUER partida posterior não muda nada», «trocar o resultado da anterior não
muda nada». A segunda forma é a que pega o vazamento que ninguém pensou em
testar.
"""

from __future__ import annotations

import itertools
from datetime import timedelta
from decimal import Decimal
from typing import Final

import pytest

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
    production_feature_catalog,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    V1_SIZE,
    extended_feature_catalog,
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.fitting.fitter import RobustNormalizerFitter
from sports_intelligence.domain.features.fitting.population import FeaturePopulation
from sports_intelligence.domain.features.fitting.transformer import (
    RobustNormalizerTransformer,
)
from sports_intelligence.domain.features.normalization import DEFAULT_V1_NORMALIZER
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import corte
from tests.support.snapshot_fixtures import extrair
from tests.support.v2_fixtures import (
    COMPETICAO,
    KICKOFF_A,
    KICKOFF_ATUAL,
    KICKOFF_B,
    KICKOFF_C,
    MATCH_A,
    MATCH_B,
    MATCH_C,
    contexto_de_partida,
    cotacao,
    entrada_v2,
    extrair_v2,
    observacao,
    odds_do_cenario,
    populacao,
    valores_de_zero_a,
)
from tests.unit.test_feature_catalog import GOLDEN_SPACE

pytestmark = pytest.mark.property

#: Quantas partidas posteriores o sentinela do contexto tenta injetar.
SENTINELAS: Final[int] = 200


def valores(snapshot: FeatureSnapshot, chaves: tuple[str, ...]) -> dict[str, float | None]:
    return {k: snapshot.value_of(k).numeric for k in chaves}


CHAVES_DE_CONTEXTO: Final[tuple[str, ...]] = tuple(
    k for k in match_state_raw_space_v2().keys if k.startswith("ctx_")
)
CHAVES_DE_MERCADO: Final[tuple[str, ...]] = tuple(
    k for k in match_state_raw_space_v2().keys if k.startswith("market_")
)


# ------------------------------------------------------------------ §214 --


class TestOContextoEcausal:
    """`Context(M) = f(anteriores da mesma competição)`."""

    def test_partidas_posteriores_nao_entram_no_contexto(self) -> None:
        """§164 — o tipo RECUSA, e a recusa é a prova.

        Uma partida posterior ao apito não é filtrada em silêncio: ela é erro
        de quem montou o contexto. Filtrar produziria um contexto plausível de
        um calendário que não existia.
        """
        from sports_intelligence.domain.shared.errors import ValidationError

        posterior = KICKOFF_ATUAL + timedelta(days=1)
        with pytest.raises(ValidationError, match="depois do próprio"):
            contexto_de_partida(
                casa=((KICKOFF_C, MATCH_C), (posterior, MATCH_A)),
            )

    def test_o_resultado_da_partida_atual_nao_muda_o_contexto(self) -> None:
        """§165."""
        sem = extrair_v2(entrada_v2(result=None))
        com = extrair_v2(entrada_v2(result=MatchResult(regular_time=Score(home=9, away=0))))
        assert valores(com, CHAVES_DE_CONTEXTO) == valores(sem, CHAVES_DE_CONTEXTO)

    def test_o_contexto_e_o_mesmo_em_todos_os_cortes(self) -> None:
        """§159, §22 — ele descreve o que havia ANTES do apito."""
        cortes = [
            corte(10, periodo=Period.FIRST_HALF, conhecimento=10),
            corte(30, periodo=Period.FIRST_HALF, conhecimento=30),
            corte(63, conhecimento=63),
            corte(80, conhecimento=80),
        ]
        referencia = valores(extrair_v2(as_of=cortes[0]), CHAVES_DE_CONTEXTO)
        for alvo in cortes[1:]:
            assert valores(extrair_v2(as_of=alvo), CHAVES_DE_CONTEXTO) == referencia

    def test_o_valor_do_resultado_anterior_nao_muda_o_contexto(self) -> None:
        """§166 — medimos CALENDÁRIO, e não desempenho.

        O contexto recebe apenas `(instante, id)` da partida anterior: o placar
        dela não chega ao domínio. Trocar `1-0` por `5-0` no corpus não teria
        por onde mudar a feature — e o TIPO é a prova, porque ele não carrega
        resultado nenhum.
        """
        from sports_intelligence.domain.features.prematch.models import PriorMatchRef

        campos = set(PriorMatchRef.__dataclass_fields__)
        assert campos == {"kickoff", "match_id"}

    def test_uma_partida_de_outra_competicao_nao_muda_nada(self) -> None:
        """§168 — o escopo é local, e a leitura já filtra.

        O contexto do domínio só recebe partidas da competição; uma de outra
        simplesmente não chega. O que se prova aqui é que a política declara
        isso, e que o escopo cruzado é recusado.
        """
        from sports_intelligence.domain.features.prematch.policy import (
            ContextScope,
            HistoricalContextPolicy,
        )
        from sports_intelligence.domain.shared.errors import ValidationError

        assert (
            extended_feature_catalog()
            .spec_of("ctx_same_comp_matches_14d_home")
            .definition.parameters["context_scope"]
            == ContextScope.SAME_COMPETITION.value
        )
        with pytest.raises(ValidationError):
            HistoricalContextPolicy(scope=ContextScope.ALL_COMPETITIONS)

    def test_remover_a_anterior_da_versao_muda_o_contexto(self) -> None:
        """§167 — a pertinência à versão decide o que existe."""
        com = extrair_v2()
        sem = extrair_v2(
            contexto=contexto_de_partida(casa=((KICKOFF_A, MATCH_A), (KICKOFF_B, MATCH_B)))
        )
        assert (
            com.value_of("ctx_same_comp_prev_gap_hours_home").numeric
            != sem.value_of("ctx_same_comp_prev_gap_hours_home").numeric
        )
        assert com.value_of("ctx_same_comp_matches_14d_home").numeric == 1
        assert sem.value_of("ctx_same_comp_matches_14d_home").numeric == 0

    @pytest.mark.parametrize("dias", [1, 7, 14, 30, 90])
    def test_a_ordem_das_anteriores_nao_muda_o_resultado(self, dias: int) -> None:
        anteriores = tuple(
            (KICKOFF_ATUAL - timedelta(days=d), MatchId.derive("pr054-ordem", str(d)))
            for d in (dias, dias + 3, dias + 9)
        )
        direta = extrair_v2(contexto=contexto_de_partida(casa=anteriores))
        invertida = extrair_v2(contexto=contexto_de_partida(casa=tuple(reversed(anteriores))))
        assert valores(invertida, CHAVES_DE_CONTEXTO) == valores(direta, CHAVES_DE_CONTEXTO)


# ------------------------------------------------------------------ §215 --


class TestOMercadoEcausal:
    """`Market_t = f(cotações elegíveis ≤ t)`."""

    def test_cotacoes_futuras_nao_mudam_o_mercado(self) -> None:
        """§174 — a cotação vista aos 80 não existe num snapshot de 63."""
        alvo = corte(63, conhecimento=63)
        so_passado = extrair_v2(entrada_v2(odds=odds_do_cenario(minuto=-60.0)), as_of=alvo)
        com_futuro = extrair_v2(
            entrada_v2(
                odds=(
                    *odds_do_cenario(minuto=-60.0),
                    *odds_do_cenario(casas_1x2=("9.99",), com_btts=False, minuto=80.0),
                )
            ),
            as_of=alvo,
        )
        assert valores(com_futuro, CHAVES_DE_MERCADO) == valores(so_passado, CHAVES_DE_MERCADO)

    def test_a_ordem_das_casas_nao_muda_nada(self) -> None:
        """§169, §170 — nem valor, nem digest de procedência."""
        direta = extrair_v2(entrada_v2(odds=odds_do_cenario()))
        invertida = extrair_v2(entrada_v2(odds=tuple(reversed(odds_do_cenario()))))
        assert valores(invertida, CHAVES_DE_MERCADO) == valores(direta, CHAVES_DE_MERCADO)
        for chave in CHAVES_DE_MERCADO:
            assert (
                invertida.value_of(chave).provenance.contribution_digest
                == direta.value_of(chave).provenance.contribution_digest
            )

    def test_toda_permutacao_das_casas_da_o_mesmo_resultado(self) -> None:
        base = odds_do_cenario(com_btts=False)
        impressoes = {
            tuple(extrair_v2(entrada_v2(odds=ordem)).value_of(k).numeric for k in CHAVES_DE_MERCADO)
            for ordem in itertools.permutations(base)
        }
        assert len(impressoes) == 1

    def test_uma_casa_da_mediana_e_nao_da_dispersao(self) -> None:
        """§171."""
        snapshot = extrair_v2(entrada_v2(odds=odds_do_cenario(casas_1x2=("2.00",), com_btts=False)))
        assert snapshot.value_of("market_1x2_home_median").numeric == 2.0
        assert snapshot.value_of("market_1x2_home_support").numeric == 1
        assert not snapshot.value_of("market_1x2_home_iqr").is_available

    def test_quatro_casas_iguais_dao_dispersao_zero(self) -> None:
        """§172 — aqui o zero é OBSERVADO."""
        snapshot = extrair_v2(
            entrada_v2(
                odds=odds_do_cenario(casas_1x2=("2.00", "2.00", "2.00", "2.00"), com_btts=False)
            )
        )
        assert snapshot.value_of("market_1x2_home_median").numeric == 2.0
        assert snapshot.value_of("market_1x2_home_iqr").numeric == 0.0
        assert snapshot.value_of("market_1x2_home_support").numeric == 4

    def test_sem_mercado_a_disponibilidade_e_correta(self) -> None:
        """§173, §66."""
        from tests.support.snapshot_fixtures import TODAS_AS_FAMILIAS

        snapshot = extrair_v2(
            entrada_v2(families=TODAS_AS_FAMILIAS, odds=()),
            families=TODAS_AS_FAMILIAS,
        )
        for chave in CHAVES_DE_MERCADO:
            computada = snapshot.value_of(chave)
            assert computada.availability is FeatureAvailability.NOT_DECLARED
            assert computada.numeric is None

    def test_o_mercado_muda_com_o_corte(self) -> None:
        """§160, §161, §162 — ao contrário do contexto, ele evolui.

        A CASA2 REVISA O PREÇO aos 20 minutos. Ela é uma das duas do MEIO da
        amostra de quatro — e isso importa: com `n = 4` a mediana é a média do
        segundo com o terceiro, então revisar uma das PONTAS mudaria o IQR e
        deixaria a mediana onde estava. O cenário mexe onde a mediana sente.

            pré-jogo   1.80  1.90  2.00  2.10   →  mediana 1.95
            aos 20'    1.20  1.80  2.00  2.10   →  mediana 1.90
        """
        cotacoes = (
            *odds_do_cenario(minuto=-60.0, com_btts=False),
            cotacao("CASA2", "1.20", minuto=20.0),
        )
        cedo = extrair_v2(
            entrada_v2(odds=cotacoes),
            as_of=corte(10, periodo=Period.FIRST_HALF, conhecimento=10),
        )
        tarde = extrair_v2(entrada_v2(odds=cotacoes), as_of=corte(63, conhecimento=63))
        assert cedo.value_of("market_1x2_home_support").numeric == 4
        assert tarde.value_of("market_1x2_home_support").numeric == 4
        assert cedo.value_of("market_1x2_home_median").numeric == 1.95
        assert tarde.value_of("market_1x2_home_median").numeric == 1.90

    def test_a_revisao_de_uma_ponta_move_a_dispersao_e_nao_o_nivel(self) -> None:
        """A recíproca do teste acima — e a razão de ele mexer no meio."""
        cotacoes = (
            *odds_do_cenario(minuto=-60.0, com_btts=False),
            cotacao("CASA1", "1.10", minuto=20.0),
        )
        cedo = extrair_v2(
            entrada_v2(odds=cotacoes),
            as_of=corte(10, periodo=Period.FIRST_HALF, conhecimento=10),
        )
        tarde = extrair_v2(entrada_v2(odds=cotacoes), as_of=corte(63, conhecimento=63))
        assert (
            cedo.value_of("market_1x2_home_median").numeric
            == tarde.value_of("market_1x2_home_median").numeric
        )
        assert (
            cedo.value_of("market_1x2_home_iqr").numeric
            != tarde.value_of("market_1x2_home_iqr").numeric
        )


# ------------------------------------------------- §216, §217, §218 --


class TestONormalizador:
    def test_populacoes_de_competicoes_diferentes_sao_disjuntas(self) -> None:
        """§216, §110 — a competição é do CONJUNTO, e não de cada membro."""
        outra = CompetitionId.derive("pr054", "outra-liga")
        premier = populacao(valores_de_zero_a(30))
        laliga = FeaturePopulation.of(
            outra, "shots_home_5m", [observacao(n, str(n)) for n in range(30)]
        )
        assert premier.competition_id != laliga.competition_id
        assert premier.digest != laliga.digest

    def test_o_artefato_da_outra_liga_nao_normaliza(self) -> None:
        """§110, §132."""
        from sports_intelligence.domain.shared.errors import ValidationError

        artefato = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER).fit(
            populacao(valores_de_zero_a(30)),
            feature=production_feature_catalog().spec_of("shots_home_5m").definition,
            source_corpus_fingerprint="a" * 64,
            source_space_fingerprint="b" * 64,
        )
        with pytest.raises(ValidationError, match="competição"):
            RobustNormalizerTransformer(artifact=artefato).transform(
                feature_key="shots_home_5m",
                feature_fingerprint=artefato.feature_fingerprint,
                competition_id=CompetitionId.derive("pr054", "outra-liga"),
                raw=Decimal(1),
            )

    def test_mesma_populacao_mesmo_artefato(self) -> None:
        """§217."""
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        definicao = production_feature_catalog().spec_of("shots_home_5m").definition
        impressoes = {
            fitter.fit(
                populacao(valores_de_zero_a(30)),
                feature=definicao,
                source_corpus_fingerprint="a" * 64,
                source_space_fingerprint="b" * 64,
            ).fingerprint
            for _ in range(5)
        }
        assert len(impressoes) == 1

    @pytest.mark.parametrize("giro", [1, 7, 13, 29])
    def test_a_ordem_da_populacao_nao_muda_o_artefato(self, giro: int) -> None:
        """§106, §217."""
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        definicao = production_feature_catalog().spec_of("shots_home_5m").definition
        observacoes = [observacao(n, str(n)) for n in range(30)]
        girada = [*observacoes[giro:], *observacoes[:giro]]
        a = fitter.fit(
            FeaturePopulation.of(COMPETICAO, "shots_home_5m", observacoes),
            feature=definicao,
            source_corpus_fingerprint="a" * 64,
            source_space_fingerprint="b" * 64,
        )
        b = fitter.fit(
            FeaturePopulation.of(COMPETICAO, "shots_home_5m", girada),
            feature=definicao,
            source_corpus_fingerprint="a" * 64,
            source_space_fingerprint="b" * 64,
        )
        assert a.fingerprint == b.fingerprint

    def test_normalizar_nao_muta_o_valor_cru(self) -> None:
        """§218 — o cru sobrevive, e viaja junto."""
        artefato = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER).fit(
            populacao(valores_de_zero_a(30)),
            feature=production_feature_catalog().spec_of("shots_home_5m").definition,
            source_corpus_fingerprint="a" * 64,
            source_space_fingerprint="b" * 64,
        )
        cru = Decimal("7")
        resultado = RobustNormalizerTransformer(artifact=artefato).transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=cru,
        )
        assert cru == Decimal("7")
        assert resultado.raw == cru
        assert resultado.scaled != resultado.raw

    def test_o_snapshot_cru_nao_muda_por_existir_normalizador(self) -> None:
        """§94, §152 — o espaço continua cru."""
        antes = extrair_v2().fingerprint
        artefato = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER).fit(
            populacao(valores_de_zero_a(30)),
            feature=production_feature_catalog().spec_of("shots_home_5m").definition,
            source_corpus_fingerprint="a" * 64,
            source_space_fingerprint="b" * 64,
        )
        RobustNormalizerTransformer(artifact=artefato).transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal(3),
        )
        assert extrair_v2().fingerprint == antes


# ------------------------------------------------------------------ §219 --


class TestAV1EImutavel:
    def test_a_impressao_dourada_da_v1_continua(self) -> None:
        """§175, §219."""
        assert match_state_raw_space_v1().fingerprint == GOLDEN_SPACE

    def test_o_snapshot_v1_continua_reproduzivel(self) -> None:
        assert extrair().fingerprint == extrair().fingerprint

    def test_as_setenta_e_cinco_da_v2_sao_as_da_v1(self) -> None:
        """§157, §158 — os valores herdados são os MESMOS."""
        v1 = extrair(
            entrada_v2(),
        )
        v2 = extrair_v2(entrada_v2(), as_of=corte())
        for herdada in v2.features[:V1_SIZE]:
            correspondente = v1.value_of(herdada.definition_key)
            assert herdada.numeric == correspondente.numeric
            assert herdada.availability == correspondente.availability
            assert (
                herdada.provenance.contribution_digest
                == correspondente.provenance.contribution_digest
            )

    def test_as_impressoes_dos_snapshots_diferem_porque_o_espaco_difere(self) -> None:
        """§158 — natural, e não defeito."""
        v1 = extrair(entrada_v2())
        v2 = extrair_v2(entrada_v2(), as_of=corte())
        assert v1.fingerprint != v2.fingerprint
        assert v1.space.fingerprint != v2.space.fingerprint


# ------------------------------------------------------------------ §176 --


class TestAReprodutibilidadeDaV2:
    def test_dez_extracoes_dao_a_mesma_impressao(self) -> None:
        impressoes = {extrair_v2().fingerprint for _ in range(10)}
        assert len(impressoes) == 1

    def test_corte_diferente_muda_a_impressao(self) -> None:
        assert (
            extrair_v2(as_of=corte(30, periodo=Period.FIRST_HALF)).fingerprint
            != extrair_v2().fingerprint
        )

    def test_contexto_diferente_muda_a_impressao(self) -> None:
        assert (
            extrair_v2(contexto=contexto_de_partida(casa=())).fingerprint
            != extrair_v2().fingerprint
        )

    def test_mercado_diferente_muda_a_impressao(self) -> None:
        assert (
            extrair_v2(
                entrada_v2(odds=odds_do_cenario(casas_1x2=("3.00", "3.10", "3.20", "3.30")))
            ).fingerprint
            != extrair_v2().fingerprint
        )
