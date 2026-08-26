"""O custo da projeção efetiva — 100.000 eventos e revisões.

POR QUE ESTE BENCHMARK EXISTE, e por que ele é o ÚNICO deste PR (§146). Não há
feature real para medir: o que este PR entrega são contratos e guardas. A
projeção é a única peça que de fato PROCESSA volume — ela ordena a história,
avalia cada evento contra o corte e resolve a cadeia de revisão —, e uma
implementação ingênua dela viraria o gargalo de toda a fase seguinte.

    CORRETUDE TEMPORAL > THROUGHPUT (§148)

O número aqui não é uma meta. Ele é um ponto de comparação: se a projeção
passar a custar dez vezes mais depois de uma mudança, alguém precisa saber.

ELE NÃO PRECISA DE BANCO. A projeção é pura — recebe eventos em memória,
devolve a visão efetiva. Um benchmark que subisse PostgreSQL para medi-la
mediria o PostgreSQL.
"""

from __future__ import annotations

from typing import Final

import pytest

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.projection import EffectiveEventProjection
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.shared.temporal import Period
from tests.performance.test_resolution_100k import _relatar
from tests.support.feature_fixtures import _id, corte, evento
from tests.support.instrumentation import medindo

pytestmark = pytest.mark.performance

#: O volume do §147. Cem mil eventos é a ordem de grandeza de uma temporada
#: inteira de uma liga com dado evento a evento.
EVENTOS: Final[int] = 100_000

#: Uma correção a cada vinte eventos. A proporção é generosa de propósito: a
#: cadeia de revisão é a parte mais cara da projeção, e um cenário sem correção
#: mediria só a ordenação.
A_CADA: Final[int] = 20


def _historia_grande() -> tuple[CanonicalMatchEvent, ...]:
    """Cem mil eventos com revisões, em ordem EMBARALHADA de propósito.

    A ORDEM DA ENTRADA É RUIM DE PROPÓSITO: a projeção ordena, e medir sobre
    uma entrada já ordenada esconderia o custo dessa ordenação — que é
    justamente o que o volume torna caro.
    """
    eventos: list[CanonicalMatchEvent] = []
    for n in range(EVENTOS):
        minuto = n % 90
        periodo = Period.FIRST_HALF if minuto < 45 else Period.SECOND_HALF
        e_revisao = n % A_CADA == 0 and n > 0
        eventos.append(
            evento(
                f"perf-{n}",
                minuto=minuto,
                periodo=periodo,
                tipo=EventType.SHOT if n % 3 else EventType.PASS,
                sequencia=n,
                supersedes=_id(f"perf-{n - 1}") if e_revisao else None,
                revision=2 if e_revisao else 1,
                status=EventStatus.ACTIVE,
            )
        )
    # A ORDEM EMBARALHADA, e determinística: passo primo sobre o índice.
    return tuple(eventos[(i * 7919) % EVENTOS] for i in range(EVENTOS))


class TestAProjecaoEmVolume:
    def test_cem_mil_eventos_projetados(self) -> None:
        """§147. Duração, throughput e pico de memória."""
        historia = _historia_grande()
        projecao = EffectiveEventProjection.with_policy(TemporalAvailabilityPolicy.default())
        with medindo("projeção efetiva") as medida:
            resultado = projecao.project(historia, as_of=corte(63))

        _relatar(
            f"PR-05.1 · projeção efetiva de {EVENTOS:_} eventos",
            [
                f"duração          {medida.segundos:.2f}s · "
                f"{medida.por_segundo(EVENTOS):.0f} eventos/s",
                f"pico de memória  {medida.pico_mb:.0f} MB",
                "",
                f"entrada          {EVENTOS:_} eventos ({EVENTOS // A_CADA:_} revisões)",
                f"efetivos         {resultado.size:_}",
                f"excluídos        {resultado.excluded_total:_} · {resultado.excluded_by_reason}",
            ],
        )

        assert resultado.size > 0
        # O CRITÉRIO É A FORMA, e não o segundo: uma projeção quadrática sobre
        # cem mil eventos não terminaria em segundos nenhum.
        assert medida.segundos < 30, (
            f"a projeção levou {medida.segundos:.1f}s para cem mil eventos: o custo "
            "deixou de ser linear, e a fase seguinte herdaria isso"
        )

    def test_o_modo_retrospectivo_custa_o_mesmo(self) -> None:
        """A verdade retrospectiva muda o QUE entra, e não o custo de decidir.

        Se ela custasse muito mais, seria sinal de que o caminho canônico-final
        está refazendo trabalho — e a auditoria de um corpus grande passaria a
        ser inviável por acidente de implementação.
        """
        historia = _historia_grande()
        projecao = EffectiveEventProjection.with_policy(TemporalAvailabilityPolicy.default())
        with medindo("causal") as causal:
            projecao.project(historia, as_of=corte(63))
        with medindo("retrospectivo") as retrospectivo:
            projecao.project(historia, as_of=corte(63, mode=TemporalMode.CANONICAL_FINAL))
        _relatar(
            "PR-05.1 · projeção por modo temporal",
            [
                f"AS_KNOWN         {causal.segundos:.2f}s",
                f"CANONICAL_FINAL  {retrospectivo.segundos:.2f}s",
            ],
        )
        assert retrospectivo.segundos < causal.segundos * 3 + 1
