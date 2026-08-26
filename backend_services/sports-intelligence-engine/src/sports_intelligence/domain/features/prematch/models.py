"""Os insumos do contexto pré-jogo — e a prova de que o corpus alcança o passado.

O PONTO MAIS SUTIL DESTE PR ESTÁ AQUI (§31 ao §34).

«Zero partidas nos últimos 14 dias» tem duas causas que produzem o mesmo
número: o time de fato não jogou, ou o corpus começa depois de `T - 14d`. A
segunda é o caso da PRIMEIRA RODADA de qualquer corpus — e ali «zero» seria uma
afirmação sobre o mundo feita a partir de uma limitação do arquivo.

    corpus alcança T - 14d   e nenhuma partida  ⇒  0 OBSERVADO
    corpus começa em T - 3d                     ⇒  INSUFFICIENT_COVERAGE

`ContextCoverage` carrega o instante da PRIMEIRA partida daquela competição na
versão publicada. É contra ele que a janela é conferida — e é o que torna a
distinção acima decidível em vez de adivinhada.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId, TeamId
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class PriorMatchRef:
    """Uma partida anterior elegível — o mínimo que o contexto precisa dela.

    ELA NÃO CARREGA O RESULTADO, e a omissão é o §11 tornado estrutural: o
    contexto da V1 mede CALENDÁRIO, e um objeto que carregasse o placar
    convidaria a próxima pessoa a somar pontos. `concluded` diz apenas que a
    conclusão foi PROVADA — não como ela terminou.
    """

    kickoff: Instant
    match_id: MatchId

    @property
    def key(self) -> tuple[Instant, str]:
        """A chave de ORDENAÇÃO — instante, e o id como desempate textual.

        DUAS PARTIDAS PODEM COMEÇAR NO MESMO INSTANTE, e numa rodada inteira
        isso é a regra e não a exceção: seis jogos às 15:00 de sábado. Ordenar
        só por instante deixaria o desempate para o `MatchId`, que NÃO tem
        ordem total — e nem deveria ter: «uma partida menor que outra» não
        significa nada.

        O desempate é o TEXTO do identificador. Ele não tem significado
        esportivo nenhum, e é exatamente por isso que serve: ele é estável
        entre execuções, e a lista precisa de uma ordem só para que o digest da
        procedência não dependa de quem leu primeiro.
        """
        return (self.kickoff, str(self.match_id))

    def as_canonical(self) -> dict[str, str]:
        from sports_intelligence.domain.shared.canonical import instant_text

        return {"kickoff": instant_text(self.kickoff), "match_id": str(self.match_id)}


@final
@dataclass(frozen=True, slots=True)
class TeamPriorMatches:
    """As partidas anteriores de UM time, para UMA partida atual.

    ELAS JÁ CHEGAM FILTRADAS PELO ESCOPO E PELA ELEGIBILIDADE. Quem lê o corpus
    aplica a política; o domínio recebe a lista e conta. Uma lista que chegasse
    crua obrigaria o domínio a conhecer competição, versão e prova de conclusão
    — que é conhecimento de leitura, não de cálculo.
    """

    team_id: TeamId
    #: Em ordem CRESCENTE de instante. A ordem é imposta na construção: a do
    #: banco não pode decidir qual é «a anterior».
    matches: tuple[PriorMatchRef, ...] = ()

    def __post_init__(self) -> None:
        if list(self.matches) != sorted(self.matches, key=lambda m: m.key):
            raise ValidationError(
                f"partidas anteriores do time {self.team_id} fora de ordem — a ordem "
                "decide qual é a mais recente, e a do banco não pode decidi-la"
            )
        ids = [m.match_id for m in self.matches]
        if len(set(ids)) != len(ids):
            raise ValidationError(f"partida anterior repetida para o time {self.team_id}")

    @property
    def latest(self) -> PriorMatchRef | None:
        """A mais recente. `None` quando não há nenhuma (§26)."""
        return self.matches[-1] if self.matches else None

    def within(self, *, start: Instant, end: Instant) -> tuple[PriorMatchRef, ...]:
        """As partidas em `[start, end)` (§28, §29, §30).

        FECHADO NO INÍCIO, ABERTO NO FIM. A partida exatamente em `T - w` entra;
        a partida exatamente em `T` — a atual — nunca. As duas pontas são
        decisões, e as duas são testadas.
        """
        return tuple(m for m in self.matches if start <= m.kickoff < end)


@final
@dataclass(frozen=True, slots=True)
class ContextCoverage:
    """Até onde o corpus alcança, para aquela competição (§32, §33, §34).

    `earliest_kickoff` é o instante da PRIMEIRA partida da competição NAQUELA
    versão publicada. `None` significa que a versão não publica partida nenhuma
    daquela competição — e aí nada é afirmável.
    """

    competition_id: CompetitionId
    earliest_kickoff: Instant | None = None

    def covers(self, *, start: Instant) -> bool:
        """Se o corpus alcança `start` — o começo da janela pedida.

        FAIL-CLOSED (§34). Sem primeira partida conhecida, a resposta é «não
        dá para provar», e o contexto vira `INSUFFICIENT_COVERAGE` em vez de
        zero.
        """
        if self.earliest_kickoff is None:
            return False
        return self.earliest_kickoff <= start


@final
@dataclass(frozen=True, slots=True)
class MatchContextInput:
    """O contexto de UMA partida atual, pronto para virar feature.

    `kickoff` É O DA PARTIDA ATUAL, e é a fronteira de tudo (§22). Ele NÃO é o
    `FeatureAsOf`: o contexto pré-jogo é o mesmo aos 10, aos 30 e aos 63
    minutos — ele descreve o que havia ANTES do apito, e não muda durante o
    jogo.
    """

    match_id: MatchId
    competition_id: CompetitionId
    kickoff: Instant
    home: TeamPriorMatches
    away: TeamPriorMatches
    #: SEM PADRÃO, e é deliberado: uma cobertura «vazia» por omissão faria toda
    #: contagem virar `INSUFFICIENT_COVERAGE` em silêncio, ou — pior — um
    #: padrão otimista faria zero passar por observado. Quem monta o contexto
    #: sabe qual competição é, e precisa dizer até onde o corpus alcança.
    coverage: ContextCoverage

    def __post_init__(self) -> None:
        if self.coverage.competition_id != self.competition_id:
            raise ValidationError(
                f"a cobertura é da competição {self.coverage.competition_id} e o "
                f"contexto é de {self.competition_id}"
            )
        for lado in (self.home, self.away):
            posteriores = [m for m in lado.matches if m.kickoff >= self.kickoff]
            if posteriores:
                # §29, §164 — uma partida do futuro no contexto produziria
                # descanso e carga que ninguém tinha no apito inicial.
                raise ValidationError(
                    f"o contexto de {self.match_id} recebeu {len(posteriores)} "
                    f"partida(s) do time {lado.team_id} em ou depois do próprio "
                    "apito inicial",
                    context={"match_id": str(self.match_id)},
                )
            proprias = [m for m in lado.matches if m.match_id == self.match_id]
            if proprias:
                raise ValidationError(f"a partida {self.match_id} aparece no próprio contexto")

    def side(self, team_id: TeamId) -> TeamPriorMatches | None:
        if team_id == self.home.team_id:
            return self.home
        if team_id == self.away.team_id:
            return self.away
        return None


def team_prior_matches(team_id: TeamId, refs: Sequence[PriorMatchRef]) -> TeamPriorMatches:
    """Constrói o histórico de um time ORDENANDO — a porta normal.

    O construtor direto RECUSA lista fora de ordem, e é assim que ele detecta
    quem montou o objeto sem passar por aqui. Esta função é a que ordena.
    """
    return TeamPriorMatches(team_id=team_id, matches=tuple(sorted(refs, key=lambda m: m.key)))
