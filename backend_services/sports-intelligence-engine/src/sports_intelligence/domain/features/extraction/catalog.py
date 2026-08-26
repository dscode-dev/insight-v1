"""O CATÁLOGO DE FEATURES DE PRODUÇÃO — o primeiro que existe.

Até aqui o motor tinha o contrato de feature e nenhuma feature. Este módulo é a
primeira declaração de produção: setenta e cinco definições, um espaço ordenado
e um registro que as recusa quando entram em conflito.

TRÊS DECISÕES ESTRUTURAM O ARQUIVO INTEIRO:

**1. Feature é contrato deliberado, e não campo promovido (§9).** Não existe
tradução automática de `HistoricalMatchState` para features. Cada definição foi
escolhida, tem unidade declarada, semântica de disponibilidade e justificativa.
O estado tem mais campos do que este catálogo tem features, e a diferença é
intencional.

**2. As famílias repetitivas são GERADAS, e não copiadas (§38, §68).** Cinco
famílias móveis, dois lados mais a diferença, quatro janelas: sessenta
definições. Escrevê-las à mão produziria sessenta oportunidades de errar um
parâmetro, e o erro seria invisível: a feature existiria, calcularia, e estaria
descrevendo outra coisa. Aqui elas saem de fábricas tipadas.

**3. Cada definição vem com um ESPECIFICADOR tipado (§39).** O extrator precisa
saber o que calcular para cada definição. A forma barata é olhar o nome —
`if key.startswith("shots_home_")` — e ela é frágil de um jeito específico: o
dia em que alguém renomear uma chave, o cálculo silenciosamente para de
acontecer e a feature vira indisponível sem que nada explique. Aqui a ligação é
um objeto: `RollingFeatureSpec(family=SHOT, side=HOME, window=5m)`.

O QUE ESTE CATÁLOGO NÃO TEM, e cada ausência é uma decisão registrada:

    passes            §55 — contagem altamente sensível à granularidade do
                      provedor; dois provedores dão números incomparáveis
    total de eventos  §56 — mede a taxonomia da fonte, não o jogo
    pressão           §57 — o `EventType.PRESSURE` existir não autoriza um
                      score de pressão; isso é composição, e é outra fase
    odds              §98, §99 — um espaço de dimensão fixa não pode depender
                      de quantas casas de aposta existem. Antes é preciso
                      mercado canônico, contrato de seleção e consenso
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import FactKind
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
    FeatureScope,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.extraction.windows import (
    WINDOWS_V1,
    RollingWindow,
)
from sports_intelligence.domain.features.registry import FeatureDefinitionRegistry
from sports_intelligence.domain.features.space import (
    CorpusRequirement,
    FeatureSpaceDefinition,
)
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import FeatureSpaceVersion, Version

#: A versão de TODA definição deste catálogo. Uma só, e é de propósito: elas
#: nascem juntas, e versioná-las separadamente sugeriria uma evolução
#: independente que a V1 não tem. Mudar a semântica de uma exige subir a dela.
V1: Final[Version] = Version(major=1, minor=0)

#: O nome do espaço de produção (§10).
MATCH_STATE_RAW_V1_NAME: Final[str] = "MATCH_STATE_RAW_V1"


@final
class FeatureSide(StrEnum):
    """De quem é o número (§63, §67).

    A V1 MANTÉM `HOME`/`AWAY` EXPLÍCITOS. Não existe `attacking_team`,
    `reference_team` nem `stronger_team`: essas orientações dependem de uma
    escolha — quem é a referência? — que ainda não foi feita, e antecipá-la
    embutiria uma decisão de modelagem dentro de um fato.

    `DIFFERENCE` é `home - away`, sempre nessa ordem.
    """

    HOME = "HOME"
    AWAY = "AWAY"
    DIFFERENCE = "DIFFERENCE"

    @property
    def suffix(self) -> str:
        return {"HOME": "home", "AWAY": "away", "DIFFERENCE": "diff"}[self.value]

    @property
    def scope(self) -> FeatureScope:
        if self is FeatureSide.HOME:
            return FeatureScope.HOME_TEAM
        if self is FeatureSide.AWAY:
            return FeatureScope.AWAY_TEAM
        return FeatureScope.MATCH


def _rotulo(side: FeatureSide) -> str:
    """«mandante» ou «visitante», para a descrição legível da definição."""
    return "mandante" if side is FeatureSide.HOME else "visitante"


#: Os dois lados que produzem valor próprio. A diferença é derivada deles, e
#: por isso não está aqui: ela entra depois, com dependência declarada.
LADOS: Final[tuple[FeatureSide, ...]] = (FeatureSide.HOME, FeatureSide.AWAY)


# ================================================ features de estado ==


@final
class StateFeatureKind(StrEnum):
    """O que extrair do `HistoricalMatchState` (§29 ao §36).

    ELAS SÃO EXTRAÍDAS DO ESTADO, E NUNCA RECONTADAS DOS EVENTOS (§36). O
    estado já reduziu gols, cartões e substituições; percorrer os eventos de
    novo para chegar ao mesmo número criaria uma segunda contagem que
    divergiria da primeira no primeiro caso degradado — e as duas apareceriam
    lado a lado no mesmo snapshot.
    """

    CLOCK_PERIOD_ORDER = "CLOCK_PERIOD_ORDER"
    CLOCK_MINUTE = "CLOCK_MINUTE"
    CLOCK_STOPPAGE = "CLOCK_STOPPAGE"

    SCORE_HOME = "SCORE_HOME"
    SCORE_AWAY = "SCORE_AWAY"
    SCORE_DIFFERENCE = "SCORE_DIFFERENCE"

    PLAYERS_ON_FIELD_HOME = "PLAYERS_ON_FIELD_HOME"
    PLAYERS_ON_FIELD_AWAY = "PLAYERS_ON_FIELD_AWAY"
    MANPOWER_DIFFERENCE = "MANPOWER_DIFFERENCE"

    YELLOW_CARDS_HOME = "YELLOW_CARDS_HOME"
    YELLOW_CARDS_AWAY = "YELLOW_CARDS_AWAY"
    DISMISSALS_HOME = "DISMISSALS_HOME"
    DISMISSALS_AWAY = "DISMISSALS_AWAY"

    SUBSTITUTIONS_HOME = "SUBSTITUTIONS_HOME"
    SUBSTITUTIONS_AWAY = "SUBSTITUTIONS_AWAY"


@final
class RollingFamily(StrEnum):
    """As famílias móveis de produção (§37).

    `SHOT` CONTA `EventType.SHOT`, E NÃO `SHOT` MAIS `GOAL`. A taxonomia é
    fechada e declarada: um gol é `EventType.GOAL`, e assumir que todo gol
    também é uma finalização somaria os dois quando o provedor emite os dois
    para o mesmo lance. A escolha subconta em provedores que só emitem `GOAL`
    — e subcontar uma coisa declarada é visível, enquanto contar duas vezes a
    mesma finalização não é. Quem quiser «finalizações totais» soma
    `shots_*` com `goals_*`, que estão os dois no espaço.
    """

    SHOT = "SHOT"
    SHOT_ON_TARGET = "SHOT_ON_TARGET"
    XG = "XG"
    GOAL = "GOAL"
    CORNER = "CORNER"

    @property
    def prefix(self) -> str:
        return {
            "SHOT": "shots",
            "SHOT_ON_TARGET": "shots_on_target",
            "XG": "xg",
            "GOAL": "goals",
            "CORNER": "corners",
        }[self.value]

    @property
    def event_type(self) -> EventType:
        """O tipo canônico que a família conta.

        `XG` E `SHOT_ON_TARGET` LEEM O MESMO TIPO que `SHOT` — as três
        descrevem finalizações; o que muda é o que se extrai de cada uma.
        """
        return {
            "SHOT": EventType.SHOT,
            "SHOT_ON_TARGET": EventType.SHOT,
            "XG": EventType.SHOT,
            "GOAL": EventType.GOAL,
            "CORNER": EventType.CORNER,
        }[self.value]

    @property
    def output_type(self) -> FeatureOutputType:
        return FeatureOutputType.FLOAT if self is RollingFamily.XG else FeatureOutputType.INTEGER

    @property
    def unit(self) -> str:
        """A unidade, declarada (§66). Ela nunca fica implícita."""
        return {
            "SHOT": "count",
            "SHOT_ON_TARGET": "count",
            "XG": "expected_goals",
            "GOAL": "goals",
            "CORNER": "count",
        }[self.value]

    @property
    def needs_shot_detail(self) -> bool:
        """Se a família exige `ShotDetail` completo para ser afirmável (§44, §50)."""
        return self in (RollingFamily.SHOT_ON_TARGET, RollingFamily.XG)


#: A ordem das famílias móveis DENTRO de cada janela. Ela é conteúdo (§74,
#: §75): é a ordem dos eixos do vetor futuro, e ordená-las por alfabeto seria
#: deixar a ordem ser decidida pela grafia dos nomes.
FAMILIAS_MOVEIS: Final[tuple[RollingFamily, ...]] = (
    RollingFamily.SHOT,
    RollingFamily.SHOT_ON_TARGET,
    RollingFamily.XG,
    RollingFamily.GOAL,
    RollingFamily.CORNER,
)


# ======================================================= os especificadores ==


@final
@dataclass(frozen=True, slots=True)
class StateFeatureSpec:
    """Uma feature derivada do estado, com o QUE extrair declarado por tipo."""

    definition: FeatureDefinition
    kind: StateFeatureKind


@final
@dataclass(frozen=True, slots=True)
class RollingFeatureSpec:
    """Uma feature de janela, com família, lado e janela declarados (§68).

    ELE É O QUE SUBSTITUI A MÁGICA DE STRING (§39). O extrator lê
    `spec.family`, `spec.side` e `spec.window` — três valores tipados — em vez
    de decompor `"shots_on_target_diff_10m"` procurando sublinhados.
    """

    definition: FeatureDefinition
    family: RollingFamily
    side: FeatureSide
    window: RollingWindow


FeatureSpec = StateFeatureSpec | RollingFeatureSpec


# ============================================================== as fábricas ==


def _state_definition(
    *,
    key: str,
    description: str,
    unit: str,
    output_type: FeatureOutputType = FeatureOutputType.INTEGER,
    scope: FeatureScope = FeatureScope.MATCH,
    families: tuple[CoverageFamily, ...] = (),
    fact_kinds: tuple[FactKind, ...] = (),
    depends_on: tuple[str, ...] = (),
) -> FeatureDefinition:
    return FeatureDefinition(
        key=key,
        version=V1,
        description=description,
        output_type=output_type,
        scope=scope,
        temporal_class=FeatureTemporalClass.INTRA_MATCH_CAUSAL,
        required_families=families,
        required_fact_kinds=fact_kinds,
        parameters={"source": "MATCH_STATE"},
        unit=unit,
        depends_on_features=depends_on,
    )


def rolling_definition(
    *, family: RollingFamily, side: FeatureSide, window: RollingWindow
) -> FeatureDefinition:
    """A definição de UMA feature móvel — gerada, e estável (§68, §69, §70).

    A CHAVE É COMPOSTA DE VALORES DECLARADOS, e nunca de `repr` de enum (§69):
    `f"{family.prefix}_{side.suffix}_{window.label}"`. Um `repr` mudaria com a
    refatoração do enum e levaria toda a identidade junto.

    OS PARÂMETROS ENTRAM NA IMPRESSÃO (§22, §70). Família, tipo de evento
    canônico, lado, agregação e janela em segundos — é isso que impede
    `shots_home_5m` e `shots_home_10m` de terem a mesma identidade, e é isso
    que faz trocar a janela de uma feature ser detectado em vez de assumido.
    """
    chave = f"{family.prefix}_{side.suffix}_{window.label}"
    agregacao = "SUM" if family is RollingFamily.XG else "COUNT"
    if side is FeatureSide.DIFFERENCE:
        dependencias = tuple(f"{family.prefix}_{lado.suffix}_{window.label}" for lado in LADOS)
        descricao = (
            f"Diferença mandante menos visitante de {family.prefix} na janela "
            f"{window.label}, medida em tempo efetivo local ao período"
        )
    else:
        dependencias = ()
        lado = "mandante" if side is FeatureSide.HOME else "visitante"
        descricao = (
            f"{family.prefix} do {lado} na janela {window.label} — eventos efetivos "
            f"em (t-{window.label}, t] dentro do mesmo período"
        )
    return FeatureDefinition(
        key=chave,
        version=V1,
        description=descricao,
        output_type=family.output_type,
        scope=side.scope,
        temporal_class=FeatureTemporalClass.INTRA_MATCH_CAUSAL,
        required_families=(CoverageFamily.EVENT,),
        required_fact_kinds=(FactKind.EVENT_ORIGINAL,),
        parameters={
            "aggregation": agregacao,
            "canonical_event_type": family.event_type.value,
            "family": family.value,
            "side": side.value,
            "window_scope": "PERIOD_LOCAL",
            "window_seconds": window.seconds,
        },
        unit=family.unit,
        depends_on_features=dependencias,
    )


# =========================================================== o catálogo ==


def _specs_de_estado() -> tuple[StateFeatureSpec, ...]:
    """As quinze features derivadas do estado, na ordem do espaço (§74)."""
    relogio = (
        (
            StateFeatureKind.CLOCK_PERIOD_ORDER,
            "clock_period_order",
            "A posição da fase do jogo na ordem canônica das fases",
            "period_index",
        ),
        (
            StateFeatureKind.CLOCK_MINUTE,
            "clock_minute",
            "O minuto do relógio da partida no corte, sem os acréscimos",
            "minutes",
        ),
        (
            StateFeatureKind.CLOCK_STOPPAGE,
            "clock_stoppage",
            "Os minutos de acréscimo do corte, separados do minuto (§13)",
            "minutes",
        ),
    )
    placar = (
        (StateFeatureKind.SCORE_HOME, "score_home", FeatureSide.HOME),
        (StateFeatureKind.SCORE_AWAY, "score_away", FeatureSide.AWAY),
    )
    campo = (
        (
            StateFeatureKind.PLAYERS_ON_FIELD_HOME,
            "players_on_field_home",
            FeatureSide.HOME,
        ),
        (
            StateFeatureKind.PLAYERS_ON_FIELD_AWAY,
            "players_on_field_away",
            FeatureSide.AWAY,
        ),
    )
    disciplina = (
        (StateFeatureKind.YELLOW_CARDS_HOME, "yellow_cards_home", FeatureSide.HOME),
        (StateFeatureKind.YELLOW_CARDS_AWAY, "yellow_cards_away", FeatureSide.AWAY),
        (StateFeatureKind.DISMISSALS_HOME, "dismissals_home", FeatureSide.HOME),
        (StateFeatureKind.DISMISSALS_AWAY, "dismissals_away", FeatureSide.AWAY),
    )
    substituicoes = (
        (StateFeatureKind.SUBSTITUTIONS_HOME, "substitutions_home", FeatureSide.HOME),
        (StateFeatureKind.SUBSTITUTIONS_AWAY, "substitutions_away", FeatureSide.AWAY),
    )

    specs: list[StateFeatureSpec] = []
    # ---- relógio. NÃO exige família nenhuma: o corte é dado de entrada, e o
    # relógio dele é conhecido por construção (§12).
    for tipo, chave, descricao, unidade in relogio:
        specs.append(
            StateFeatureSpec(
                definition=_state_definition(key=chave, description=descricao, unit=unidade),
                kind=tipo,
            )
        )
    # ---- placar. Exige EVENT: o placar do estado é reduzido de gols (§126).
    for tipo, chave, lado in placar:
        specs.append(
            StateFeatureSpec(
                definition=_state_definition(
                    key=chave,
                    description=(
                        f"Gols do {_rotulo(lado)} no corte, somando tempo normal e "
                        "prorrogação e nunca a disputa de pênaltis"
                    ),
                    unit="goals",
                    scope=lado.scope,
                    families=(CoverageFamily.EVENT,),
                    fact_kinds=(FactKind.EVENT_ORIGINAL,),
                ),
                kind=tipo,
            )
        )
    specs.append(
        StateFeatureSpec(
            definition=_state_definition(
                key="score_difference",
                description="Gols do mandante menos gols do visitante no corte",
                unit="goals",
                families=(CoverageFamily.EVENT,),
                fact_kinds=(FactKind.EVENT_ORIGINAL,),
                depends_on=("score_home", "score_away"),
            ),
            kind=StateFeatureKind.SCORE_DIFFERENCE,
        )
    )
    # ---- elenco em campo. Exige LINEUP: sem escalação inicial não há base.
    for tipo, chave, lado in campo:
        specs.append(
            StateFeatureSpec(
                definition=_state_definition(
                    key=chave,
                    description=(
                        f"Jogadores em campo pelo {_rotulo(lado)} no corte — nunca "
                        "assumido como onze (§32)"
                    ),
                    unit="players",
                    scope=lado.scope,
                    families=(CoverageFamily.LINEUP, CoverageFamily.EVENT),
                    fact_kinds=(FactKind.LINEUP_INITIAL, FactKind.EVENT_ORIGINAL),
                ),
                kind=tipo,
            )
        )
    specs.append(
        StateFeatureSpec(
            definition=_state_definition(
                key="manpower_difference",
                description="Jogadores em campo do mandante menos os do visitante",
                unit="players",
                families=(CoverageFamily.LINEUP, CoverageFamily.EVENT),
                fact_kinds=(FactKind.LINEUP_INITIAL, FactKind.EVENT_ORIGINAL),
                depends_on=("players_on_field_home", "players_on_field_away"),
            ),
            kind=StateFeatureKind.MANPOWER_DIFFERENCE,
        )
    )
    # ---- disciplina e substituições. Exigem EVENT (§128).
    for tipo, chave, lado in (*disciplina, *substituicoes):
        assunto = chave.rsplit("_", 1)[0].replace("_", " ")
        specs.append(
            StateFeatureSpec(
                definition=_state_definition(
                    key=chave,
                    description=f"{assunto} do {_rotulo(lado)} até o corte",
                    unit="count",
                    scope=lado.scope,
                    families=(CoverageFamily.EVENT,),
                    fact_kinds=(FactKind.EVENT_ORIGINAL,),
                ),
                kind=tipo,
            )
        )
    return tuple(specs)


def _specs_moveis() -> tuple[RollingFeatureSpec, ...]:
    """As sessenta features móveis, na ordem do espaço (§74).

    A ORDEM É `janela → família → lado`. Ela agrupa por horizonte temporal,
    que é como um humano lê o vetor: «o que aconteceu no último minuto» fica
    junto, e não espalhado entre as cinco famílias.
    """
    specs: list[RollingFeatureSpec] = []
    for janela in WINDOWS_V1:
        for familia in FAMILIAS_MOVEIS:
            for lado in (*LADOS, FeatureSide.DIFFERENCE):
                specs.append(
                    RollingFeatureSpec(
                        definition=rolling_definition(family=familia, side=lado, window=janela),
                        family=familia,
                        side=lado,
                        window=janela,
                    )
                )
    return tuple(specs)


@final
@dataclass(frozen=True, slots=True)
class ProductionFeatureCatalog:
    """As definições de produção, ORDENADAS, com o que extrair em cada uma.

    ELE É A ÚNICA FONTE (§72, §73). Não há tabela de features no PostgreSQL, e
    a ausência é decisão: uma linha de banco pode dizer «janela de 5 minutos»
    enquanto o código calcula 10, e a divergência não quebra nada visível — o
    número continua sendo um número plausível. O código versionado pelo git é
    a definição, e ele não pode divergir de si mesmo.
    """

    specs: tuple[FeatureSpec, ...]

    def __post_init__(self) -> None:
        chaves = [s.definition.key for s in self.specs]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(f"catálogo de produção com chave repetida: {repetidas}")

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return tuple(s.definition for s in self.specs)

    @property
    def size(self) -> int:
        return len(self.specs)

    def spec_of(self, key: str) -> FeatureSpec:
        for spec in self.specs:
            if spec.definition.key == key:
                return spec
        raise ValidationError(f"o catálogo não contém a feature {key!r}")


def production_feature_catalog() -> ProductionFeatureCatalog:
    """O catálogo de produção da V1 — estado primeiro, janelas depois (§74)."""
    return ProductionFeatureCatalog(specs=(*_specs_de_estado(), *_specs_moveis()))


def production_feature_registry() -> FeatureDefinitionRegistry:
    """O registro de produção (§72, §139).

    ELE NÃO É UM SEGUNDO CATÁLOGO. É o mesmo, visto pela porta que recusa
    conflito: chave repetida, identidade repetida, mesma chave e versão com
    conteúdos diferentes, dependência inexistente, ciclo.
    """
    return FeatureDefinitionRegistry.of(production_feature_catalog().definitions)


def match_state_raw_space_v1() -> FeatureSpaceDefinition:
    """O primeiro espaço de features de PRODUÇÃO (§10, §11).

    `normalization = NONE` É ESTRUTURAL, E NÃO UM CAMPO (§11, §100). Nenhuma
    definição deste espaço declara `normalizer_key`, e nenhum caminho do motor
    executa normalizador. O contrato de normalização existe desde o PR-05.1 e
    continua sem execução: normalizar exige população de referência,
    ajuste por competição e versionamento do ajuste — três decisões que
    pertencem à fase seguinte.

    `live_comparable=True` É UMA PROMESSA COM DEFESA ESTRUTURAL. Todas as
    definições são `INTRA_MATCH_CAUSAL`; o construtor do espaço recusaria uma
    feature pós-jogo aqui dentro.
    """
    catalogo = production_feature_catalog()
    return FeatureSpaceDefinition(
        name=MATCH_STATE_RAW_V1_NAME,
        version=FeatureSpaceVersion(major=1, minor=0),
        features=catalogo.definitions,
        temporal_mode=TemporalMode.AS_KNOWN,
        live_comparable=True,
        requirement=CorpusRequirement.of(CoverageFamily.EVENT, CoverageFamily.LINEUP),
        description=(
            "Features CRUAS do estado da partida e das janelas móveis de 1, 3, 5 e "
            "10 minutos. Sem normalização, sem composição, sem interpretação."
        ),
    )
