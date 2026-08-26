"""O extrator — de estado e fatos efetivos aos primeiros números do motor.

    FeatureSnapshot_t = Extract(HistoricalMatchState_t, EffectiveEvents_t, FeatureSpace)

ELE É PURO (§88, §89). Recebe um contexto tipado e devolve um snapshot. Sem
banco, sem object store, sem relógio, sem sorteio. É essa propriedade que
permite provar as invariantes do PR sobre conjuntos inteiros de entrada em vez
de sobre exemplos.

ELE NÃO RECONSTRÓI NEM REPROJETA (§90, §91). O estado chega pronto; a projeção
chega pronta, e é a MESMA que produziu o estado. Chamar o construtor de estado
aqui dobraria o custo; reprojetar criaria uma segunda verdade temporal.

UMA VARREDURA, NÃO SESSENTA (§106 ao §110). A forma ingênua — para cada
feature, percorrer todos os eventos — custaria `O(E * F)`: com quatrocentos
eventos e setenta e cinco features, trinta mil comparações por corte, e dez
mil cortes fariam disso trezentos milhões. Aqui os eventos são percorridos UMA
vez e classificados em baldes por `(janela, lado)`; as features leem os baldes.
O custo é `O(E * W + F)`, com `W = 4`.

O FAIL-CLOSED É A REGRA (§133). Quando o extrator não sabe se pode calcular —
cobertura ausente, detalhe incompleto, período sem eixo local — o resultado é
indisponível com motivo tipado. Nunca zero.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.details import ShotDetail
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
)
from sports_intelligence.domain.features.extraction.catalog import (
    FAMILIAS_MOVEIS,
    FeatureSide,
    RollingFamily,
    RollingFeatureSpec,
    StateFeatureKind,
    StateFeatureSpec,
)
from sports_intelligence.domain.features.extraction.context import (
    MatchFeatureExtractionContext,
)
from sports_intelligence.domain.features.extraction.windows import (
    WINDOWS_V1,
    PeriodLocalTime,
    RollingWindow,
)
from sports_intelligence.domain.features.provenance import (
    FeatureContribution,
    FeatureProvenance,
    FeatureProvenanceClass,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.state.issues import StateIssueCode
from sports_intelligence.domain.features.state.match_state import HistoricalMatchState
from sports_intelligence.domain.features.values import ComputedFeature
from sports_intelligence.domain.shared.identity import TeamId

#: Quantas casas decimais o somatório de xG mantém. Ele é generoso para a
#: precisão de qualquer fonte real (três casas é o comum) e FIXO, que é o que
#: importa: um arredondamento variável faria a mesma soma produzir impressões
#: diferentes conforme a ordem de acumulação.
XG_DECIMAL_PLACES: Final[int] = 6

_XG_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-XG_DECIMAL_PLACES)

#: Os segundos de cada janela, em ordem crescente. Pré-calculado porque a
#: busca binária o consulta uma vez por evento.
_LIMITES: Final[tuple[int, ...]] = tuple(j.seconds for j in WINDOWS_V1)

#: Os tipos canônicos que alimentam alguma família móvel. Um evento fora desta
#: lista não entra em balde nenhum — e não é erro: um passe é fato do jogo que
#: nenhuma feature desta fase conta (§55).
_TIPOS_DE_INTERESSE: Final[frozenset[EventType]] = frozenset(f.event_type for f in FAMILIAS_MOVEIS)


@final
@dataclass(slots=True)
class _Balde:
    """Os fatos de UMA janela e UM lado. Mutável, e não viaja para fora daqui.

    ELE GUARDA IDS, e não eventos: a procedência precisa das referências, e
    manter os eventos inteiros multiplicaria a memória do lote pelo número de
    janelas em que cada evento cabe.
    """

    shots: list[str] = field(default_factory=list)
    #: Finalizações sem `ShotDetail` — não dá para dizer se foram no alvo.
    shots_sem_detalhe: int = 0
    on_target: list[str] = field(default_factory=list)
    xg_shots: list[str] = field(default_factory=list)
    xg_sum: Decimal = Decimal(0)
    #: Finalizações cujo xG a fonte não publicou (§49, §50).
    xg_ausente: int = 0
    goals: list[str] = field(default_factory=list)
    corners: list[str] = field(default_factory=list)


@final
@dataclass(slots=True)
class _Indice:
    """Os baldes de todas as janelas e lados, mais o que foi recusado.

    `familias_com_time_irresoluvel` GUARDA O DEFEITO ESTRUTURAL do §41: um
    evento que o domínio exige que tenha time e cujo time não é nenhum dos dois
    da partida. Ele não é ignorado em silêncio — a família inteira daquela
    janela fica indisponível, porque somar num lado ao acaso é pior que não
    somar.
    """

    baldes: dict[tuple[int, FeatureSide], _Balde] = field(default_factory=dict)
    familias_irresoluveis: set[tuple[int, RollingFamily]] = field(default_factory=set)
    recusados_do_futuro: int = 0

    def balde(self, janela: int, lado: FeatureSide) -> _Balde:
        chave = (janela, lado)
        atual = self.baldes.get(chave)
        if atual is None:
            atual = _Balde()
            self.baldes[chave] = atual
        return atual

    def irresoluvel(self, janela: int, familia: RollingFamily) -> bool:
        return (janela, familia) in self.familias_irresoluveis


@final
@dataclass(frozen=True, slots=True)
class MatchStateFeatureExtractor:
    """Produz o `FeatureSnapshot` de UM corte (§88).

    ELE NÃO CRIA CONTRATO NOVO (§77). O snapshot é o do PR-05.1, e os valores
    são `ComputedFeature`. Um `FeatureSnapshotV2` só para caber o que este PR
    produz significaria que o contrato anterior estava errado — e ele não
    estava; ele estava vazio.
    """

    def compute_values(self, context: MatchFeatureExtractionContext) -> tuple[ComputedFeature, ...]:
        """Os valores das features do catálogo, NA ORDEM — sem o snapshot.

        ELA EXISTE PARA QUE A V2 REUSE A V1 (PR-05.4 §156, §157). O espaço
        estendido precisa das mesmas setenta e cinco features calculadas pelo
        MESMO código; copiá-las produziria duas implementações que concordam
        hoje e divergem no primeiro ajuste feito num lado só.
        """
        indice = _indexar(context)
        valores: list[ComputedFeature] = []
        por_chave: dict[str, ComputedFeature] = {}

        for spec in context.catalog.specs:
            if isinstance(spec, StateFeatureSpec):
                computada = _do_estado(spec, context, por_chave)
            else:
                computada = _da_janela(spec, context, indice, por_chave)
            por_chave[spec.definition.key] = computada
            valores.append(computada)
        return tuple(valores)

    def extract(self, context: MatchFeatureExtractionContext) -> FeatureSnapshot:
        return FeatureSnapshot.of(
            as_of=context.as_of,
            space=context.space,
            source=context.source,
            policy=context.policy,
            features=self.compute_values(context),
        )


# ============================================================ a varredura ==


def _indexar(context: MatchFeatureExtractionContext) -> _Indice:
    """Classifica os eventos efetivos em baldes — UMA passagem (§107, §110).

    A JANELA É UM SUFIXO. As janelas estão em ordem crescente, então o conjunto
    de janelas que contém um evento a `d` segundos do corte é
    `{w : d < w}` — um sufixo da lista. Uma busca binária acha onde ele começa,
    e o evento é lançado em todas as janelas dali em diante. Sem isso, seriam
    quatro varreduras da lista inteira.
    """
    indice = _Indice()
    corte = PeriodLocalTime.of_position(context.as_of.position)
    casa = context.state.identity.home_team_id
    fora = context.state.identity.away_team_id

    for projetado in context.effective_events.events:
        evento = projetado.event
        if evento.type not in _TIPOS_DE_INTERESSE:
            continue
        momento = PeriodLocalTime.of_clock(evento.clock)
        if not momento.shares_axis_with(corte):
            # §15, §18 — a janela é local ao período, e um fato de outro
            # período não participa dela. Isso é decisão declarada.
            continue
        distancia = momento.seconds_before(corte)
        if distancia < 0:
            # DEFESA EM PROFUNDIDADE (§28). A projeção já removeu o futuro.
            indice.recusados_do_futuro += 1
            continue
        primeira = bisect.bisect_right(_LIMITES, distancia)
        if primeira >= len(_LIMITES):
            continue
        lado = _lado_de(evento.team_id, casa=casa, fora=fora)
        for posicao in range(primeira, len(_LIMITES)):
            if lado is None:
                # §41 — o time não é nenhum dos dois desta partida. A família
                # inteira daquela janela perde a base: creditar ao acaso
                # inventaria a resposta.
                indice.familias_irresoluveis.update(
                    (posicao, f) for f in FAMILIAS_MOVEIS if f.event_type is evento.type
                )
                continue
            _acumular(indice.balde(posicao, lado), evento)
    return indice


def _lado_de(team_id: TeamId | None, *, casa: TeamId, fora: TeamId) -> FeatureSide | None:
    if team_id is None:
        return None
    if team_id == casa:
        return FeatureSide.HOME
    if team_id == fora:
        return FeatureSide.AWAY
    return None


def _acumular(balde: _Balde, event: CanonicalMatchEvent) -> None:
    """Joga UM evento no balde, extraindo o que cada família precisa dele."""
    referencia = str(event.id)
    if event.type is EventType.CORNER:
        balde.corners.append(referencia)
        return
    if event.type is EventType.GOAL:
        balde.goals.append(referencia)
        return
    if event.type is not EventType.SHOT:  # pragma: no cover - filtrado antes
        return

    balde.shots.append(referencia)
    detalhe = event.detail
    if not isinstance(detalhe, ShotDetail):
        # §43, §44 — sem detalhe tipado não dá para dizer se foi no alvo nem
        # qual era o xG. Não se adivinha: as duas famílias que dependem disso
        # ficam parciais, e a CONTAGEM de finalizações continua válida.
        balde.shots_sem_detalhe += 1
        balde.xg_ausente += 1
        return
    if detalhe.on_target:
        balde.on_target.append(referencia)
    if detalhe.xg is None or not detalhe.xg.is_available:
        # §49 — xG ausente NÃO é xG zero.
        balde.xg_ausente += 1
        return
    balde.xg_shots.append(referencia)
    balde.xg_sum += Decimal(str(detalhe.xg.require("ShotDetail.xg")))


# ================================================= features de estado ==


def _do_estado(
    spec: StateFeatureSpec,
    context: MatchFeatureExtractionContext,
    calculadas: dict[str, ComputedFeature],
) -> ComputedFeature:
    """O valor de uma feature derivada do estado (§29 ao §36)."""
    estado = context.state
    tipo = spec.kind

    if tipo is StateFeatureKind.CLOCK_PERIOD_ORDER:
        return _disponivel(spec.definition, context, estado.as_of.position.period.order, ())
    if tipo is StateFeatureKind.CLOCK_MINUTE:
        return _disponivel(spec.definition, context, estado.as_of.position.minute, ())
    if tipo is StateFeatureKind.CLOCK_STOPPAGE:
        return _disponivel(spec.definition, context, estado.as_of.position.stoppage, ())

    if tipo in (StateFeatureKind.SCORE_HOME, StateFeatureKind.SCORE_AWAY):
        if not estado.score.is_available:
            # §30 — placar não afirmável não vira 0-0.
            return _indisponivel(
                spec.definition,
                context,
                estado.score.availability,
                estado.score.detail,
            )
        valor = estado.score.home if tipo is StateFeatureKind.SCORE_HOME else estado.score.away
        return _disponivel(spec.definition, context, valor, estado.provenance.score.sample)

    if tipo in (
        StateFeatureKind.PLAYERS_ON_FIELD_HOME,
        StateFeatureKind.PLAYERS_ON_FIELD_AWAY,
    ):
        lado = (
            estado.on_field.home
            if tipo is StateFeatureKind.PLAYERS_ON_FIELD_HOME
            else estado.on_field.away
        )
        if not lado.is_available:
            # §32 — sem escalação NÃO se assume onze.
            return _indisponivel(spec.definition, context, lado.availability, lado.detail)
        return _disponivel(spec.definition, context, lado.size, estado.provenance.on_field.sample)

    if tipo in (
        StateFeatureKind.YELLOW_CARDS_HOME,
        StateFeatureKind.YELLOW_CARDS_AWAY,
        StateFeatureKind.DISMISSALS_HOME,
        StateFeatureKind.DISMISSALS_AWAY,
    ):
        do_time = (
            estado.discipline.home
            if tipo in (StateFeatureKind.YELLOW_CARDS_HOME, StateFeatureKind.DISMISSALS_HOME)
            else estado.discipline.away
        )
        if not do_time.is_available:
            return _indisponivel(
                spec.definition,
                context,
                do_time.availability,
                "a versão do corpus não publica evento para esta partida",
            )
        # §34 — zero cartão com EVENT publicado é um FATO, e é AVAILABLE.
        valor = (
            do_time.yellow_cards
            if tipo in (StateFeatureKind.YELLOW_CARDS_HOME, StateFeatureKind.YELLOW_CARDS_AWAY)
            else do_time.dismissals
        )
        return _disponivel(spec.definition, context, valor, estado.provenance.discipline.sample)

    if tipo in (
        StateFeatureKind.SUBSTITUTIONS_HOME,
        StateFeatureKind.SUBSTITUTIONS_AWAY,
    ):
        if not estado.substitutions.is_available:
            return _indisponivel(
                spec.definition,
                context,
                estado.substitutions.availability,
                "substituições não afirmáveis neste corpus",
            )
        time = (
            estado.identity.home_team_id
            if tipo is StateFeatureKind.SUBSTITUTIONS_HOME
            else estado.identity.away_team_id
        )
        aplicadas = estado.substitutions.by_team(time)
        return _disponivel(
            spec.definition,
            context,
            len(aplicadas),
            tuple(FeatureContribution(kind="EVENT", reference=str(s.event_id)) for s in aplicadas),
        )

    return _diferenca(spec.definition, context, calculadas)


# ================================================== features de janela ==


def _da_janela(
    spec: RollingFeatureSpec,
    context: MatchFeatureExtractionContext,
    indice: _Indice,
    calculadas: dict[str, ComputedFeature],
) -> ComputedFeature:
    """O valor de uma feature móvel (§37 ao §54)."""
    if spec.side is FeatureSide.DIFFERENCE:
        return _diferenca(spec.definition, context, calculadas)

    indisponivel = _bloqueio_de_janela(spec.window, context)
    if indisponivel is not None:
        return _indisponivel(spec.definition, context, *indisponivel)

    posicao = WINDOWS_V1.index(spec.window)
    if indice.irresoluvel(posicao, spec.family):
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.PARTIAL_INPUT,
            "há fato desta família creditado a um time que não joga esta partida",
        )
    balde = indice.baldes.get((posicao, spec.side)) or _Balde()

    if spec.family is RollingFamily.SHOT:
        return _contagem(spec.definition, context, balde.shots)
    if spec.family is RollingFamily.GOAL:
        return _contagem(spec.definition, context, balde.goals)
    if spec.family is RollingFamily.CORNER:
        return _contagem(spec.definition, context, balde.corners)
    if spec.family is RollingFamily.SHOT_ON_TARGET:
        if balde.shots_sem_detalhe:
            # §44 — contar só as conhecidas e chamar de total seria produzir um
            # número menor que o real com cara de completo.
            return _indisponivel(
                spec.definition,
                context,
                FeatureAvailability.PARTIAL_INPUT,
                f"{balde.shots_sem_detalhe} finalização(ões) sem detalhe tipado na janela",
            )
        return _contagem(spec.definition, context, balde.on_target)

    # ---- xG. A política é conservadora por decisão (§50).
    if balde.xg_ausente:
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.PARTIAL_INPUT,
            f"{balde.xg_ausente} finalização(ões) sem xG publicado na janela",
        )
    total = balde.xg_sum.quantize(_XG_QUANTUM).normalize()
    return _disponivel(
        spec.definition,
        context,
        float(total),
        tuple(FeatureContribution(kind="EVENT", reference=r) for r in balde.xg_shots),
    )


def _bloqueio_de_janela(
    window: RollingWindow, context: MatchFeatureExtractionContext
) -> tuple[FeatureAvailability, str] | None:
    """O que impede esta janela de ser afirmada, se algo impedir.

    TRÊS BLOQUEIOS, E A ORDEM DELES É A DA CAUSA MAIS ESTRUTURAL:

        §59  a versão não publica `EVENT` — nenhuma contagem é observável
        §60  a história de eventos é incompleta para este corte — zero seria
             uma afirmação que ninguém pode fazer
        §124 o período do corte não tem cronômetro correndo, e uma janela
             precisa de um eixo local para existir
    """
    if not context.publishes_events:
        return (
            FeatureAvailability.NOT_DECLARED,
            "a versão do corpus não publica a família EVENT",
        )
    incompleta = any(
        i.code is StateIssueCode.INCOMPLETE_EVENT_HISTORY for i in context.state.issues
    )
    if incompleta:
        return (
            FeatureAvailability.INSUFFICIENT_COVERAGE,
            "a história de eventos não é completa o bastante para afirmar zero",
        )
    fase = context.as_of.position.period
    if not fase.is_ball_in_play and not context.as_of.is_pre_match:
        # §122, §124 — intervalo, disputa de pênaltis e apito final não têm
        # cronômetro: `MatchClock` recusa minuto diferente de zero neles, e uma
        # janela de cinco minutos sobre um único ponto não mede nada. Responder
        # zero seria responder outra pergunta.
        return (
            FeatureAvailability.NOT_APPLICABLE,
            f"{fase.value} não tem cronômetro correndo: a janela {window.label} não "
            "tem eixo local sobre o qual existir",
        )
    return None


# ==================================================== auxiliares comuns ==


def _diferenca(
    definition: FeatureDefinition,
    context: MatchFeatureExtractionContext,
    calculadas: dict[str, ComputedFeature],
) -> ComputedFeature:
    """`home - away`, e SÓ quando os dois lados existem (§64, §65, §134).

    NUNCA SE PREENCHE O LADO AUSENTE COM ZERO. Uma diferença calculada contra
    um zero fabricado teria o sinal e a magnitude de uma vantagem que ninguém
    mediu — e ela entraria em qualquer média parecendo um número.

    A PROCEDÊNCIA É A UNIÃO DAS DUAS BASES (§134). Perdê-la faria a diferença
    ser o único número do snapshot sem defesa.
    """
    chaves = definition.depends_on_features
    if len(chaves) != 2:  # pragma: no cover - o catálogo sempre declara duas
        raise ValueError(f"{definition.key} não declara duas dependências")
    casa, fora = (calculadas[c] for c in chaves)
    if not casa.is_available or not fora.is_available:
        ausente = casa if not casa.is_available else fora
        return _indisponivel(
            definition,
            context,
            ausente.availability,
            f"{ausente.definition_key} não é afirmável neste corte",
        )
    valor_casa = casa.numeric
    valor_fora = fora.numeric
    assert valor_casa is not None
    assert valor_fora is not None
    if definition.output_type is FeatureOutputType.INTEGER:
        diferenca: float = round(valor_casa - valor_fora)
    else:
        # A SUBTRAÇÃO É DECIMAL pelo mesmo motivo da soma (§47): dois floats
        # que somam 0,83 e 0,21 não subtraem 0,62 em binário, e a diferença
        # entraria na impressão da feature.
        diferenca = float(
            (Decimal(str(valor_casa)) - Decimal(str(valor_fora))).quantize(_XG_QUANTUM).normalize()
        )
    return _disponivel(
        definition,
        context,
        diferenca,
        (*casa.provenance.sample, *fora.provenance.sample),
    )


def _contagem(
    definition: FeatureDefinition,
    context: MatchFeatureExtractionContext,
    referencias: list[str],
) -> ComputedFeature:
    """Uma contagem de eventos, com os contribuintes na procedência.

    ZERO É UM VALOR (§51, §62, §84). Quando a cobertura prova que a ausência
    seria observável, `0` é o número certo e a procedência diz honestamente que
    nenhum fato o sustenta — que é diferente de não existir número.
    """
    return _disponivel(
        definition,
        context,
        len(referencias),
        tuple(FeatureContribution(kind="EVENT", reference=r) for r in referencias),
    )


def _disponivel(
    definition: FeatureDefinition,
    context: MatchFeatureExtractionContext,
    value: float | int,
    contributions: tuple[FeatureContribution, ...],
) -> ComputedFeature:
    return ComputedFeature.available(
        definition_key=definition.key,
        definition_fingerprint=definition.fingerprint,
        as_of=context.as_of,
        value=value,
        provenance=FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL, contributions
        ),
    )


def _indisponivel(
    definition: FeatureDefinition,
    context: MatchFeatureExtractionContext,
    availability: FeatureAvailability,
    detail: str = "",
) -> ComputedFeature:
    return ComputedFeature.unavailable(
        definition_key=definition.key,
        definition_fingerprint=definition.fingerprint,
        as_of=context.as_of,
        availability=availability,
        detail=detail,
    )


def state_of(context: MatchFeatureExtractionContext) -> HistoricalMatchState:
    """O estado do contexto — atalho para quem lê o snapshot ao lado dele."""
    return context.state
