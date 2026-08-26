"""O acumulador que transforma um FLUXO de partidas nos resumos do manifesto.

POR QUE UM ACUMULADOR, e não uma função sobre a lista: dez mil partidas com
vetor, cobertura, licenças e problemas é exatamente o pico de memória que o
§86 proíbe. Aqui cada lote entra, é absorvido e é descartado — o que fica é um
punhado de contadores e uma impressão de 32 bytes.

ELE NÃO RECALCULA NADA (§133, §134, §135). Recebe o veredito que a avaliação
gravou e a decisão que o build emitiu, e AGREGA. Uma segunda opinião sobre
qualidade produzida aqui divergiria da primeira no primeiro ajuste de política,
e as duas apareceriam com o mesmo nome.

O PIOR CASO, NUNCA A MÉDIA (§25). Média de dez mil vetores esconde as cem
partidas de linhagem quebrada no terceiro decimal, e são elas que precisam
aparecer.

`NOT_DECLARED` SOBREVIVE À AGREGAÇÃO (§24). Somar contagens e reportar `0%`
para eventos apagaria a diferença entre «as fontes não trabalham com eventos» e
«as fontes prometeram e não veio nada» — que exigem ações opostas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.build.decisions import BuildDecision, FamilyOutcome
from sports_intelligence.domain.corpus.composition import ComposedMatchCorpusFacts
from sports_intelligence.domain.corpus.fingerprint import CorpusFingerprintBuilder
from sports_intelligence.domain.corpus.manifest import (
    MAX_ISSUE_EXAMPLES,
    FamilyCoverageSummary,
    IssueSummary,
    LicenseSummary,
    QualitySummary,
)
from sports_intelligence.domain.corpus.membership import (
    CorpusMember,
    EventCorpusCounts,
    MembershipCounts,
)
from sports_intelligence.domain.corpus.scope import CorpusScope
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.coverage import (
    FAMILY_ORDER,
    CoverageFamily,
    CoverageState,
)
from sports_intelligence.domain.quality.dimensions import DIMENSION_ORDER, QualityVector
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.quality.runs import MatchQualityRecord
from sports_intelligence.domain.shared.provenance import LicenseClass

#: A ordem em que os eixos entram no resumo — a mesma da impressão (§33).
_EIXOS: Final[tuple[str, ...]] = tuple(d.value.lower() for d in DIMENSION_ORDER)

#: As famílias cuja cobertura é medida sobre os EVENTOS publicados, e não sobre
#: o que a avaliação de qualidade declarou (PR-04.4.2 §26, §29). `SPATIAL` está
#: aqui porque coordenada é atributo de evento: sem evento não há o que cobrir,
#: e com evento a cobertura é uma fração de eventos — não de partidas.
_FAMILIAS_DE_EVENTO: Final[frozenset[CoverageFamily]] = frozenset(
    {CoverageFamily.EVENT, CoverageFamily.SPATIAL}
)


@final
@dataclass(slots=True)
class _CoberturaAcumulada:
    """Contadores de uma família, ao longo do fluxo.

    `estado` é rebaixado e nunca promovido: uma família `MEASURED` numa
    partida e `AVAILABILITY_ONLY` noutra é `AVAILABILITY_ONLY` no conjunto,
    porque o denominador que falta numa não existe no total. Promover seria o
    relatório afirmar mais do que sabe.
    """

    estado: CoverageState = CoverageState.NOT_DECLARED
    com_dado: int = 0
    total: int = 0
    disponivel: int = 0
    esperado: int | None = None
    viu_declaracao: bool = False


@final
@dataclass(slots=True)
class CorpusAccumulator:
    """Absorve partidas e devolve os resumos. Memória constante.

    NÃO É `frozen` — ele é um acumulador por definição, como o
    `CorpusFingerprintBuilder` que ele carrega. O que é imutável é o
    RESULTADO: os resumos saem como
    dataclasses congeladas e o acumulador não viaja para lugar nenhum.
    """

    usage: UsageScope
    #: O escopo declarado. Ele entra no CABEÇALHO da impressão, e por isso o
    #: acumulador precisa dele antes do primeiro membro (PR-04.3.1 §5).
    scope: CorpusScope
    #: A política que DECIDIU os vereditos. Ela existe aqui por um motivo só:
    #: a severidade de um problema é dela, e o `QualityIssue` não a carrega
    #: (PR-04.2 §12). Sem ela, «quantos bloqueantes este corpus contém» ficaria
    #: sem resposta — e adivinhar a severidade seria o acumulador discordar da
    #: política que de fato reprovou as partidas.
    policy: HistoricalQualityPolicy | None = None
    _impressao: CorpusFingerprintBuilder = field(init=False)
    counts: MembershipCounts = field(default_factory=MembershipCounts)

    # --- qualidade -------------------------------------------------------
    _pior: dict[str, float] = field(default_factory=dict)
    _elegiveis: int = 0
    _em_revisao: int = 0
    _inelegiveis: int = 0

    # --- cobertura -------------------------------------------------------
    _cobertura: dict[CoverageFamily, _CoberturaAcumulada] = field(default_factory=dict)
    _cobertura_por_particao: dict[str, dict[CoverageFamily, _CoberturaAcumulada]] = field(
        default_factory=dict
    )

    # --- licença ---------------------------------------------------------
    _licencas: set[LicenseClass] = field(default_factory=set)
    _suporte_independente: set[LicenseClass] = field(default_factory=set)
    _familias_incluidas: set[CoverageFamily] = field(default_factory=set)
    _familias_excluidas: set[CoverageFamily] = field(default_factory=set)
    _motivos: dict[str, dict[str, int]] = field(default_factory=dict)
    _licenca_da_exclusao: dict[str, str] = field(default_factory=dict)

    # --- eventos ---------------------------------------------------------
    #: Os números de evento do corpus inteiro e por partição. Eles NÃO vêm da
    #: avaliação de qualidade: vêm do que a versão de fato publica, evento a
    #: evento (PR-04.4.2 §29). A avaliação responde «a fonte prometeu
    #: eventos?»; isto responde «quantos entraram», e as duas perguntas têm
    #: respostas diferentes com frequência.
    _eventos: EventCorpusCounts = field(default_factory=lambda: EventCorpusCounts())
    _eventos_por_particao: dict[str, EventCorpusCounts] = field(default_factory=dict)
    #: As licenças dos eventos publicados e as dos que ficaram de fora, com o
    #: motivo. É o §37: «events=0» não explica nada; «excluído por
    #: LICENSE_POLICY, RESEARCH_ONLY, num build COMMERCIAL» explica.
    _licencas_de_evento: set[LicenseClass] = field(default_factory=set)
    _eventos_excluidos: dict[str, int] = field(default_factory=dict)
    _licencas_excluidas_de_evento: set[str] = field(default_factory=set)

    # --- problemas -------------------------------------------------------
    _por_codigo: dict[str, int] = field(default_factory=dict)
    _por_severidade: dict[str, int] = field(default_factory=dict)
    _pulados: int = 0
    _exemplos: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ entrada --

    def __post_init__(self) -> None:
        self._impressao = CorpusFingerprintBuilder(scope=self.scope)

    def absorb(
        self,
        facts: ComposedMatchCorpusFacts,
        *,
        assessment: MatchQualityRecord | None = None,
    ) -> CorpusMember:
        """Absorve UMA partida COMPOSTA e devolve a pertinência dela.

        `ComposedMatchCorpusFacts` E NÃO `MatchCorpusFacts` (PR-04.3.1 §30): o
        que entra no corpus é o resultado da composição de todos os builds que
        falam daquela partida, com a união das famílias e a linhagem inteira.
        Absorver a contribuição de um build só reintroduziria o «um build
        vence» pela porta do acumulador.

        `assessment` É OPCIONAL E A AUSÊNCIA É VISÍVEL: sem ele, os resumos de
        qualidade, cobertura e licença simplesmente não recebem esta partida.
        Inventar um vetor perfeito para a que faltou seria o pior erro
        possível — silencioso e favorável.
        """
        membro = facts.as_member()
        # A ORDEM É VERIFICADA AQUI DENTRO: o construtor recusa membro fora de
        # ordem ou repetido, que é o que substituiu a comutatividade do XOR.
        self._impressao.add(membro)
        self.counts = self.counts.merged_with(MembershipCounts.of((membro,)))
        self._familias_incluidas.update(facts.included_families)
        self._absorver_eventos(facts, membro.partition_key)

        if assessment is not None:
            self._absorver_qualidade(assessment.assessment.quality)
            self._absorver_elegibilidade(assessment.assessment.eligibility)
            self._absorver_cobertura(assessment, membro.partition_key)
            self._absorver_licencas(assessment, facts.included_families)
            self._absorver_problemas(assessment)
        return membro

    def absorb_exclusions(self, decisions: BuildDecision) -> None:
        """Absorve as famílias que FICARAM DE FORA, com motivo e licença (§26).

        «ODDS EXCLUÍDA» NÃO RESPONDE NADA. O que responde é «excluída por
        LICENSE_POLICY, RESEARCH_ONLY, num build COMMERCIAL» — e é a pergunta
        que uma auditoria jurídica de fato faz (ADR-0025).
        """
        for decisao in decisions.families:
            if decisao.outcome is FamilyOutcome.INCLUDED:
                continue
            familia = decisao.family.value
            self._familias_excluidas.add(decisao.family)
            motivo = decisao.reason.value if decisao.reason else "UNSPECIFIED"
            por_motivo = self._motivos.setdefault(familia, {})
            por_motivo[motivo] = por_motivo.get(motivo, 0) + 1
            if decisao.license_class is not None:
                self._licenca_da_exclusao[familia] = decisao.license_class.value

    def absorb_event_exclusions(
        self, *, by_reason: Mapping[str, int], licenses: Iterable[str]
    ) -> None:
        """Os eventos que a canonicalização NÃO publicou, com o motivo (§37).

        POR QUE ISTO ENTRA NO MANIFESTO DO CORPUS. Um corpus comercial cujos
        eventos restritos ficaram de fora tem `events=0` para aquelas partidas
        — e `events=0` é indistinguível de «a fonte não tinha eventos». A
        diferença é jurídica e é exatamente a que uma auditoria pergunta: o
        dado existe, e o direito de publicá-lo NESTE escopo é que falta
        (ADR-0025).
        """
        for motivo, quantos in by_reason.items():
            if quantos <= 0:
                continue
            self._eventos_excluidos[motivo] = self._eventos_excluidos.get(motivo, 0) + quantos
        self._licencas_excluidas_de_evento.update(licenses)

    def fingerprint(self) -> ContentHash:
        """A impressão semântica do corpus acumulado (PR-04.3.1 §5)."""
        return self._impressao.finish(self.counts)

    @property
    def event_counts(self) -> EventCorpusCounts:
        """Os números de evento do corpus inteiro (§31)."""
        return self._eventos

    def note_skipped(self, count: int = 1) -> None:
        """Partidas que a composição encontrou e não incluiu (§27)."""
        self._pulados += count

    # ------------------------------------------------------------- saída --

    def quality_summary(self) -> QualitySummary:
        return QualitySummary(
            worst_integrity=self._pior.get("integrity", 1.0),
            worst_consistency=self._pior.get("consistency", 1.0),
            worst_completeness=self._pior.get("completeness", 1.0),
            worst_identity_confidence=self._pior.get("identity_confidence", 1.0),
            worst_temporal_integrity=self._pior.get("temporal_integrity", 1.0),
            worst_provenance_quality=self._pior.get("provenance_quality", 1.0),
            eligible=self._elegiveis,
            review_required=self._em_revisao,
            ineligible=self._inelegiveis,
        )

    def coverage_summary(self) -> tuple[FamilyCoverageSummary, ...]:
        """A cobertura de TODAS as famílias, em ordem canônica.

        AS NÃO DECLARADAS APARECEM. Omiti-las faria `TRACKING` sumir do
        relatório, e sumir é indistinguível de «ninguém pensou nisso» (§20 do
        PR-04.1).
        """
        return tuple(
            self._resumo_de_familia(familia, self._cobertura.get(familia), self._eventos)
            for familia in FAMILY_ORDER
        )

    def coverage_by_partition(self) -> dict[str, list[dict[str, object]]]:
        """A cobertura por partição — com EVENT e SPATIAL da partição (§32).

        OS NÚMEROS DE EVENTO SÃO OS DAQUELA PARTIÇÃO, e não os do corpus: uma
        competição com eventos e outra sem é o caso normal, e repetir o total
        global em cada linha faria a partição sem eventos parecer tê-los.
        """
        particoes = {*self._cobertura_por_particao, *self._eventos_por_particao}
        return {
            particao: [
                self._resumo_de_familia(
                    familia,
                    self._cobertura_por_particao.get(particao, {}).get(familia),
                    self._eventos_por_particao.get(particao, EventCorpusCounts()),
                ).as_canonical()
                for familia in FAMILY_ORDER
                if familia in self._cobertura_por_particao.get(particao, {})
                or (
                    familia in _FAMILIAS_DE_EVENTO
                    and self._eventos_por_particao.get(particao, EventCorpusCounts()).total
                )
            ]
            for particao in sorted(particoes)
        }

    def license_summary(self) -> LicenseSummary:
        """O resumo de licença — agora com a família `EVENT` (§33, §37).

        AS LICENÇAS DOS EVENTOS PUBLICADOS ENTRAM EM `licenses_present`, e
        pela mesma razão das outras famílias: um corpus que publica eventos
        `RESEARCH_ONLY` precisa declará-lo, senão o resumo afirma um direito de
        uso que o conteúdo não tem.
        """
        licencas = {*self._licencas, *self._licencas_de_evento}
        excluidas = set(self._familias_excluidas)
        motivos = {k: dict(v) for k, v in self._motivos.items()}
        licencas_da_exclusao = dict(self._licenca_da_exclusao)
        if self._eventos_excluidos:
            # A FAMÍLIA EVENT APARECE COMO EXCLUÍDA quando eventos existiam e
            # não entraram. `events=0` sozinho seria indistinguível de «não há
            # evento nenhum na fonte» (§37).
            excluidas.add(CoverageFamily.EVENT)
            motivos[CoverageFamily.EVENT.value] = dict(sorted(self._eventos_excluidos.items()))
            if self._licencas_excluidas_de_evento:
                licencas_da_exclusao[CoverageFamily.EVENT.value] = ",".join(
                    sorted(self._licencas_excluidas_de_evento)
                )
        return LicenseSummary(
            usage_scope=self.usage.value,
            licenses_present=tuple(sorted(lic.value for lic in licencas)),
            independent_support=tuple(sorted(lic.value for lic in self._suporte_independente)),
            families_included=tuple(f.value for f in FAMILY_ORDER if f in self._familias_incluidas),
            families_excluded=tuple(f.value for f in FAMILY_ORDER if f in excluidas),
            exclusion_reasons=motivos,
            exclusion_licenses=licencas_da_exclusao,
            requires_attribution=any(lic.requires_attribution for lic in licencas),
        )

    def issue_summary(self) -> IssueSummary:
        return IssueSummary(
            by_code=dict(self._por_codigo),
            by_severity=dict(self._por_severidade),
            records_skipped=self._pulados,
            records_review_required=self._em_revisao,
            families_excluded=len(self._familias_excluidas),
            examples=tuple(self._exemplos[:MAX_ISSUE_EXAMPLES]),
        )

    # ---------------------------------------------------------- internos --

    def _absorver_qualidade(self, vetor: QualityVector) -> None:
        for eixo in _EIXOS:
            valor = float(getattr(vetor, eixo))
            atual = self._pior.get(eixo)
            if atual is None or valor < atual:
                self._pior[eixo] = valor

    def _absorver_elegibilidade(self, eligibility: BuildEligibility) -> None:
        if eligibility is BuildEligibility.ELIGIBLE:
            self._elegiveis += 1
        elif eligibility is BuildEligibility.REVIEW_REQUIRED:
            self._em_revisao += 1
        else:
            self._inelegiveis += 1

    def _absorver_cobertura(
        self, assessment: MatchQualityRecord, particao: tuple[str, str]
    ) -> None:
        chave = f"{particao[0]}/{particao[1]}"
        do_escopo = self._cobertura_por_particao.setdefault(chave, {})
        for cobertura in assessment.assessment.coverage.families:
            for destino in (self._cobertura, do_escopo):
                acumulado = destino.setdefault(cobertura.family, _CoberturaAcumulada())
                acumulado.total += 1
                if cobertura.state is CoverageState.NOT_DECLARED:
                    continue
                acumulado.viu_declaracao = True
                acumulado.disponivel += cobertura.available_count
                if cobertura.available_count:
                    acumulado.com_dado += 1
                if cobertura.expected_count is None:
                    # O denominador que falta numa partida não existe no
                    # total: o conjunto vira disponibilidade, e não medição.
                    acumulado.esperado = None
                    acumulado.estado = CoverageState.AVAILABILITY_ONLY
                else:
                    if acumulado.estado is CoverageState.NOT_DECLARED:
                        acumulado.estado = CoverageState.MEASURED
                    if acumulado.estado is CoverageState.MEASURED:
                        acumulado.esperado = (acumulado.esperado or 0) + cobertura.expected_count

    def _absorver_licencas(
        self, assessment: MatchQualityRecord, incluidas: tuple[CoverageFamily, ...]
    ) -> None:
        """SÓ AS LICENÇAS DAS FAMÍLIAS QUE ENTRARAM (§26).

        Listar as licenças das famílias EXCLUÍDAS entre as «presentes» faria o
        manifesto de um corpus comercial declarar `RESEARCH_ONLY` — e é
        exatamente o corpus que não tem nenhum dado restrito dentro.
        """
        pegada = assessment.assessment.usage.footprint
        for familia in incluidas:
            self._licencas.update(pegada.by_family.get(familia, frozenset()))
            # CONFIRMAÇÃO NÃO É DERIVAÇÃO (PR-04.2.1 §42). Sem esta segunda
            # coleta, um corpus comercial cujo núcleo é sustentado sozinho por
            # uma fonte pública apareceria no manifesto apenas como «contém
            # RESEARCH_ONLY» — verdadeiro e enganoso.
            self._suporte_independente.update(pegada.independent_support.get(familia, frozenset()))

    def _absorver_problemas(self, assessment: MatchQualityRecord) -> None:
        for problema in assessment.assessment.issues:
            codigo = problema.code.value
            self._por_codigo[codigo] = self._por_codigo.get(codigo, 0) + 1
            if self.policy is not None:
                severidade = self.policy.severity_of(problema.code).name
                self._por_severidade[severidade] = self._por_severidade.get(severidade, 0) + 1
            if len(self._exemplos) < MAX_ISSUE_EXAMPLES:
                self._exemplos.append(f"{codigo}: {problema.subject}")

    def _absorver_eventos(self, facts: ComposedMatchCorpusFacts, particao: tuple[str, str]) -> None:
        """Conta os eventos desta partida — e só os que ela PUBLICA.

        ELE NÃO GUARDA EVENTO NENHUM. O que sobrevive ao lote são contadores;
        acumular os eventos de dez mil partidas para contá-los no fim é
        exatamente o pico de memória que o §90 proíbe.
        """
        if not facts.events:
            return
        contagem = facts.event_counts()
        self._eventos = self._eventos.merged_with(contagem)
        # AS CONTAGENS DO MANIFESTO SEGUEM JUNTO, e não são remontadas no fim:
        # duas somas do mesmo fluxo divergiriam no primeiro campo novo, e a
        # divergência apareceria como o rodapé da impressão discordando do
        # corpo (`CorpusFingerprintBuilder.finish` recusa exatamente isso).
        self.counts = self.counts.with_events(contagem)
        chave = f"{particao[0]}/{particao[1]}"
        self._eventos_por_particao[chave] = self._eventos_por_particao.get(
            chave, EventCorpusCounts()
        ).merged_with(contagem)
        for evento in facts.events:
            self._licencas_de_evento.add(evento.provenance.license_class)

    @staticmethod
    def _resumo_de_familia(
        family: CoverageFamily,
        acumulado: _CoberturaAcumulada | None,
        eventos: EventCorpusCounts,
    ) -> FamilyCoverageSummary:
        """O resumo de uma família — com EVENT e SPATIAL vindos do PUBLICADO.

        AS DUAS FAMÍLIAS DE EVENTO NÃO SAEM DA AVALIAÇÃO (§29, §30). A
        avaliação de qualidade fala do que a FONTE declarou; estas falam do que
        o corpus PUBLICA, e a diferença é o assunto inteiro: um dataset que
        declara eventos e cujo escopo comercial os excluiu por licença tem
        declaração e não tem conteúdo.

        SEM EVENTO PUBLICADO, o comportamento é o de antes deste PR: o que a
        avaliação disser vale, inclusive `NOT_DECLARED`.
        """
        if family in _FAMILIAS_DE_EVENTO and eventos.total:
            return CorpusAccumulator._resumo_de_evento(family, acumulado, eventos)
        return CorpusAccumulator._resumo_de(family, acumulado)

    @staticmethod
    def _resumo_de_evento(
        family: CoverageFamily,
        acumulado: _CoberturaAcumulada | None,
        eventos: EventCorpusCounts,
    ) -> FamilyCoverageSummary:
        """`EVENT` e `SPATIAL` medidas sobre o conteúdo publicado (§28, §30).

        `EVENT` É `AVAILABILITY_ONLY`, E ISSO É HONESTIDADE, não limitação.
        Medir cobertura de evento exigiria saber quantos eventos a partida
        DEVERIA ter, e ninguém sabe: não há denominador — nem a fonte declara,
        nem o motor tem autoridade para estimar. Inventar
        `expected = 1000` produziria uma porcentagem que parece medida e é
        chute (§30).

        `SPATIAL` É `MEASURED` porque aqui o denominador EXISTE e é honesto: os
        eventos que acontecem num ponto do campo. Um apito inicial sem
        coordenada não é cobertura faltando (§27).
        """
        total_partidas = 0 if acumulado is None else acumulado.total
        if family is CoverageFamily.EVENT:
            return FamilyCoverageSummary(
                family=family.value,
                state=CoverageState.AVAILABILITY_ONLY.value,
                matches_with_data=eventos.matches_with_events,
                matches_total=max(total_partidas, eventos.matches_with_events),
                available_total=eventos.total,
                expected_total=None,
            )
        return FamilyCoverageSummary(
            family=family.value,
            state=(
                CoverageState.MEASURED.value
                if eventos.spatially_eligible
                # SEM EVENTO ESPACIALMENTE ELEGÍVEL não há denominador, e a
                # cobertura é indefinida — nunca 0% (§28).
                else CoverageState.AVAILABILITY_ONLY.value
            ),
            matches_with_data=eventos.matches_with_coordinates,
            matches_total=max(total_partidas, eventos.matches_with_events),
            available_total=eventos.with_coordinates,
            expected_total=eventos.spatially_eligible or None,
        )

    @staticmethod
    def _resumo_de(
        family: CoverageFamily, acumulado: _CoberturaAcumulada | None
    ) -> FamilyCoverageSummary:
        if acumulado is None or not acumulado.viu_declaracao:
            return FamilyCoverageSummary(
                family=family.value,
                state=CoverageState.NOT_DECLARED.value,
                matches_total=0 if acumulado is None else acumulado.total,
            )
        return FamilyCoverageSummary(
            family=family.value,
            state=acumulado.estado.value,
            matches_with_data=acumulado.com_dado,
            matches_total=acumulado.total,
            available_total=acumulado.disponivel,
            expected_total=acumulado.esperado,
        )
