"""A régua das janelas móveis — fronteiras, períodos e determinismo.

O QUE ESTES TESTES PROVAM. Não são features (isso vem depois): são as
propriedades da RÉGUA. `(t-w, t]` é uma convenção, e uma convenção só vale se
for a mesma em todo lugar — dois trechos do motor com fronteiras opostas
produziriam contagens que diferem por um, e ninguém saberia qual está certa.

TRÊS COISAS SÃO VERIFICADAS AQUI:

    a fronteira      `t` entra, `t - w` não
    o período        a janela não atravessa o intervalo, e a distância entre
                     períodos NÃO EXISTE — a subtração levanta
    a ordem          entrada embaralhada, mesma saída
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.extraction.windows import (
    SECONDS_PER_MINUTE,
    WINDOWS_V1,
    PeriodLocalTime,
    RollingEventWindowSelector,
    RollingWindow,
)
from sports_intelligence.domain.features.projection import ProjectedEvent
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import PARTIDA
from tests.support.snapshot_fixtures import evento


def corte_em(minuto: int, periodo: Period = Period.SECOND_HALF) -> FeatureAsOf:
    return FeatureAsOf.at(PARTIDA, periodo, minuto)


def projetados(*eventos: object) -> tuple[ProjectedEvent, ...]:
    return tuple(ProjectedEvent(event=e) for e in eventos)  # type: ignore[arg-type]


class TestPeriodLocalTime:
    def test_o_tempo_local_soma_minuto_e_acrescimo(self) -> None:
        """`45+2` fica em 47 minutos locais — depois do 45, e nunca antes."""
        regular = PeriodLocalTime.of(Period.FIRST_HALF, 45)
        acrescimo = PeriodLocalTime.of(Period.FIRST_HALF, 45, 2)
        assert acrescimo > regular
        assert acrescimo.elapsed_seconds == 47 * SECONDS_PER_MINUTE

    def test_o_acrescimo_nao_colide_com_minuto_regular_do_periodo(self) -> None:
        """O primeiro tempo acaba em 45: nenhum minuto regular chega a 47."""
        acrescimo = PeriodLocalTime.of(Period.FIRST_HALF, 45, 2)
        assert acrescimo.period is Period.FIRST_HALF
        assert acrescimo.elapsed_seconds // SECONDS_PER_MINUTE == 47

    def test_a_distancia_entre_periodos_diferentes_e_recusada(self) -> None:
        """§16 — o corpus não publica a duração do intervalo."""
        primeiro = PeriodLocalTime.of(Period.FIRST_HALF, 45, 3)
        segundo = PeriodLocalTime.of(Period.SECOND_HALF, 46)
        with pytest.raises(ValidationError, match="não compartilham eixo"):
            primeiro.seconds_before(segundo)

    def test_45_mais_3_nao_e_o_minuto_48_do_segundo_tempo(self) -> None:
        """§13, §16 — os dois têm o mesmo número e não são o mesmo momento."""
        acrescimo = PeriodLocalTime.of(Period.FIRST_HALF, 45, 3)
        segundo = PeriodLocalTime.of(Period.SECOND_HALF, 48)
        assert acrescimo.elapsed_seconds == segundo.elapsed_seconds
        assert acrescimo != segundo
        assert not acrescimo.shares_axis_with(segundo)

    def test_a_ordem_entre_periodos_e_a_do_jogo(self) -> None:
        """Ordem existe; distância não. As duas coisas são diferentes."""
        assert PeriodLocalTime.of(Period.FIRST_HALF, 45, 3) < PeriodLocalTime.of(
            Period.SECOND_HALF, 46
        )

    def test_os_periodos_sem_cronometro_sao_reconhecidos(self) -> None:
        for fase in (Period.HALF_TIME, Period.PENALTY_SHOOTOUT, Period.FULL_TIME):
            assert not PeriodLocalTime.of(fase).has_running_clock
        for fase in (Period.FIRST_HALF, Period.SECOND_HALF):
            assert PeriodLocalTime.of(fase, 10).has_running_clock


class TestRollingWindow:
    def test_as_janelas_de_producao_sao_quatro(self) -> None:
        """§21 — 1, 3, 5 e 10 minutos, em ordem crescente."""
        assert [j.minutes for j in WINDOWS_V1] == [1, 3, 5, 10]
        assert list(WINDOWS_V1) == sorted(WINDOWS_V1)

    def test_a_janela_de_duracao_zero_e_recusada(self) -> None:
        with pytest.raises(ValidationError):
            RollingWindow(seconds=0)

    def test_a_janela_mais_fina_que_o_minuto_e_recusada(self) -> None:
        """§23 — a resolução do corpus é o minuto; 90s aparentaria precisão."""
        with pytest.raises(ValidationError, match="múltipla de um minuto"):
            RollingWindow(seconds=90)

    def test_o_evento_exatamente_em_t_entra(self) -> None:
        """§20, §152."""
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 63)
        assert RollingWindow.of_minutes(5).contains(corte, cutoff=corte)

    def test_o_evento_exatamente_em_t_menos_w_nao_entra(self) -> None:
        """§20, §151 — o início é EXCLUSIVO."""
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 63)
        fronteira = PeriodLocalTime.of(Period.SECOND_HALF, 58)
        assert not RollingWindow.of_minutes(5).contains(fronteira, cutoff=corte)

    def test_um_minuto_depois_da_fronteira_entra(self) -> None:
        """§153 — a precisão da fronteira, do lado de dentro."""
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 63)
        dentro = PeriodLocalTime.of(Period.SECOND_HALF, 59)
        assert RollingWindow.of_minutes(5).contains(dentro, cutoff=corte)

    def test_o_evento_do_futuro_nao_entra(self) -> None:
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 63)
        depois = PeriodLocalTime.of(Period.SECOND_HALF, 64)
        assert not RollingWindow.of_minutes(5).contains(depois, cutoff=corte)

    def test_o_evento_de_outro_periodo_nao_entra(self) -> None:
        """§15, §18, §154 — a janela é local ao período, sempre."""
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 47)
        primeiro_tempo = PeriodLocalTime.of(Period.FIRST_HALF, 45, 2)
        assert not RollingWindow.of_minutes(5).contains(primeiro_tempo, cutoff=corte)

    def test_a_janela_maior_contem_a_menor(self) -> None:
        """As janelas são aninhadas — e o indexador do extrator conta com isso."""
        corte = PeriodLocalTime.of(Period.SECOND_HALF, 63)
        momento = PeriodLocalTime.of(Period.SECOND_HALF, 61)
        contidas = [j.minutes for j in WINDOWS_V1 if j.contains(momento, cutoff=corte)]
        assert contidas == [3, 5, 10]

    def test_o_rotulo_alimenta_a_chave_da_feature(self) -> None:
        assert [j.label for j in WINDOWS_V1] == ["1m", "3m", "5m", "10m"]


class TestRollingEventWindowSelector:
    def _historia(self) -> tuple[ProjectedEvent, ...]:
        return projetados(
            evento("w-58", tipo=EventType.SHOT, minuto=58, sequencia=1),
            evento("w-59", tipo=EventType.SHOT, minuto=59, sequencia=2),
            evento("w-61", tipo=EventType.SHOT, minuto=61, sequencia=3),
            evento("w-63", tipo=EventType.SHOT, minuto=63, sequencia=4),
        )

    def test_seleciona_o_intervalo_aberto_fechado(self) -> None:
        selecao = RollingEventWindowSelector(RollingWindow.of_minutes(5)).select(
            self._historia(), as_of=corte_em(63)
        )
        assert [e.clock.minute for e in selecao.events] == [59, 61, 63]

    def test_a_ordem_da_entrada_nao_muda_a_selecao(self) -> None:
        """§26, §155 — a ordem é imposta, e não herdada."""
        direta = self._historia()
        invertida = tuple(reversed(direta))
        seletor = RollingEventWindowSelector(RollingWindow.of_minutes(10))
        assert [e.id for e in seletor.select(direta, as_of=corte_em(63)).events] == [
            e.id for e in seletor.select(invertida, as_of=corte_em(63)).events
        ]

    def test_eventos_do_primeiro_tempo_nao_entram_numa_janela_do_segundo(self) -> None:
        historia = projetados(
            evento(
                "w-ht",
                tipo=EventType.SHOT,
                minuto=45,
                stoppage=2,
                periodo=Period.FIRST_HALF,
                sequencia=1,
            ),
            evento("w-46", tipo=EventType.SHOT, minuto=46, sequencia=2),
        )
        selecao = RollingEventWindowSelector(RollingWindow.of_minutes(10)).select(
            historia, as_of=corte_em(47)
        )
        assert [e.clock.minute for e in selecao.events] == [46]

    def test_o_futuro_e_recusado_e_contado(self) -> None:
        """§28 — defesa em profundidade, visível em vez de silenciosa."""
        historia = projetados(
            evento("w-63", tipo=EventType.SHOT, minuto=63, sequencia=1),
            evento("w-70", tipo=EventType.SHOT, minuto=70, sequencia=2),
        )
        selecao = RollingEventWindowSelector(RollingWindow.of_minutes(10)).select(
            historia, as_of=corte_em(63)
        )
        assert selecao.size == 1
        assert selecao.refused_future == 1

    def test_a_selecao_vazia_e_um_resultado_e_nao_um_erro(self) -> None:
        selecao = RollingEventWindowSelector(RollingWindow.of_minutes(1)).select(
            (), as_of=corte_em(63)
        )
        assert selecao.size == 0
        assert selecao.refused_future == 0
