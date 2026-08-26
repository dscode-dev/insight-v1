"""Temporal, procedência, qualidade, versões, eventos e idempotência."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sports_intelligence.domain.events.envelope import EventEnvelope, SchemaVersion
from sports_intelligence.domain.events.idempotency import (
    IdempotencyKey,
    ImportId,
    SourceEventId,
)
from sports_intelligence.domain.shared.errors import (
    EngineError,
    ErrorCategory,
    ErrorDetail,
    InvariantViolationError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
    precedence_rank,
)
from sports_intelligence.domain.shared.quality import (
    USABILITY_THRESHOLD,
    DataQuality,
    QualityIssue,
)
from sports_intelligence.domain.shared.temporal import (
    Instant,
    MatchClock,
    ObservationTimes,
    Period,
    instant,
    parse_instant,
)
from sports_intelligence.domain.shared.versioning import (
    EngineVersion,
    FeatureSpaceVersion,
    VersionMismatchError,
)

BASE = instant(datetime(2026, 8, 12, 15, 0, tzinfo=UTC))


def _mais(segundos: int) -> Instant:
    return instant(BASE + timedelta(seconds=segundos))


class TestTempo:
    def test_instante_sem_fuso_e_recusado(self) -> None:
        """Assumir UTC para um datetime ingênuo é o defeito clássico de
        ingestão de fonte pública: o arquivo publica em hora local, ninguém
        declara, e a partida cai no dia errado."""
        with pytest.raises(ValueError, match="fuso"):
            # O datetime sem fuso e o SUJEITO do teste, nao um descuido.
            instant(datetime(2026, 8, 12, 15, 0))  # noqa: DTZ001

    def test_converte_para_utc_preservando_o_instante(self) -> None:
        from datetime import timezone

        saopaulo = datetime(2026, 8, 12, 12, 0, tzinfo=timezone(timedelta(hours=-3)))
        assert instant(saopaulo) == BASE

    def test_parse_aceita_z_e_offset(self) -> None:
        assert parse_instant("2026-08-12T15:00:00Z") == BASE
        assert parse_instant("2026-08-12T12:00:00-03:00") == BASE

    def test_os_quatro_carimbos_precisam_estar_em_ordem(self) -> None:
        """Um observed_at anterior ao occurred_at significa que o provedor viu
        antes de acontecer — a assinatura de um fuso mal lido."""
        with pytest.raises(ValueError, match="antes de acontecer"):
            ObservationTimes(
                occurred_at=_mais(100),
                observed_at=BASE,
                received_at=_mais(200),
                ingested_at=_mais(300),
            )

    def test_as_latencias_sao_separaveis(self) -> None:
        """A do provedor e a nossa são problemas de gente diferente."""
        t = ObservationTimes(
            occurred_at=BASE,
            observed_at=_mais(10),
            received_at=_mais(15),
            ingested_at=_mais(20),
        )
        assert t.provider_lag == timedelta(seconds=10)
        assert t.pipeline_lag == timedelta(seconds=10)
        assert t.total_lag == timedelta(seconds=20)


class TestRelogioDaPartida:
    def test_acrescimo_nao_e_achatado(self) -> None:
        """45+3 e 48 são momentos táticos diferentes."""
        assert MatchClock(Period.FIRST_HALF, 45, 3).label == "45+3"
        assert MatchClock(Period.SECOND_HALF, 48).label == "48"

    def test_intervalo_nao_tem_relogio_correndo(self) -> None:
        with pytest.raises(ValueError, match="relógio"):
            MatchClock(Period.HALF_TIME, 45)

    def test_periodos_com_bola_rolando(self) -> None:
        assert Period.FIRST_HALF.is_ball_in_play
        assert not Period.HALF_TIME.is_ball_in_play
        assert not Period.PENALTY_SHOOTOUT.is_ball_in_play


class TestProcedencia:
    def test_provedor_e_obrigatorio_para_fonte_externa(self) -> None:
        """Sem provedor não há precedência possível quando duas fontes
        discordam."""
        with pytest.raises(ValueError, match="provider_id"):
            DataProvenance(
                source_type=SourceType.OPEN_DATA,
                provider_id=None,
                source_record_id="x",
                times=ObservationTimes.at_once(BASE),
            )

    def test_nativo_nao_tem_provedor_externo(self) -> None:
        with pytest.raises(ValueError, match="INSIGHT_NATIVE"):
            DataProvenance(
                source_type=SourceType.INSIGHT_NATIVE,
                provider_id=ProviderId("espn"),
                source_record_id="x",
                times=ObservationTimes.at_once(BASE),
            )

    def test_licenca_desconhecida_nao_permite_uso_comercial(self) -> None:
        """O default de uma licença desconhecida NUNCA pode ser 'pode tudo'."""
        assert not LicenseClass.UNKNOWN.allows_commercial_use
        assert not LicenseClass.RESEARCH_ONLY.allows_commercial_use
        assert LicenseClass.PUBLIC_DOMAIN.allows_commercial_use

    def test_o_nativo_vence_a_precedencia(self) -> None:
        assert precedence_rank(SourceType.INSIGHT_NATIVE) < precedence_rank(
            SourceType.COMMERCIAL_PROVIDER
        )
        assert precedence_rank(SourceType.COMMERCIAL_PROVIDER) < precedence_rank(
            SourceType.OPEN_DATA
        )

    def test_atalho_nativo_libera_uso_comercial(self) -> None:
        p = DataProvenance.native(ObservationTimes.at_once(BASE))
        assert p.is_native
        assert p.license_class.allows_commercial_use
        assert p.provider_ref is None


class TestQualidade:
    def test_o_elo_mais_fraco_governa(self) -> None:
        """Média deixa um eixo em 0,1 ser mascarado por três em 0,9, e um
        dado de identidade duvidosa não fica bom por estar completo."""
        q = DataQuality(completeness=0.9, consistency=0.9, freshness=0.9, identity_confidence=0.1)
        assert q.overall == 0.1
        assert not q.is_usable

    def test_fora_da_faixa_e_recusado(self) -> None:
        with pytest.raises(ValueError, match=r"\[0,1\]"):
            DataQuality(completeness=1.5, consistency=1.0, freshness=1.0, identity_confidence=1.0)

    def test_problema_bloqueante_reprova_com_score_alto(self) -> None:
        """Identidade não resolvida não é 'qualidade baixa' — é não saber de
        quem é o dado, e nenhum score alto nos outros eixos compensa."""
        q = DataQuality.perfect().with_issue(QualityIssue.UNRESOLVED_ENTITY)
        assert q.overall == 1.0
        assert not q.is_usable

    def test_o_limiar_mora_num_lugar_so(self) -> None:
        assert 0.0 < USABILITY_THRESHOLD < 1.0


class TestVersoes:
    def test_versoes_diferentes_nao_se_comparam(self) -> None:
        """Comparar vetores de espaços diferentes produz um número válido
        sobre coisas diferentes."""
        with pytest.raises(VersionMismatchError):
            FeatureSpaceVersion(1, 0).assert_comparable(FeatureSpaceVersion(1, 1))

    def test_tipos_diferentes_nao_se_comparam(self) -> None:
        with pytest.raises(VersionMismatchError, match="tipos"):
            FeatureSpaceVersion(1, 0).assert_comparable(EngineVersion(1, 0))  # type: ignore[arg-type]

    def test_a_mesma_versao_passa(self) -> None:
        FeatureSpaceVersion(2, 3).assert_comparable(FeatureSpaceVersion(2, 3))

    @pytest.mark.parametrize("bruto", ["v1.0", "v10.25", "v0.1"])
    def test_parse_aceita_o_formato(self, bruto: str) -> None:
        assert str(FeatureSpaceVersion.parse(bruto)) == bruto

    @pytest.mark.parametrize("bruto", ["1.0", "v1", "v1.0.0", "va.b", ""])
    def test_parse_recusa_o_resto(self, bruto: str) -> None:
        with pytest.raises(ValueError, match="vMAJOR"):
            FeatureSpaceVersion.parse(bruto)

    def test_sao_ordenaveis(self) -> None:
        assert FeatureSpaceVersion(1, 2) < FeatureSpaceVersion(1, 10)
        assert FeatureSpaceVersion(2, 0) > FeatureSpaceVersion(1, 99)


class TestEnvelopeDeEvento:
    def _envelope(self) -> EventEnvelope:
        return EventEnvelope.create(
            event_type="match.goal.scored",
            schema_version=SchemaVersion(1, 0),
            occurred_at=BASE,
            produced_at=_mais(1),
            payload={"minute": 63},
        )

    def test_evento_raiz_e_a_propria_correlacao(self) -> None:
        e = self._envelope()
        assert e.is_root
        assert e.causation_id is None

    def test_derivado_herda_correlacao_e_aponta_a_causa(self) -> None:
        """Correlação responde 'o que mais aconteceu por causa disso';
        causação responde 'o que exatamente causou isto'."""
        raiz = self._envelope()
        derivado = raiz.caused_by(
            event_type="state.snapshot.created",
            schema_version=SchemaVersion(1, 0),
            occurred_at=_mais(2),
            produced_at=_mais(2),
            payload={},
        )
        assert derivado.correlation_id == raiz.correlation_id
        assert derivado.causation_id == raiz.event_id
        assert not derivado.is_root

    def test_produzido_antes_de_ocorrer_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="antes de o fato"):
            EventEnvelope.create(
                event_type="match.goal.scored",
                schema_version=SchemaVersion(1, 0),
                occurred_at=_mais(10),
                produced_at=BASE,
                payload={},
            )

    @pytest.mark.parametrize("tipo", ["", "Match.Goal", "match goal", "   "])
    def test_tipo_fora_da_convencao_e_recusado(self, tipo: str) -> None:
        """A convenção existe para que o roteamento por prefixo seja possível
        sem que cada consumidor invente o próprio parser."""
        with pytest.raises(ValueError, match="event_type"):
            EventEnvelope.create(
                event_type=tipo,
                schema_version=SchemaVersion(1, 0),
                occurred_at=BASE,
                produced_at=BASE,
                payload={},
            )

    def test_evento_nao_pode_ser_a_propria_causa(self) -> None:
        identificador = uuid.uuid4()
        with pytest.raises(ValueError, match="própria causa"):
            EventEnvelope(
                event_id=identificador,
                event_type="a.b",
                schema_version=SchemaVersion(1, 0),
                occurred_at=BASE,
                produced_at=BASE,
                correlation_id=uuid.uuid4(),
                causation_id=identificador,
                payload={},
            )


class TestIdempotencia:
    def test_a_mesma_operacao_da_a_mesma_chave(self) -> None:
        a = IdempotencyKey.derive("import_csv", "BRA.csv", "2026-08-12")
        b = IdempotencyKey.derive("import_csv", "BRA.csv", "2026-08-12")
        assert a == b

    def test_operacoes_diferentes_dao_chaves_diferentes(self) -> None:
        assert IdempotencyKey.derive("a", "x") != IdempotencyKey.derive("b", "x")

    def test_chave_curta_e_recusada(self) -> None:
        """Colisão aqui SUPRIME uma operação legítima."""
        with pytest.raises(ValueError, match="curta"):
            IdempotencyKey("abc")

    def test_source_event_id_e_escopado_pelo_provedor(self) -> None:
        """Dois provedores podem usar o id 1 para coisas diferentes."""
        a = SourceEventId(ProviderId("football_data"), "1")
        b = SourceEventId(ProviderId("statsbomb"), "1")
        assert a.key != b.key

    def test_reenviar_o_mesmo_lote_e_reconhecido(self) -> None:
        """Sem isto, reenviar BRA.csv duas vezes gera dois ImportId e o
        segundo parece um lote novo."""
        assert ImportId.derive("football_data", "BRA.csv") == ImportId.derive(
            "football_data", "BRA.csv"
        )
        assert ImportId.new() != ImportId.new()


class TestErros:
    def test_erro_do_dominio_nao_conhece_http(self) -> None:
        """A tradução para status code é do adapter. Um erro que carrega 404
        já decidiu que existe uma requisição para responder — e num worker
        não existe."""
        erro = ValidationError("campo inválido")
        assert not hasattr(erro, "status_code")
        assert erro.category is ErrorCategory.VALIDATION

    def test_relata_todos_os_problemas_de_uma_vez(self) -> None:
        """Quatro campos errados relatados um por vez custam quatro idas e
        voltas, e quem conserta começa a adivinhar na segunda."""
        erro = ValidationError(
            "registro inválido",
            details=(
                ErrorDetail("season", "formato inválido"),
                ErrorDetail("home_team", "clube não resolvido"),
            ),
        )
        assert len(erro.as_dict()["details"]) == 2

    def test_categoria_diz_se_vale_tentar_de_novo(self) -> None:
        assert ErrorCategory.TRANSIENT.is_retryable
        assert not ErrorCategory.VALIDATION.is_retryable

    def test_invariante_quebrado_nao_e_culpa_de_quem_chamou(self) -> None:
        assert not ErrorCategory.INVARIANT_VIOLATION.is_caller_fault
        assert issubclass(InvariantViolationError, EngineError)

    def test_contexto_vai_para_o_log(self) -> None:
        erro = EngineError("falhou", context={"match_id": "abc"})
        assert erro.as_dict()["context"]["match_id"] == "abc"
