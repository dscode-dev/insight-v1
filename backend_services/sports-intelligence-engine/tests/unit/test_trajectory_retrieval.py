"""Os goldens da trajetória — a janela, o deslocamento e a distância.

OS DOIS TESTES CENTRAIS DO PR ESTÃO EM `TestOQuePRExisteParaProvar`, e o §260
diz por extenso que o PR só fecha se os dois passarem:

    mesmo estado atual + movimento OPOSTO   →  a trajetória separa
    nível diferente   + movimento IGUAL     →  a trajetória reconhece

O RESTO SUSTENTA OS DOIS. A janela impede que o lookback atravesse o intervalo
ou olhe para o futuro; o deslocamento impede que a representação vire uma
concatenação de níveis; a cobertura impede que um horizonte solto passe por
evidência.

`m = 5`, `|H| = 3`, `n = 15`. Os pisos com esse `n`:

    células     `s >= 8`  e  `5s >= 45`  ->  `s >= 9`
    horizontes  `>= 2` evidenciais, e um horizonte precisa de `>= 4` eixos
"""

from __future__ import annotations

import math

import pytest

from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.retrieval.availability import (
    AvailabilityInconsistencyError,
)
from sports_intelligence.domain.retrieval.availability_distance import (
    MISSING_AXIS_PENALTY,
)
from sports_intelligence.domain.retrieval.coverage import ceil_div
from sports_intelligence.domain.retrieval.distance import FLOAT_SEMANTICS_V1
from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    DEFAULT_RETRIEVAL_PROFILE,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    DISPLACEMENT_REPRESENTATION_V1,
    TrajectoryRepresentation,
    build_representation,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    EFFECTIVE_FLOOR_ALGORITHM_V1,
    INSUFFICIENT_PER_HORIZON_COVERAGE,
    INSUFFICIENT_SHARED_HORIZONS,
    INSUFFICIENT_SHARED_TRAJECTORY_CELLS,
    MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1,
    HorizonCoverage,
    TrajectoryCoverageAssessment,
    TrajectoryCoveragePolicy,
    TrajectoryProfileInsufficientAxesError,
)
from sports_intelligence.domain.retrieval.trajectory_distance import (
    MISSING_CELL_PENALTY,
    TrajectoryDistanceDefinition,
    TrajectoryDistanceMethod,
)
from sports_intelligence.domain.retrieval.trajectory_evidence import (
    TrajectoryDistanceContribution,
    trajectory_evidence_summary,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1,
    TrajectoryRepresentationMethod,
    TrajectoryRetrievalProfile,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    DEFAULT_TRAJECTORY_WINDOW,
    HORIZONS,
    SAME_PERIOD_FIXED_HORIZON_1_3_5_V1,
    PeriodCrossingPolicy,
    SlotStatus,
    TrajectoryDirection,
    TrajectoryNotApplicableError,
    TrajectorySourceRowMissingError,
    TrajectoryWindowPolicy,
    UnsupportedTrajectoryGridError,
    period_first_minute,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from tests.support.availability_fixtures import CINCO_EIXOS, perfil_ciente
from tests.support.retrieval_fixtures import DISPONIVEL, SEM_ESCALA, perfil
from tests.support.trajectory_fixtures import (
    ANCORA,
    ANCORA_47,
    ANCORA_49,
    GRADE,
    com_horizontes,
    curva,
    distancia_de_trajetoria,
    linha,
    perfil_de_trajetoria,
    representacao_de_trajetoria,
    trajetoria,
)

PERFIL = perfil_de_trajetoria()
DISTANCIA = distancia_de_trajetoria(PERFIL)


def _cheio(valor: float) -> dict[str, float | None]:
    return dict.fromkeys(CINCO_EIXOS, valor)


def _parcial(n: int, valor: float) -> dict[str, float | None]:
    """Os `n` primeiros eixos com valor; o resto AUSENTE."""
    return dict.fromkeys(CINCO_EIXOS[:n], valor)


# ============================================ o que o PR existe para provar ==


class TestOQuePRExisteParaProvar:
    """§68, §69, §149, §150, §239, §260 — os dois goldens centrais."""

    def test_mesmo_estado_atual_e_movimento_OPOSTO_a_trajetoria_separa(self) -> None:
        """§68, §149 — o teste que justifica o PR inteiro.

        Query e os dois candidatos estão em `0` AGORA — o estado empata os
        três. A query e `A` vieram de `-2`; `B` veio de `+2`.

            Δ_query =  (0,5 · 1,5 · 2,0)
            Δ_A     =  (0,5 · 1,5 · 2,0)      mesma direção
            Δ_B     = (-0,5 · -1,5 · -2,0)    direção oposta

        A conta de `B`, célula a célula: `1 + 9 + 16 = 26` por eixo, vezes
        cinco eixos, dá `130`; sobre `n = 15`, `8,667`.
        """
        query = representacao_de_trajetoria(**curva(de=-2.0, para=0.0))
        a = representacao_de_trajetoria(match="ref-a", **curva(de=-2.0, para=0.0))
        b = representacao_de_trajetoria(match="ref-b", **curva(de=2.0, para=0.0))

        # O ESTADO ATUAL É O MESMO NOS TRÊS — é isso que faz o teste valer.
        assert query.trajectory.anchor_position == a.trajectory.anchor_position
        for representacao in (query, a, b):
            assert representacao.usable_count == 15

        assert DISTANCIA.evaluate(query, a).value == 0.0
        assert DISTANCIA.evaluate(query, b).value == 130 / 15
        assert DISTANCIA.evaluate(query, b).value > DISTANCIA.evaluate(query, a).value

    def test_e_A_rankeia_antes_de_B(self) -> None:
        """A separação chega até o ranking, e não só até o número."""
        from sports_intelligence.domain.features.dataset.rows import (
            HistoricalFeatureSnapshotKey,
        )
        from tests.support.availability_fixtures import consulta_ciente, pedido_ciente
        from tests.support.trajectory_fixtures import (
            candidato_de_trajetoria,
            recuperador_de_trajetoria,
        )

        chave = HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=ANCORA.minute)
        resultado = recuperador_de_trajetoria(profile=PERFIL).retrieve(
            query=pedido_ciente(k=3, key=chave),
            snapshot=consulta_ciente(grid_index=ANCORA.minute, position=ANCORA),
            query_representation=representacao_de_trajetoria(**curva(de=-2.0, para=0.0)),
            candidates=[
                candidato_de_trajetoria(match="ref-b", **curva(de=2.0, para=0.0)),
                candidato_de_trajetoria(match="ref-a", **curva(de=-2.0, para=0.0)),
            ],
            reference_content_fingerprint="r" * 64,
        )
        assert [v.anchor_key.match_key for v in resultado.neighbors] == ["ref-a", "ref-b"]
        assert resultado.neighbors[0].trajectory_dissimilarity == 0.0

    def test_nivel_diferente_e_movimento_IGUAL_a_trajetoria_reconhece(self) -> None:
        """§69, §150 — e a igualdade é EXATA, e não aproximada.

        Uma sobe de `0` a `2`; a outra, de `8` a `10`. O estado as separa por
        oito unidades em todo eixo; a trajetória as reconhece como a MESMA
        forma.
        """
        uma = representacao_de_trajetoria(**curva(de=0.0, para=2.0))
        outra = representacao_de_trajetoria(match="ref-c", **curva(de=8.0, para=10.0))

        assert DISTANCIA.evaluate(uma, outra).value == 0.0
        # E OS NÍVEIS SÃO MESMO DIFERENTES — se não fossem, o teste seria vazio.
        assert uma.trajectory.anchor_row_digest != outra.trajectory.anchor_row_digest


# ============================================ a janela ==


class TestAJanelaNaoAtravessaOPeriodo:
    """§16, §17, §153 — a decisão que o módulo existe para impor."""

    def test_o_segundo_tempo_comeca_no_46(self) -> None:
        """Os limites vêm da GRADE, e não de constantes locais."""
        assert period_first_minute(Period.FIRST_HALF, GRADE) == 1
        assert period_first_minute(Period.SECOND_HALF, GRADE) == 46
        assert period_first_minute(Period.EXTRA_TIME_FIRST, GRADE) == 91

    def test_no_minuto_51_os_tres_horizontes_cabem(self) -> None:
        """§22, §85."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA, grid=GRADE)
        assert [s.status for s in slots] == [SlotStatus.AVAILABLE] * 3
        assert [s.target.minute for s in slots if s.target] == [50, 48, 46]

    def test_no_minuto_49_o_de_cinco_cai_no_PRIMEIRO_TEMPO(self) -> None:
        """§17, §84, §153 — o golden do intervalo."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA_49, grid=GRADE)
        assert [s.status for s in slots] == [
            SlotStatus.AVAILABLE,
            SlotStatus.AVAILABLE,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
        ]
        assert [s.target.minute for s in slots if s.target] == [48, 46]
        # E O MINUTO 44 NÃO É PEDIDO — nem como alvo, nem por acidente.
        assert all(s.target is None or s.target.minute >= 46 for s in slots)

    def test_no_minuto_47_so_o_de_um_minuto_existe(self) -> None:
        """§83."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA_47, grid=GRADE)
        assert [s.status for s in slots] == [
            SlotStatus.AVAILABLE,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
        ]

    def test_no_minuto_4_do_primeiro_tempo(self) -> None:
        """§21 — `t-1` e `t-3` cabem, `t-5` não."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(
            GridTimePoint.of(Period.FIRST_HALF, 4), grid=GRADE
        )
        assert [s.status for s in slots] == [
            SlotStatus.AVAILABLE,
            SlotStatus.AVAILABLE,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
        ]
        assert [s.target.minute for s in slots if s.target] == [3, 1]

    def test_a_prorrogacao_tambem_e_period_local(self) -> None:
        """§23 — e o começo dela vem da grade, e não do placar."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(
            GridTimePoint.of(Period.EXTRA_TIME_FIRST, 93), grid=GRADE
        )
        assert [s.status for s in slots] == [
            SlotStatus.AVAILABLE,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
            SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
        ]
        assert [s.target.minute for s in slots if s.target] == [92]

    def test_o_slot_indisponivel_NAO_carrega_alvo(self) -> None:
        """Um alvo num slot ausente é o convite para alguém lê-lo."""
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA_47, grid=GRADE)
        assert all(s.target is None for s in slots if not s.status.is_available)


class TestAJanelaNaoOlhaParaOFuturo:
    """§213, §254 — não há como pedir `t + h`."""

    def test_o_catalogo_de_direcao_tem_um_membro(self) -> None:
        assert {d.value for d in TrajectoryDirection} == {"BACKWARD"}

    def test_um_horizonte_negativo_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="FUTURO"):
            TrajectoryWindowPolicy(horizons=(-1, 3, 5))

    def test_um_horizonte_zero_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="própria âncora"):
            TrajectoryWindowPolicy(horizons=(0, 3, 5))

    def test_todo_alvo_e_ANTERIOR_a_ancora(self) -> None:
        for minuto in range(46, 91):
            ancora = GridTimePoint.of(Period.SECOND_HALF, minuto)
            for slot in DEFAULT_TRAJECTORY_WINDOW.resolve(ancora, grid=GRADE):
                assert slot.target is None or slot.target < ancora


class TestPreMatchEIntervaloNaoTemTrajetoria:
    """§24, §25, §155."""

    @pytest.mark.parametrize(
        "fase",
        [Period.PRE_MATCH, Period.HALF_TIME, Period.FULL_TIME, Period.PENALTY_SHOOTOUT],
    )
    def test_a_fase_sem_minuto_interno_nao_e_aplicavel(self, fase: Period) -> None:
        ancora = GridTimePoint.of(fase, 0)
        assert not DEFAULT_TRAJECTORY_WINDOW.is_applicable(ancora)
        slots = DEFAULT_TRAJECTORY_WINDOW.resolve(ancora, grid=GRADE)
        assert [s.status for s in slots] == [SlotStatus.NOT_APPLICABLE] * 3

    def test_e_a_recusa_tem_tipo_proprio(self) -> None:
        with pytest.raises(TrajectoryNotApplicableError) as erro:
            DEFAULT_TRAJECTORY_WINDOW.assert_applicable(GridTimePoint.of(Period.PRE_MATCH, 0))
        assert erro.value.reason == "TRAJECTORY_NOT_APPLICABLE"


class TestAGradeEhConferida:
    """§27, §28, §156 — uma grade de cinco cortes também tem minuto."""

    def test_a_grade_de_producao_e_suportada(self) -> None:
        assert DEFAULT_TRAJECTORY_WINDOW.supports(GRADE)

    def test_uma_grade_desconhecida_e_recusada(self) -> None:
        outra = SnapshotGridPolicy(name="GRADE_DE_CINCO_CORTES_V1")
        assert not DEFAULT_TRAJECTORY_WINDOW.supports(outra)
        with pytest.raises(UnsupportedTrajectoryGridError) as erro:
            DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA, grid=outra)
        assert erro.value.reason == "UNSUPPORTED_TRAJECTORY_GRID"

    def test_a_conferencia_vem_ANTES_da_aritmetica(self) -> None:
        """Uma grade incompatível não produz slot nenhum, nem inválido."""
        outra = SnapshotGridPolicy(name="OUTRA_V1")
        with pytest.raises(UnsupportedTrajectoryGridError):
            DEFAULT_TRAJECTORY_WINDOW.resolve(GridTimePoint.of(Period.PRE_MATCH, 0), grid=outra)


# ============================================ a montagem ==


class TestAMontagemDaTrajetoria:
    """§30, §41, §42, §157, §171."""

    def test_a_trajetoria_carrega_os_digestos_das_linhas(self) -> None:
        montada, _ = trajetoria(passado={h: _cheio(1.0) for h in HORIZONS})
        assert montada.available_horizon_count == 3
        assert all(s.source_row_digest for s in montada.available_slots)
        assert montada.horizons == (1, 3, 5)

    def test_a_linha_que_deveria_existir_e_nao_veio_PARA(self) -> None:
        """§30, §157 — corrupção, e não ausência de feature."""
        with pytest.raises(TrajectorySourceRowMissingError) as erro:
            trajetoria(passado={1: _cheio(1.0), 5: _cheio(1.0)})
        assert erro.value.reason == "TRAJECTORY_SOURCE_ROW_MISSING"
        assert erro.value.target.endswith("048")

    def test_o_slot_fora_do_periodo_nao_exige_linha(self) -> None:
        """A ausência ESTRUTURAL não é corrupção — e não para nada."""
        montada, _ = trajetoria(anchor=ANCORA_49, passado={1: _cheio(1.0), 3: _cheio(1.0)})
        assert montada.available_horizon_count == 2
        cinco = montada.slot_of(5)
        assert cinco is not None
        assert cinco.status is SlotStatus.OUTSIDE_PERIOD_LOOKBACK

    def test_a_ordem_das_linhas_nao_importa(self) -> None:
        """§171 — elas são indexadas por INSTANTE, que é a identidade."""
        uma, _linhas = trajetoria(passado={h: _cheio(float(h)) for h in HORIZONS})
        outra, _ = trajetoria(passado={h: _cheio(float(h)) for h in reversed(HORIZONS)})
        assert uma.fingerprint == outra.fingerprint

    def test_uma_linha_de_outra_partida_PARA(self) -> None:
        from sports_intelligence.domain.features.dataset.rows import (
            HistoricalFeatureSnapshotKey,
        )
        from sports_intelligence.domain.retrieval.trajectory import assemble_trajectory

        resolvidos = DEFAULT_TRAJECTORY_WINDOW.resolve(ANCORA, grid=GRADE)
        linhas = {
            s.target: linha(match="outra", position=s.target, valores=_cheio(1.0))
            for s in resolvidos
            if s.target is not None
        }
        with pytest.raises(ValidationError, match="cruzar partidas"):
            assemble_trajectory(
                policy=DEFAULT_TRAJECTORY_WINDOW,
                resolved=resolvidos,
                anchor_key=HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=51),
                match_key="eva-001",
                competition="PREMIER",
                anchor_position=ANCORA,
                anchor_row_digest="d",
                rows=linhas,
            )


# ============================================ o deslocamento ==


class TestODeslocamentoNaoEhConcatenacao:
    """§45, §46, §47, §66, §102."""

    def test_a_representacao_tem_n_igual_a_tres_m(self) -> None:
        """§54 — `n = |H| · m`, e ele NÃO encolhe."""
        assert PERFIL.axis_count == 5
        assert PERFIL.horizon_count == 3
        assert PERFIL.cell_count == 15
        assert representacao_de_trajetoria().cell_count == 15

    def test_o_horizonte_fora_do_periodo_mantem_as_celulas_no_denominador(self) -> None:
        """§75, §76 — a decisão que impede uma trajetória curta de parecer completa."""
        curta = representacao_de_trajetoria(
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(-1.0), 3: _cheio(-2.0)}),
        )
        assert curta.cell_count == 15
        assert curta.usable_count == 10
        assert curta.mask_text == "1" * 10 + "0" * 5

    def test_o_deslocamento_e_ancora_menos_lookback(self) -> None:
        representacao = representacao_de_trajetoria(
            **com_horizontes(
                agora=_cheio(5.0),
                horizontes={1: _cheio(4.0), 3: _cheio(2.0), 5: _cheio(1.0)},
            )
        )
        # ORDEM CANÔNICA: horizonte primeiro, eixo depois.
        assert representacao.displacements[0] == 1.0
        assert representacao.displacements[5] == 3.0
        assert representacao.displacements[10] == 4.0

    def test_somar_uma_constante_a_TODOS_os_extremos_nao_muda_nada(self) -> None:
        """§66, §161 — a prova de que isto mede MOVIMENTO."""
        base = com_horizontes(
            agora=_cheio(1.0), horizontes={1: _cheio(0.5), 3: _cheio(0.0), 5: _cheio(-1.0)}
        )
        deslocada = com_horizontes(
            agora=_cheio(9.0), horizontes={1: _cheio(8.5), 3: _cheio(8.0), 5: _cheio(7.0)}
        )
        assert (
            representacao_de_trajetoria(**base).displacements
            == representacao_de_trajetoria(**deslocada).displacements
        )

    def test_um_extremo_so_NAO_produz_meio_deslocamento(self) -> None:
        """§159 — e o eixo fica ausente, e não zero."""
        representacao = representacao_de_trajetoria(
            **com_horizontes(
                agora=_parcial(3, 1.0),
                horizontes={h: _cheio(0.0) for h in HORIZONS},
            )
        )
        # OS DOIS ÚLTIMOS EIXOS SÓ TÊM O EXTREMO PASSADO.
        assert representacao.mask[:5] == (True, True, True, False, False)
        assert representacao.displacements[3] is None

    def test_zero_fill_mudaria_o_resultado_e_NAO_acontece(self) -> None:
        """§102, §160 — o sentinela do preenchimento.

        O CENÁRIO É CONSTRUÍDO PARA QUE A FRAUDE SEJA VISÍVEL. A query não se
        moveu (`Δ = 0`). Se o extremo passado ausente do candidato virasse o
        valor da âncora dele, `Δ` sairia `0` e ele empataria com a query —
        estabilidade inventada.
        """
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        oco = representacao_de_trajetoria(
            match="ref-oco",
            **com_horizontes(
                agora=_cheio(3.0),
                horizontes={1: _cheio(3.0), 3: _parcial(0, 0.0), 5: _parcial(0, 0.0)},
            ),
        )
        # AS CÉLULAS AUSENTES NÃO VIRARAM `Δ = 0`: elas continuam ausentes.
        assert oco.usable_count == 5
        assert all(x is None for x in oco.displacements[5:])
        conta = DISTANCIA.evaluate(query, oco)
        # COM ZERO-FILL, `D_T` seria 10/15; sem ele, a penalidade cobra 10.
        assert conta.observed_sum == 0.0
        assert conta.missing_penalty_sum == 10.0
        assert conta.value == 10 / 15


# ============================================ a distância ==


class TestAContaTemporal:
    """§91 ao §101, §242."""

    def test_o_denominador_e_n_e_nunca_s(self) -> None:
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        parcial = representacao_de_trajetoria(
            match="ref-a",
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(0.0), 3: _cheio(0.0)}),
        )
        conta = DISTANCIA.evaluate(query, parcial)
        assert conta.shared_cells == 10
        assert conta.observed_sum == 0.0
        assert conta.missing_penalty_sum == 5.0
        # COM DENOMINADOR MÓVEL, ISTO SERIA `0/10 = 0`.
        assert conta.value == 5 / 15

    def test_a_penalidade_e_a_MESMA_do_PR_06_2(self) -> None:
        """§93, §94 — mesmo valor, mesma unidade."""
        assert MISSING_CELL_PENALTY == MISSING_AXIS_PENALTY == 1.0
        assert DISTANCIA.missing_penalty == 1.0

    def test_a_reversao_custa_o_dobro_ao_quadrado(self) -> None:
        """§162 — `(Δq - Δc)² = (2Δq)²` quando `Δc = -Δq`."""
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(2.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        invertido = representacao_de_trajetoria(
            match="ref-inv",
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(2.0) for h in HORIZONS}),
        )
        conta = DISTANCIA.evaluate(query, invertido)
        # Δq = +2, Δc = -2 em toda célula: (4)² = 16, vezes 15 células.
        assert conta.observed_sum == 16 * 15
        assert conta.value == 16.0

    def test_ambas_ausentes_continuam_custando(self) -> None:
        """§100 — dois desconhecidos não são movimento igual."""
        curta = com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(0.0), 3: _cheio(0.0)})
        uma = representacao_de_trajetoria(anchor=ANCORA_49, **curta)
        outra = representacao_de_trajetoria(match="ref-a", anchor=ANCORA_49, **curta)
        conta = DISTANCIA.evaluate(uma, outra)
        assert conta.missing_penalty_sum == 5.0
        assert conta.value == 5 / 15

    def test_a_evidencia_nova_substitui_a_incerteza(self) -> None:
        """§101 — a célula revelada e igual troca `1` por `0`."""
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        parcial = representacao_de_trajetoria(
            match="ref-a",
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(0.0), 3: _cheio(0.0)}),
        )
        completo = representacao_de_trajetoria(
            match="ref-a",
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS}),
        )
        assert DISTANCIA.evaluate(query, parcial).value == 5 / 15
        assert DISTANCIA.evaluate(query, completo).value == 0.0

    def test_a_abertura_por_horizonte_existe_e_soma(self) -> None:
        """§111, §199."""
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        candidato = representacao_de_trajetoria(
            match="ref-a",
            **com_horizontes(
                agora=_cheio(0.0),
                horizontes={1: _cheio(-1.0), 3: _cheio(0.0), 5: _cheio(0.0)},
            ),
        )
        conta = DISTANCIA.evaluate(query, candidato)
        por_horizonte = {c.horizon_minutes: c.observed for c in conta.horizons}
        assert por_horizonte == {1: 5.0, 3: 0.0, 5: 0.0}
        assert conta.observed_sum == 5.0
        assert conta.horizon_share(1) == 1.0
        assert conta.horizon_share(5) == 0.0


class TestNaoEhMetricaTemporal:
    """§97, §98, §163 ao §167."""

    def test_nao_negatividade(self) -> None:
        uma = representacao_de_trajetoria(**curva(de=-5.0, para=3.0))
        outra = representacao_de_trajetoria(match="ref-a", **curva(de=4.0, para=-2.0))
        assert DISTANCIA.evaluate(uma, outra).value >= 0

    def test_simetria(self) -> None:
        """§166."""
        uma = representacao_de_trajetoria(**curva(de=-5.0, para=3.0))
        outra = representacao_de_trajetoria(match="ref-a", **curva(de=4.0, para=-2.0))
        assert DISTANCIA.evaluate(uma, outra).value == DISTANCIA.evaluate(outra, uma).value

    def test_auto_dissimilaridade_zero_quando_completa(self) -> None:
        """§163."""
        x = representacao_de_trajetoria(**curva(de=-5.0, para=3.0))
        assert DISTANCIA.evaluate(x, x).value == 0.0

    def test_auto_dissimilaridade_POSITIVA_quando_incompleta(self) -> None:
        """§164 — a prova mais curta de que isto não é métrica."""
        x = representacao_de_trajetoria(
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(1.0), 3: _cheio(2.0)}),
        )
        assert DISTANCIA.evaluate(x, x).value == 5 / 15
        assert DISTANCIA.incomplete_self_dissimilarity(10) == 5 / 15
        assert DISTANCIA.incomplete_self_dissimilarity(15) == 0.0
        assert not DISTANCIA.is_metric


# ============================================ a cobertura ==


class TestACoberturaTemporal:
    """§70 ao §87, §240."""

    def test_a_politica_declara_os_numeros(self) -> None:
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert p.name == MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1
        assert p.minimum_profile_axes == 4
        assert p.minimum_usable_horizons == 2
        assert p.minimum_shared_horizons == 2
        assert p.minimum_query_trajectory_cells == 8
        assert p.minimum_shared_trajectory_cells == 8
        assert p.query_trajectory_coverage_floor.text == "3/5"
        assert p.shared_trajectory_coverage_floor.text == "3/5"
        assert p.per_horizon_axis_coverage_floor.text == "3/5"
        assert p.minimum_axes_per_evidential_horizon == 4

    def test_o_minimo_de_oito_celulas_e_o_produto_dos_dois_pisos(self) -> None:
        """§73 — e não um número solto."""
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert (
            p.minimum_shared_horizons * p.minimum_axes_per_evidential_horizon
            == p.minimum_shared_trajectory_cells
        )

    def test_um_horizonte_so_NAO_e_evidencia(self) -> None:
        """§87 — o sentinela da trajetória quase vazia."""
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert not p.admits_pair(shared_cells=5, cell_count=15, shared_horizons=1)
        # NEM COM O HORIZONTE PERFEITO: cinco de quinze não bate o piso.
        assert not p.admits_pair(shared_cells=15, cell_count=15, shared_horizons=1)

    def test_dois_horizontes_cheios_bastam(self) -> None:
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert p.admits_pair(shared_cells=10, cell_count=15, shared_horizons=2)

    def test_a_razao_corta_em_nove_celulas(self) -> None:
        """`5s >= 45` -> `s >= 9`, e o mínimo de células é 8."""
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert p.admits_pair(shared_cells=9, cell_count=15, shared_horizons=2)
        assert not p.admits_pair(shared_cells=8, cell_count=15, shared_horizons=2)

    def test_um_horizonte_com_poucos_eixos_nao_conta(self) -> None:
        """§81 — evidencial exige `>= 4` eixos E `>= 3/5` deles."""
        p = DEFAULT_TRAJECTORY_COVERAGE
        assert p.is_evidential_horizon(usable_axes=4, axis_count=5)
        assert not p.is_evidential_horizon(usable_axes=3, axis_count=5)
        assert not p.is_evidential_horizon(usable_axes=4, axis_count=20)

    def test_a_politica_recusa_um_minimo_de_um_horizonte(self) -> None:
        with pytest.raises(ValidationError, match="um minuto de história"):
            TrajectoryCoveragePolicy(minimum_usable_horizons=1)

    def test_o_perfil_pequeno_recusa_a_competicao(self) -> None:
        """§24 do PR-06.2, transposto."""
        with pytest.raises(TrajectoryProfileInsufficientAxesError) as erro:
            DEFAULT_TRAJECTORY_COVERAGE.assert_profile_admissible(
                axis_count=3, competition="PREMIER"
            )
        assert erro.value.reason == "TRAJECTORY_PROFILE_INSUFFICIENT_AXES"

    def test_a_avaliacao_conta_horizontes_evidenciais(self) -> None:
        query = representacao_de_trajetoria(
            **com_horizontes(agora=_cheio(0.0), horizontes={h: _cheio(0.0) for h in HORIZONS})
        )
        parcial = representacao_de_trajetoria(
            match="ref-a",
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(0.0), 3: _cheio(0.0)}),
        )
        cobertura = DISTANCIA.assess(query, parcial)
        assert cobertura.cell_count == 15
        assert cobertura.shared_cells == 10
        assert cobertura.shared_horizons == 2
        assert cobertura.query_usable_horizons == 3
        assert cobertura.candidate_usable_horizons == 2
        assert cobertura.meets_shared_floor
        assert not cobertura.is_complete

    def test_a_intersecao_maior_que_o_menor_lado_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="interseção"):
            TrajectoryCoverageAssessment(
                cell_count=15,
                axis_count=5,
                query_usable_cells=5,
                candidate_usable_cells=15,
                shared_cells=10,
            )


# ============================================ os contratos ==


class TestOsContratosEOsNomes:
    def test_a_janela_tem_o_nome_por_extenso(self) -> None:
        assert DEFAULT_TRAJECTORY_WINDOW.name == SAME_PERIOD_FIXED_HORIZON_1_3_5_V1
        assert DEFAULT_TRAJECTORY_WINDOW.horizons == (1, 3, 5)
        assert (
            DEFAULT_TRAJECTORY_WINDOW.period_crossing is PeriodCrossingPolicy.STOP_AT_PERIOD_START
        )

    def test_o_catalogo_de_cruzamento_tem_um_membro(self) -> None:
        """`ALLOW` não existe — atravessar o intervalo não é configurável."""
        assert {p.value for p in PeriodCrossingPolicy} == {"STOP_AT_PERIOD_START"}

    def test_o_perfil_tem_o_nome_por_extenso(self) -> None:
        assert PERFIL.profile.name == ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1
        assert PERFIL.profile.is_diagnostic
        assert PERFIL.profile.representation is TrajectoryRepresentationMethod.ABSOLUTE_DISPLACEMENT

    def test_o_catalogo_de_representacao_nao_tem_velocidade(self) -> None:
        """§49, §51, §52 — `Δ/h` e `Δ²` não existem, e a ausência é a decisão."""
        assert {m.value for m in TrajectoryRepresentationMethod} == {DISPLACEMENT_REPRESENTATION_V1}
        assert not {m.name for m in TrajectoryRepresentationMethod} & {
            "VELOCITY",
            "ACCELERATION",
            "LEVEL_CONCATENATION",
        }

    def test_o_metodo_da_distancia_e_fechado(self) -> None:
        assert {m.value for m in TrajectoryDistanceMethod} == {
            "MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY_V1"
        }

    def test_a_semantica_de_float_e_a_dos_PRs_anteriores(self) -> None:
        """§58."""
        assert DISTANCIA.float_semantics == FLOAT_SEMANTICS_V1

    def test_o_perfil_base_de_CASO_COMPLETO_e_recusado(self) -> None:
        """§34 — os eixos vêm do perfil CIENTE, e a troca mudaria o espaço."""
        with pytest.raises(ValidationError, match="CIENTE DE DISPONIBILIDADE"):
            TrajectoryRetrievalProfile(base=DEFAULT_RETRIEVAL_PROFILE)

    def test_resolver_sob_outra_regra_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="outra regra de seleção"):
            TrajectoryRetrievalProfile().resolve(perfil(eixos=CINCO_EIXOS))

    def test_a_impressao_da_distancia_cobre_a_janela(self) -> None:
        """§104 — dois conjuntos de horizontes são duas definições."""
        outra = TrajectoryRetrievalProfile(
            window=TrajectoryWindowPolicy(name="SO_UM_E_TRES", horizons=(1, 3))
        )
        resolvida = outra.resolve(perfil_ciente())
        assert distancia_de_trajetoria(resolvida).fingerprint != DISTANCIA.fingerprint
        assert resolvida.cell_count == 10

    def test_a_impressao_da_distancia_cobre_o_piso(self) -> None:
        outro = TrajectoryCoveragePolicy(name="PISO_OUTRO", minimum_shared_trajectory_cells=12)
        assert (
            distancia_de_trajetoria(PERFIL, coverage_policy=outro).fingerprint
            != DISTANCIA.fingerprint
        )


class TestOsEixosSaoOsMesmosDoEstado:
    """§34, §35, §36 — a condição para a comparação significar alguma coisa."""

    def test_os_eixos_resolvidos_sao_iguais(self) -> None:
        assert PERFIL.feature_keys == perfil_ciente().feature_keys
        assert PERFIL.base.fingerprint == perfil_ciente().fingerprint

    def test_e_a_regra_de_selecao_e_a_MESMA(self) -> None:
        assert PERFIL.profile.base is AVAILABILITY_AWARE_RETRIEVAL_PROFILE

    def test_mas_a_impressao_do_perfil_e_OUTRA(self) -> None:
        """Mesmos eixos, outro espaço: os dois números não se confundem."""
        assert PERFIL.fingerprint != perfil_ciente().fingerprint


# ============================================ a máscara e a evidência ==


class TestAInconsistenciaParaAMontagem:
    """§56 — falha fechada, como no PR-06.2."""

    def test_disponivel_sem_valor_PARA(self) -> None:
        from sports_intelligence.domain.features.dataset.rows import (
            HistoricalFeatureSnapshotKey,
        )
        from sports_intelligence.domain.retrieval.trajectory import TrajectoryRow

        montada, linhas = trajetoria(passado={h: _cheio(0.0) for h in HORIZONS})
        alvo = next(iter(linhas))
        linhas[alvo] = TrajectoryRow(
            key=HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=alvo.minute),
            position=alvo,
            row_digest="d",
            values={CINCO_EIXOS[0]: None},
            availabilities={CINCO_EIXOS[0]: DISPONIVEL},
        )
        with pytest.raises(AvailabilityInconsistencyError):
            build_representation(
                trajectory=montada,
                feature_keys=PERFIL.feature_keys,
                horizons=PERFIL.horizons,
                profile_fingerprint=PERFIL.fingerprint,
                anchor_values=_cheio(0.0),
                anchor_availabilities=dict.fromkeys(CINCO_EIXOS, DISPONIVEL),
                rows=linhas,
            )

    def test_indisponivel_COM_valor_tambem_PARA(self) -> None:
        montada, linhas = trajetoria(passado={h: _cheio(0.0) for h in HORIZONS})
        with pytest.raises(AvailabilityInconsistencyError):
            build_representation(
                trajectory=montada,
                feature_keys=PERFIL.feature_keys,
                horizons=PERFIL.horizons,
                profile_fingerprint=PERFIL.fingerprint,
                anchor_values=_cheio(0.0),
                anchor_availabilities=dict.fromkeys(CINCO_EIXOS, SEM_ESCALA),
                rows=linhas,
            )


class TestAEvidenciaTemporal:
    """§109 ao §113, §242."""

    def _par(self) -> tuple[TrajectoryRepresentation, TrajectoryRepresentation]:
        query = representacao_de_trajetoria(**curva(de=-2.0, para=0.0))
        candidato = representacao_de_trajetoria(match="ref-b", **curva(de=2.0, para=0.0))
        return query, candidato

    def test_ela_reconstroi_o_numero(self) -> None:
        from sports_intelligence.domain.retrieval.trajectory_evidence import (
            build_trajectory_evidence,
        )

        query, candidato = self._par()
        prova = build_trajectory_evidence(
            query=query,
            candidate=candidato,
            coverage=DISTANCIA.assess(query, candidato),
            breakdown=DISTANCIA.evaluate(query, candidato),
            window_policy_fingerprint=DEFAULT_TRAJECTORY_WINDOW.fingerprint,
            trajectory_profile_fingerprint=PERFIL.fingerprint,
            coverage_policy_fingerprint=DEFAULT_TRAJECTORY_COVERAGE.fingerprint,
            distance_definition_fingerprint=DISTANCIA.fingerprint,
        )
        assert prova.is_reconstructible
        assert (prova.observed_sum + prova.missing_penalty_sum) / 15 == prova.dissimilarity
        assert len(prova.contributions) == 15
        assert math.fsum(c.squared_contribution for c in prova.contributions) == 130.0

    def test_ela_conta_as_REVERSOES(self) -> None:
        from sports_intelligence.domain.retrieval.trajectory_evidence import (
            build_trajectory_evidence,
        )

        query, candidato = self._par()
        prova = build_trajectory_evidence(
            query=query,
            candidate=candidato,
            coverage=DISTANCIA.assess(query, candidato),
            breakdown=DISTANCIA.evaluate(query, candidato),
            window_policy_fingerprint="w",
            trajectory_profile_fingerprint=PERFIL.fingerprint,
            coverage_policy_fingerprint="c",
            distance_definition_fingerprint="d",
        )
        # TODAS AS QUINZE CÉLULAS SÃO REVERSÃO — é o cenário do §68.
        assert prova.reversals == 15
        assert any("dissimilaridade" in linha for linha in trajectory_evidence_summary(prova))

    def test_ela_NAO_carrega_desfecho_nem_futuro(self) -> None:
        from sports_intelligence.domain.retrieval.trajectory_evidence import (
            build_trajectory_evidence,
        )

        query, candidato = self._par()
        prova = build_trajectory_evidence(
            query=query,
            candidate=candidato,
            coverage=DISTANCIA.assess(query, candidato),
            breakdown=DISTANCIA.evaluate(query, candidato),
            window_policy_fingerprint="w",
            trajectory_profile_fingerprint=PERFIL.fingerprint,
            coverage_policy_fingerprint="c",
            distance_definition_fingerprint="d",
        )
        proibidos = {
            "winner",
            "final_score",
            "next_goal",
            "outcome",
            "future",
            "probability",
            "confidence",
        }
        assert not set(prova.as_canonical()) & proibidos

    def test_a_contribuicao_negativa_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="negativa"):
            TrajectoryDistanceContribution(
                horizon_minutes=1,
                feature_key="x",
                query_displacement=0.0,
                candidate_displacement=0.0,
                squared_contribution=-1.0,
            )


def test_a_grade_de_producao_e_a_do_dataset() -> None:
    """Uma guarda contra o teste que passa porque usa outra grade."""
    assert GRADE is DEFAULT_SNAPSHOT_GRID
    assert isinstance(DISTANCIA, TrajectoryDistanceDefinition)


# ==================================================== OS PISOS EFETIVOS ==


def _cobertura(
    *,
    m: int,
    compartilhadas: int,
    horizontes: tuple[int, ...],
) -> TrajectoryCoverageAssessment:
    """Uma avaliação com `m` eixos e um número dado de eixos por horizonte.

    `horizontes` É QUANTOS EIXOS CADA HORIZONTE COMPARTILHA, e a soma deles tem
    de bater com `compartilhadas` — é a mesma coerência que o motor exige, e
    montá-la à mão aqui é o que torna os goldens legíveis.
    """
    assert sum(horizontes) == compartilhadas
    return TrajectoryCoverageAssessment(
        cell_count=3 * m,
        axis_count=m,
        query_usable_cells=3 * m,
        candidate_usable_cells=3 * m,
        shared_cells=compartilhadas,
        horizons=tuple(
            HorizonCoverage(
                horizon_minutes=minutos,
                axis_count=m,
                query_usable_axes=m,
                candidate_usable_axes=m,
                shared_axes=eixos,
            )
            for minutos, eixos in zip((1, 3, 5), horizontes, strict=True)
        ),
    )


class TestOPisoEfetivoDeCelulas:
    """§1 ao §14 do adendo — `8` é um MÍNIMO ABSOLUTO, e não o piso.

    A COMPOSIÇÃO É O ASSUNTO INTEIRO. `minimum_shared_trajectory_cells = 8` e
    `shared_trajectory_coverage_floor = 3/5` são DOIS pisos, e nenhum deles
    autoriza sozinho. O piso que decide é

        E_s = max( 8, ceil(3n/5) )        n = 3m

    e a diferença entre lê-lo assim e lê-lo como «oito bastam» é a diferença
    entre recusar e admitir um par com `m = 6` e dez células.
    """

    def test_golden_A_o_minimo_absoluto_domina_quando_o_espaco_e_pequeno(self) -> None:
        """§20.A — com `n` pequeno o piso racional fica ABAIXO do absoluto.

        E AQUI VAI UMA CONSTATAÇÃO HONESTA: sob a V1 este caso NÃO ocorre para
        perfil admissível nenhum. `ceil(3n/5) < 8` exige `n <= 12`, isto é
        `m <= 4`, e `minimum_profile_axes = 4` corta em `m = 4` — onde os dois
        pisos EMPATAM em oito. O mínimo absoluto nunca é ESTRITAMENTE o que
        decide.

        O golden continua existindo porque ele prova a FÓRMULA, e não o alcance
        dela: se um dia a política admitir perfis menores, é este teste que
        garante que oito continua sendo o chão.
        """
        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(3)
        assert pisos.total_trajectory_cells == 9
        assert pisos.ratio_shared_cell_floor == 6
        assert pisos.absolute_shared_cell_floor == 8
        assert pisos.effective_shared_cell_floor == 8
        assert not pisos.shared_floor_is_rational

    def test_golden_B_em_m_igual_a_4_os_dois_pisos_empatam(self) -> None:
        """§20.B — `n = 12`, `ceil(36/5) = 8`, e o absoluto vale 8 também.

        ESTE É O ÚNICO PONTO DE ENCONTRO, e ele é o menor perfil admissível. A
        partir daqui é sempre a razão que manda.
        """
        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(4)
        assert pisos.total_trajectory_cells == 12
        assert pisos.absolute_shared_cell_floor == pisos.ratio_shared_cell_floor == 8
        assert pisos.effective_shared_cell_floor == 8
        assert pisos.shared_floor_is_rational

    def test_golden_C_o_piso_racional_domina_a_partir_de_m_igual_a_5(self) -> None:
        """§20.C — a tabela do adendo, valor a valor."""
        esperado = {
            5: (15, 8, 9, 9),
            6: (18, 8, 11, 11),
            10: (30, 8, 18, 18),
            15: (45, 8, 27, 27),
            20: (60, 8, 36, 36),
        }
        for m, (n, absoluto, racional, efetivo) in esperado.items():
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            assert pisos.total_trajectory_cells == n
            assert pisos.absolute_shared_cell_floor == absoluto
            assert pisos.ratio_shared_cell_floor == racional
            assert pisos.effective_shared_cell_floor == efetivo

    def test_golden_D_o_exemplo_obrigatorio_do_paragrafo_5(self) -> None:
        """§5 — `m = 6`, `n = 18`: oito, nove e dez são RECUSADOS; onze passa.

        ESTE É O GOLDEN QUE O ADENDO CHAMA DE OBRIGATÓRIO, e ele é a prova de
        que a leitura «oito células bastam» estaria errada por três células:
        dois horizontes minimamente evidenciais dão `4 + 4 = 8`, e oito é menor
        que onze.
        """
        politica = DEFAULT_TRAJECTORY_COVERAGE
        for compartilhadas in (8, 9, 10):
            assert not politica.admits_pair(
                shared_cells=compartilhadas, cell_count=18, shared_horizons=2
            ), f"{compartilhadas} celulas passaram com n = 18, e o piso e 11"
        assert politica.admits_pair(shared_cells=11, cell_count=18, shared_horizons=2)

    def test_golden_E_os_dois_pisos_de_horizonte_com_m_igual_a_6(self) -> None:
        """§8 — `E_h = max(4, ceil(18/5)) = max(4, 4) = 4`.

        Um horizonte é evidencial somente com QUATRO eixos compartilhados; três
        não bastam, ainda que três de seis seja meio espaço.
        """
        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(6)
        assert pisos.absolute_horizon_axis_floor == 4
        assert pisos.ratio_horizon_axis_floor == 4
        assert pisos.effective_horizon_axis_floor == 4
        assert not DEFAULT_TRAJECTORY_COVERAGE.is_evidential_horizon(usable_axes=3, axis_count=6)
        assert DEFAULT_TRAJECTORY_COVERAGE.is_evidential_horizon(usable_axes=4, axis_count=6)

    def test_golden_F_o_piso_de_horizonte_tambem_passa_a_ser_racional(self) -> None:
        """§8 — a partir de `m = 7` é `ceil(3m/5)` que decide o horizonte."""
        esperado = {4: 4, 5: 4, 6: 4, 7: 5, 10: 6, 15: 9, 20: 12}
        for m, piso in esperado.items():
            assert DEFAULT_TRAJECTORY_COVERAGE.floors(m).effective_horizon_axis_floor == piso

    def test_o_piso_efetivo_e_calculado_em_inteiros(self) -> None:
        """§4 — a derivação é INTEIRA, e o float tem um fim demonstrável.

        NA FAIXA REAL AS DUAS FORMAS CONCORDAM — a propriedade que varre dois
        milhões de valores está em `tests/property`. O motivo de usar
        `-((-a) // b)` não é que o float erre num perfil de futebol: é que a
        forma inteira é exata POR CONSTRUÇÃO, e a de ponto flutuante depende de
        um argumento de arredondamento que tem limite. Aqui está o limite, com
        o mesmo `3/5` da política.
        """
        fora_da_faixa = 9_999_999_999_999_997
        assert ceil_div(3 * fora_da_faixa, 5) == 5_999_999_999_999_999
        assert math.ceil(0.6 * fora_da_faixa) == 5_999_999_999_999_997
        assert ceil_div(3 * fora_da_faixa, 5) != math.ceil(0.6 * fora_da_faixa)

    def test_a_derivacao_entra_na_impressao_da_politica(self) -> None:
        """§16 — a FÓRMULA é parte do contrato, e não só os números."""
        canonica = DEFAULT_TRAJECTORY_COVERAGE.as_canonical()
        assert canonica["effective_floor_algorithm"] == EFFECTIVE_FLOOR_ALGORITHM_V1
        assert EFFECTIVE_FLOOR_ALGORITHM_V1 == "MAX_ABSOLUTE_CEIL_RATIONAL_V1"

    def test_os_pisos_NAO_sao_persistidos_como_autoridade(self) -> None:
        """§15 — eles são derivados, e a avaliação canônica não os carrega.

        DUAS FONTES DE VERDADE DIVERGEM. Se o piso viajasse dentro da avaliação
        canônica, uma avaliação antiga sob uma política nova traria o piso
        velho, e a impressão diria que os dois concordam.
        """
        canonica = _cobertura(m=6, compartilhadas=12, horizontes=(4, 4, 4)).as_canonical()
        assert not [c for c in canonica if "floor" in c]

    def test_a_avaliacao_EXIBE_os_pisos_efetivos(self) -> None:
        """§17 — quem recusou, e de quanto foi a falta."""
        cobertura = _cobertura(m=6, compartilhadas=10, horizontes=(4, 4, 2))
        assert cobertura.total_trajectory_cells == 18
        assert cobertura.effective_shared_cell_floor == 11
        assert cobertura.effective_horizon_axis_floor == 4
        assert cobertura.meets_horizon_count_floor
        assert not cobertura.meets_shared_cell_floor
        assert not cobertura.meets_shared_floor
        assert "11" in str(cobertura)


class TestOsTresMotivosDeRecusa:
    """§19 do adendo — «poucas células» e «só um horizonte» são causas distintas.

    A ORDEM DO DIAGNÓSTICO VAI DO RELÓGIO PARA A FEATURE. Um par que só alcança
    um horizonte também não alcança células bastante; reportá-lo como «poucas
    células» apontaria para a atrição de feature quando a causa é o começo do
    período, e é essa confusão que o motivo único produzia.
    """

    def test_um_horizonte_alcancado_e_recusado_por_HORIZONTES(self) -> None:
        cobertura = _cobertura(m=6, compartilhadas=6, horizontes=(6, 0, 0))
        assert cobertura.horizons_with_shared_axes == 1
        assert cobertura.refusal_reason == INSUFFICIENT_SHARED_HORIZONS

    def test_tres_horizontes_rasos_sao_recusados_por_PER_HORIZON(self) -> None:
        """Os três horizontes existem, e nenhum descreve movimento.

        NOVE CÉLULAS SOBRE DEZOITO, e o piso de células é onze — mas não é ele
        que responde: a causa é que três eixos de seis não fazem um horizonte
        evidencial, e é essa a frase que o operador precisa ler.
        """
        cobertura = _cobertura(m=6, compartilhadas=9, horizontes=(3, 3, 3))
        assert cobertura.horizons_with_shared_axes == 3
        assert cobertura.shared_horizons == 0
        assert cobertura.refusal_reason == INSUFFICIENT_PER_HORIZON_COVERAGE

    def test_dois_horizontes_cheios_e_poucas_celulas_sao_CELULAS(self) -> None:
        """`4 + 4 = 8` — o produto dos dois mínimos, e ele NÃO basta."""
        cobertura = _cobertura(m=6, compartilhadas=8, horizontes=(4, 4, 0))
        assert cobertura.shared_horizons == 2
        assert cobertura.meets_horizon_count_floor
        assert cobertura.refusal_reason == INSUFFICIENT_SHARED_TRAJECTORY_CELLS

    def test_o_par_admitido_NAO_tem_motivo(self) -> None:
        cobertura = _cobertura(m=6, compartilhadas=12, horizontes=(4, 4, 4))
        assert cobertura.meets_shared_floor
        assert cobertura.refusal_reason is None
