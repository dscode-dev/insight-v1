"""A janela móvel — e a régua que ela usa, que não é a do relógio de parede.

O PROBLEMA QUE ESTE MÓDULO EXISTE PARA NÃO RESOLVER ERRADO (§14 ao §17).
«Últimos cinco minutos» exige medir DISTÂNCIA entre dois pontos do jogo. A
forma óbvia é subtrair `minute`, e ela quebra no lugar mais comum do futebol:

    FIRST_HALF  45+3      um `minute` de 45 com 3 de acréscimo
    SECOND_HALF 46        um `minute` de 46

Achatar os dois numa linha contínua exigiria saber quanto durou o intervalo, e
o corpus não sabe. Qualquer conversão aqui seria invenção — e uma invenção que
quebra monotonicidade, porque `45+3` viraria «48» e ficaria DEPOIS de um
evento do segundo tempo que aconteceu antes dele no relógio da TV.

A DECISÃO V1 É A JANELA SER LOCAL AO PERÍODO (§15, §18). Uma janela nunca
atravessa o intervalo. Aos 47 do segundo tempo, a janela de cinco minutos
enxerga o segundo tempo e nada mais — nem os 45+3 do primeiro. Isso é decisão
declarada, e não acidente: a alternativa seria fabricar um relógio contínuo
que não existe.

    Window_w(t) = (t - w, t]            §19

INÍCIO EXCLUSIVO, FIM INCLUSIVO. O evento exatamente em `t` entra; o
exatamente em `t - w` não. A escolha é arbitrária como toda convenção de
intervalo, e o que importa é ela ser UMA — dois trechos do motor com
convenções opostas produziriam contagens que diferem por um e ninguém saberia
qual está certa.

A MEMBRESIA É POR TEMPO EFETIVO (§115, §116). Um chute dos 58 cuja correção só
ficou conhecida aos 64 continua sendo um fato dos 58: ele está fora de
`(60, 65]`. O tempo de conhecimento decide se o fato é VISÍVEL — isso já
aconteceu na projeção —, e nunca ONDE ele está na linha do tempo.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.features.projection import ProjectedEvent
from sports_intelligence.domain.features.temporal import FeatureAsOf, MatchTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import MatchClock, Period

#: Quantos segundos tem um minuto de relógio de partida. Nomeado porque ele
#: aparece na conversão e na definição das janelas, e dois `60` soltos são dois
#: lugares para alguém mudar um só.
SECONDS_PER_MINUTE: Final[int] = 60


@final
@dataclass(frozen=True, slots=True, order=True)
class PeriodLocalTime:
    """Uma posição medida DENTRO de um período, em segundos inteiros.

    POR QUE SEGUNDOS E NÃO MINUTOS (§23). O corpus tem resolução de minuto, e
    é tentador guardar minutos. Segundos custam o mesmo e deixam a régua
    pronta para uma fonte mais fina sem que a definição de janela mude de
    unidade — que é o tipo de mudança que reescreve toda impressão de feature.
    Continua sendo inteiro: `float` aqui traria `0.1 + 0.2` para dentro de uma
    comparação de fronteira.

    O EIXO É O PERÍODO. Dois `PeriodLocalTime` de períodos diferentes NÃO são
    comparáveis por subtração, e o tipo recusa a conta. Ordená-los é possível
    — `Period.order` vem primeiro — porque ordem total entre fases existe; o
    que não existe é DISTÂNCIA entre elas.

    `elapsed_seconds` VEM DE `minute + stoppage`, e isso é monotônico dentro
    de um período: o primeiro tempo vai de 0 a 45 e depois 45+1, 45+2 — que
    dão 46, 47 —, e nenhum minuto regular do primeiro tempo chega a 46. O
    mesmo vale para o segundo, que termina em 90 e continua em 90+1. Não há
    colisão entre minuto regular e acréscimo DENTRO do período, e é só dentro
    dele que a conta é usada.
    """

    #: A ordem da fase vem primeiro para que a comparação entre dois pontos de
    #: períodos diferentes ordene pelo jogo, e não pelo cronômetro local.
    _period_order: int
    elapsed_seconds: int

    def __post_init__(self) -> None:
        if self.elapsed_seconds < 0:
            raise ValidationError(f"tempo local negativo: {self.elapsed_seconds}s")

    @classmethod
    def of(cls, period: Period, minute: int = 0, stoppage: int = 0) -> Self:
        return cls(
            _period_order=period.order,
            elapsed_seconds=(minute + stoppage) * SECONDS_PER_MINUTE,
        )

    @classmethod
    def of_clock(cls, clock: MatchClock) -> Self:
        return cls.of(clock.period, clock.minute, clock.stoppage)

    @classmethod
    def of_position(cls, point: MatchTimePoint) -> Self:
        """A posição de um corte, sem o desempate por sequência.

        A SEQUÊNCIA NÃO ENTRA NA RÉGUA TEMPORAL, e a omissão é deliberada: ela
        desempata FATOS DO MESMO MINUTO, e não mede tempo. Usá-la aqui faria
        dois eventos do minuto 63 estarem a «uma unidade» um do outro, o que
        não é uma duração de coisa nenhuma.
        """
        return cls(
            _period_order=point.period.order,
            elapsed_seconds=(point.minute + point.stoppage) * SECONDS_PER_MINUTE,
        )

    @property
    def period(self) -> Period:
        return _FASE_POR_ORDEM[self._period_order]

    @property
    def has_running_clock(self) -> bool:
        """Se este período tem cronômetro correndo (§124).

        Intervalo, disputa de pênaltis e apito final não têm: `MatchClock` já
        recusa minuto diferente de zero neles. Uma janela móvel sobre um
        período sem cronômetro mediria a distância entre um ponto e ele mesmo.
        """
        return self.period.is_ball_in_play

    def shares_axis_with(self, other: PeriodLocalTime) -> bool:
        return self._period_order == other._period_order

    def seconds_before(self, other: PeriodLocalTime) -> int:
        """Quantos segundos este ponto está ANTES do outro, no mesmo período.

        ELA RECUSA PERÍODOS DIFERENTES (§16). «Quanto tempo entre 45+3 do
        primeiro tempo e 46 do segundo» não tem resposta no corpus — a duração
        do intervalo não está publicada em lugar nenhum, e devolver um número
        aqui seria inventá-la.
        """
        if not self.shares_axis_with(other):
            raise ValidationError(
                f"distância entre {self.period.value} e {other.period.value}: os dois "
                "períodos não compartilham eixo, e o corpus não publica a duração do "
                "intervalo entre eles (PR-05.3 §16, §17)"
            )
        return other.elapsed_seconds - self.elapsed_seconds

    def __str__(self) -> str:
        return f"{self.period.value}:{self.elapsed_seconds // SECONDS_PER_MINUTE}'"


_FASE_POR_ORDEM: Final[dict[int, Period]] = {fase.order: fase for fase in Period}


@final
@dataclass(frozen=True, slots=True, order=True)
class RollingWindow:
    """Uma janela `(t - w, t]`, medida em segundos inteiros (§19, §21, §23).

    ELA É UM VALOR, E ENTRA NA IMPRESSÃO DA FEATURE (§22). «Chutes nos últimos
    cinco minutos» e «chutes nos últimos dez» são features diferentes com a
    mesma forma — e o que as separa é este número. Deixá-lo fora da identidade
    permitiria trocar cinco por dez sem que nada denunciasse.
    """

    seconds: int

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValidationError(
                f"janela de {self.seconds}s: uma janela de duração zero ou negativa "
                "não contém intervalo nenhum"
            )
        if self.seconds % SECONDS_PER_MINUTE:
            # A RESOLUÇÃO DO CORPUS É O MINUTO. Uma janela de 90 segundos
            # produziria uma fronteira que nenhum evento consegue cruzar, e a
            # feature pareceria fina sem ser.
            raise ValidationError(
                f"janela de {self.seconds}s não é múltipla de um minuto — a resolução "
                "do corpus histórico é o minuto, e uma janela mais fina que o dado "
                "aparenta precisão que não existe"
            )

    @classmethod
    def of_minutes(cls, minutes: int) -> Self:
        return cls(seconds=minutes * SECONDS_PER_MINUTE)

    @property
    def minutes(self) -> int:
        return self.seconds // SECONDS_PER_MINUTE

    @property
    def label(self) -> str:
        """O sufixo que aparece na chave da feature: `1m`, `5m`, `10m`."""
        return f"{self.minutes}m"

    def contains(self, moment: PeriodLocalTime, *, cutoff: PeriodLocalTime) -> bool:
        """Se aquele instante está em `(cutoff - w, cutoff]` (§19, §20).

        TRÊS RECUSAS, e cada uma é uma decisão:

            período diferente   §15 — a janela não atravessa o intervalo
            posterior ao corte  §28 — defesa em profundidade contra futuro
            exatamente em t-w   §20 — o início é exclusivo
        """
        if not moment.shares_axis_with(cutoff):
            return False
        distancia = moment.seconds_before(cutoff)
        return 0 <= distancia < self.seconds

    def __str__(self) -> str:
        return self.label


#: AS JANELAS DE PRODUÇÃO (§21). Elas são quatro e estão aqui — e não
#: espalhadas como `5` e `600` em quatro arquivos —, porque cada uma vira
#: quinze features, e um número mágico repetido é um número que alguém muda
#: num lugar só.
#:
#: A ORDEM É CRESCENTE E É CONTEÚDO: ela decide a ordem dos eixos do espaço
#: de features, e ordenar por outra coisa trocaria as dimensões de lugar.
WINDOWS_V1: Final[tuple[RollingWindow, ...]] = (
    RollingWindow.of_minutes(1),
    RollingWindow.of_minutes(3),
    RollingWindow.of_minutes(5),
    RollingWindow.of_minutes(10),
)


@final
@dataclass(frozen=True, slots=True)
class WindowSelection:
    """Os eventos de uma janela, mais o que foi recusado na porta.

    `refused_future` NÃO DEVERIA SER NUNCA MAIOR QUE ZERO. Ele existe porque a
    alternativa a contar é confiar (§28): a projeção já removeu o futuro, e se
    um evento posterior ao corte chegar aqui, o motor precisa recusá-lo de
    forma visível em vez de contá-lo ou de morrer no meio de um lote de dez
    mil partidas.
    """

    events: tuple[CanonicalMatchEvent, ...] = ()
    refused_future: int = 0

    @property
    def size(self) -> int:
        return len(self.events)


@final
@dataclass(frozen=True, slots=True)
class RollingEventWindowSelector:
    """Escolhe os eventos de uma janela. Puro, determinístico (§24, §25, §26).

    ELE NÃO REAVALIA CAUSALIDADE (§25). Os eventos que chegam aqui já são
    EFETIVOS: a projeção do PR-05.1 já decidiu quem era conhecível e quem foi
    substituído por correção. Reimplementar a regra de conhecimento aqui
    criaria uma segunda autoridade sobre a mesma pergunta — e ela divergiria
    da primeira exatamente no caso difícil.

    O QUE ELE FAZ É UMA COISA SÓ: aplicar `(t - w, t]` sobre o eixo local do
    período do corte.
    """

    window: RollingWindow

    def select(self, events: Iterable[ProjectedEvent], *, as_of: FeatureAsOf) -> WindowSelection:
        corte = PeriodLocalTime.of_position(as_of.position)
        dentro: list[CanonicalMatchEvent] = []
        futuros = 0
        for projetado in events:
            momento = PeriodLocalTime.of_clock(projetado.event.clock)
            if momento.shares_axis_with(corte) and momento > corte:
                # DEFESA EM PROFUNDIDADE (§28). A projeção já deveria ter
                # removido isto; contar em silêncio faria a feature enxergar o
                # futuro sem que nada no resultado denunciasse.
                futuros += 1
                continue
            if self.window.contains(momento, cutoff=corte):
                dentro.append(projetado.event)
        return WindowSelection(events=_em_ordem_canonica(dentro), refused_future=futuros)


def _em_ordem_canonica(
    events: list[CanonicalMatchEvent],
) -> tuple[CanonicalMatchEvent, ...]:
    """A ordem canônica de fatos — posição, e `id` como desempate final (§27).

    ELA NÃO É A ORDEM DA ENTRADA. Duas leituras do mesmo corpus podem devolver
    os mesmos eventos em ordens diferentes, e a seleção precisa produzir a
    mesma sequência nos dois casos — senão a procedência da feature mudaria de
    digest sem o conteúdo mudar.
    """
    return tuple(
        sorted(
            events,
            key=lambda e: (
                MatchTimePoint.from_clock(e.clock, sequence=e.sequence),
                str(e.id),
            ),
        )
    )
