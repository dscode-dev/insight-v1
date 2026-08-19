"""«Este evento pode entrar?» — a decisão, por evento, com o porquê.

A ORDEM DAS GUARDAS É A ORDEM DA CAUSA RAIZ, e ela importa: a primeira que
dispara é a que vira o motivo, então a mais fundamental precisa vir primeiro.
Um evento cuja partida não é elegível e cujo tipo também não está mapeado tem
UM problema que interessa — a partida —, e reportar o tipo mandaria alguém
mapear um rótulo para descobrir que o evento continua fora.

    partida        sem partida elegível, nada mais importa
    tipo           sem tradução, não há evento canônico possível
    identidade     o que o tipo EXIGE precisa existir
    relógio        um momento impossível não é um momento
    licença        o direito de publicar naquele escopo

O QUE ELA NÃO FAZ, e a lista é o limite (§45, §47):

    não julga futebol      «este jogo deveria ter 90 minutos» não é verificação
                           de integridade, é palpite — e prorrogação existe
    não recalibra          se a resolução marcou o jogador como REVIEW, a
    confiança              decisão dela vale aqui; recalcular seria uma segunda
                           opinião sobre a mesma evidência (§46)
    não inventa eixo       os seis do PR-04.1 bastam (§43)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.events.build import (
    EventEligibility,
    EventExclusionReason,
    source_key_of,
)
from sports_intelligence.domain.events.records import HistoricalEventRecord
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.quality.issues import IssueCode, QualityIssue
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import Period
from sports_intelligence.historical.events.references import EventReferences

#: O teto de minuto que denuncia erro ESTRUTURAL, e não julgamento esportivo.
#:
#: 200 é folgado de propósito: prorrogação vai a 120, acréscimos existem, e o
#: número está aqui para pegar coluna trocada e parse errado — `1998` num
#: campo de minuto —, não para opinar sobre quanto um jogo dura (§47).
MAX_PLAUSIBLE_MINUTE: Final[int] = 200

#: Os períodos em que o relógio corre. Um evento aos 30 minutos do INTERVALO é
#: estruturalmente impossível: o relógio não está correndo lá.
_COM_RELOGIO: Final[frozenset[Period]] = frozenset(
    {
        Period.FIRST_HALF,
        Period.SECOND_HALF,
        Period.EXTRA_TIME_FIRST,
        Period.EXTRA_TIME_SECOND,
        Period.PENALTY_SHOOTOUT,
    }
)


@final
@dataclass(frozen=True, slots=True)
class EventEligibilityPolicy:
    """O que basta para um evento entrar. Versionada, como toda política.

    ELA NÃO É UMA `HistoricalQualityPolicy` PARALELA (§41). A política de
    qualidade continua decidindo sobre a PARTIDA, e esta decide o que é
    específico do evento — tipo não mapeado, identidade exigida pelo tipo,
    relógio estrutural. Duplicar a de partida aqui faria os pisos de eixo
    existirem em dois lugares e divergirem no primeiro ajuste.
    """

    scope: UsageScope
    #: As licenças que podem publicar neste escopo. Vem do mesmo catálogo da
    #: pegada de licença do PR-04.1 — não é uma segunda tabela.
    allowed_licenses: frozenset[LicenseClass]
    #: Tipo desconhecido vira revisão, e não descarte silencioso (§14). O
    #: rótulo cru sobrevive na linhagem, então «o que era esse evento» tem
    #: resposta sem reabrir o arquivo.
    unmapped_goes_to_review: bool = True
    version: int = 1

    @classmethod
    def research(cls) -> EventEligibilityPolicy:
        return cls(
            scope=UsageScope.RESEARCH,
            allowed_licenses=frozenset(
                {
                    LicenseClass.PUBLIC_DOMAIN,
                    LicenseClass.ATTRIBUTION_REQUIRED,
                    LicenseClass.COMMERCIAL_ALLOWED,
                    LicenseClass.RESEARCH_ONLY,
                }
            ),
        )

    @classmethod
    def commercial(cls) -> EventEligibilityPolicy:
        """O comercial NÃO aceita `RESEARCH_ONLY` nem `UNKNOWN`.

        `UNKNOWN` fica de fora porque licença não declarada tratada como
        permissiva é supor permissividade — e o custo do erro é jurídico
        (ADR-0025).
        """
        return cls(
            scope=UsageScope.COMMERCIAL,
            allowed_licenses=frozenset(
                {LicenseClass.PUBLIC_DOMAIN, LicenseClass.COMMERCIAL_ALLOWED}
            ),
        )

    def permits(self, license_class: LicenseClass) -> bool:
        return license_class in self.allowed_licenses


@final
@dataclass(frozen=True, slots=True)
class EventEligibilityEvaluator:
    """Decide, evento a evento. Sem estado entre chamadas."""

    policy: EventEligibilityPolicy
    types: EventTypeMapping

    def evaluate(
        self,
        record: HistoricalEventRecord,
        *,
        references: EventReferences,
        eligible_matches: frozenset[MatchId],
        license_class: LicenseClass,
    ) -> EventEligibility:
        chave = source_key_of(record)
        escopo = self.policy.scope

        # 1. A PARTIDA. Sem ela, o evento não pertence a nada.
        partida = references.match_for(record)
        if partida is None:
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.IDENTITY_FAILURE,
                issues=(
                    QualityIssue(
                        code=IssueCode.UNRESOLVED_IDENTITY,
                        subject=f"match:{record.match_reference}",
                    ),
                ),
                detail=(
                    f"a referência de partida {record.match_reference!r} não tem "
                    "mapeamento provado para este provedor"
                ),
            )
        if partida not in eligible_matches:
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.MATCH_NOT_ELIGIBLE,
                issues=(
                    QualityIssue(
                        code=IssueCode.DANGLING_CANONICAL_REFERENCE,
                        subject=f"match:{partida}",
                    ),
                ),
                detail=(
                    "a partida existe e não é elegível nesta avaliação — um evento "
                    "não pode entrar num corpus onde a partida dele não entrou"
                ),
            )

        # 2. O TIPO. Sem tradução, não há evento canônico possível (§14).
        traducao = self.types.resolve(record.raw_type)
        if not traducao.is_mapped:
            problema = (
                QualityIssue(
                    code=IssueCode.MISSING_REQUIRED_IDENTITY,
                    subject=f"event_type:{record.raw_type}",
                    context={"raw_type": record.raw_type},
                ),
            )
            detalhe = (
                f"tipo {record.raw_type!r} não está na tabela do provedor "
                f"{record.provider_id} — mapeá-lo é uma decisão, e escolher um "
                "tipo canônico por conta própria produziria fato errado"
            )
            if self.policy.unmapped_goes_to_review:
                return EventEligibility.review(
                    record_key=chave,
                    scope=escopo,
                    reason=EventExclusionReason.UNMAPPED_TYPE,
                    issues=problema,
                    detail=detalhe,
                )
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.UNMAPPED_TYPE,
                issues=problema,
                detail=detalhe,
            )
        tipo = traducao.require()

        # 3. A IDENTIDADE QUE O TIPO EXIGE — e só a que ele exige (§58, §59).
        falta = self._identidade_faltando(record, tipo, references)
        if falta is not None:
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.IDENTITY_FAILURE,
                issues=(QualityIssue(code=IssueCode.UNRESOLVED_IDENTITY, subject=falta),),
                detail=(
                    f"{tipo} exige {falta.split(':')[0]} e a referência não resolveu. "
                    "Inventar um id aqui produziria um fato atribuído a quem não o "
                    "praticou"
                ),
            )

        # 4. O RELÓGIO. Estrutura, não julgamento esportivo (§47).
        problema_de_relogio = self._relogio_impossivel(record)
        if problema_de_relogio is not None:
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.INVALID_CLOCK,
                issues=(QualityIssue(code=IssueCode.TEMPORAL_INCONSISTENCY, subject=chave),),
                detail=problema_de_relogio,
            )

        # 5. A LICENÇA. Por último porque ela não é defeito do dado: o evento
        # está perfeito e o direito de publicá-lo NESTE escopo é que falta.
        if not self.policy.permits(license_class):
            return EventEligibility.excluded(
                record_key=chave,
                scope=escopo,
                reason=EventExclusionReason.LICENSE_POLICY,
                license_class=license_class,
                issues=(
                    QualityIssue(
                        code=IssueCode.LICENSE_RESTRICTED
                        if license_class is not LicenseClass.UNKNOWN
                        else IssueCode.LICENSE_UNKNOWN,
                        subject=chave,
                    ),
                ),
                detail=(
                    f"evidência {license_class} num build {escopo} — o evento é "
                    "válido e não pode ser publicado neste escopo"
                ),
            )

        return EventEligibility.included(record_key=chave, scope=escopo)

    @staticmethod
    def _identidade_faltando(
        record: HistoricalEventRecord,
        tipo: EventType,
        references: EventReferences,
    ) -> str | None:
        """O que o TIPO exige e não resolveu. `None` quando está tudo lá.

        AS EXIGÊNCIAS SÃO DO DOMÍNIO (§58, §59). `requires_team` e
        `requires_player` são propriedades do `EventType` desde o PR-01;
        impor requisitos maiores aqui faria um apito final precisar de dono, e
        o domínio recusaria o evento que esta camada acabou de aprovar.
        """
        if tipo.requires_team and references.team_for(record) is None:
            return f"team:{record.team_reference or '—'}"
        if tipo.requires_player and references.player_for(record) is None:
            return f"player:{record.player_reference or '—'}"
        if tipo is EventType.SUBSTITUTION:
            # A SUBSTITUIÇÃO EXIGE OS DOIS JOGADORES, e a exigência é do
            # `SubstitutionDetail`: um par desemparelhado — alguém sai e
            # ninguém entra — é o que o detalhe tipado existe para impedir.
            for papel in (
                "EVENT_PLAYER_OUT_PROVIDER_ID",
                "EVENT_PLAYER_IN_PROVIDER_ID",
            ):
                referencia = record.detail(papel)
                if references.player_by_reference(referencia) is None:
                    return f"player:{referencia or '—'}"
        return None

    @staticmethod
    def _relogio_impossivel(record: HistoricalEventRecord) -> str | None:
        relogio = record.clock
        if relogio.period not in _COM_RELOGIO and (relogio.minute or relogio.stoppage):
            return (
                f"{relogio.period} não tem relógio correndo e veio {relogio.label} — "
                "quase sempre coluna de período trocada"
            )
        if relogio.minute > MAX_PLAUSIBLE_MINUTE:
            return (
                f"minuto {relogio.minute} acima de {MAX_PLAUSIBLE_MINUTE}: é erro de "
                "parse ou coluna trocada, não um jogo longo"
            )
        return None
