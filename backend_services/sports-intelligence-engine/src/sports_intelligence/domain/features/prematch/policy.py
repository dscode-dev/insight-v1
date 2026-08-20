"""A política do contexto pré-jogo — o que conta como «partida anterior».

O QUE ESTA POLÍTICA EXISTE PARA TORNAR EXPLÍCITO (§17). «Quantos dias de
descanso o time teve» parece uma pergunta objetiva e esconde quatro decisões:

    escopo         partidas de qual competição contam?
    elegibilidade  o que prova que a partida anterior terminou?
    janelas        «recente» é quanto?
    fronteiras     a partida exatamente no limite entra?

Cada uma tem uma resposta defensável e várias plausíveis. Deixá-las
implícitas produziria uma feature cujo significado depende de quem a leu.

A V1 É `SAME_COMPETITION` (§13, §14, §15), e isso subconta descanso de
propósito: um time que jogou a Champions na quarta aparece aqui como se tivesse
descansado a semana inteira. A alternativa — cruzar competições — exigiria
decidir quais torneios compõem a carga de qual time, e essa decisão tem
evidência própria. Enquanto ela não existe, a feature diz honestamente o que
mede, e o NOME dela também (§16): `same_competition`, e nunca `rest_days`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import Version

#: A versão da política de referência. Constante de módulo porque uma chamada
#: de função no `default` de um `dataclass` é avaliada uma vez na definição da
#: classe — o que aqui seria inofensivo e mesmo assim é o padrão que o linter
#: recusa, com razão: em objetos mutáveis ele produz estado compartilhado.
_V1: Final[Version] = Version(major=1, minor=0)

#: O algoritmo da impressão da política de contexto.
CONTEXT_POLICY_FINGERPRINT_ALGORITHM: Final[str] = "historical-context-sha256-v1"

#: Quantos segundos tem uma hora. Nomeado porque o `gap` é publicado em horas e
#: calculado em segundos.
SECONDS_PER_HOUR: Final[int] = 3_600

#: Quantos segundos tem um dia — o passo das janelas de contagem.
SECONDS_PER_DAY: Final[int] = 86_400


@final
class ContextScope(StrEnum):
    """De qual população as partidas anteriores saem (§13).

    `SAME_COMPETITION` é a V1. `ALL_COMPETITIONS` está no catálogo e é
    RECUSADA — nomeá-la é o que permite recusá-la com mensagem em vez de não
    ter como expressá-la, e é o que deixa registrado que a ausência é decisão.
    """

    SAME_COMPETITION = "SAME_COMPETITION"
    ALL_COMPETITIONS = "ALL_COMPETITIONS"


@final
class PriorMatchEligibility(StrEnum):
    """O que prova que uma partida anterior aconteceu (§18, §19, §20)."""

    #: A partida está na versão publicada, começou antes da atual, e o corpus
    #: publica um `MatchResult` para ela.
    #:
    #: O `MatchResult` DA ANTERIOR NÃO É VAZAMENTO (§20): ela terminou antes de
    #: a atual começar, então o resultado dela já era conhecido no apito
    #: inicial da atual. O que este PR NÃO faz é usar o VALOR desse resultado —
    #: nenhuma feature de forma, força ou saldo (§11).
    PUBLISHED_RESULT = "PUBLISHED_RESULT"
    #: Basta pertencer à versão e ter começado antes. Mais permissiva, e mais
    #: frágil: uma partida adiada continuaria contando como jogada.
    KICKOFF_BEFORE = "KICKOFF_BEFORE"


@final
class WindowBoundary(StrEnum):
    """Como a janela de contagem trata os extremos (§28, §30)."""

    #: `[T - w, T)` — a partida exatamente em `T - w` ENTRA; a atual nunca.
    CLOSED_OPEN = "CLOSED_OPEN"


@final
@dataclass(frozen=True, slots=True)
class HistoricalContextPolicy:
    """Como o contexto pré-jogo é apurado. VERSIONADA e impressa (§17).

    `lookback_days` É ORDENADO E ENTRA NA IMPRESSÃO. Trocar `(14, 30)` por
    `(7, 30)` muda o que a feature mede, e a identidade precisa mudar junto.
    """

    version: Version = _V1
    scope: ContextScope = ContextScope.SAME_COMPETITION
    eligibility: PriorMatchEligibility = PriorMatchEligibility.PUBLISHED_RESULT
    lookback_days: tuple[int, ...] = (14, 30)
    boundary: WindowBoundary = WindowBoundary.CLOSED_OPEN

    def __post_init__(self) -> None:
        if self.scope is ContextScope.ALL_COMPETITIONS:
            raise ValidationError(
                "escopo ALL_COMPETITIONS: a V1 do contexto é local à competição "
                "(PR-05.4 §13, §15). Cruzar torneios exigiria decidir quais deles "
                "compõem a carga de cada time, e essa decisão tem evidência própria",
                context={"scope": self.scope.value},
            )
        if not self.lookback_days:
            raise ValidationError("política de contexto sem janela de retrospecto")
        if sorted(set(self.lookback_days)) != list(self.lookback_days):
            raise ValidationError(
                f"janelas de retrospecto fora de ordem ou repetidas: "
                f"{self.lookback_days}. A ordem é a dos eixos do espaço"
            )
        if any(d <= 0 for d in self.lookback_days):
            raise ValidationError("janela de retrospecto não positiva")

    @property
    def max_lookback_days(self) -> int:
        """A maior janela — o horizonte que a leitura precisa cobrir."""
        return self.lookback_days[-1]

    def window_seconds(self, days: int) -> int:
        return days * SECONDS_PER_DAY

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": CONTEXT_POLICY_FINGERPRINT_ALGORITHM,
            "boundary": self.boundary.value,
            "eligibility": self.eligibility.value,
            "lookback_days": list(self.lookback_days),
            "scope": self.scope.value,
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"contexto@{self.version}#{self.fingerprint[:12]}"


#: A política de referência da V1.
DEFAULT_CONTEXT_POLICY: Final[HistoricalContextPolicy] = HistoricalContextPolicy()
