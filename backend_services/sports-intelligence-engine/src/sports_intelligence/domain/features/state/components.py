"""Os componentes do estado — placar, campo, disciplina, substituições, odds.

CADA UM TEM DISPONIBILIDADE PRÓPRIA (§54, §55, §106). Um estado não é
«disponível» ou «indisponível» como um todo: o placar pode ser confiável
enquanto a escalação não foi publicada, e as cotações podem estar fora do
corte sem que isso diga nada sobre os cartões. Um booleano global obrigaria
quem consome a descartar tudo por causa de uma parte.

    score       AVAILABLE
    on_field    NOT_DECLARED
    discipline  AVAILABLE
    odds        TEMPORALLY_UNAVAILABLE

`ObservedZero ≠ Unavailable` VALE EM TODOS ELES (§198). Zero cartão até os 63
minutos é um fato — desde que a família `EVENT` esteja publicada e a história
seja completa. Sem `EVENT`, «zero cartões» é uma afirmação que ninguém pode
fazer, e o componente diz `NOT_DECLARED`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.temporal import MatchTimePoint
from sports_intelligence.domain.shared.canonical import decimal_text, instant_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import PlayerId, TeamId
from sports_intelligence.domain.shared.temporal import Instant

#: Quantos jogadores um time pode ter em campo. Ele é um teto e nunca um alvo:
#: menos de onze é legítimo depois de uma expulsão (§28), e mais de onze é
#: conflito de estado — nunca uma lista para «cortar» (§27).
MAX_EM_CAMPO: Final[int] = 11


@final
@dataclass(frozen=True, slots=True)
class Tally:
    """Um par mandante/visitante. Nunca negativo."""

    home: int = 0
    away: int = 0

    def __post_init__(self) -> None:
        if self.home < 0 or self.away < 0:
            raise ValidationError(f"contagem negativa: {self.home}x{self.away}")

    def plus_home(self) -> Tally:
        return Tally(home=self.home + 1, away=self.away)

    def plus_away(self) -> Tally:
        return Tally(home=self.home, away=self.away + 1)

    @property
    def total(self) -> int:
        return self.home + self.away

    def as_canonical(self) -> dict[str, int]:
        return {"away": self.away, "home": self.home}

    def __str__(self) -> str:
        return f"{self.home}-{self.away}"


@final
@dataclass(frozen=True, slots=True)
class ScoreState:
    """O placar no corte — consequência dos GOLS EFETIVOS, e de nada mais.

    ELE NÃO VEM DO `MatchResult` (§10, §12, §200). O resultado final é um fato
    pós-jogo; o placar aos 63 minutos é a soma dos gols que já aconteceram e
    já podiam ser conhecidos. Derivá-lo do resultado seria dar ao minuto 63 uma
    informação que só existe no apito final — e, pior, um placar que não muda
    quando os eventos mudam.

    AS TRÊS CONTAGENS SÃO SEPARADAS porque o futebol as separa, e o
    `MatchResult` canônico também: tempo normal, prorrogação e disputa de
    pênaltis são resultados diferentes do mesmo jogo. `home`/`away` somam
    normal e prorrogação — que é o placar corrente —, e a disputa fica fora
    (§19, §98).
    """

    regular: Tally = Tally()
    extra_time: Tally = Tally()
    shootout: Tally = Tally()
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE
    detail: str = ""

    @property
    def home(self) -> int:
        return self.regular.home + self.extra_time.home

    @property
    def away(self) -> int:
        return self.regular.away + self.extra_time.away

    @property
    def difference(self) -> int:
        """Positivo quando o mandante está à frente."""
        return self.home - self.away

    @property
    def is_level(self) -> bool:
        return self.difference == 0

    @property
    def leader(self) -> str | None:
        """`"HOME"`, `"AWAY"` ou `None` no empate.

        `None` E NÃO `"NONE"`: empate é ausência de líder, e um rótulo o faria
        parecer um terceiro time.
        """
        if self.difference > 0:
            return "HOME"
        if self.difference < 0:
            return "AWAY"
        return None

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def unavailable(self, availability: FeatureAvailability, detail: str = "") -> ScoreState:
        """O placar que não pode ser afirmado (§14).

        ELE ZERA AS CONTAGENS de propósito: um placar indisponível carregando
        `2-1` seria lido como `2-1` por quem não olhasse a disponibilidade.
        """
        return ScoreState(availability=availability, detail=detail)

    def as_canonical(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "extra_time": self.extra_time.as_canonical(),
            "regular": self.regular.as_canonical(),
            "shootout": self.shootout.as_canonical(),
        }

    def __str__(self) -> str:
        if not self.is_available:
            return f"placar ∅ ({self.availability.value})"
        pentas = f" (pen {self.shootout})" if self.shootout.total else ""
        return f"{self.home}-{self.away}{pentas}"


@final
@dataclass(frozen=True, slots=True)
class TeamOnFieldState:
    """Quem está em campo por UM time (§24).

    A LISTA É UM CONJUNTO ORDENADO. Ordem canônica por `PlayerId` porque ela
    entra na impressão do estado, e a ordem de leitura do banco não pode
    decidir a identidade do estado (§66).
    """

    team_id: TeamId
    players: tuple[PlayerId, ...] = ()
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE
    detail: str = ""

    def __post_init__(self) -> None:
        if len(set(self.players)) != len(self.players):
            raise ValidationError(
                f"time {self.team_id} com jogador repetido em campo — um jogador não "
                "ocupa duas posições (§25)"
            )
        if len(self.players) > MAX_EM_CAMPO:
            # O TETO É DO TIPO, e não só de quem transiciona (§27). O reducer
            # já recusa a substituição que passaria de onze; sem a guarda aqui,
            # uma escalação com doze titulares entraria pelo estado INICIAL, e
            # o caminho que ninguém testa é sempre o que passa.
            raise ValidationError(
                f"time {self.team_id} com {len(self.players)} em campo — o máximo é "
                f"{MAX_EM_CAMPO}, e doze nunca é uma lista para cortar (§27)"
            )

    @classmethod
    def of(
        cls,
        team_id: TeamId,
        players: tuple[PlayerId, ...],
        *,
        availability: FeatureAvailability = FeatureAvailability.AVAILABLE,
        detail: str = "",
    ) -> Self:
        # ORDENA E NÃO DEDUPLICA. `set(players)` faria o mesmo jogador duas
        # vezes virar um só em silêncio — que é o reparo que o §167 proíbe, e
        # ainda por cima o mais fácil de não notar: a lista simplesmente
        # encolhe, e nada denuncia.
        return cls(
            team_id=team_id,
            players=tuple(sorted(players, key=str)),
            availability=availability,
            detail=detail,
        )

    @property
    def size(self) -> int:
        return len(self.players)

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def has(self, player: PlayerId) -> bool:
        return player in self.players

    def with_players(self, players: tuple[PlayerId, ...]) -> TeamOnFieldState:
        return TeamOnFieldState.of(
            self.team_id, players, availability=self.availability, detail=self.detail
        )

    def degraded(self, availability: FeatureAvailability, detail: str) -> TeamOnFieldState:
        """Sem jogadores e com motivo (§22, §31).

        A LISTA SOME JUNTO com a disponibilidade: um campo «indisponível» que
        ainda carregasse dez nomes seria usado como se fossem dez nomes.
        """
        return TeamOnFieldState(
            team_id=self.team_id, players=(), availability=availability, detail=detail
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "players": [str(p) for p in self.players],
            "team_id": str(self.team_id),
        }

    def __str__(self) -> str:
        if not self.is_available:
            return f"{self.team_id}: ∅ ({self.availability.value})"
        return f"{self.team_id}: {self.size} em campo"


@final
@dataclass(frozen=True, slots=True)
class OnFieldState:
    """Quem está em campo, pelos dois times (§21, §26).

    `InitialLineup ≠ CurrentOnFieldState` é o contrato inteiro deste tipo: a
    escalação inicial é um fato publicado e IMUTÁVEL; o estado em campo é o
    resultado de aplicar as transições efetivas sobre ela.

    O MESMO JOGADOR NOS DOIS TIMES NÃO CONSTRÓI (§26). Não é um caso a
    corrigir: é um defeito do dado, e um estado que o «resolvesse» escolhendo
    um lado inventaria a resposta.
    """

    home: TeamOnFieldState
    away: TeamOnFieldState

    def __post_init__(self) -> None:
        dos_dois = set(self.home.players) & set(self.away.players)
        if dos_dois:
            nomes = ", ".join(sorted(str(p) for p in dos_dois))
            raise ValidationError(
                f"jogador(es) em campo pelos DOIS times: {nomes}. Corrigir escolhendo "
                "um lado inventaria a resposta (PR-05.2 §26)",
                context={"players": nomes},
            )

    @property
    def is_available(self) -> bool:
        """Disponível quando os DOIS lados são. Meio campo não é campo."""
        return self.home.is_available and self.away.is_available

    def team(self, team_id: TeamId) -> TeamOnFieldState | None:
        if self.home.team_id == team_id:
            return self.home
        if self.away.team_id == team_id:
            return self.away
        return None

    def with_team(self, novo: TeamOnFieldState) -> OnFieldState:
        if self.home.team_id == novo.team_id:
            return OnFieldState(home=novo, away=self.away)
        if self.away.team_id == novo.team_id:
            return OnFieldState(home=self.home, away=novo)
        raise ValidationError(f"time {novo.team_id} não joga esta partida")

    def as_canonical(self) -> dict[str, object]:
        return {"away": self.away.as_canonical(), "home": self.home.as_canonical()}

    def __str__(self) -> str:
        return f"{self.home} · {self.away}"


@final
@dataclass(frozen=True, slots=True)
class TeamDisciplinaryState:
    """Cartões e expulsões de UM time, até o corte (§35).

    `SECOND_YELLOW` CONTA NOS DOIS LUGARES, e é o que ele é: um segundo amarelo
    é um amarelo — o jogador o recebeu — e é uma expulsão. Contá-lo só como
    expulsão faria a contagem de amarelos do time ficar menor do que a súmula.
    """

    team_id: TeamId
    yellow_cards: int = 0
    dismissals: int = 0
    sent_off: tuple[PlayerId, ...] = ()
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE

    def __post_init__(self) -> None:
        if self.yellow_cards < 0 or self.dismissals < 0:
            raise ValidationError("contagem disciplinar negativa")

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def plus_yellow(self) -> TeamDisciplinaryState:
        return replace(self, yellow_cards=self.yellow_cards + 1)

    def plus_dismissal(self, player: PlayerId | None) -> TeamDisciplinaryState:
        """A expulsão conta MESMO sem saber quem foi (§39).

        O time perdeu um jogador — isso é fato disciplinar e sobrevive. Quem
        saiu é outra pergunta, e a resposta ausente degrada o CAMPO, não a
        disciplina.
        """
        expulsos = (
            self.sent_off if player is None else tuple(sorted({*self.sent_off, player}, key=str))
        )
        return replace(self, dismissals=self.dismissals + 1, sent_off=expulsos)

    def as_canonical(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "dismissals": self.dismissals,
            "sent_off": [str(p) for p in self.sent_off],
            "team_id": str(self.team_id),
            "yellow_cards": self.yellow_cards,
        }

    def __str__(self) -> str:
        if not self.is_available:
            return f"{self.team_id}: disciplina ∅"
        return f"{self.team_id}: {self.yellow_cards}A {self.dismissals}V"


@final
@dataclass(frozen=True, slots=True)
class DisciplinaryState:
    """A disciplina dos dois times."""

    home: TeamDisciplinaryState
    away: TeamDisciplinaryState

    @property
    def is_available(self) -> bool:
        return self.home.is_available and self.away.is_available

    def team(self, team_id: TeamId) -> TeamDisciplinaryState | None:
        if self.home.team_id == team_id:
            return self.home
        if self.away.team_id == team_id:
            return self.away
        return None

    def with_team(self, novo: TeamDisciplinaryState) -> DisciplinaryState:
        if self.home.team_id == novo.team_id:
            return DisciplinaryState(home=novo, away=self.away)
        if self.away.team_id == novo.team_id:
            return DisciplinaryState(home=self.home, away=novo)
        raise ValidationError(f"time {novo.team_id} não joga esta partida")

    def as_canonical(self) -> dict[str, object]:
        return {"away": self.away.as_canonical(), "home": self.home.as_canonical()}

    def __str__(self) -> str:
        return f"{self.home} · {self.away}"


@final
@dataclass(frozen=True, slots=True)
class AppliedSubstitution:
    """Uma substituição JÁ APLICADA ao estado (§34).

    ELA GUARDA REFERÊNCIA, e não o evento: o estado não carrega payload de
    evento — quem precisa do fato inteiro vai ao corpus com o id.
    """

    event_id: uuid.UUID
    team_id: TeamId
    player_out: PlayerId
    player_in: PlayerId
    at: MatchTimePoint

    def as_canonical(self) -> dict[str, object]:
        return {
            "at": self.at.as_canonical(),
            "event_id": str(self.event_id),
            "player_in": str(self.player_in),
            "player_out": str(self.player_out),
            "team_id": str(self.team_id),
        }


@final
@dataclass(frozen=True, slots=True)
class SubstitutionState:
    """As substituições aplicadas até o corte, em ordem canônica."""

    applied: tuple[AppliedSubstitution, ...] = ()
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE

    @property
    def count(self) -> int:
        return len(self.applied)

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def by_team(self, team_id: TeamId) -> tuple[AppliedSubstitution, ...]:
        return tuple(s for s in self.applied if s.team_id == team_id)

    def plus(self, substitution: AppliedSubstitution) -> SubstitutionState:
        return replace(self, applied=(*self.applied, substitution))

    def as_canonical(self) -> dict[str, object]:
        return {
            "applied": [s.as_canonical() for s in self.applied],
            "availability": self.availability.value,
            "count": self.count,
        }

    def __str__(self) -> str:
        return f"{self.count} substituição(ões)"


@final
@dataclass(frozen=True, slots=True)
class OddsQuoteState:
    """A ÚLTIMA cotação conhecida de um fluxo, no corte (§121, §122).

    «ÚLTIMA CONHECIDA» É ESTADO DE OBSERVAÇÃO, E NÃO INFERÊNCIA DE VALOR
    (§126). O contrato diz «a última vez que vimos este mercado, ele estava
    assim» — e não «este é o preço agora». A diferença aparece quando a
    cotação tem meia hora: o estado continua verdadeiro, e usá-lo como preço
    corrente seria interpolar sem dizer.
    """

    bookmaker: str
    market: str
    selection: str
    decimal_odds: str
    observed_at: Instant
    line: str | None = None
    #: A referência da observação de origem, para a travessia (§62).
    source_reference: str = ""

    def stream_key(self) -> tuple[str, str, str, str]:
        """O fluxo a que esta cotação pertence.

        A LINHA FAZ PARTE DA CHAVE: `over 2.5` e `over 3.5` são mercados
        diferentes com o mesmo nome, e uni-los faria a última observação de um
        sobrescrever a do outro.
        """
        return (self.bookmaker, self.market, self.selection, self.line or "")

    def as_canonical(self) -> dict[str, object]:
        return {
            "bookmaker": self.bookmaker,
            "decimal_odds": self.decimal_odds,
            "line": self.line,
            "market": self.market,
            "observed_at": instant_text(self.observed_at),
            "selection": self.selection,
        }

    def __str__(self) -> str:
        linha = f" {self.line}" if self.line else ""
        return f"{self.bookmaker} {self.market}{linha} {self.selection}={self.decimal_odds}"


@final
@dataclass(frozen=True, slots=True)
class OddsState:
    """As cotações conhecidas no corte — sem agregação nenhuma (§46, §49).

    NADA DE MEDIANA, CONSENSO OU MOVIMENTO. Duas casas cotando o mesmo mercado
    continuam duas observações (§50, §124); reduzi-las a um número seria a
    primeira feature de mercado, e ela tem versão, escopo e política próprios.
    """

    quotes: tuple[OddsQuoteState, ...] = ()
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE
    detail: str = ""

    def __post_init__(self) -> None:
        chaves = [q.stream_key() for q in self.quotes]
        if len(set(chaves)) != len(chaves):
            raise ValidationError(
                "duas cotações do MESMO fluxo no estado — só a última conhecida entra "
                "(PR-05.2 §122)"
            )

    @classmethod
    def of(
        cls,
        quotes: tuple[OddsQuoteState, ...],
        *,
        availability: FeatureAvailability = FeatureAvailability.AVAILABLE,
        detail: str = "",
    ) -> Self:
        return cls(
            quotes=tuple(sorted(quotes, key=lambda q: q.stream_key())),
            availability=availability,
            detail=detail,
        )

    @property
    def count(self) -> int:
        return len(self.quotes)

    @property
    def bookmakers(self) -> tuple[str, ...]:
        return tuple(sorted({q.bookmaker for q in self.quotes}))

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def as_canonical(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "quotes": [q.as_canonical() for q in self.quotes],
        }

    def __str__(self) -> str:
        if not self.is_available:
            return f"odds ∅ ({self.availability.value})"
        return f"{self.count} cotação(ões) de {len(self.bookmakers)} casa(s)"


@final
@dataclass(frozen=True, slots=True)
class EventStructuralState:
    """O que o estado guarda sobre os eventos efetivos (§42, §44).

    ELE NÃO CARREGA OS EVENTOS. Cem mil objetos dentro de um estado tornariam
    inviável reconstruir dez mil partidas — e a projeção efetiva continua sendo
    a autoridade sobre eles (§45). O que fica aqui é o suficiente para
    identificar o conjunto: quantos, qual o último, e a impressão do conjunto.

    NÃO HÁ CONTAGEM POR TIPO (§43). «Oito chutes do mandante» é feature, e ela
    chega no PR-05.3 lendo a mesma projeção.
    """

    effective_count: int = 0
    latest_event_id: uuid.UUID | None = None
    latest_position: MatchTimePoint | None = None
    digest: str = ""
    availability: FeatureAvailability = FeatureAvailability.AVAILABLE

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def as_canonical(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "digest": self.digest,
            "effective_count": self.effective_count,
            "latest_event_id": (
                None if self.latest_event_id is None else str(self.latest_event_id)
            ),
            "latest_position": (
                None if self.latest_position is None else self.latest_position.as_canonical()
            ),
        }

    def __str__(self) -> str:
        return f"{self.effective_count} evento(s) efetivo(s)"


def decimal_as_text(valor: object) -> str:
    """O decimal de uma cotação como texto canônico.

    `float` NÃO SERVE: `float(Decimal("2.05"))` não é 2.05, e a impressão do
    estado depende de bytes iguais para conteúdo igual.
    """
    from decimal import Decimal

    if valor is None:
        raise ValidationError("cotação sem valor")
    texto = decimal_text(Decimal(str(valor)))
    if texto is None:  # pragma: no cover - `decimal_text` só devolve None para None
        raise ValidationError("cotação sem valor")
    return texto
