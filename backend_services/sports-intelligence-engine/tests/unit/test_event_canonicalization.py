"""A canonicalização de eventos: contrato, identidade, revisão, detalhe.

O QUE ESTES TESTES PROTEGEM — a lista é a do §129, e cada classe fecha um item:

    contrato          um arquivo de partidas não declara papel de evento
    identidade        provedor → canônico, e o que não resolveu não entra
    tipo              desconhecido não vira o tipo parecido
    relógio           `45+3` continua `45+3`
    ordem             determinística, e não a do arquivo
    revisão           correção e cancelamento preservam o anterior
    reprocessamento   a mesma fonte duas vezes não duplica
    ausência          `xg` ausente ≠ `xg = 0`; coordenada ausente ≠ (0,0)
    licença           pesquisa aceita o restrito, comércio não
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.events.build import (
    EventBuildRecordStatus,
    EventExclusionReason,
    EventOutcome,
)
from sports_intelligence.domain.events.canonical import EventStatus
from sports_intelligence.domain.events.contract import (
    REQUIRED_EVENT_ROLES,
    inspect_contract,
)
from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
    RawEventClock,
    ordering_key,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import ObservationTimes, Period
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.historical.events.builder import (
    CanonicalEventBuilder,
    canonical_event_id,
)
from sports_intelligence.historical.events.eligibility import (
    EventEligibilityEvaluator,
    EventEligibilityPolicy,
)
from sports_intelligence.historical.events.pipeline import EventBatchCanonicalizer
from sports_intelligence.historical.events.references import EventReferences
from tests.support.build_fixtures import AGORA
from tests.support.event_fixtures import (
    ARTILHEIRO,
    OUTRO_TIME,
    PARTIDA,
    PROVEDOR,
    REF_DA_PARTIDA,
    REF_DO_ARTILHEIRO,
    REF_DO_RESERVA,
    REF_DO_TIME,
    RESERVA,
    TIME,
    cartao,
    chute_com_xg_zero,
    chute_sem_jogador_resolvido,
    chute_sem_xg,
    evento,
    fim_de_periodo,
    gol,
    gol_sem_jogador,
    substituicao,
    tabela_de_tipos,
    tipo_desconhecido,
)

REFERENCIAS = EventReferences(
    matches={REF_DA_PARTIDA: PARTIDA},
    teams={REF_DO_TIME: TIME, "prov-team-88": OUTRO_TIME},
    players={REF_DO_ARTILHEIRO: ARTILHEIRO, REF_DO_RESERVA: RESERVA},
)
ELEGIVEIS = frozenset({PARTIDA})

PROCEDENCIA = DataProvenance(
    source_type=SourceType.OPEN_DATA,
    provider_id=PROVEDOR,
    source_record_id="linha-1",
    times=ObservationTimes.at_once(AGORA),
    license_class=LicenseClass.PUBLIC_DOMAIN,
)


def _avaliador(
    policy: EventEligibilityPolicy | None = None,
) -> EventEligibilityEvaluator:
    return EventEligibilityEvaluator(
        policy=policy or EventEligibilityPolicy.research(), types=tabela_de_tipos()
    )


def _canonicalizador(
    policy: EventEligibilityPolicy | None = None,
) -> EventBatchCanonicalizer:
    return EventBatchCanonicalizer(
        evaluator=_avaliador(policy),
        builder=CanonicalEventBuilder(),
        build_run_id="11111111-1111-4111-8111-111111111111",
        ingested_at=AGORA,
    )


def _rodar(
    registros: tuple[HistoricalEventRecord, ...],
    *,
    policy: EventEligibilityPolicy | None = None,
    license_class: LicenseClass = LicenseClass.PUBLIC_DOMAIN,
    references: EventReferences | None = None,
) -> object:
    return _canonicalizador(policy).canonicalize(
        registros,
        references=references or REFERENCIAS,
        eligible_matches=ELEGIVEIS,
        license_class=license_class,
    )


class TestOContratoDaFonte:
    """§5, §7, §9. Um arquivo é de partidas OU de eventos, nunca os dois."""

    def test_um_arquivo_de_partidas_nao_declara_papel_de_evento(self) -> None:
        relatorio = inspect_contract(
            kind=RecordKind.MATCH_RECORD,
            roles=frozenset({SemanticRole.HOME_SCORE, SemanticRole.EVENT_MINUTE}),
        )
        assert not relatorio.is_usable
        assert SemanticRole.EVENT_MINUTE in relatorio.misplaced
        with pytest.raises(ValidationError, match="papéis do outro mundo"):
            relatorio.assert_usable()

    def test_um_arquivo_de_eventos_precisa_do_minimo(self) -> None:
        relatorio = inspect_contract(
            kind=RecordKind.EVENT_RECORD,
            roles=frozenset({SemanticRole.EVENT_TYPE}),
        )
        assert not relatorio.is_usable
        assert SemanticRole.MATCH_PROVIDER_ID in relatorio.missing
        with pytest.raises(ValidationError, match="não existe evento"):
            relatorio.assert_usable()

    def test_o_minimo_completo_e_utilizavel(self) -> None:
        relatorio = inspect_contract(kind=RecordKind.EVENT_RECORD, roles=REQUIRED_EVENT_ROLES)
        assert relatorio.is_usable

    def test_sem_id_de_evento_a_fonte_nao_e_reprocessavel(self) -> None:
        """§19, §24. A consequência é ESTRUTURAL, e o contrato a diz antes de
        alguém descobrir reprocessando."""
        relatorio = inspect_contract(kind=RecordKind.EVENT_RECORD, roles=REQUIRED_EVENT_ROLES)
        assert not relatorio.is_reprocessable
        assert SemanticRole.EVENT_PROVIDER_ID in relatorio.weak

        com_id = inspect_contract(
            kind=RecordKind.EVENT_RECORD,
            roles=REQUIRED_EVENT_ROLES | {SemanticRole.EVENT_PROVIDER_ID},
        )
        assert com_id.is_reprocessable

    def test_coordenada_pela_metade_e_recusada(self) -> None:
        relatorio = inspect_contract(
            kind=RecordKind.EVENT_RECORD,
            roles=REQUIRED_EVENT_ROLES | {SemanticRole.EVENT_X},
        )
        assert SemanticRole.EVENT_Y in relatorio.missing


class TestOsQuatroTipos:
    """§84, §85. GOAL, SHOT, CARD e SUBSTITUTION numa partida só."""

    def test_a_cardinalidade_e_preservada(self) -> None:
        registros = (gol(1), chute_sem_xg(2), cartao(4), substituicao(5))
        resultado = _rodar(registros)
        assert len(resultado.events) == 4  # type: ignore[attr-defined]
        assert {e.type for e in resultado.events} == {  # type: ignore[attr-defined]
            EventType.GOAL,
            EventType.SHOT,
            EventType.CARD,
            EventType.SUBSTITUTION,
        }

    def test_o_detalhe_do_cartao_e_tipado(self) -> None:
        from sports_intelligence.domain.events.details import CardDetail, CardType

        resultado = _rodar((cartao(4),))
        detalhe = resultado.events[0].detail  # type: ignore[attr-defined]
        assert isinstance(detalhe, CardDetail)
        assert detalhe.card_type is CardType.YELLOW

    def test_a_substituicao_carrega_os_dois_jogadores(self) -> None:
        """§34. Um par desemparelhado é o que o detalhe tipado impede."""
        from sports_intelligence.domain.events.details import SubstitutionDetail

        resultado = _rodar((substituicao(5),))
        detalhe = resultado.events[0].detail  # type: ignore[attr-defined]
        assert isinstance(detalhe, SubstitutionDetail)
        assert detalhe.player_out == ARTILHEIRO
        assert detalhe.player_in == RESERVA

    def test_evento_sem_time_exigido_sobrevive(self) -> None:
        """§59, §91. O apito final não é de ninguém."""
        resultado = _rodar((fim_de_periodo(6),))
        assert len(resultado.events) == 1  # type: ignore[attr-defined]
        evento_final = resultado.events[0]  # type: ignore[attr-defined]
        assert evento_final.type is EventType.PERIOD_END
        assert evento_final.team_id is None
        assert evento_final.player_id is None


class TestOTipoDoProvedor:
    """§13, §14, §89. Traduzido explicitamente, ou não entra."""

    def test_tipo_desconhecido_vai_para_revisao(self) -> None:
        resultado = _rodar((tipo_desconhecido(7),))
        assert resultado.events == ()  # type: ignore[attr-defined]
        registro = resultado.records[0]  # type: ignore[attr-defined]
        assert registro.status is EventBuildRecordStatus.REVIEW_REQUIRED
        assert registro.reason is EventExclusionReason.UNMAPPED_TYPE

    def test_o_rotulo_cru_sobrevive_na_linhagem(self) -> None:
        """«O que era esse evento que não entrou» tem resposta sem reabrir o
        arquivo."""
        resultado = _rodar((tipo_desconhecido(7),))
        assert resultado.records[0].raw_type == "corner_won"  # type: ignore[attr-defined]

    def test_corner_won_nao_vira_corner_por_parecer(self) -> None:
        """A heurística que casaria os dois é exatamente a que produziria
        `PENALTY_GOAL` virando `GOAL`."""
        traducao = tabela_de_tipos().resolve("corner_won")
        assert not traducao.is_mapped
        with pytest.raises(ValidationError, match="não mapeado"):
            traducao.require()

    def test_a_tabela_normaliza_caso_e_espaco_e_so(self) -> None:
        tabela = tabela_de_tipos()
        assert tabela.resolve("GOAL").canonical is EventType.GOAL
        assert tabela.resolve(" goal ").canonical is EventType.GOAL
        assert tabela.resolve("penalty_goal").canonical is None


class TestAIdentidade:
    """§10, §11, §12, §90. O que não resolveu não entra — e não é inventado."""

    def test_jogador_nao_resolvido_bloqueia_o_tipo_que_o_exige(self) -> None:
        """`SHOT` exige executante. `GOAL` não — e essa distinção é do
        domínio desde o PR-01, não desta camada (§58, §59)."""
        resultado = _rodar((chute_sem_jogador_resolvido(8),))
        assert resultado.events == ()  # type: ignore[attr-defined]
        registro = resultado.records[0]  # type: ignore[attr-defined]
        assert registro.status is EventBuildRecordStatus.SKIPPED
        assert registro.reason is EventExclusionReason.IDENTITY_FAILURE

    def test_o_tipo_que_nao_exige_jogador_entra_sem_ele(self) -> None:
        """§58. Impor requisito maior que o contrato faria um gol contra —
        legítimo e sem executante declarado — ficar de fora."""
        resultado = _rodar((gol_sem_jogador(12),))
        assert len(resultado.events) == 1  # type: ignore[attr-defined]
        assert resultado.events[0].player_id is None  # type: ignore[attr-defined]

    def test_partida_nao_resolvida_bloqueia_o_evento(self) -> None:
        sem_partida = EventReferences(teams={REF_DO_TIME: TIME})
        resultado = _rodar((gol(1),), references=sem_partida)
        assert resultado.events == ()  # type: ignore[attr-defined]
        assert (
            resultado.records[0].reason is EventExclusionReason.IDENTITY_FAILURE  # type: ignore[attr-defined]
        )

    def test_partida_resolvida_mas_nao_elegivel_bloqueia(self) -> None:
        """Um evento não entra num corpus onde a partida dele não entrou."""
        canonicalizador = _canonicalizador()
        resultado = canonicalizador.canonicalize(
            (gol(1),),
            references=REFERENCIAS,
            eligible_matches=frozenset(),
            license_class=LicenseClass.PUBLIC_DOMAIN,
        )
        assert resultado.records[0].reason is EventExclusionReason.MATCH_NOT_ELIGIBLE

    def test_o_construtor_recusa_montar_sem_o_exigido(self) -> None:
        """§57. A segunda guarda: o construtor é público."""
        with pytest.raises(ValidationError, match="exige executante"):
            CanonicalEventBuilder().build(
                gol(1),
                match_id=PARTIDA,
                event_type=EventType.SHOT,
                references=EventReferences(
                    matches={REF_DA_PARTIDA: PARTIDA}, teams={REF_DO_TIME: TIME}
                ),
                provenance=PROCEDENCIA,
                source_key="x",
                sequence=0,
            )


class TestORelogio:
    """§15, §16, §47. `45+3` continua `45+3`."""

    def test_o_acrescimo_nao_e_achatado(self) -> None:
        resultado = _rodar((fim_de_periodo(6),))
        relogio = resultado.events[0].clock  # type: ignore[attr-defined]
        assert relogio.minute == 45
        assert relogio.stoppage == 2
        assert relogio.label == "45+2"

    def test_periodo_sem_relogio_correndo_com_minuto_e_recusado(self) -> None:
        no_intervalo = evento(
            9, tipo="goal", minuto=30, periodo=Period.HALF_TIME, jogador=REF_DO_ARTILHEIRO
        )
        resultado = _rodar((no_intervalo,))
        assert resultado.records[0].reason is EventExclusionReason.INVALID_CLOCK  # type: ignore[attr-defined]

    def test_minuto_implausivel_e_recusado_como_ESTRUTURA(self) -> None:
        """§47. O teto pega coluna trocada, e não opina sobre duração de jogo:
        prorrogação aos 120 continua passando."""
        prorrogacao = evento(
            10,
            tipo="goal",
            minuto=118,
            periodo=Period.EXTRA_TIME_SECOND,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        assert len(_rodar((prorrogacao,)).events) == 1  # type: ignore[attr-defined]

        absurdo = evento(
            11,
            tipo="goal",
            minuto=1998,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        assert _rodar((absurdo,)).records[0].reason is EventExclusionReason.INVALID_CLOCK  # type: ignore[attr-defined]


class TestAOrdemDeterminística:
    """§17, §18, §86. Dois eventos no mesmo minuto ficam em ordem estável."""

    def test_a_ordem_nao_vem_do_arquivo(self) -> None:
        primeiro = evento(
            1,
            tipo="goal",
            minuto=23,
            sequencia=1,
            id_do_evento="a",
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        segundo = evento(
            2,
            tipo="shot",
            minuto=23,
            sequencia=2,
            id_do_evento="b",
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "SAVED"},
        )
        # A MESMA ENTRADA, EM DUAS ORDENS DE ARQUIVO.
        direta = _rodar((primeiro, segundo))
        invertida = _rodar((segundo, primeiro))
        assert [e.id for e in direta.events] == [e.id for e in invertida.events]  # type: ignore[attr-defined]
        assert [e.sequence for e in direta.events] == [0, 1]  # type: ignore[attr-defined]

    def test_o_desempate_usa_a_sequencia_do_provedor(self) -> None:
        cedo = evento(
            1,
            tipo="goal",
            minuto=23,
            sequencia=1,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        tarde = evento(
            2,
            tipo="goal",
            minuto=23,
            sequencia=9,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        assert ordering_key(cedo) < ordering_key(tarde)

    def test_o_acrescimo_ordena_depois_do_minuto(self) -> None:
        normal = evento(
            1, tipo="goal", minuto=45, jogador=REF_DO_ARTILHEIRO, detalhes={"EVENT_OUTCOME": "GOAL"}
        )
        no_acrescimo = evento(
            2,
            tipo="goal",
            minuto=45,
            acrescimo=3,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        assert ordering_key(normal) < ordering_key(no_acrescimo)

    def test_a_sequencia_canonica_e_por_periodo(self) -> None:
        primeiro_tempo = evento(
            1, tipo="goal", minuto=10, jogador=REF_DO_ARTILHEIRO, detalhes={"EVENT_OUTCOME": "GOAL"}
        )
        segundo_tempo = evento(
            2,
            tipo="goal",
            minuto=50,
            periodo=Period.SECOND_HALF,
            jogador=REF_DO_ARTILHEIRO,
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        resultado = _rodar((primeiro_tempo, segundo_tempo))
        assert [e.sequence for e in resultado.events] == [0, 0]  # type: ignore[attr-defined]


class TestAIdentidadeDoEvento:
    """§19, §20, §24, §87. Derivada, estável, idempotente."""

    def test_o_id_e_derivado_e_estavel(self) -> None:
        a = canonical_event_id(source_key="p:1", revision=1, match_id=PARTIDA)
        b = canonical_event_id(source_key="p:1", revision=1, match_id=PARTIDA)
        assert a == b

    def test_a_revisao_muda_o_id(self) -> None:
        primeira = canonical_event_id(source_key="p:1", revision=1, match_id=PARTIDA)
        segunda = canonical_event_id(source_key="p:1", revision=2, match_id=PARTIDA)
        assert primeira != segunda

    def test_a_partida_entra_no_id(self) -> None:
        outra = MatchId.derive("pr0441", "outra-partida")
        assert canonical_event_id(
            source_key="p:1", revision=1, match_id=PARTIDA
        ) != canonical_event_id(source_key="p:1", revision=1, match_id=outra)

    def test_reprocessar_a_mesma_fonte_produz_os_mesmos_ids(self) -> None:
        registros = (gol(1), cartao(4))
        primeira = _rodar(registros)
        segunda = _rodar(registros)
        assert [e.id for e in primeira.events] == [e.id for e in segunda.events]  # type: ignore[attr-defined]

    def test_chave_repetida_no_mesmo_lote_nao_duplica(self) -> None:
        """§87. O segundo é registrado como visto, e não construído."""
        registros = (gol(1, id_do_evento="ev-x"), gol(2, id_do_evento="ev-x"))
        resultado = _rodar(registros)
        assert len(resultado.events) == 1  # type: ignore[attr-defined]
        pulados = [
            r
            for r in resultado.records  # type: ignore[attr-defined]
            if r.status is EventBuildRecordStatus.SKIPPED
        ]
        assert len(pulados) == 1
        assert pulados[0].reason is EventExclusionReason.IDENTITY_CONFLICT


class TestARevisao:
    """§21, §22, §23, §88, §100. O anterior sobrevive, sempre."""

    def test_a_correcao_cria_evento_novo_e_marca_o_anterior(self) -> None:
        original = gol(1, id_do_evento="ev-1")
        correcao = evento(
            2,
            tipo="goal",
            minuto=24,
            id_do_evento="ev-1c",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CORRECTION,
            substitui="ev-1",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        resultado = _rodar((original, correcao))
        assert len(resultado.events) == 2  # type: ignore[attr-defined]
        revisado = next(e for e in resultado.events if e.revision == 2)  # type: ignore[attr-defined]
        anterior = next(e for e in resultado.events if e.revision == 1)  # type: ignore[attr-defined]
        assert revisado.supersedes == anterior.id
        assert resultado.superseded == ((anterior.id, revisado.id),)  # type: ignore[attr-defined]

    def test_o_cancelamento_nao_cria_evento_novo(self) -> None:
        """§23. Um gol anulado pelo VAR não é um gol corrigido — e criar uma
        revisão «cancelada» faria o registro ter dois gols."""
        original = gol(1, id_do_evento="ev-1")
        cancelamento = evento(
            2,
            tipo="goal",
            minuto=23,
            id_do_evento="ev-1x",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CANCELLATION,
            substitui="ev-1",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        resultado = _rodar((original, cancelamento))
        assert len(resultado.events) == 1  # type: ignore[attr-defined]
        assert len(resultado.cancelled) == 1  # type: ignore[attr-defined]
        assert resultado.cancelled[0] == resultado.events[0].id  # type: ignore[attr-defined]

    def test_revisao_sem_predecessor_no_conjunto_vai_para_revisao(self) -> None:
        orfa = evento(
            1,
            tipo="goal",
            minuto=23,
            id_do_evento="ev-2",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CORRECTION,
            substitui="ev-inexistente",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        resultado = _rodar((orfa,))
        assert resultado.events == ()  # type: ignore[attr-defined]
        assert (
            resultado.records[0].reason is EventExclusionReason.DANGLING_REVISION  # type: ignore[attr-defined]
        )

    def test_uma_correcao_sem_dizer_o_que_corrige_e_recusada_no_registro(self) -> None:
        with pytest.raises(ValidationError, match="sem dizer QUAL"):
            HistoricalEventRecord(
                record_ref=gol(1).record_ref,
                provider_id=PROVEDOR,
                match_reference=REF_DA_PARTIDA,
                raw_type="goal",
                clock=RawEventClock(period=Period.FIRST_HALF, minute=10),
                revision=EventRevisionKind.CORRECTION,
            )

    def test_o_evento_construido_nasce_ativo(self) -> None:
        resultado = _rodar((gol(1),))
        assert resultado.events[0].status is EventStatus.ACTIVE  # type: ignore[attr-defined]


class TestAusenciaNaoEZero:
    """§32, §93, §94, §95. O teste obrigatório."""

    def test_xg_ausente_nao_e_xg_zero(self) -> None:
        sem = _rodar((chute_sem_xg(2),)).events[0].detail  # type: ignore[attr-defined]
        zero = _rodar((chute_com_xg_zero(3),)).events[0].detail  # type: ignore[attr-defined]
        assert sem is not None
        assert zero is not None
        assert not sem.xg.is_available
        assert zero.xg.is_available
        assert zero.xg.require("xg") == 0.0

    def test_xg_medido_em_zero_e_observacao_legitima(self) -> None:
        detalhe = _rodar((chute_com_xg_zero(3),)).events[0].detail  # type: ignore[attr-defined]
        assert detalhe.xg.require("xg") == 0.0

    def test_coordenada_ausente_nao_e_a_origem_do_campo(self) -> None:
        com = _rodar((gol(1),)).events[0]  # type: ignore[attr-defined]
        sem = _rodar((cartao(4),)).events[0]  # type: ignore[attr-defined]
        assert com.start_location is not None
        assert com.start_location.x == pytest.approx(0.88)
        assert sem.start_location is None

    def test_a_coordenada_usa_o_pitch_coordinate_do_dominio(self) -> None:
        """§38, §92. Round-trip exato, e referencial declarado."""
        from sports_intelligence.domain.events.coordinates import CoordinateFrame

        ponto = _rodar((gol(1),)).events[0].start_location  # type: ignore[attr-defined]
        assert ponto.frame is CoordinateFrame.ATTACKING
        assert ponto.x == pytest.approx(0.88)
        assert ponto.y == pytest.approx(0.52)


class TestALicenca:
    """§49, §51, §97. Pesquisa aceita o restrito; comércio não."""

    def test_pesquisa_aceita_research_only(self) -> None:
        resultado = _rodar(
            (gol(1),),
            policy=EventEligibilityPolicy.research(),
            license_class=LicenseClass.RESEARCH_ONLY,
        )
        assert len(resultado.events) == 1  # type: ignore[attr-defined]

    def test_comercio_recusa_research_only_com_a_licenca_no_motivo(self) -> None:
        resultado = _rodar(
            (gol(1),),
            policy=EventEligibilityPolicy.commercial(),
            license_class=LicenseClass.RESEARCH_ONLY,
        )
        assert resultado.events == ()  # type: ignore[attr-defined]
        registro = resultado.records[0]  # type: ignore[attr-defined]
        assert registro.reason is EventExclusionReason.LICENSE_POLICY

    def test_comercio_aceita_dominio_publico(self) -> None:
        resultado = _rodar(
            (gol(1),),
            policy=EventEligibilityPolicy.commercial(),
            license_class=LicenseClass.PUBLIC_DOMAIN,
        )
        assert len(resultado.events) == 1  # type: ignore[attr-defined]

    def test_comercio_recusa_licenca_desconhecida(self) -> None:
        """Licença não declarada tratada como permissiva é supor
        permissividade, e o custo do erro é jurídico."""
        assert not EventEligibilityPolicy.commercial().permits(LicenseClass.UNKNOWN)

    def test_o_veredito_carrega_a_licenca_que_causou(self) -> None:
        veredito = _avaliador(EventEligibilityPolicy.commercial()).evaluate(
            gol(1),
            references=REFERENCIAS,
            eligible_matches=ELEGIVEIS,
            license_class=LicenseClass.RESEARCH_ONLY,
        )
        assert veredito.outcome is EventOutcome.EXCLUDED
        assert veredito.license_class is LicenseClass.RESEARCH_ONLY


class TestARotuloNaoEFato:
    """§96. A fronteira do PR-04.2.1 vale igual para evento."""

    def test_nome_de_jogador_e_rotulo(self) -> None:
        assert SemanticRole.EVENT_PLAYER_NAME.is_identity_label
        assert not SemanticRole.EVENT_PLAYER_NAME.is_factual

    def test_minuto_e_coordenada_sao_fato(self) -> None:
        assert SemanticRole.EVENT_MINUTE.is_factual
        assert SemanticRole.EVENT_X.is_factual
        assert SemanticRole.EVENT_XG.is_factual

    def test_o_papel_de_evento_e_reconhecivel(self) -> None:
        assert SemanticRole.EVENT_TYPE.is_event
        assert not SemanticRole.HOME_SCORE.is_event


class TestALinhagem:
    """§48. O que NÃO entrou também deixa linha."""

    def test_todo_registro_produz_linhagem(self) -> None:
        registros = (gol(1), tipo_desconhecido(7), chute_sem_jogador_resolvido(8))
        resultado = _rodar(registros)
        assert len(resultado.records) == 3  # type: ignore[attr-defined]
        assert resultado.records_read == 3  # type: ignore[attr-defined]

    def test_a_linhagem_liga_o_evento_a_linha_do_arquivo(self) -> None:
        resultado = _rodar((gol(1),))
        registro = resultado.records[0]  # type: ignore[attr-defined]
        assert registro.event_id == resultado.events[0].id  # type: ignore[attr-defined]
        assert ":1" in registro.record_ref

    def test_a_recusa_diz_o_motivo_e_o_detalhe(self) -> None:
        resultado = _rodar((tipo_desconhecido(7),))
        registro = resultado.records[0]  # type: ignore[attr-defined]
        assert registro.reason is EventExclusionReason.UNMAPPED_TYPE
        assert registro.detail is not None
        assert "corner_won" in registro.detail
