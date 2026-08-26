"""O que um calculador de feature enxerga — e o que ele nunca vai enxergar.

A FRONTEIRA EM UMA FRASE (§94, §97): o calculador recebe FATOS JÁ FILTRADOS de
UMA partida, num corte. Não recebe conexão de banco, cliente de object store,
repositório nem o corpus inteiro. Quem lê o corpus é a camada de aplicação;
quem calcula recebe o resultado da leitura.

    CanonicalFeatureContext  =  fatos de UMA partida, ATÉ um corte

TRÊS COISAS QUE ELE NÃO TEM, E CADA AUSÊNCIA É A DECISÃO:

    o corpus inteiro     ele é `match`-scoped. Um contexto global permitiria
                         uma feature «média da liga» carregar dez mil partidas
                         para dentro de um cálculo de uma (§97)
    o resultado final    `result` só é entregue quando o corte é pós-jogo. Um
                         contexto que sempre o carregasse tornaria o vazamento
                         uma questão de disciplina (§13, §14)
    o evento cru         os eventos vêm pela PROJEÇÃO EFETIVA, e não pela lista
                         canônica final: em modo `AS_KNOWN`, o que o calculador
                         vê é o que se sabia (§98)

A ORIGEM É PARTE DO CONTEXTO (§60). Todo cálculo sabe de qual versão do corpus
os fatos vieram e qual é a impressão dela — sem isso, um valor calculado hoje
não teria como ser reproduzido contra o mesmo dado amanhã.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self, final

from sports_intelligence.domain.corpus.versions import HistoricalCanonicalDatasetVersion
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.projection import (
    EffectiveEventProjection,
    EventKnowledge,
    ProjectionOutcome,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import DatasetVersion


@final
@dataclass(frozen=True, slots=True)
class CorpusSource:
    """De onde os fatos vieram — versão e impressão (§60, §142).

    A IMPRESSÃO É O QUE TORNA A ORIGEM VERIFICÁVEL. O id da versão diz «da
    1.0»; a impressão diz «da 1.0 cujo conteúdo era este». Se alguém
    republicar conteúdo diferente sob o mesmo número — o que o ADR-0026
    impede, e a defesa em profundidade não custa —, a impressão denuncia.
    """

    version_id: str
    version: DatasetVersion
    corpus_fingerprint: ContentHash
    #: As famílias que aquela versão de fato publica. É contra elas que o
    #: `FeatureSpace` confere as exigências dele (§57).
    published_families: frozenset[CoverageFamily] = frozenset()

    def __post_init__(self) -> None:
        if not self.version_id.strip():
            raise ValidationError("origem de corpus sem id de versão")

    @classmethod
    def of(
        cls,
        version: HistoricalCanonicalDatasetVersion,
        *,
        published_families: frozenset[CoverageFamily] = frozenset(),
    ) -> Self:
        """A origem a partir de uma versão publicada.

        ELA RECUSA VERSÃO NÃO PUBLICADA (§2). Uma versão em `BUILDING` pode
        estar com pertinência pela metade, e uma feature calculada sobre ela
        descreveria um corpus que nunca existiu.
        """
        if not version.status.is_readable_corpus:
            raise ValidationError(
                f"a versão {version.version} está em {version.status} e não é legível "
                "como corpus: features só se calculam sobre versão publicada "
                "(PR-05.1 §2)",
                context={"version_id": version.id, "status": version.status.value},
            )
        if version.corpus_fingerprint is None:
            raise ValidationError(
                f"a versão {version.version} não tem impressão de corpus — sem ela, "
                "o cálculo não teria como ser reproduzido contra o mesmo dado"
            )
        return cls(
            version_id=version.id,
            version=version.version,
            corpus_fingerprint=version.corpus_fingerprint,
            published_families=published_families,
        )

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra na impressão do snapshot.

        O `version_id` NÃO ENTRA — ele é um UUID de linha, e duas publicações
        independentes do mesmo conteúdo teriam ids diferentes. O que identifica
        o conteúdo é a impressão (§141).
        """
        return {
            "corpus_fingerprint": self.corpus_fingerprint.value,
            "version": str(self.version),
        }

    def __str__(self) -> str:
        return f"corpus {self.version} [{self.corpus_fingerprint.value[:12]}]"


@final
@dataclass(frozen=True, slots=True)
class CanonicalFeatureContext:
    """Os fatos de UMA partida, filtrados para UM corte (§93).

    ELE É CONSTRUÍDO PELA APLICAÇÃO E CONSUMIDO PELO DOMÍNIO. A construção
    envolve I/O — ler o corpus, projetar os eventos —, e por isso não acontece
    aqui: o que este objeto faz é GUARDAR o resultado com as guardas certas.

    `result` É PROPRIEDADE E NÃO CAMPO, e essa é a diferença que importa: o
    resultado final só é devolvido quando o corte é pós-jogo. Guardá-lo num
    campo público faria o vazamento depender de o calculador «lembrar» de não
    olhar (§13, §14).
    """

    as_of: FeatureAsOf
    source: CorpusSource
    policy: TemporalAvailabilityPolicy
    match: Match
    #: A projeção EFETIVA — não a lista canônica final (§98).
    events: ProjectionOutcome = field(default_factory=ProjectionOutcome)
    #: A escalação inicial, quando a versão a publica e a política a admite.
    lineups: tuple[Lineup, ...] = ()
    #: As cotações JÁ FILTRADAS pelo corte. Uma cotação posterior nunca chega
    #: aqui: o filtro é feito por quem monta o contexto, com o mesmo guarda.
    odds: tuple[CanonicalOddsObservation, ...] = ()
    #: O resultado final. Ele é privado de propósito — veja `result`.
    _result: MatchResult | None = None

    def __post_init__(self) -> None:
        if self.match.id != self.as_of.match_id:
            raise ValidationError(
                f"contexto de {self.as_of.match_id} carregando a partida {self.match.id}"
            )

    @property
    def result(self) -> MatchResult | None:
        """O resultado final — SÓ quando o corte é pós-jogo (§13, §73).

        Ele não levanta: devolver `None` é a resposta certa para «qual era o
        placar final aos 63 minutos», e ela é a mesma que o mundo dava naquele
        instante. Quem precisa do motivo tipado usa o guarda.
        """
        if not self.as_of.is_post_match:
            return None
        return self._result

    @property
    def has_result_in_corpus(self) -> bool:
        """Se o resultado EXISTE no corpus — independente de poder ser usado.

        A DISTINÇÃO É O §67 aplicada ao contexto: «não existe» e «existe e é do
        futuro» produzem o mesmo `None` em `result`, e são diagnósticos
        diferentes.
        """
        return self._result is not None

    def publishes(self, family: CoverageFamily) -> bool:
        return family in self.source.published_families

    @classmethod
    def build(
        cls,
        *,
        as_of: FeatureAsOf,
        source: CorpusSource,
        policy: TemporalAvailabilityPolicy,
        match: Match,
        canonical_events: tuple[CanonicalMatchEvent, ...] = (),
        knowledge: EventKnowledge | None = None,
        lineups: tuple[Lineup, ...] = (),
        odds: tuple[CanonicalOddsObservation, ...] = (),
        result: MatchResult | None = None,
    ) -> Self:
        """Monta o contexto PROJETANDO os eventos (§98).

        ESTA É A ÚNICA PORTA que produz um contexto a partir de eventos
        canônicos, e ela projeta sempre. Um construtor que aceitasse a lista
        canônica direta deixaria a projeção opcional — e o dia em que alguém a
        pulasse, o cálculo veria correções do futuro sem nada denunciar.
        """
        projecao = EffectiveEventProjection.with_policy(policy).project(
            canonical_events, as_of=as_of, knowledge=knowledge
        )
        return cls(
            as_of=as_of,
            source=source,
            policy=policy,
            match=match,
            events=projecao,
            lineups=lineups,
            odds=odds,
            _result=result,
        )

    def as_canonical(self) -> dict[str, object]:
        """A procedência temporal do contexto — para a impressão do snapshot."""
        return {
            "as_of": self.as_of.as_canonical(),
            "policy_fingerprint": self.policy.fingerprint,
            "policy_version": str(self.policy.version),
            "source": self.source.as_canonical(),
        }

    def digest(self) -> str:
        import hashlib

        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"contexto {self.as_of} · {self.events.size} evento(s) efetivo(s)"
