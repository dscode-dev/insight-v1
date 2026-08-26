"""As INVARIANTES do PR-05.3 — o gate do §148 ao §163 e do §198 ao §203.

    §198  Snapshot(F<=t)  =  Snapshot(F<=t mais F>t)
    §199  e ∈ Window_w(t) ⟺ period(e)=period(t) ∧ t-w < Effective(e) ≤ t
    §200  visibilidade ← KnowledgeTime;  membresia ← EffectiveTime
    §201  ObservedZero ≠ Unavailable
    §202  MissingXG    ≠ 0
    §203  mesmo corpus + estado + fatos efetivos + espaço ⇒ mesmo snapshot

A DIFERENÇA ENTRE ESTES TESTES E OS DE UNIDADE. Os de unidade conferem os
setenta e cinco números de um corte contra uma tabela escrita à mão. Estes
provam propriedades sobre CONJUNTOS de entrada: «acrescentar qualquer fato do
futuro não muda nada», «qualquer permutação da entrada dá o mesmo resultado».
A segunda forma é a que pega o vazamento que ninguém pensou em testar.

O SENTINELA (§148) é o que transforma «passou» em «passou por bom motivo»: o
futuro carrega novecentos e noventa e nove fatos, e um snapshot que os
enxergasse mudaria de ordem de grandeza em vez de errar por uma unidade que se
confunde com ruído.
"""

from __future__ import annotations

import itertools
from typing import Final

import pytest

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.details import ShotOutcome
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.extraction.catalog import (
    FeatureSide,
    RollingFamily,
    rolling_definition,
)
from sports_intelligence.domain.features.extraction.windows import RollingWindow
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import CASA, FORA, PARTIDA, corte, relogio_de_parede
from tests.support.snapshot_fixtures import (
    ESPERADO_63,
    TODAS_AS_FAMILIAS,
    entrada,
    espaco,
    evento,
    extrair,
    id_de,
    primeiro_tempo,
    segundo_tempo_ate_o_corte,
)

pytestmark = pytest.mark.property

#: Quantos fatos absurdos o futuro sintético carrega (§148).
SENTINELAS: Final[int] = 999

SEM_EVENTO: Final[frozenset[CoverageFamily]] = frozenset(
    {CoverageFamily.MATCH, CoverageFamily.LINEUP}
)


def futuro_absurdo() -> tuple[CanonicalMatchEvent, ...]:
    """Novecentos e noventa e nove fatos depois do corte, de todas as famílias.

    ELE COBRE AS CINCO FAMÍLIAS MÓVEIS. Um sentinela só de chutes provaria que
    chutes não vazam e deixaria escanteios, gols e xG sem prova.
    """
    fatos: list[CanonicalMatchEvent] = []
    for n in range(SENTINELAS):
        minuto = 70 + (n % 20)
        tipo = (EventType.SHOT, EventType.GOAL, EventType.CORNER)[n % 3]
        fatos.append(
            evento(
                f"sentinela-{n}",
                tipo=tipo,
                minuto=minuto,
                sequencia=1000 + n,
                time=CASA if n % 2 else FORA,
                outcome=ShotOutcome.SAVED if tipo is EventType.SHOT else None,
                xg="0.99" if tipo in (EventType.SHOT, EventType.GOAL) else None,
            )
        )
    return tuple(fatos)


def valores(snapshot: FeatureSnapshot) -> dict[str, float | None]:
    return {f.definition_key: f.numeric for f in snapshot.features}


def disponibilidades(snapshot: FeatureSnapshot) -> dict[str, FeatureAvailability]:
    return {f.definition_key: f.availability for f in snapshot.features}


def digests(snapshot: FeatureSnapshot) -> dict[str, str]:
    return {f.definition_key: f.provenance.contribution_digest for f in snapshot.features}


# ------------------------------------------------------------------ §198 --


class TestFuturoNaoVaza:
    """`Snapshot(F<=t) = Snapshot(F<=t mais F>t)` — para qualquer `F>t`."""

    def test_novecentos_e_noventa_e_nove_fatos_do_futuro_nao_mudam_nada(self) -> None:
        passado = (*primeiro_tempo(), *segundo_tempo_ate_o_corte())
        so_passado = extrair(entrada(eventos=passado))
        com_futuro = extrair(entrada(eventos=(*passado, *futuro_absurdo())))
        assert valores(com_futuro) == valores(so_passado)
        assert digests(com_futuro) == digests(so_passado)
        assert com_futuro.fingerprint == so_passado.fingerprint

    def test_o_futuro_absurdo_nao_move_nenhuma_janela(self) -> None:
        passado = (*primeiro_tempo(), *segundo_tempo_ate_o_corte())
        com_futuro = extrair(entrada(eventos=(*passado, *futuro_absurdo())))
        for chave, esperado in ESPERADO_63.items():
            assert com_futuro.value_of(chave).numeric == pytest.approx(esperado), chave

    @pytest.mark.parametrize("minuto", [47, 52, 58, 60, 63, 75, 89])
    def test_a_propriedade_vale_em_todo_corte(self, minuto: int) -> None:
        """§198 vale para QUALQUER `t`, e não só para o de referência.

        O ruído começa aos 70: antes disso os dois snapshots precisam
        coincidir, e depois eles PRECISAM divergir — senão o teste estaria
        passando por estar cego em vez de por estar certo.
        """
        alvo = FeatureAsOf.at(PARTIDA, Period.SECOND_HALF, minuto)
        historia = (*primeiro_tempo(), *segundo_tempo_ate_o_corte())
        limpo = extrair(entrada(eventos=historia), as_of=alvo)
        ruidoso = extrair(entrada(eventos=(*historia, *futuro_absurdo())), as_of=alvo)
        if minuto >= 70:
            assert valores(ruidoso) != valores(limpo)
        else:
            assert valores(ruidoso) == valores(limpo)

    def test_o_resultado_publicado_nao_muda_o_snapshot_intra_jogo(self) -> None:
        """§149, §200 — o `MatchResult` é invisível antes do apito."""
        sem = extrair(entrada(result=None))
        com = extrair(entrada(result=MatchResult(regular_time=Score(home=9, away=0))))
        assert com.fingerprint == sem.fingerprint

    @pytest.mark.parametrize(
        "resultado",
        [
            None,
            MatchResult(regular_time=Score(home=0, away=0)),
            MatchResult(regular_time=Score(home=4, away=4)),
        ],
    )
    def test_qualquer_resultado_publicado_da_o_mesmo_snapshot(
        self, resultado: MatchResult | None
    ) -> None:
        assert extrair(entrada(result=resultado)).fingerprint == extrair().fingerprint


# ------------------------------------------------------------------ §199 --


class TestAFronteiraDaJanela:
    """`t - w < Effective(e) <= t`, e o período tem de ser o mesmo."""

    def _com_chute_em(self, minuto: int) -> FeatureSnapshot:
        return extrair(
            entrada(
                eventos=(
                    evento(
                        "fronteira",
                        tipo=EventType.SHOT,
                        minuto=minuto,
                        sequencia=90,
                        xg="0.10",
                    ),
                )
            )
        )

    def test_o_evento_em_t_entra(self) -> None:
        """§152."""
        assert self._com_chute_em(63).value_of("shots_home_5m").numeric == 1

    def test_o_evento_em_t_menos_w_nao_entra(self) -> None:
        """§151 — o início é exclusivo."""
        assert self._com_chute_em(58).value_of("shots_home_5m").numeric == 0

    def test_um_minuto_dentro_e_um_minuto_fora(self) -> None:
        """§153 — a precisão da fronteira, dos dois lados."""
        assert self._com_chute_em(59).value_of("shots_home_5m").numeric == 1
        assert self._com_chute_em(57).value_of("shots_home_5m").numeric == 0

    @pytest.mark.parametrize(("minuto", "esperado"), [(63, 1), (62, 0), (61, 0)])
    def test_a_janela_de_um_minuto_e_estreita(self, minuto: int, esperado: int) -> None:
        """`(62, 63]` contém APENAS o minuto 63.

        O minuto 62 é exatamente `t - w`, e o início é exclusivo (§19, §20). É
        a janela mais estreita do catálogo, e por isso a que mais expõe a
        convenção: com `[t-w, t]` ela conteria dois minutos, e a contagem de
        toda a família de um minuto dobraria.
        """
        assert self._com_chute_em(minuto).value_of("shots_home_1m").numeric == esperado

    def test_a_janela_nao_atravessa_o_periodo(self) -> None:
        """§154, §199 — nem no acréscimo, que é o caso mais tentador."""
        com = extrair(
            entrada(
                eventos=(
                    evento(
                        "acrescimo",
                        tipo=EventType.SHOT,
                        minuto=45,
                        stoppage=2,
                        periodo=Period.FIRST_HALF,
                        sequencia=91,
                        xg="0.10",
                    ),
                )
            ),
            as_of=FeatureAsOf.at(PARTIDA, Period.SECOND_HALF, 47),
        )
        assert com.value_of("shots_home_5m").numeric == 0
        assert com.value_of("shots_home_10m").numeric == 0

    def test_a_prorrogacao_nao_ve_o_segundo_tempo(self) -> None:
        """§121 — o mesmo princípio entre segundo tempo e prorrogação."""
        snapshot = extrair(
            entrada(eventos=segundo_tempo_ate_o_corte()),
            as_of=FeatureAsOf.at(PARTIDA, Period.EXTRA_TIME_FIRST, 92),
        )
        assert snapshot.value_of("shots_home_10m").numeric == 0


# ------------------------------------------------------------------ §200 --


class TestTempoEfetivoContraTempoDeConhecimento:
    """Membresia é do fato; visibilidade é do conhecimento."""

    def _com_correcao(self) -> tuple[CanonicalMatchEvent, ...]:
        """Chute aos 58, corrigido por um sucessor conhecido só aos 64 (§117)."""
        original = evento(
            "corrigido-58",
            tipo=EventType.SHOT,
            minuto=58,
            sequencia=80,
            outcome=ShotOutcome.SAVED,
            xg="0.30",
            status=EventStatus.CORRECTED,
        )
        sucessor = evento(
            "correcao-58",
            tipo=EventType.SHOT,
            minuto=58,
            sequencia=80,
            outcome=ShotOutcome.SAVED,
            xg="0.35",
            revision=2,
            supersedes=original.id,
            conhecido_em=relogio_de_parede(64),
        )
        return (original, sucessor)

    def _conhecimento(self) -> EventKnowledge:
        return EventKnowledge(by_event={id_de("correcao-58"): relogio_de_parede(64)})

    def test_a_correcao_recente_nao_traz_o_fato_para_a_janela(self) -> None:
        """§115, §117 — o fato continua sendo dos 58, e `(60,65]` não o contém."""
        snapshot = extrair(
            entrada(eventos=self._com_correcao(), knowledge=self._conhecimento()),
            as_of=corte(65, conhecimento=70),
        )
        assert snapshot.value_of("shots_home_5m").numeric == 0

    def test_o_fato_corrigido_conta_uma_vez_so_na_janela_que_o_contem(self) -> None:
        """A cadeia é resolvida: um chute, e não dois."""
        snapshot = extrair(
            entrada(eventos=self._com_correcao(), knowledge=self._conhecimento()),
            as_of=corte(65, conhecimento=70),
        )
        assert snapshot.value_of("shots_home_10m").numeric == 1

    def test_a_visibilidade_da_correcao_muda_o_valor_e_nao_a_posicao(self) -> None:
        """§116, §160 — o xG muda porque a correção entrou; a janela não muda."""
        antes = extrair(
            entrada(eventos=self._com_correcao(), knowledge=self._conhecimento()),
            as_of=corte(65, conhecimento=60),
        )
        depois = extrair(
            entrada(eventos=self._com_correcao(), knowledge=self._conhecimento()),
            as_of=corte(65, conhecimento=70),
        )
        assert antes.value_of("shots_home_10m").numeric == 1
        assert depois.value_of("shots_home_10m").numeric == 1
        assert antes.value_of("xg_home_10m").numeric == 0.30
        assert depois.value_of("xg_home_10m").numeric == 0.35

    def test_o_cancelamento_conhecido_antes_do_corte_remove_a_contribuicao(self) -> None:
        """§118, §161."""
        original = evento(
            "cancelavel-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=81,
            xg="0.30",
            status=EventStatus.CORRECTED,
        )
        cancelamento = evento(
            "cancelamento-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=81,
            xg="0.30",
            revision=2,
            supersedes=original.id,
            status=EventStatus.CANCELLED,
            conhecido_em=relogio_de_parede(62),
        )
        conhecimento = EventKnowledge(by_event={cancelamento.id: relogio_de_parede(62)})
        snapshot = extrair(
            entrada(eventos=(original, cancelamento), knowledge=conhecimento),
            as_of=corte(63, conhecimento=63),
        )
        assert snapshot.value_of("shots_home_3m").numeric == 0

    def test_o_cancelamento_ainda_desconhecido_preserva_o_fato(self) -> None:
        """§119 — em `AS_KNOWN`, o que ainda não se sabia não se aplica."""
        original = evento(
            "cancelavel-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=81,
            xg="0.30",
            status=EventStatus.CORRECTED,
        )
        cancelamento = evento(
            "cancelamento-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=81,
            xg="0.30",
            revision=2,
            supersedes=original.id,
            status=EventStatus.CANCELLED,
            conhecido_em=relogio_de_parede(70),
        )
        conhecimento = EventKnowledge(by_event={cancelamento.id: relogio_de_parede(70)})
        snapshot = extrair(
            entrada(eventos=(original, cancelamento), knowledge=conhecimento),
            as_of=corte(63, conhecimento=63),
        )
        assert snapshot.value_of("shots_home_3m").numeric == 1


# ------------------------------------------------------------------ §201 --


class TestZeroNaoEAusente:
    def test_zero_observado_e_ausencia_declarada_sao_snapshots_diferentes(self) -> None:
        """§156."""
        observado = extrair(entrada(eventos=segundo_tempo_ate_o_corte()))
        ausente = extrair(entrada(families=SEM_EVENTO), families=SEM_EVENTO)
        assert observado.value_of("corners_away_5m").numeric == 0
        assert ausente.value_of("corners_away_5m").numeric is None
        assert observado.fingerprint != ausente.fingerprint

    def test_nenhuma_feature_indisponivel_carrega_valor(self) -> None:
        ausente = extrair(entrada(families=SEM_EVENTO), families=SEM_EVENTO)
        for computada in ausente.features:
            if not computada.is_available:
                assert computada.numeric is None

    def test_a_ausencia_tem_motivo_tipado_e_nao_texto_livre(self) -> None:
        ausente = extrair(entrada(families=SEM_EVENTO), families=SEM_EVENTO)
        estados = {e for e in disponibilidades(ausente).values() if not e.is_available}
        assert estados <= set(FeatureAvailability)
        assert FeatureAvailability.NOT_DECLARED in estados


# ------------------------------------------------------------------ §202 --


class TestXgAusenteNaoEZero:
    def test_xg_zero_observado_continua_disponivel(self) -> None:
        """§157, primeira metade."""
        com_zero = extrair(
            entrada(
                eventos=(evento("zero", tipo=EventType.SHOT, minuto=62, sequencia=95, xg="0.0"),)
            )
        )
        computada = com_zero.value_of("xg_home_3m")
        assert computada.is_available
        assert computada.numeric == 0.0

    def test_xg_ausente_torna_a_soma_indisponivel(self) -> None:
        """§157, segunda metade — e as duas produzem valores diferentes."""
        sem_xg = extrair(
            entrada(eventos=(evento("sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=96),))
        )
        computada = sem_xg.value_of("xg_home_3m")
        assert not computada.is_available
        assert computada.availability is FeatureAvailability.PARTIAL_INPUT

    def test_um_chute_sem_xg_contamina_a_janela_inteira(self) -> None:
        """§50 — a política é conservadora por decisão declarada."""
        eventos = (
            evento("com-xg", tipo=EventType.SHOT, minuto=61, sequencia=97, xg="0.4"),
            evento("sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=98),
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert not snapshot.value_of("xg_home_3m").is_available
        # E a janela de UM minuto, que não contém o defeituoso, sobrevive.
        assert snapshot.value_of("xg_home_1m").is_available

    def test_a_contagem_de_chutes_nao_e_contaminada(self) -> None:
        """§158 — independência entre features da mesma família."""
        eventos = (
            evento("com-xg", tipo=EventType.SHOT, minuto=61, sequencia=97, xg="0.4"),
            evento("sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=98),
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert snapshot.value_of("shots_home_3m").numeric == 2


# --------------------------------------------------- §159 e as diferenças --


class TestDiferencas:
    def test_um_lado_indisponivel_torna_a_diferenca_indisponivel(self) -> None:
        """§159, §65 — nunca se completa o lado ausente com zero."""
        eventos = (
            evento("sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=99),
            evento(
                "fora-com-xg",
                tipo=EventType.SHOT,
                minuto=62,
                sequencia=100,
                time=FORA,
                xg="0.20",
            ),
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert not snapshot.value_of("xg_home_3m").is_available
        assert snapshot.value_of("xg_away_3m").is_available
        assert not snapshot.value_of("xg_diff_3m").is_available

    def test_a_diferenca_e_casa_menos_fora(self) -> None:
        snapshot = extrair()
        for prefixo in ("shots", "shots_on_target", "goals", "corners"):
            for janela in ("1m", "3m", "5m", "10m"):
                casa = snapshot.value_of(f"{prefixo}_home_{janela}").numeric
                fora = snapshot.value_of(f"{prefixo}_away_{janela}").numeric
                diff = snapshot.value_of(f"{prefixo}_diff_{janela}").numeric
                assert casa is not None, f"{prefixo}_{janela}"
                assert fora is not None, f"{prefixo}_{janela}"
                assert diff == casa - fora, f"{prefixo}_{janela}"

    def test_a_diferenca_de_estado_tambem_respeita_a_guarda(self) -> None:
        snapshot = extrair(entrada(families=SEM_EVENTO), families=SEM_EVENTO)
        assert not snapshot.value_of("score_difference").is_available


# ------------------------------------------------------------------ §203 --


class TestDeterminismo:
    def test_dez_extracoes_dao_a_mesma_impressao(self) -> None:
        impressoes = {extrair().fingerprint for _ in range(10)}
        assert len(impressoes) == 1

    @pytest.mark.parametrize("giro", [1, 3, 5, 7])
    def test_rotacionar_a_entrada_nao_muda_o_snapshot(self, giro: int) -> None:
        """§155 — valores, digests de procedência e impressão."""
        fatos = segundo_tempo_ate_o_corte()
        girada = (*fatos[giro:], *fatos[:giro])
        direto = extrair(entrada(eventos=fatos))
        girado = extrair(entrada(eventos=girada))
        assert valores(girado) == valores(direto)
        assert digests(girado) == digests(direto)
        assert girado.fingerprint == direto.fingerprint

    def test_a_entrada_invertida_produz_o_mesmo_snapshot(self) -> None:
        fatos = segundo_tempo_ate_o_corte()
        assert (
            extrair(entrada(eventos=tuple(reversed(fatos)))).fingerprint
            == extrair(entrada(eventos=fatos)).fingerprint
        )

    def test_toda_permutacao_de_um_recorte_da_o_mesmo_snapshot(self) -> None:
        """Cento e vinte ordens, um snapshot (§87, §155)."""
        recorte = segundo_tempo_ate_o_corte()[:5]
        impressoes = {
            extrair(entrada(eventos=ordem)).fingerprint for ordem in itertools.permutations(recorte)
        }
        assert len(impressoes) == 1

    def test_corpus_diferente_muda_a_impressao(self) -> None:
        outro = frozenset(TODAS_AS_FAMILIAS)
        primeiro = extrair(families=outro)
        from sports_intelligence.domain.features.extraction.context import (
            MatchFeatureExtractionContext,
        )
        from sports_intelligence.domain.features.extraction.extractor import (
            MatchStateFeatureExtractor,
        )
        from sports_intelligence.domain.features.state.builder import (
            HistoricalMatchStateBuilder,
        )
        from tests.support.feature_fixtures import origem
        from tests.support.snapshot_fixtures import catalogo
        from tests.support.snapshot_fixtures import espaco as espaco_de_producao

        politica = TemporalAvailabilityPolicy.default()
        fonte = origem(families=outro, fingerprint="e" * 64)
        build = HistoricalMatchStateBuilder(policy=politica).build(
            entrada(), as_of=corte(), source=fonte
        )
        segundo = MatchStateFeatureExtractor().extract(
            MatchFeatureExtractionContext.of(
                build,
                space=espaco_de_producao(),
                catalog=catalogo(),
                source=fonte,
                policy=politica,
            )
        )
        assert segundo.fingerprint != primeiro.fingerprint

    def test_politica_diferente_muda_a_impressao(self) -> None:
        estrita = extrair(policy=TemporalAvailabilityPolicy.strict_observed())
        assert estrita.fingerprint != extrair().fingerprint

    def test_modo_temporal_diferente_muda_a_impressao(self) -> None:
        final = extrair(as_of=corte(mode=TemporalMode.CANONICAL_FINAL))
        assert final.fingerprint != extrair().fingerprint


# ------------------------------------------------------------------ §163 --


class TestMudancaDeEspaco:
    def test_trocar_a_janela_muda_a_identidade_da_feature(self) -> None:
        cinco = rolling_definition(
            family=RollingFamily.SHOT,
            side=FeatureSide.HOME,
            window=RollingWindow.of_minutes(5),
        )
        dez = rolling_definition(
            family=RollingFamily.SHOT,
            side=FeatureSide.HOME,
            window=RollingWindow.of_minutes(10),
        )
        assert cinco.key != dez.key
        assert cinco.fingerprint != dez.fingerprint

    def test_o_espaco_entra_na_impressao_do_snapshot(self) -> None:
        """§163 — mudar o espaço muda o snapshot, mesmo com os mesmos fatos."""
        from dataclasses import replace

        base = extrair()
        reduzido = replace(
            base,
            space=replace(espaco(), version=espaco().version.__class__(major=2, minor=0)),
        )
        assert reduzido.fingerprint != base.fingerprint
