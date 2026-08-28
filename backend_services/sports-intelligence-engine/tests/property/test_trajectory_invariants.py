"""As invariantes da recuperação de trajetória.

    §228  identidade da trajetória sob permutação, lote e layout
    §229  invariância a deslocamento constante
    §230  imunidade ao futuro
    §231  simetria
    §232  não-negatividade
    §233  auto-dissimilaridade zero quando completa
    §234  auto-dissimilaridade positiva quando incompleta
    §235  prefixo do top-K
    §236  o MESMO universo do PR-06.2

A IMUNIDADE AO FUTURO É A INVARIANTE CENTRAL DESTE PR (§63, §151, §254). Ela é
provada da forma mais direta possível: as linhas de `t+1`, `t+3` e `t+5` são
construídas com valores absurdos e entregues ao montador junto com as do
passado. Se alguma delas entrasse, a impressão mudaria.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator, Sequence

import pytest

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    TrajectoryRepresentation,
    build_representation,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
)
from sports_intelligence.domain.retrieval.trajectory_exact import TrajectoryCandidate
from sports_intelligence.domain.retrieval.trajectory_result import (
    TrajectoryRetrievalResult,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    DEFAULT_TRAJECTORY_WINDOW,
    HORIZONS,
)
from sports_intelligence.domain.shared.temporal import Period
from tests.support.availability_fixtures import (
    CINCO_EIXOS,
    consulta_ciente,
    pedido_ciente,
    perfil_ciente,
)
from tests.support.retrieval_fixtures import LIGA_A, LIGA_B
from tests.support.trajectory_fixtures import (
    ANCORA,
    ANCORA_49,
    GRADE,
    candidato_de_trajetoria,
    com_horizontes,
    curva,
    distancia_de_trajetoria,
    linha,
    perfil_de_trajetoria,
    recuperador_de_trajetoria,
    representacao_de_trajetoria,
    trajetoria,
)

pytestmark = pytest.mark.property

PERFIL = perfil_de_trajetoria()
DISTANCIA = distancia_de_trajetoria(PERFIL)
REFERENCIA = "r" * 64
CHAVE = HistoricalFeatureSnapshotKey(match_key="eva-001", grid_index=ANCORA.minute)


def _cheio(valor: float) -> dict[str, float | None]:
    return dict.fromkeys(CINCO_EIXOS, valor)


def _executar(
    candidatos: Sequence[TrajectoryCandidate],
    *,
    k: int = 5,
    query: TrajectoryRepresentation | None = None,
) -> TrajectoryRetrievalResult:
    return recuperador_de_trajetoria(profile=PERFIL).retrieve(
        query=pedido_ciente(k=k, key=CHAVE),
        snapshot=consulta_ciente(grid_index=ANCORA.minute, position=ANCORA),
        query_representation=query or representacao_de_trajetoria(**curva(de=-2.0, para=0.0)),
        candidates=list(candidatos),
        reference_content_fingerprint=REFERENCIA,
    )


def _populacao(n: int = 24) -> list[TrajectoryCandidate]:
    """Candidatos com movimentos variados — subindo, descendo, estáveis.

    O SORTEIO É SEMEADO E FIXO. O que varia nos testes é a ORDEM em que a
    população é percorrida, e é isso que as propriedades medem.
    """
    sorteio = random.Random(20260827)
    linhas: list[TrajectoryCandidate] = []
    for i in range(n):
        de = round(sorteio.uniform(-3.0, 3.0), 2)
        para = round(sorteio.uniform(-3.0, 3.0), 2)
        linhas.append(candidato_de_trajetoria(match=f"ref-{i:03d}", **curva(de=de, para=para)))
    return linhas


# ================================================= a imunidade ao futuro ==


class TestONadaDoFuturoEntra:
    """§63, §151, §230, §254 — a invariante central deste PR."""

    def test_as_linhas_do_FUTURO_sao_ignoradas(self) -> None:
        """As linhas de `t+1`, `t+3` e `t+5` são entregues junto, com valores
        absurdos. Se alguma entrasse, a impressão mudaria."""
        montada, passado = trajetoria(passado={h: _cheio(1.0) for h in HORIZONS})
        limpa = build_representation(
            trajectory=montada,
            feature_keys=PERFIL.feature_keys,
            horizons=PERFIL.horizons,
            profile_fingerprint=PERFIL.fingerprint,
            anchor_values=_cheio(0.0),
            anchor_availabilities=dict.fromkeys(CINCO_EIXOS, "AVAILABLE"),
            rows=passado,
        )
        contaminada = dict(passado)
        for adiante in (1, 3, 5):
            alvo = GridTimePoint.of(Period.SECOND_HALF, ANCORA.minute + adiante)
            contaminada[alvo] = linha(match="eva-001", position=alvo, valores=_cheio(999.0))
        suja = build_representation(
            trajectory=montada,
            feature_keys=PERFIL.feature_keys,
            horizons=PERFIL.horizons,
            profile_fingerprint=PERFIL.fingerprint,
            anchor_values=_cheio(0.0),
            anchor_availabilities=dict.fromkeys(CINCO_EIXOS, "AVAILABLE"),
            rows=contaminada,
        )
        assert suja.fingerprint == limpa.fingerprint
        assert suja.displacements == limpa.displacements

    def test_um_slot_apontando_para_o_futuro_e_RECUSADO(self) -> None:
        """A guarda estrutural, e não só a ausência de uso."""
        from sports_intelligence.domain.retrieval.trajectory import (
            HistoricalTrajectory,
            TrajectorySlot,
        )
        from sports_intelligence.domain.retrieval.trajectory_window import SlotStatus
        from sports_intelligence.domain.shared.errors import ValidationError

        adiante = GridTimePoint.of(Period.SECOND_HALF, ANCORA.minute + 1)
        with pytest.raises(ValidationError, match="posterior a t"):
            HistoricalTrajectory(
                anchor_key=CHAVE,
                match_key="eva-001",
                competition=LIGA_A,
                anchor_position=ANCORA,
                anchor_row_digest="d",
                policy_fingerprint="p",
                policy_identity="i",
                slots=(
                    TrajectorySlot(
                        horizon_minutes=1,
                        target=adiante,
                        status=SlotStatus.AVAILABLE,
                        source_key=CHAVE,
                        source_row_digest="x",
                    ),
                ),
            )

    def test_um_slot_de_OUTRO_PERIODO_e_RECUSADO(self) -> None:
        """§153 — a guarda do intervalo, no construtor."""
        from sports_intelligence.domain.retrieval.trajectory import (
            HistoricalTrajectory,
            TrajectorySlot,
        )
        from sports_intelligence.domain.retrieval.trajectory_window import SlotStatus
        from sports_intelligence.domain.shared.errors import ValidationError

        primeiro_tempo = GridTimePoint.of(Period.FIRST_HALF, 44)
        with pytest.raises(ValidationError, match="intervalo"):
            HistoricalTrajectory(
                anchor_key=CHAVE,
                match_key="eva-001",
                competition=LIGA_A,
                anchor_position=ANCORA_49,
                anchor_row_digest="d",
                policy_fingerprint="p",
                policy_identity="i",
                slots=(
                    TrajectorySlot(
                        horizon_minutes=5,
                        target=primeiro_tempo,
                        status=SlotStatus.AVAILABLE,
                        source_key=CHAVE,
                        source_row_digest="x",
                    ),
                ),
            )

    def test_o_PASSADO_muda_a_trajetoria(self) -> None:
        """§64, §152 — o espelho: se nada mudasse, o teste anterior seria vazio."""
        uma = representacao_de_trajetoria(
            **com_horizontes(
                agora=_cheio(0.0),
                horizontes={1: _cheio(1.0), 3: _cheio(2.0), 5: _cheio(3.0)},
            )
        )
        outra = representacao_de_trajetoria(
            **com_horizontes(
                agora=_cheio(0.0),
                horizontes={1: _cheio(1.0), 3: _cheio(9.0), 5: _cheio(3.0)},
            )
        )
        assert uma.fingerprint != outra.fingerprint

    def test_a_ANCORA_muda_todos_os_deslocamentos(self) -> None:
        """§65 — e isso é correto: `Δ` depende dos dois extremos."""
        passado = {h: _cheio(0.0) for h in HORIZONS}
        uma = representacao_de_trajetoria(**com_horizontes(agora=_cheio(1.0), horizontes=passado))
        outra = representacao_de_trajetoria(**com_horizontes(agora=_cheio(2.0), horizontes=passado))
        assert all(d == 1.0 for d in uma.displacements if d is not None)
        assert all(d == 2.0 for d in outra.displacements if d is not None)


# ================================================= a invariância de nível ==


class TestOMovimentoNaoDependeDoNivel:
    """§66, §161, §229."""

    def test_somar_a_MESMA_constante_a_tudo_nao_muda_o_deslocamento(self) -> None:
        sorteio = random.Random(4242)
        for _ in range(200):
            base = round(sorteio.uniform(-5.0, 5.0), 4)
            constante = round(sorteio.uniform(-100.0, 100.0), 4)
            passado = {h: _cheio(base - h / 2) for h in HORIZONS}
            deslocado = {h: _cheio(base - h / 2 + constante) for h in HORIZONS}
            uma = representacao_de_trajetoria(
                **com_horizontes(agora=_cheio(base), horizontes=passado)
            )
            outra = representacao_de_trajetoria(
                **com_horizontes(agora=_cheio(base + constante), horizontes=deslocado)
            )
            assert uma.displacements == pytest.approx(outra.displacements)

    def test_e_com_valores_DIADICOS_a_igualdade_e_EXATA(self) -> None:
        """A distinção que o cenário do §150 obrigou a fazer.

        `x + k` e `y + k` só produzem deslocamentos IDÊNTICOS bit a bit quando
        as somas são exatas em `binary64`. Com valores diádicos elas são; com
        valores quaisquer, a propriedade vale a menos do arredondamento — e o
        teste acima a verifica assim, de propósito.
        """
        for constante in (0.0, 8.0, -16.0, 1024.0, 0.5, 0.25):
            uma = representacao_de_trajetoria(**curva(de=0.0, para=2.0))
            outra = representacao_de_trajetoria(**curva(de=0.0 + constante, para=2.0 + constante))
            assert uma.displacements == outra.displacements
            assert DISTANCIA.evaluate(uma, outra).value == 0.0


# ================================================= a conta ==


class TestAsPropriedadesDaConta:
    """§162, §165, §166, §231 ao §234."""

    def test_nao_negatividade(self) -> None:
        for um, outro in zip(_populacao(20), _populacao(20)[::-1], strict=True):
            assert DISTANCIA.evaluate(um.representation, outro.representation).value >= 0

    def test_simetria(self) -> None:
        """§166, §231."""
        populacao = _populacao(20)
        for um, outro in zip(populacao, populacao[::-1], strict=True):
            direto = DISTANCIA.evaluate(um.representation, outro.representation).value
            inverso = DISTANCIA.evaluate(outro.representation, um.representation).value
            assert direto == inverso

    def test_auto_dissimilaridade_ZERO_quando_completa(self) -> None:
        """§163, §233."""
        for candidato in _populacao(20):
            assert (
                DISTANCIA.evaluate(candidato.representation, candidato.representation).value == 0.0
            )

    def test_auto_dissimilaridade_POSITIVA_quando_incompleta(self) -> None:
        """§164, §234."""
        curta = representacao_de_trajetoria(
            anchor=ANCORA_49,
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(1.0), 3: _cheio(2.0)}),
        )
        assert DISTANCIA.evaluate(curta, curta).value > 0
        assert DISTANCIA.evaluate(curta, curta).value == 5 / 15

    def test_a_reversao_e_o_quadrado_do_dobro(self) -> None:
        """§162 — sobre uma população, e não num caso."""
        sorteio = random.Random(99)
        for _ in range(100):
            delta = round(sorteio.uniform(0.1, 4.0), 4)
            query = representacao_de_trajetoria(
                **com_horizontes(agora=_cheio(delta), horizontes={h: _cheio(0.0) for h in HORIZONS})
            )
            invertido = representacao_de_trajetoria(
                match="ref-inv",
                **com_horizontes(
                    agora=_cheio(0.0), horizontes={h: _cheio(delta) for h in HORIZONS}
                ),
            )
            conta = DISTANCIA.evaluate(query, invertido)
            assert conta.observed_sum == pytest.approx(15 * (2 * delta) ** 2)

    def test_o_denominador_e_SEMPRE_n(self) -> None:
        """§44 — sobre toda a população."""
        for vizinho in _executar(_populacao(24), k=20).neighbors:
            conta = vizinho.evidence.breakdown
            assert conta.cell_count == 15
            assert conta.value == (conta.observed_sum + conta.missing_penalty_sum) / 15


# ================================================= o determinismo ==


class TestODeterminismo:
    """§168 ao §172, §228."""

    def test_a_ordem_dos_candidatos_nao_importa(self) -> None:
        populacao = _populacao()
        base = _executar(populacao)
        sorteio = random.Random(7)
        for _ in range(10):
            embaralhado = populacao[:]
            sorteio.shuffle(embaralhado)
            assert _executar(embaralhado).fingerprint == base.fingerprint
        assert _executar(list(reversed(populacao))).fingerprint == base.fingerprint

    @pytest.mark.parametrize("lote", [1, 7, 128, 512, 2048, 4096])
    def test_o_lote_nao_importa(self, lote: int) -> None:
        populacao = _populacao(40)

        def _em_lotes() -> Iterator[TrajectoryCandidate]:
            for inicio in range(0, len(populacao), lote):
                yield from populacao[inicio : inicio + lote]

        esperado = _executar(populacao)
        obtido = recuperador_de_trajetoria(profile=PERFIL).retrieve(
            query=pedido_ciente(k=5, key=CHAVE),
            snapshot=consulta_ciente(grid_index=ANCORA.minute, position=ANCORA),
            query_representation=representacao_de_trajetoria(**curva(de=-2.0, para=0.0)),
            candidates=_em_lotes(),
            reference_content_fingerprint=REFERENCIA,
        )
        assert obtido.fingerprint == esperado.fingerprint

    def test_a_ordem_das_linhas_de_lookback_nao_importa(self) -> None:
        """§171 — elas são indexadas por INSTANTE, e não por chegada."""
        montada, linhas = trajetoria(passado={h: _cheio(float(h)) for h in HORIZONS})
        invertidas = dict(reversed(list(linhas.items())))
        uma = build_representation(
            trajectory=montada,
            feature_keys=PERFIL.feature_keys,
            horizons=PERFIL.horizons,
            profile_fingerprint=PERFIL.fingerprint,
            anchor_values=_cheio(0.0),
            anchor_availabilities=dict.fromkeys(CINCO_EIXOS, "AVAILABLE"),
            rows=linhas,
        )
        outra = build_representation(
            trajectory=montada,
            feature_keys=PERFIL.feature_keys,
            horizons=PERFIL.horizons,
            profile_fingerprint=PERFIL.fingerprint,
            anchor_values=_cheio(0.0),
            anchor_availabilities=dict.fromkeys(CINCO_EIXOS, "AVAILABLE"),
            rows=invertidas,
        )
        assert uma.fingerprint == outra.fingerprint

    def test_a_impressao_da_trajetoria_e_estavel(self) -> None:
        uma, _ = trajetoria(passado={h: _cheio(float(h)) for h in HORIZONS})
        outra, _ = trajetoria(passado={h: _cheio(float(h)) for h in HORIZONS})
        assert uma.fingerprint == outra.fingerprint


class TestOPrefixoDoK:
    """§125, §235 — com empate em cada um dos três primeiros critérios."""

    def test_o_prefixo_vale_na_populacao_geral(self) -> None:
        populacao = _populacao(40)
        grande = _executar(populacao, k=20)
        for k in (1, 3, 7, 10):
            pequeno = _executar(populacao, k=k)
            assert [v.anchor_key.text for v in grande.top(k)] == [
                v.anchor_key.text for v in pequeno.neighbors
            ]

    def test_com_empate_em_D_T_e_em_celulas(self) -> None:
        """Seis candidatos idênticos: só a chave os separa."""
        iguais = [
            candidato_de_trajetoria(match=f"ref-{letra}", **curva(de=-2.0, para=0.0))
            for letra in "abcdef"
        ]
        grande = _executar(iguais, k=6)
        assert len({v.trajectory_dissimilarity for v in grande.neighbors}) == 1
        assert len({v.shared_cells for v in grande.neighbors}) == 1
        for k in (1, 2, 3, 4, 5):
            pequeno = _executar(iguais, k=k)
            assert [v.anchor_key.text for v in grande.top(k)] == [
                v.anchor_key.text for v in pequeno.neighbors
            ]

    def test_com_empate_em_D_T_e_HORIZONTES_diferentes(self) -> None:
        """§122 — o desempate que este PR acrescentou.

        A CONSTRUÇÃO EXIGIU DEZ EIXOS, e o motivo é aritmético. Todos os
        candidatos de uma query compartilham a MESMA âncora — o alinhamento é
        exato —, logo os slots ESTRUTURAIS são idênticos para todos: a única
        variação possível entre candidatos é a de disponibilidade de FEATURE.

        Com `m = 5`, um horizonte é evidencial com quatro eixos, e não há como
        formar dois grupos com o mesmo número de células e contagens de
        horizonte diferentes. Com `m = 10`, há:

            grupo A   2 horizontes x 9 eixos = 18 células, 2 evidenciais
            grupo B   3 horizontes x 6 eixos = 18 células, 3 evidenciais

        Os dois têm `D_T = 12/30` — nenhuma discrepância observada, doze
        células ausentes — e o mesmo `s`. Só os horizontes os separam, e o
        grupo B tem de vir antes.
        """
        from tests.support.availability_fixtures import DEZ_EIXOS

        perfil_dez = perfil_de_trajetoria(eixos=DEZ_EIXOS)
        assert perfil_dez.cell_count == 30

        def _n(quantos: int) -> dict[str, float | None]:
            return dict.fromkeys(DEZ_EIXOS[:quantos], 0.0)

        query = representacao_de_trajetoria(
            profile=perfil_dez,
            **com_horizontes(agora=_n(10), horizontes={h: _n(10) for h in HORIZONS}),
        )
        dois = [
            candidato_de_trajetoria(
                match=f"ref-b-dois-{i}",
                profile=perfil_dez,
                **com_horizontes(agora=_n(10), horizontes={1: _n(9), 3: _n(9), 5: _n(0)}),
            )
            for i in range(2)
        ]
        tres = [
            candidato_de_trajetoria(
                match=f"ref-a-tres-{i}",
                profile=perfil_dez,
                **com_horizontes(agora=_n(10), horizontes={1: _n(6), 3: _n(6), 5: _n(6)}),
            )
            for i in range(2)
        ]
        alvo = recuperador_de_trajetoria(profile=perfil_dez)
        populacao = [*dois, *tres]

        def _rodar(k: int) -> TrajectoryRetrievalResult:
            return alvo.retrieve(
                query=pedido_ciente(k=k, key=CHAVE),
                snapshot=consulta_ciente(grid_index=ANCORA.minute, position=ANCORA),
                query_representation=query,
                candidates=list(populacao),
                reference_content_fingerprint=REFERENCIA,
            )

        grande = _rodar(4)
        assert grande.returned_k == 4
        assert {v.trajectory_dissimilarity for v in grande.neighbors} == {12 / 30}
        assert {v.shared_cells for v in grande.neighbors} == {18}
        assert [v.shared_horizons for v in grande.neighbors] == [3, 3, 2, 2]
        # OS DE TRÊS HORIZONTES VÊM ANTES, apesar de a chave deles ser MENOR
        # só por construção — o teste os nomeou para que a ordem alfabética
        # coincidisse, e o que decide é o horizonte.
        assert [v.anchor_key.match_key for v in grande.neighbors[:2]] == [
            "ref-a-tres-0",
            "ref-a-tres-1",
        ]
        for k in (1, 2, 3):
            assert [v.anchor_key.text for v in grande.top(k)] == [
                v.anchor_key.text for v in _rodar(k).neighbors
            ]


# ================================================= a exaustividade ==


class TestAVarreduraEhExaustiva:
    """§118, §119, §244."""

    def test_a_soma_das_tres_contagens_e_o_universo(self) -> None:
        populacao = _populacao(40)
        resultado = _executar(populacao, k=3)
        assert (
            (
                resultado.trajectory_eligible_count
                + resultado.trajectory_ineligible_count
                + resultado.structural_ineligible_count
            )
            == resultado.universe_count
            == len(populacao)
        )
        assert resultado.exhaustive

    def test_os_elegiveis_sao_MEDIDOS_e_nao_devolvidos(self) -> None:
        resultado = _executar(_populacao(40), k=1)
        assert resultado.returned_k == 1
        assert resultado.trajectory_eligible_count == 40

    def test_o_melhor_pode_ser_o_ULTIMO_da_varredura(self) -> None:
        ruins = [
            candidato_de_trajetoria(match=f"ref-{i:03d}", **curva(de=5.0, para=-5.0))
            for i in range(30)
        ]
        melhor = candidato_de_trajetoria(match="ref-zzz", **curva(de=-2.0, para=0.0))
        resultado = _executar([*ruins, melhor], k=1)
        assert resultado.neighbors[0].anchor_key.match_key == "ref-zzz"
        assert resultado.neighbors[0].trajectory_dissimilarity == 0.0

    def test_o_candidato_de_UM_horizonte_e_contado_e_nao_entra(self) -> None:
        """§86, §87 — o sentinela da trajetória quase vazia.

        A ÂNCORA É A MESMA de todos: sob alinhamento exato, ela tem de ser. O
        que o torna quase vazio é a DISPONIBILIDADE DE FEATURE — os horizontes
        de três e cinco minutos não têm eixo nenhum utilizável.
        """
        oco = candidato_de_trajetoria(
            match="ref-oco",
            **com_horizontes(agora=_cheio(0.0), horizontes={1: _cheio(0.0), 3: {}, 5: {}}),
        )
        cheio = candidato_de_trajetoria(match="ref-cheio", **curva(de=3.0, para=-3.0))
        resultado = _executar([oco, cheio], k=5)
        assert resultado.returned_k == 1
        assert resultado.neighbors[0].anchor_key.match_key == "ref-cheio"
        assert resultado.trajectory_ineligible_count == 1


# ================================================= o universo ==


class TestOUniversoNaoMudou:
    """§6, §7, §236 — a trajetória muda COMO se compara, e não QUEM."""

    def test_a_impressao_do_universo_e_a_do_PR_06_2(self) -> None:
        from sports_intelligence.domain.retrieval.availability_exact import (
            AvailabilityAwareHistoricalRetriever,
        )
        from sports_intelligence.domain.retrieval.candidate_policy import (
            DEFAULT_CANDIDATE_POLICY,
        )
        from tests.support.availability_fixtures import candidato_ciente, distancia_ciente

        populacao = _populacao(12)
        trajetoria_resultado = _executar(populacao, k=5)

        # O MESMO UNIVERSO, pelo caminho do PR-06.2: mesmas chaves, mesmos
        # digestos de âncora — é isso que a identidade semântica cobre.
        estado = AvailabilityAwareHistoricalRetriever(
            policy=DEFAULT_CANDIDATE_POLICY,
            profile=perfil_ciente(),
            distance=distancia_ciente(perfil_ciente()),
        ).retrieve(
            query=pedido_ciente(k=5, key=CHAVE),
            snapshot=consulta_ciente(grid_index=ANCORA.minute, position=ANCORA),
            candidates=[
                candidato_ciente(
                    match=c.match_id,
                    grid_index=ANCORA.minute,
                    position=ANCORA,
                    valores=_cheio(0.0),
                )
                for c in populacao
            ],
            reference_content_fingerprint=REFERENCIA,
        )
        assert trajetoria_resultado.universe_count == estado.universe_count
        assert (
            trajetoria_resultado.candidate_policy_fingerprint == estado.candidate_policy_fingerprint
        )

    def test_um_candidato_de_outra_competicao_PARA(self) -> None:
        """§9, §174."""
        from sports_intelligence.domain.shared.errors import ValidationError

        with pytest.raises(ValidationError, match="ajustada por competição"):
            _executar(
                [
                    candidato_de_trajetoria(match="ref-a", **curva(de=0.0, para=1.0)),
                    candidato_de_trajetoria(
                        match="ref-b", competition=LIGA_B, **curva(de=0.0, para=1.0)
                    ),
                ]
            )

    def test_uma_ancora_em_outro_instante_PARA(self) -> None:
        """§10 — o alinhamento da ÂNCORA continua exato."""
        from sports_intelligence.domain.shared.errors import ValidationError

        with pytest.raises(ValidationError, match="ÂNCORA é EXATA"):
            _executar(
                [
                    candidato_de_trajetoria(
                        match="ref-a", anchor=ANCORA_49, **curva(de=0.0, para=1.0)
                    )
                ]
            )

    def test_a_propria_partida_e_excluida_como_ESTRUTURAL(self) -> None:
        resultado = _executar(
            [
                candidato_de_trajetoria(match="eva-001", **curva(de=0.0, para=1.0)),
                candidato_de_trajetoria(match="ref-a", **curva(de=0.0, para=1.0)),
            ]
        )
        assert resultado.structural_ineligible_count == 1
        assert resultado.trajectory_ineligible_count == 0
        assert resultado.returned_k == 1


# ================================================= a evidência ==


class TestTodaEvidenciaReconstroi:
    """§110, §242 — sobre toda a população."""

    def test_toda_evidencia_fecha_a_conta(self) -> None:
        for vizinho in _executar(_populacao(40), k=20).neighbors:
            prova = vizinho.evidence
            assert prova.is_reconstructible
            assert (
                prova.observed_sum + prova.missing_penalty_sum
            ) / prova.coverage.cell_count == vizinho.trajectory_dissimilarity
            assert prova.missing_penalty_sum == float(15 - vizinho.shared_cells)

    def test_as_mascaras_sao_consistentes(self) -> None:
        for vizinho in _executar(_populacao(24), k=10).neighbors:
            prova = vizinho.evidence
            for q, c, s in zip(
                prova.query_cell_mask,
                prova.candidate_cell_mask,
                prova.shared_cell_mask,
                strict=True,
            ):
                assert (s == "1") == (q == "1" and c == "1")

    def test_a_abertura_por_horizonte_soma_o_observado(self) -> None:
        for vizinho in _executar(_populacao(24), k=10).neighbors:
            conta = vizinho.evidence.breakdown
            assert sum(c.observed for c in conta.horizons) == pytest.approx(conta.observed_sum)
            assert sum(c.missing_penalty for c in conta.horizons) == pytest.approx(
                conta.missing_penalty_sum
            )

    def test_a_impressao_da_evidencia_e_estavel_sob_permutacao(self) -> None:
        populacao = _populacao(24)
        base = {
            v.anchor_key.text: v.evidence.fingerprint for v in _executar(populacao, k=10).neighbors
        }
        sorteio = random.Random(11)
        for _ in range(5):
            embaralhado = populacao[:]
            sorteio.shuffle(embaralhado)
            atual = {
                v.anchor_key.text: v.evidence.fingerprint
                for v in _executar(embaralhado, k=10).neighbors
            }
            assert atual == base


# ================================================= a janela, em volume ==


class TestAJanelaSobreTodaAGrade:
    """A aritmética period-local, exercitada em todo minuto da grade."""

    def test_nenhum_lookback_atravessa_o_periodo(self) -> None:
        for fase, primeiro, ultimo in (
            (Period.FIRST_HALF, 1, 45),
            (Period.SECOND_HALF, 46, 90),
            (Period.EXTRA_TIME_FIRST, 91, 105),
            (Period.EXTRA_TIME_SECOND, 106, 120),
        ):
            for minuto in range(primeiro, ultimo + 1):
                ancora = GridTimePoint.of(fase, minuto)
                for slot in DEFAULT_TRAJECTORY_WINDOW.resolve(ancora, grid=GRADE):
                    if slot.target is None:
                        continue
                    assert slot.target.period is fase
                    assert slot.target.minute >= primeiro
                    assert slot.target.minute == minuto - slot.horizon_minutes

    def test_os_primeiros_minutos_de_cada_periodo_perdem_horizontes(self) -> None:
        """§36, §193 — a atrição de começo de período, medida."""
        esperado = {46: 0, 47: 1, 48: 1, 49: 2, 50: 2, 51: 3}
        for minuto, disponiveis in esperado.items():
            slots = DEFAULT_TRAJECTORY_WINDOW.resolve(
                GridTimePoint.of(Period.SECOND_HALF, minuto), grid=GRADE
            )
            assert sum(1 for s in slots if s.status.is_available) == disponiveis


class TestOsPisosEfetivosSaoConsistentes:
    """§21 ao §24 do adendo — as quatro propriedades do piso efetivo.

    ELAS EXISTEM PORQUE UM PISO É UMA FRONTEIRA, e uma fronteira só está certa
    se os dois lados dela estão: o valor exato passa, e o anterior não. Um teste
    que só verificasse o lado de dentro aceitaria um piso frouxo demais, e um
    que só verificasse o de fora aceitaria um piso apertado demais.

    A FAIXA VAI ATÉ `m = 2000` de propósito. `n = 6000` é muito além de qualquer
    perfil real, e é justamente aí que uma derivação em ponto flutuante começaria
    a divergir da exata — a propriedade cobre o alcance em que ela ainda não
    diverge E o alcance em que ela divergiria.
    """

    def test_o_piso_efetivo_NUNCA_decresce_com_o_perfil(self) -> None:
        """§21 — mais eixos nunca exigem MENOS evidência.

        UM PISO QUE CAÍSSE seria um convite a resolver perfis maiores para
        passar com menos: acrescentar um eixo ao perfil da competição relaxaria
        a exigência sobre todo par, e a atrição melhoraria sem que dado nenhum
        tivesse melhorado.
        """
        anterior_celulas = 0
        anterior_eixos = 0
        for m in range(1, 2001):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            assert pisos.effective_shared_cell_floor >= anterior_celulas
            assert pisos.effective_horizon_axis_floor >= anterior_eixos
            anterior_celulas = pisos.effective_shared_cell_floor
            anterior_eixos = pisos.effective_horizon_axis_floor

    def test_o_valor_EXATO_do_piso_e_admitido(self) -> None:
        """§22 — o piso é `>=`, e não `>`. A fronteira pertence ao lado de dentro."""
        for m in range(4, 401):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            piso = pisos.effective_shared_cell_floor
            assert DEFAULT_TRAJECTORY_COVERAGE.admits_pair(
                shared_cells=piso, cell_count=pisos.total_trajectory_cells, shared_horizons=2
            ), f"m = {m}: o proprio piso {piso} foi recusado"

    def test_o_ANTECESSOR_do_piso_e_recusado(self) -> None:
        """§23 — e o lado de fora também pertence a ele. Um a menos NÃO passa."""
        for m in range(4, 401):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            piso = pisos.effective_shared_cell_floor
            assert not DEFAULT_TRAJECTORY_COVERAGE.admits_pair(
                shared_cells=piso - 1,
                cell_count=pisos.total_trajectory_cells,
                shared_horizons=2,
            ), f"m = {m}: {piso - 1} passou, e o piso e {piso}"

    def test_a_derivacao_e_INTEIRA_em_toda_a_faixa(self) -> None:
        """§24 — `E_s` bate com a fórmula exata, e o tipo é `int`.

        A FÓRMULA É REESCRITA AQUI DE PROPÓSITO. O teste não chama o mesmo
        helper que o motor chama: ele compara contra `-((-a) // b)` escrito à
        mão, porque um erro dentro de `ceil_div` passaria despercebido se os
        dois lados da igualdade viessem do mesmo lugar.
        """
        for m in range(1, 2001):
            n = 3 * m
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            esperado = max(8, -((-3 * n) // 5))
            assert pisos.effective_shared_cell_floor == esperado
            assert type(pisos.effective_shared_cell_floor) is int
            assert pisos.effective_horizon_axis_floor == max(4, -((-3 * m) // 5))
            assert type(pisos.effective_horizon_axis_floor) is int

    def test_a_derivacao_em_FLOAT_divergiria_e_o_ponto_e_medido(self) -> None:
        """§4 — onde a versão ingênua começa a errar.

        DENTRO DA FAIXA REAL AS DUAS CONCORDAM, e dizer o contrário seria falso.
        Foram medidos os dois milhões de primeiros `n` e não há UMA divergência
        — a justificativa da aritmética inteira não é que o float erre num
        perfil de futebol.

        A JUSTIFICATIVA É OUTRA, e ela é mais forte: a versão inteira é exata
        POR CONSTRUÇÃO, e a de ponto flutuante é correta apenas sob um argumento
        de arredondamento que precisaria ser reestabelecido a cada mudança de
        numerador, de denominador ou de faixa. E o argumento tem fim: em
        `n = 9_999_999_999_999_997` as duas divergem por DOIS.
        """
        divergencias = [n for n in range(1, 2_000_001) if math.ceil(0.6 * n) != -((-3 * n) // 5)]
        assert divergencias == []

        fora_da_faixa = 9_999_999_999_999_997
        assert math.ceil(0.6 * fora_da_faixa) == 5_999_999_999_999_997
        assert -((-3 * fora_da_faixa) // 5) == 5_999_999_999_999_999


class TestOAlcanceDoMinimoAbsoluto:
    """§10 do gate — o mínimo absoluto é alcançável, e nunca DOMINA sozinho.

    A ESPECIFICAÇÃO PEDIU UM GOLDEN QUE NÃO EXISTE. Ela pediu um caso em que o
    piso absoluto dominasse ESTRITAMENTE o racional dentro do domínio
    admissível da V1 — e esse caso é vazio. A prova é elementar, e está aqui
    escrita como teste para que ela não precise ser refeita de cabeça:

        piso racional = ceil(3n/5) = ceil(9m/5)      porque n = 3m

        m = 4   ->  ceil(36/5) =  8   EMPATA com o absoluto
        m > 4   ->  ceil(9m/5) >  8   o racional DOMINA

    e `minimum_profile_axes = 4` corta exatamente no ponto de empate. Logo:

        para todo perfil admissível, absoluto <= racional

    Isso NÃO é defeito de produto, de implementação ou de política. É um
    defeito do GOLDEN pedido, e a classificação honesta dele é o que este
    módulo registra.
    """

    def test_o_piso_racional_e_ceil_de_9m_sobre_5(self) -> None:
        """`n = 3m`, logo `ceil(3n/5)` é `ceil(9m/5)`. A identidade primeiro."""
        for m in range(1, 1001):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            assert pisos.ratio_shared_cell_floor == -((-9 * m) // 5)

    def test_em_m_igual_a_4_os_dois_EMPATAM(self) -> None:
        """`ceil(36/5) = 8`, e o absoluto é 8. O menor perfil admissível."""
        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(4)
        assert pisos.absolute_shared_cell_floor == 8
        assert pisos.ratio_shared_cell_floor == 8
        assert pisos.effective_shared_cell_floor == 8

    def test_para_m_maior_que_4_o_racional_DOMINA(self) -> None:
        """§10 — `m > 4  =>  ceil(9m/5) > 8`, sem exceção na faixa varrida."""
        for m in range(5, 2001):
            racional = DEFAULT_TRAJECTORY_COVERAGE.floors(m).ratio_shared_cell_floor
            assert racional > 8, f"m = {m} deu piso racional {racional}"

    def test_o_absoluto_NUNCA_domina_estritamente_no_dominio_admissivel(self) -> None:
        """A afirmação inteira, varrida: `m >= 4  =>  absoluto <= racional`.

        E COM ELA A CONSEQUÊNCIA QUE IMPORTA: o piso efetivo é SEMPRE o
        racional para todo perfil que a política admite. O mínimo absoluto de
        oito é um chão que, sob a V1, nunca é o teto de ninguém — ele existe
        para o caso em que a política mudar, e não para o caso corrente.
        """
        minimo = DEFAULT_TRAJECTORY_COVERAGE.minimum_profile_axes
        assert minimo == 4
        for m in range(minimo, 2001):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            assert pisos.absolute_shared_cell_floor <= pisos.ratio_shared_cell_floor
            assert pisos.effective_shared_cell_floor == pisos.ratio_shared_cell_floor
            assert pisos.shared_floor_is_rational

    def test_abaixo_do_dominio_admissivel_o_absoluto_DOMINA(self) -> None:
        """E ele domina — só que ali o perfil não é admissível.

        ESTE É O TESTE QUE MOSTRA QUE O CHÃO FUNCIONA. Em `m <= 3` o racional
        cai abaixo de oito e o `max` segura o piso em oito; a política apenas
        nunca chega lá, porque `admits_profile` recusa antes.
        """
        for m in (1, 2, 3):
            pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(m)
            assert pisos.ratio_shared_cell_floor < 8
            assert pisos.effective_shared_cell_floor == 8
            assert not pisos.shared_floor_is_rational
            assert not DEFAULT_TRAJECTORY_COVERAGE.admits_profile(m)
