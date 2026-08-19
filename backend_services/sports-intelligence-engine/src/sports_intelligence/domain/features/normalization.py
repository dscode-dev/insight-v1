"""O contrato do normalizador — sem normalizador nenhum ainda.

O QUE ESTE MÓDULO ENTREGA (§83, §84, §89): a declaração do que um normalizador
É, com identidade versionada e impressão. O que ele NÃO entrega é ajuste,
z-score, mediana, IQR ou qualquer estatística calculada — isso é fase
posterior, e adiantá-lo produziria números antes de existirem features para
normalizar.

DUAS FORMAS DE VAZAMENTO QUE ESTE CONTRATO EXISTE PARA IMPEDIR:

    escopo         normalizar Premier League e La Liga na mesma população
                   (§85, §86). As duas ligas têm distribuições diferentes de
                   quase tudo; misturá-las faz um valor mediano do Brasileirão
                   parecer alto na Inglaterra
    corte de fit   ajustar o normalizador com dado de MAIO para avaliar um jogo
                   de MARÇO (§87, §88). O jogo de março não conhecia maio, e um
                   z-score calculado assim carrega o futuro dentro da escala

O SEGUNDO É O MAIS TRAIÇOEIRO porque não aparece no valor: `+0.3 desvio` parece um
número inocente, e a distribuição que o produziu já tinha visto o resto da
temporada. Por isso o corte de ajuste é parte da IDENTIDADE do normalizador, e
não um parâmetro de execução.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.features.temporal import MatchTimePoint
from sports_intelligence.domain.shared.canonical import canonical_json, instant_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import NormalizerVersion

#: O algoritmo da impressão do normalizador. Nomeado pelo mesmo motivo dos
#: outros: dois hex de 64 caracteres produzidos por construções diferentes são
#: indistinguíveis, e compará-los não diria nada.
NORMALIZER_FINGERPRINT_ALGORITHM: Final[str] = "normalizer-sha256-v1"


@final
class NormalizationMethod(StrEnum):
    """Como o valor é reescalado. Catálogo FECHADO.

    NENHUM DELES ESTÁ IMPLEMENTADO (§83). Eles existem para que a declaração
    seja possível — e para que o dia em que alguém implementar o primeiro, o
    contrato já diga o que precisa ser declarado junto.
    """

    #: `(x - média) / desvio`. Sensível a extremo; presume distribuição
    #: aproximadamente simétrica.
    Z_SCORE = "Z_SCORE"
    #: `(x - mediana) / IQR`. Robusta a extremo — a escolha natural para
    #: futebol, onde o 7 a 1 existe.
    MEDIAN_IQR = "MEDIAN_IQR"
    #: `(x - mín) / (máx - mín)`. Simples e frágil: um único jogo atípico
    #: comprime todo o resto.
    MIN_MAX = "MIN_MAX"
    #: Nenhuma transformação. Declarada explicitamente para que «sem
    #: normalização» seja uma decisão e não um esquecimento.
    IDENTITY = "IDENTITY"


@final
class NormalizationScope(StrEnum):
    """A POPULAÇÃO sobre a qual o normalizador é ajustado (§85).

    A V1 É `COMPETITION`, e isso é decisão de domínio, não de conveniência:
    ligas diferentes jogam futebol diferente, e uma escala comum apaga
    justamente a diferença que se quer medir.
    """

    COMPETITION = "COMPETITION"
    COMPETITION_SEASON = "COMPETITION_SEASON"
    #: A população global, cruzando competições. Ela EXISTE no catálogo e é
    #: recusada pela validação da V1 (§86) — nomeá-la é o que permite recusá-la
    #: com mensagem em vez de não ter como expressá-la.
    GLOBAL = "GLOBAL"


@final
class FitCutoffKind(StrEnum):
    """Até onde o ajuste pode enxergar (§89)."""

    #: Só dados anteriores ao instante declarado. É o modo causal.
    BEFORE_INSTANT = "BEFORE_INSTANT"
    #: Só partidas anteriores à partida sendo avaliada, na mesma população.
    BEFORE_EVALUATED_MATCH = "BEFORE_EVALUATED_MATCH"
    #: Toda a população, sem corte. RETROSPECTIVO — e por isso proibido para
    #: espaço comparável ao vivo.
    FULL_POPULATION = "FULL_POPULATION"

    @property
    def is_causal(self) -> bool:
        return self is not FitCutoffKind.FULL_POPULATION


@final
@dataclass(frozen=True, slots=True)
class NormalizerFitCutoff:
    """O corte do ajuste — parte da IDENTIDADE, e não da execução (§89, §90).

    POR QUE ELE É IDENTIDADE. Dois normalizadores com o mesmo método e a mesma
    população, um ajustado até março e outro até maio, produzem escalas
    diferentes para o mesmo valor. Se o corte fosse parâmetro de execução, os
    dois teriam a mesma impressão — e um `+0.3 desvio` de cada um seria comparado
    como se fosse a mesma medida.
    """

    kind: FitCutoffKind
    #: Obrigatório para `BEFORE_INSTANT`, proibido nos outros: um instante
    #: pendurado num corte que não o usa é ruído que muda impressão sem mudar
    #: comportamento.
    instant: Instant | None = None
    #: A impressão do corpus de ajuste, quando o normalizador é congelado
    #: (§90). Sem ela, «este normalizador foi ajustado em quê?» não tem
    #: resposta depois que o corpus avança.
    fit_corpus_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.kind is FitCutoffKind.BEFORE_INSTANT and self.instant is None:
            raise ValidationError(
                "corte de ajuste BEFORE_INSTANT sem instante — «antes de quando?»"
            )
        if self.kind is not FitCutoffKind.BEFORE_INSTANT and self.instant is not None:
            raise ValidationError(
                f"corte {self.kind} com instante declarado: ele não seria usado, e "
                "mudaria a impressão sem mudar o comportamento"
            )

    def allows_fitting_on(self, moment: Instant) -> bool:
        """Se um dado daquele instante pode entrar no ajuste (§87).

        `FULL_POPULATION` ACEITA TUDO, e é por isso que ele não é causal: o
        chamador que o escolhe está declarando que aceita retrospectiva.
        """
        if self.kind is FitCutoffKind.FULL_POPULATION:
            return True
        if self.kind is FitCutoffKind.BEFORE_INSTANT:
            assert self.instant is not None
            return moment < self.instant
        # `BEFORE_EVALUATED_MATCH` depende da partida avaliada, que este objeto
        # não conhece — quem sabe é o chamador, e ele decide com o `kind`.
        return False

    def as_canonical(self) -> dict[str, object]:
        return {
            "fit_corpus_fingerprint": self.fit_corpus_fingerprint,
            "instant": None if self.instant is None else instant_text(self.instant),
            "kind": self.kind.value,
        }


@final
@dataclass(frozen=True, slots=True)
class NormalizerDefinition:
    """A declaração de um normalizador (§84).

    ELE NÃO CARREGA PARÂMETROS AJUSTADOS — média, desvio, mediana. Isso é o
    RESULTADO do ajuste, e ele não existe nesta fase. O que existe é o contrato
    de como o ajuste deverá ser feito, com identidade suficiente para que dois
    ajustes diferentes nunca se passem um pelo outro.
    """

    key: str
    version: NormalizerVersion
    method: NormalizationMethod
    scope: NormalizationScope
    fit_cutoff: NormalizerFitCutoff
    parameters: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValidationError("normalizador sem chave")
        if self.method is NormalizationMethod.IDENTITY and self.parameters:
            raise ValidationError(
                f"normalizador {self.key} é IDENTITY e declara parâmetros — eles não "
                "seriam usados, e mudariam a impressão sem mudar a escala"
            )

    @property
    def is_causal(self) -> bool:
        """Se este normalizador pode alimentar um espaço comparável ao vivo.

        Ele precisa das DUAS coisas: corte causal e população local. Um ajuste
        que enxerga a temporada inteira carrega o futuro na escala; um que
        cruza competições carrega a distribuição de outra liga.
        """
        return self.fit_cutoff.kind.is_causal and self.scope is not NormalizationScope.GLOBAL

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": NORMALIZER_FINGERPRINT_ALGORITHM,
            "fit_cutoff": self.fit_cutoff.as_canonical(),
            "key": self.key,
            "method": self.method.value,
            "parameters": {k: self.parameters[k] for k in sorted(self.parameters)},
            "scope": self.scope.value,
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @property
    def identity(self) -> str:
        return f"{self.key}@{self.version}#{self.fingerprint[:16]}"

    def assert_usable_for_live_comparable(self) -> None:
        """Recusa um normalizador retrospectivo num espaço causal (§86, §87).

        A MENSAGEM DIZ QUAL DAS DUAS CONDIÇÕES FALHOU, porque as correções são
        diferentes: um corte retrospectivo se conserta declarando um instante;
        um escopo global se conserta escolhendo a competição.
        """
        if not self.fit_cutoff.kind.is_causal:
            raise ValidationError(
                f"o normalizador {self.key} é ajustado sobre a população inteira e o "
                "espaço é comparável ao vivo: a escala carregaria dados posteriores "
                "ao jogo avaliado (PR-05.1 §87)",
                context={"normalizer": self.key, "cutoff": self.fit_cutoff.kind.value},
            )
        if self.scope is NormalizationScope.GLOBAL:
            raise ValidationError(
                f"o normalizador {self.key} tem escopo GLOBAL: a V1 normaliza por "
                "competição, e uma escala comum entre ligas apaga a diferença que se "
                "quer medir (PR-05.1 §85, §86)",
                context={"normalizer": self.key, "scope": self.scope.value},
            )

    def __str__(self) -> str:
        return self.identity


@final
@dataclass(frozen=True, slots=True)
class NormalizerFitWindow:
    """A janela concreta de ajuste, para quando o ajuste existir.

    ELA NÃO AJUSTA NADA. O que ela faz é responder «este dado pode entrar?» —
    e é a peça que o §87 exige que exista antes de qualquer estatística ser
    calculada, para que o vazamento de ajuste seja recusável e não apenas
    lamentável.
    """

    cutoff: NormalizerFitCutoff
    #: A posição da partida avaliada, quando o corte é relativo a ela.
    evaluated_match_start: Instant | None = None

    def admits(self, moment: Instant) -> bool:
        if self.cutoff.kind is FitCutoffKind.BEFORE_EVALUATED_MATCH:
            if self.evaluated_match_start is None:
                # FAIL-CLOSED: sem saber quando a partida avaliada começou, não
                # há como afirmar que o dado é anterior a ela.
                return False
            return moment < self.evaluated_match_start
        return self.cutoff.allows_fitting_on(moment)


#: O normalizador de referência da V1 — declarado, não ajustado. Ele existe
#: para que a decisão do §85 tenha forma executável: mediana/IQR, por
#: competição, com corte anterior à partida avaliada.
DEFAULT_V1_NORMALIZER: Final[NormalizerDefinition] = NormalizerDefinition(
    key="competition_median_iqr",
    version=NormalizerVersion(major=1, minor=0),
    method=NormalizationMethod.MEDIAN_IQR,
    scope=NormalizationScope.COMPETITION,
    fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
    description=(
        "mediana e intervalo interquartil, por competição, ajustado somente "
        "sobre partidas anteriores à avaliada"
    ),
)


def match_point_is_before(point: MatchTimePoint, cutoff: MatchTimePoint) -> bool:
    """Ajuda de leitura para quem compara posições — sem inverter o operador.

    Ela existe porque `a <= b` com dois `MatchTimePoint` é fácil de escrever ao
    contrário, e a inversão silenciosa é o defeito que este PR inteiro combate.
    """
    return point <= cutoff
