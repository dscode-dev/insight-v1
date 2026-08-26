"""O avaliador: transforma um candidato fundido em observações de qualidade.

O QUE ELE FAZ, e onde ele PARA. Ele mede — quantos campos entraram em
conflito, quais famílias a fonte trouxe, que licenças alimentaram cada uma,
qual identidade veio com que confiança — e entrega a medição para a política.
Ele nunca decide.

A LINHA É NÍTIDA E ELA IMPORTA. Um `if` contra `0.9` aqui dentro faria a
decisão de negócio morar num laço de verificação: para mudá-la seria preciso
encontrá-la, para auditá-la seria preciso ler código, e a pergunta «sob qual
limiar esta partida reprovou há seis meses» não teria resposta.

OS SEIS EIXOS SÃO MEDIDOS, NÃO ARBITRADOS. Cada um sai de uma contagem sobre
o candidato — a fração de campos sem conflito, a fração de contribuições com
procedência, o elo mais fraco da identidade. Um vetor com números escolhidos à
mão seria uma opinião com aparência de medida.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final, final

from sports_intelligence.domain.build.facts import LineupDraft
from sports_intelligence.domain.fusion.models import (
    ODDS_OBSERVATION_KIND,
    CanonicalFieldCandidate,
    FusionGroup,
    FusionRule,
)
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate
from sports_intelligence.domain.quality.assessment import (
    IdentityConfidences,
    MatchQualityAssessment,
)
from sports_intelligence.domain.quality.coverage import (
    CoverageFamily,
    CoverageReport,
    FamilyCoverage,
)
from sports_intelligence.domain.quality.dimensions import QualityVector
from sports_intelligence.domain.quality.issues import IssueCode, QualityIssue
from sports_intelligence.domain.quality.licensing import LicenseFootprint, UsageVerdict
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.quality.runs import MatchQualityRecord
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.sources.semantics import SemanticRole

#: Os papéis que compõem o NÚCLEO de uma partida. Conflito não resolvido num
#: deles é bloqueante; nos demais, não chega a virar problema de qualidade —
#: vira uma família indecidível, que é decisão de build (§45, §46).
#:
#: `KICKOFF` ENTRA AQUI (PR-04.2.1 §12, §13), e a inclusão desfaz uma
#: generalização que teria sido errada. Rótulo de identidade não vira conflito
#: — `Man City` e `Manchester City` são a mesma coisa provada. Horário NÃO é
#: rótulo: duas fontes com 20:00 e 23:00 estão discordando sobre quando a
#: partida aconteceu, e um corpus que engolisse isso guardaria um fato que
#: nenhuma das duas afirmou.
#: Os papéis do PLACAR. Eles decidem se existe RESULTADO — e só eles: o
#: horário não é placar, e exigi-lo para dizer «tem resultado» faria toda fonte
#: sem coluna de kickoff parecer sem placar.
SCORE_ROLES: Final[frozenset[SemanticRole]] = frozenset(
    {SemanticRole.HOME_SCORE, SemanticRole.AWAY_SCORE}
)

CORE_ROLES: Final[frozenset[SemanticRole]] = frozenset(SCORE_ROLES | {SemanticRole.KICKOFF})

#: As identidades sem as quais uma partida canônica não existe (§13). Jogador
#: NÃO está aqui, e a ausência é a decisão do §14: ele afeta as famílias que
#: dependem dele, nunca o núcleo.
REQUIRED_SUBJECTS: Final[tuple[SubjectType, ...]] = (
    SubjectType.COMPETITION,
    SubjectType.SEASON,
    SubjectType.TEAM,
    SubjectType.MATCH,
)

#: A que família de dado cada papel pertence. FORMAÇÃO É ESCALAÇÃO, e não
#: estatística de partida: um desacordo de formação entre fontes torna a
#: ESCALAÇÃO indecidível e deixa o placar intacto — que é exatamente o §46.
_FAMILIA_DO_PAPEL: Final[dict[SemanticRole, CoverageFamily]] = {
    SemanticRole.HOME_FORMATION: CoverageFamily.LINEUP,
    SemanticRole.AWAY_FORMATION: CoverageFamily.LINEUP,
    SemanticRole.BOOKMAKER_NAME: CoverageFamily.ODDS,
    SemanticRole.ODDS_HOME: CoverageFamily.ODDS,
    SemanticRole.ODDS_DRAW: CoverageFamily.ODDS,
    SemanticRole.ODDS_AWAY: CoverageFamily.ODDS,
    SemanticRole.PLAYER_NAME: CoverageFamily.PLAYER,
    SemanticRole.PLAYER_PROVIDER_ID: CoverageFamily.PLAYER,
    SemanticRole.PLAYER_DOB: CoverageFamily.PLAYER,
    SemanticRole.PLAYER_NATIONALITY: CoverageFamily.PLAYER,
    SemanticRole.PLAYER_POSITION: CoverageFamily.PLAYER,
}

#: Papéis cujo valor é uma contagem ou medida que não pode ser negativa. Um
#: negativo aqui é coluna trocada ou parse errado — a forma real do defeito.
_NAO_NEGATIVOS: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.HOME_SCORE,
        SemanticRole.AWAY_SCORE,
        SemanticRole.HOME_SHOTS,
        SemanticRole.AWAY_SHOTS,
        SemanticRole.HOME_SHOTS_ON_TARGET,
        SemanticRole.AWAY_SHOTS_ON_TARGET,
        SemanticRole.HOME_CORNERS,
        SemanticRole.AWAY_CORNERS,
        SemanticRole.HOME_XG,
        SemanticRole.AWAY_XG,
        SemanticRole.ATTENDANCE,
    }
)

#: Quantas escalações uma partida pode ter: uma por time. É o denominador
#: HONESTO da cobertura de escalação (§13) — e ele só é honesto quando a fonte
#: declara trabalhar com escalação, senão o «0 de 2» pareceria uma falha.
_ESCALACOES_POR_PARTIDA: Final[int] = 2


def family_of(role: SemanticRole) -> CoverageFamily:
    """A família de um papel. `MATCH` é o default e é o certo: o que não é
    escalação, jogador ou odds é dado de nível de partida."""
    return _FAMILIA_DO_PAPEL.get(role, CoverageFamily.MATCH)


@final
@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Tudo que o avaliador precisa de UMA partida, já carregado.

    O TIPO É A GUARDA CONTRA N+1. Ele recebe a identidade e a escalação já
    resolvidas pelo chamador, em lote; um avaliador que fosse buscá-las
    sozinho faria uma consulta por partida, e o §68 existe para isso não
    acontecer.
    """

    candidate: FusedMatchCandidate
    group: FusionGroup
    #: A confiança POR TIPO, vinda das `ResolutionDecision` reais (§13). NÃO é
    #: recalibrada aqui: recalibrar seria inventar uma segunda opinião sobre
    #: uma decisão que já tem evidência e versão gravadas.
    identity_confidences: Mapping[SubjectType, float] = field(default_factory=dict)
    lineup_drafts: tuple[LineupDraft, ...] = ()

    @property
    def match_id(self) -> MatchId:
        return self.candidate.canonical_match_id


@final
@dataclass(frozen=True, slots=True)
class HistoricalQualityAssessor:
    """Observa um candidato e pede o veredito à política."""

    policy: HistoricalQualityPolicy

    def assess(self, evidence: CandidateEvidence, *, quality_run_id: str) -> MatchQualityRecord:
        """A avaliação de uma partida, pronta para persistir."""
        cobertura = self._cobertura(evidence)
        pegada = self._licencas(evidence)
        identidades = IdentityConfidences(by_subject=dict(evidence.identity_confidences))
        problemas = self._problemas(evidence, pegada, identidades)
        veredito_de_uso = UsageVerdict.of(
            pegada, commercial_exclusions=self.policy.commercially_droppable
        )

        avaliacao = MatchQualityAssessment.evaluate(
            match_id=evidence.candidate.canonical_match_id,
            quality=self._vetor(evidence, identidades, problemas),
            coverage=cobertura,
            identity=identidades,
            usage=veredito_de_uso,
            issues=problemas,
            policy=self.policy,
        )
        return MatchQualityRecord.of(
            quality_run_id=quality_run_id,
            fusion_group_id=evidence.candidate.group_id,
            assessment=avaliacao,
            families_in_conflict=self._familias_em_conflito(evidence),
            families_unresolved_identity=self._familias_sem_identidade(evidence),
        )

    # ------------------------------------------------------------ cobertura --

    def _cobertura(self, evidence: CandidateEvidence) -> CoverageReport:
        """O que a fonte trouxe, por família — com denominador só onde ele é
        honesto (§13, §58).

        ODDS SAI COMO `AVAILABILITY_ONLY` de propósito. Não existe denominador
        para «quantas casas de aposta deveriam ter cotado esta partida»:
        inventar um produziria uma fração que parece medida e não é.

        `EVENT`, `SPATIAL` e `TRACKING` saem `NOT_DECLARED` porque o contrato
        fundido desta fase não os carrega. Nomear a ausência é o §20 do
        PR-04.1: um relatório que não menciona tracking não distingue «não
        temos» de «ninguém pensou nisso».
        """
        familias = [
            FamilyCoverage.measured(CoverageFamily.MATCH, available=1, expected=1),
            self._cobertura_de_escalacao(evidence),
            self._cobertura_de_odds(evidence),
            self._cobertura_de_jogador(evidence),
            FamilyCoverage.not_declared(CoverageFamily.EVENT),
            FamilyCoverage.not_declared(CoverageFamily.SPATIAL),
            FamilyCoverage.not_declared(CoverageFamily.TRACKING),
        ]
        return CoverageReport.of(*familias)

    @staticmethod
    def _cobertura_de_escalacao(evidence: CandidateEvidence) -> FamilyCoverage:
        if not evidence.lineup_drafts:
            return FamilyCoverage.not_declared(CoverageFamily.LINEUP)
        return FamilyCoverage.measured(
            CoverageFamily.LINEUP,
            available=min(len(evidence.lineup_drafts), _ESCALACOES_POR_PARTIDA),
            expected=_ESCALACOES_POR_PARTIDA,
        )

    @staticmethod
    def _cobertura_de_odds(evidence: CandidateEvidence) -> FamilyCoverage:
        conjunto = next(
            (c for c in evidence.candidate.observation_sets if c.kind == ODDS_OBSERVATION_KIND),
            None,
        )
        if conjunto is None or not len(conjunto):
            return FamilyCoverage.not_declared(CoverageFamily.ODDS)
        return FamilyCoverage.availability(CoverageFamily.ODDS, available=len(conjunto))

    @staticmethod
    def _cobertura_de_jogador(evidence: CandidateEvidence) -> FamilyCoverage:
        resolvidos = sum(
            1
            for rascunho in evidence.lineup_drafts
            for entrada in rascunho.entries
            if entrada.is_resolved
        )
        if not evidence.lineup_drafts:
            return FamilyCoverage.not_declared(CoverageFamily.PLAYER)
        return FamilyCoverage.availability(CoverageFamily.PLAYER, available=resolvidos)

    # -------------------------------------------------------------- licenças --

    @staticmethod
    def _licencas(evidence: CandidateEvidence) -> LicenseFootprint:
        """As licenças que alimentaram CADA família (§59).

        POR FAMÍLIA E NÃO UMA GLOBAL. Com uma só, `RESEARCH_ONLY` em qualquer
        campo condenaria o registro inteiro; com o mapa, dá para perguntar «e
        se as odds saírem?» — que é a pergunta do build comercial (§19).

        DE TODAS AS CONTRIBUIÇÕES, e não só da vencedora (§49). Um campo cujo
        conflito foi resolvido consultando a fonte restrita foi produzido
        usando-a, mesmo que o valor final tenha vindo de outra.

        RÓTULO DE IDENTIDADE NÃO É PROCEDÊNCIA FACTUAL (PR-04.2.1 §4, §7, §11).
        Toda fonte precisa escrever o nome dos times para que a resolução
        consiga casar a linha — e o `Match` canônico NÃO é construído a partir
        desses textos: ele vem de `MatchIdentityFacts`, lido do registro, com
        identidade provada no PR-03. Uma fonte `RESEARCH_ONLY` que apenas
        escreve `Man City` ajudou a RECONHECER o time; ela não é a autoridade
        de que a partida aconteceu.

        Contá-la faria toda fonte de odds restringir o núcleo por ter dito de
        que jogo se trata, e o §19 deixaria de ser expressável.

        MAS O FATO CONTINUA SUJEITO A PROCEDÊNCIA (§6, §8). `KICKOFF`,
        `ROUND_NUMBER`, `VENUE_NAME` e as observações AFIRMAM coisas, e quem
        as afirma é procedência factual do núcleo — com as consequências de
        licença que isso implica. Se a única fonte que afirma que a partida
        existe é `RESEARCH_ONLY`, o núcleo não vira comercialmente livre só
        porque os times já tinham id canônico.

        O SUPORTE INDEPENDENTE É A TERCEIRA PEÇA (§42). Quando várias fontes
        dizem exatamente o mesmo — `EXACT_AGREEMENT` —, o valor seria idêntico
        sem a restrita; ela confirma, não deriva. Quando o valor saiu de um
        desempate entre fontes, ele foi produzido usando todas, e a mais
        restritiva governa (§35 do PR-04.1, preservado).
        """
        por_familia: dict[CoverageFamily, set[LicenseClass]] = {}
        sozinhas: dict[CoverageFamily, set[LicenseClass]] = {}
        for campo in evidence.candidate.fields:
            if campo.field_name.is_identity_label:
                continue
            familia = family_of(campo.field_name)
            por_familia.setdefault(familia, set()).update(campo.licenses)
            independentes = _licencas_independentes(campo)
            if independentes:
                sozinhas.setdefault(familia, set()).update(independentes)
        for conjunto in evidence.candidate.observation_sets:
            familia = (
                CoverageFamily.ODDS
                if conjunto.kind == ODDS_OBSERVATION_KIND
                else CoverageFamily.MATCH
            )
            por_familia.setdefault(familia, set()).update(conjunto.licenses)
            # CADA OBSERVAÇÃO É UM FATO PRÓPRIO de uma fonte só: a cotação da
            # Bet365 não foi derivada da da Pinnacle. Cada uma sustenta a si
            # mesma, e a família é sustentada por quem trouxe qualquer uma.
            sozinhas.setdefault(familia, set()).update(conjunto.licenses)
        return LicenseFootprint(
            by_family={f: frozenset(ls) for f, ls in por_familia.items() if ls},
            independent_support={
                f: frozenset(ls) for f, ls in sozinhas.items() if ls and f in por_familia
            },
        )

    # ------------------------------------------------------------ problemas --

    def _problemas(
        self,
        evidence: CandidateEvidence,
        footprint: LicenseFootprint,
        identidades: IdentityConfidences,
    ) -> tuple[QualityIssue, ...]:
        """O que foi OBSERVADO. Sem severidade — ela é da política (§12)."""
        achados: list[QualityIssue] = []
        alvo = str(evidence.candidate.canonical_match_id)

        achados.extend(self._problemas_de_linhagem(evidence, alvo))
        achados.extend(self._problemas_de_identidade(evidence, identidades, alvo))
        achados.extend(self._problemas_de_conflito(evidence, alvo))
        achados.extend(self._problemas_de_valor(evidence))
        achados.extend(self._problemas_de_licenca(footprint, alvo))
        return tuple(achados)

    def _problemas_de_linhagem(self, evidence: CandidateEvidence, alvo: str) -> list[QualityIssue]:
        """A linhagem quebrada é bloqueante porque o corpus inteiro se
        justifica por ser rastreável (§47, §48).

        O QUE SE CONFERE AQUI é o que dá para conferir sem I/O: que o grupo
        existe, que ele tem registros, e que cada registro carrega a decisão
        que provou a identidade. A travessia completa até o SHA-256 do objeto
        bruto é cara demais por partida e é provada no teste de integração.
        """
        if not self.policy.require_complete_lineage:
            return []
        problemas: list[QualityIssue] = []
        if not evidence.candidate.group_id.strip():
            problemas.append(QualityIssue.of(IssueCode.BROKEN_LINEAGE, alvo, motivo="sem grupo"))
        sem_procedencia = [
            str(contribuicao.record_ref)
            for campo in evidence.candidate.fields
            for contribuicao in campo.contributions
            if not str(contribuicao.record_ref).strip()
        ]
        if sem_procedencia:
            problemas.append(
                QualityIssue.of(
                    IssueCode.BROKEN_LINEAGE,
                    alvo,
                    motivo="contribuição sem record_ref",
                    quantas=str(len(sem_procedencia)),
                )
            )
        sem_decisao = [
            str(registro.record_ref)
            for registro in evidence.group.records
            if not registro.resolution_decision_id.strip()
        ]
        if sem_decisao:
            problemas.append(
                QualityIssue.of(
                    IssueCode.BROKEN_LINEAGE,
                    alvo,
                    motivo="registro sem decisão de resolução",
                    quantas=str(len(sem_decisao)),
                )
            )
        return problemas

    @staticmethod
    def _problemas_de_identidade(
        evidence: CandidateEvidence, identidades: IdentityConfidences, alvo: str
    ) -> list[QualityIssue]:
        """Identidade AUSENTE e identidade FRACA são problemas diferentes.

        A primeira é bloqueante: sem `SeasonId` não existe partida canônica. A
        segunda é grave e decidível por revisão — e colapsá-las faria uma
        confiança de 0,89 ser tratada como uma temporada inexistente.
        """
        problemas: list[QualityIssue] = []
        for sujeito in REQUIRED_SUBJECTS:
            if sujeito not in identidades.by_subject:
                problemas.append(
                    QualityIssue.of(
                        IssueCode.MISSING_REQUIRED_IDENTITY, alvo, identity=sujeito.value
                    )
                )
        for sujeito, valor in sorted(identidades.by_subject.items(), key=lambda p: p[0].value):
            if valor <= 0.0:
                problemas.append(
                    QualityIssue.of(IssueCode.UNRESOLVED_IDENTITY, alvo, identity=sujeito.value)
                )
        for rascunho in evidence.lineup_drafts:
            if rascunho.unresolved:
                problemas.append(
                    QualityIssue.of(
                        # NÃO é `UNRESOLVED_IDENTITY`, que é bloqueante: um
                        # jogador não resolvido afeta a ESCALAÇÃO, não a
                        # partida (§14). O código certo é o de confiança
                        # baixa, que a política pesa como erro não bloqueante.
                        IssueCode.LOW_IDENTITY_CONFIDENCE,
                        f"{alvo}:lineup:{rascunho.team_id}",
                        identity=SubjectType.PLAYER.value,
                        unresolved=str(len(rascunho.unresolved)),
                    )
                )
        return problemas

    @staticmethod
    def _problemas_de_conflito(evidence: CandidateEvidence, alvo: str) -> list[QualityIssue]:
        """SÓ O NÚCLEO VIRA PROBLEMA DE QUALIDADE (§45, §46).

        Um conflito de placar significa que uma das fontes está errada sobre
        um fato público e verificável — e construir a partida escolhendo uma
        delas inventaria o fato. Um conflito de formação torna a escalação
        indecidível e deixa o placar intacto: ele viaja como família em
        conflito, e quem decide o que fazer é a política de build.
        """
        return [
            QualityIssue.of(
                IssueCode.UNRESOLVED_FUSION_CONFLICT,
                f"{alvo}:{campo.field_name.value}",
                field=campo.field_name.value,
            )
            for campo in evidence.candidate.unresolved_conflicts
            if campo.field_name in CORE_ROLES
        ] + (
            []
            if _tem_placar(evidence.candidate)
            else [QualityIssue.of(IssueCode.MISSING_RESULT, alvo)]
        )

    @staticmethod
    def _problemas_de_valor(evidence: CandidateEvidence) -> list[QualityIssue]:
        problemas: list[QualityIssue] = []
        for campo in evidence.candidate.fields:
            if campo.field_name not in _NAO_NEGATIVOS or campo.selected_value is None:
                continue
            try:
                numero = Decimal(campo.selected_value)
            except (ArithmeticError, InvalidOperation, ValueError):
                continue
            if numero < 0:
                problemas.append(
                    QualityIssue.of(
                        IssueCode.NEGATIVE_OBSERVED_VALUE,
                        f"{evidence.candidate.canonical_match_id}:{campo.field_name.value}",
                        value=campo.selected_value[:64],
                    )
                )
        return problemas

    @staticmethod
    def _problemas_de_licenca(footprint: LicenseFootprint, alvo: str) -> list[QualityIssue]:
        """A licença aparece no MESMO relatório e NÃO é qualidade (§16, §30).

        A dimensão afetada destes dois códigos é `None`, e é assim que o tipo
        diz que eles não pesam num eixo. Quem decide o que fazer com eles é a
        elegibilidade de uso, que roda ao lado com veredito próprio.
        """
        problemas: list[QualityIssue] = []
        for familia, licencas in sorted(footprint.by_family.items(), key=lambda p: p[0].value):
            if LicenseClass.RESEARCH_ONLY in licencas:
                problemas.append(
                    QualityIssue.of(IssueCode.LICENSE_RESTRICTED, f"{alvo}:{familia.value}")
                )
            if LicenseClass.UNKNOWN in licencas:
                problemas.append(
                    QualityIssue.of(IssueCode.LICENSE_UNKNOWN, f"{alvo}:{familia.value}")
                )
        return problemas

    # ---------------------------------------------------------------- eixos --

    @staticmethod
    def _vetor(
        evidence: CandidateEvidence,
        identidades: IdentityConfidences,
        problemas: tuple[QualityIssue, ...],
    ) -> QualityVector:
        """Os seis eixos, cada um MEDIDO sobre o candidato.

        `integrity` E `temporal_integrity` SÃO BINÁRIOS de propósito: uma
        referência aponta para algo que existe ou não aponta, e uma data fecha
        ou não fecha. Uma fração ali seria a média de coisas que não somam.

        `consistency` CONTA SÓ O NÚCLEO, e a restrição é o §46 escrito no
        eixo. Contar todos os campos faria UM conflito de formação num
        candidato de seis campos dar 0,83 — abaixo do piso de 0,95 — e a
        partida inteira reprovaria por causa de uma escalação indecidível.
        A escalação some; a partida fica. O conflito opcional continua
        visível, em `families_in_conflict`, para a política de build decidir.

        `provenance_quality` é fração porque há o que contar: contribuições
        com procedência sobre contribuições.

        `identity_confidence` é o ELO MAIS FRACO e não a média — a mesma
        decisão do PR-00, pelo mesmo motivo: média deixa um eixo em 0,4 ser
        mascarado por quatro em 0,95.
        """
        candidato = evidence.candidate
        campos = candidato.fields
        contribuicoes = [c for campo in campos for c in campo.contributions]
        com_procedencia = sum(1 for c in contribuicoes if str(c.record_ref).strip())
        nucleo_total = sum(1 for campo in campos if campo.field_name in CORE_ROLES)
        nucleo_em_conflito = sum(
            1 for campo in candidato.unresolved_conflicts if campo.field_name in CORE_ROLES
        )
        placar_presente = sum(1 for papel in SCORE_ROLES if _tem_valor(candidato, papel))
        return QualityVector(
            integrity=_zero_se(
                problemas,
                IssueCode.MISSING_REQUIRED_IDENTITY,
                IssueCode.DANGLING_CANONICAL_REFERENCE,
            ),
            consistency=_fracao(nucleo_total - nucleo_em_conflito, nucleo_total),
            completeness=_fracao(placar_presente, len(SCORE_ROLES)),
            identity_confidence=identidades.aggregate,
            temporal_integrity=_zero_se(
                problemas,
                IssueCode.TEMPORAL_INCONSISTENCY,
                IssueCode.KICKOFF_OUTSIDE_SEASON_WINDOW,
            ),
            provenance_quality=_fracao(com_procedencia, len(contribuicoes))
            * _zero_se(problemas, IssueCode.BROKEN_LINEAGE),
        )

    # -------------------------------------------------------------- famílias --

    @staticmethod
    def _familias_em_conflito(evidence: CandidateEvidence) -> tuple[CoverageFamily, ...]:
        """As famílias cujo dado ficou indecidível — para a política de build.

        O NÚCLEO NÃO ENTRA AQUI: um conflito de placar já virou problema
        BLOQUEANTE de qualidade, e listá-lo de novo faria a mesma coisa ser
        decidida em dois lugares (§5).

        OS RÓTULOS DE IDENTIDADE TAMBÉM NÃO (§5): `Man City` numa fonte e
        `Manchester City` noutra é desacordo de GRAFIA, não de fato — e
        absorvê-lo é literalmente o que a resolução existe para fazer (PR-03).
        As duas já terminaram no mesmo `TeamId`, provado por decisão com
        evidência. Tratá-lo como conflito faria toda fusão multi-fonte legítima
        derrubar o núcleo, e o motor rejeitaria exatamente os candidatos que
        várias fontes confirmam.

        MAS FATO CONTINUA SENDO FATO (§12). `KICKOFF` está no NÚCLEO e é
        bloqueante; `ROUND_NUMBER` e `VENUE_NAME` são fato de nível de partida
        e entram como família em conflito. A regra não é «papel de identidade
        nunca participa» — é «rótulo não participa».
        """
        return tuple(
            sorted(
                {
                    family_of(campo.field_name)
                    for campo in evidence.candidate.unresolved_conflicts
                    if campo.field_name not in CORE_ROLES and not campo.field_name.is_identity_label
                },
                key=lambda f: f.value,
            )
        )

    @staticmethod
    def _familias_sem_identidade(
        evidence: CandidateEvidence,
    ) -> tuple[CoverageFamily, ...]:
        """As famílias que dependem de uma identidade que não foi provada.

        SÓ AS QUE DEPENDEM (§14). Um jogador não resolvido tira a escalação e
        deixa o núcleo em pé — transformar isso num bloqueio global seria
        exatamente o «erro opcional virando blocker» que o PR proíbe.
        """
        if any(not r.is_fully_resolved for r in evidence.lineup_drafts):
            return (CoverageFamily.LINEUP, CoverageFamily.PLAYER)
        return ()


def _licencas_independentes(field: CanonicalFieldCandidate) -> frozenset[LicenseClass]:
    """As licenças das fontes que sustentam ESTE campo sozinhas (§42).

    A REGRA VEM DA `FusionRule`, e não de uma heurística nova — ela já grava
    COMO o valor foi escolhido:

        EXACT_AGREEMENT    todas disseram o mesmo. O valor seria idêntico só
                           com qualquer uma delas; cada uma o sustenta sozinha.
        MOST_COMPLETE      só uma trouxe o campo. Ela é a única e sustenta.
        desempate          o valor foi produzido COMPARANDO as fontes — sem a
                           restrita, a comparação teria sido outra. Ninguém
                           sustenta sozinho (§35, §76 do PR-04.1).
        CONFLITO ABERTO    não há valor; não há o que sustentar.

    SÓ AS FONTES QUE DISSERAM O VALOR ESCOLHIDO entram, mesmo em
    `EXACT_AGREEMENT` — a regra já garante que são todas, e filtrar por valor
    mantém a função correta se a semântica da regra mudar.
    """
    if field.rule not in (FusionRule.EXACT_AGREEMENT, FusionRule.MOST_COMPLETE):
        return frozenset()
    if field.selected_value is None:
        return frozenset()
    return frozenset(
        contribuicao.license_class
        for contribuicao in field.contributions
        if contribuicao.value == field.selected_value
    )


def _fracao(parte: int, total: int) -> float:
    """A fração, ou 1,0 quando não há o que contar.

    NADA A CONTAR É 1,0 E NÃO 0,0, e a escolha é deliberada: um candidato sem
    contribuição nenhuma não tem procedência RUIM — ele não tem campo. O que
    reprova a ausência de campo é `INCOMPLETE_CORE_MATCH`, que é um problema
    nomeado, e não um eixo silenciosamente zerado.
    """
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, parte / total))


def _zero_se(problemas: tuple[QualityIssue, ...], *codigos: IssueCode) -> float:
    """1,0 quando nenhum dos códigos apareceu; 0,0 quando algum apareceu."""
    encontrados = {p.code for p in problemas}
    return 0.0 if encontrados & set(codigos) else 1.0


def _tem_valor(candidate: FusedMatchCandidate, role: SemanticRole) -> bool:
    campo = candidate.field(role.value)
    return campo is not None and campo.selected_value is not None


def _tem_placar(candidate: FusedMatchCandidate) -> bool:
    """Os DOIS lados do PLACAR. `2-None` não é um placar — é meio placar, e
    completá-lo com zero é o defeito que o §44 existe para impedir.

    SOBRE `SCORE_ROLES` E NÃO SOBRE `CORE_ROLES`: o horário faz parte do
    núcleo da partida e não do resultado, e confundi-los faria uma fonte sem
    coluna de kickoff ser reportada como sem placar.
    """
    return all(_tem_valor(candidate, papel) for papel in SCORE_ROLES)
