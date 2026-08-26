"""A extração — os valores esperados, e a matriz de disponibilidade.

O QUE ESTES TESTES PROVAM. Duas coisas diferentes, e a segunda é a que
sobrevive:

    1. os NÚMEROS do corte de referência, conferidos contra uma tabela escrita
       à mão (§167, §168)
    2. as regras de DISPONIBILIDADE por família (§125 ao §133) — quando existe
       valor, quando não existe, e por qual motivo tipado

A tabela de valores prova que o motor conta certo hoje. A matriz de
disponibilidade prova que ele continua honesto quando o dado falta — e é aí que
um motor de features mente com mais facilidade, porque `0` sempre parece um
número plausível.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sports_intelligence.domain.events.details import ShotOutcome
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.extraction.context import (
    MatchFeatureExtractionContext,
)
from sports_intelligence.domain.features.provenance import FeatureProvenanceClass
from sports_intelligence.domain.features.state.builder import (
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import TeamId
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import FORA, PARTIDA, corte, origem
from tests.support.snapshot_fixtures import (
    ESPERADO_63,
    TODAS_AS_FAMILIAS,
    catalogo,
    contexto,
    entrada,
    espaco,
    evento,
    extrair,
    historia,
    primeiro_tempo,
    segundo_tempo_ate_o_corte,
)
from tests.support.state_fixtures import CASA_TITULARES, escalacoes

# ================================================== os valores esperados ==


class TestOsValoresDoCorteDeReferencia:
    """§167, §168 — a tabela é escrita à mão, e não computada pelo motor."""

    @pytest.mark.parametrize(("chave", "esperado"), sorted(ESPERADO_63.items()))
    def test_o_valor_e_o_esperado(self, chave: str, esperado: float) -> None:
        computada = extrair().value_of(chave)
        assert computada.is_available, f"{chave}: {computada.availability.value}"
        assert computada.numeric == pytest.approx(esperado)

    def test_todas_as_setenta_e_cinco_features_existem_no_cenario_completo(self) -> None:
        snapshot = extrair()
        assert len(snapshot.features) == 75
        assert snapshot.is_complete

    def test_a_tabela_cobre_o_espaco_inteiro(self) -> None:
        """Se uma feature nova entrar no espaço, a tabela precisa dizer o valor."""
        assert set(ESPERADO_63) == set(espaco().keys)


class TestAsFronteirasDaJanela:
    def test_o_evento_da_fronteira_entra_na_janela_maior_e_nao_na_menor(self) -> None:
        """§151, §152 — o chute dos 60 está em `(58,63]` e fora de `(60,63]`."""
        snapshot = extrair()
        assert snapshot.value_of("shots_away_5m").numeric == 2
        assert snapshot.value_of("shots_away_3m").numeric == 1

    def test_a_janela_nao_atravessa_o_periodo(self) -> None:
        """§154 — os dois chutes do primeiro tempo não entram num corte do segundo."""
        com_primeiro_tempo = extrair()
        so_segundo = extrair(entrada(eventos=segundo_tempo_ate_o_corte()))
        for chave in ("shots_home_10m", "xg_home_10m", "shots_on_target_home_10m"):
            assert com_primeiro_tempo.value_of(chave).numeric == so_segundo.value_of(chave).numeric

    def test_um_corte_no_primeiro_tempo_ve_o_primeiro_tempo(self) -> None:
        """A recíproca: os eventos existem, e a janela certa os enxerga."""
        snapshot = extrair(as_of=FeatureAsOf.at(PARTIDA, Period.FIRST_HALF, 45, 3))
        assert snapshot.value_of("shots_home_5m").numeric == 2


# =============================================== a matriz do §125 ao §131 ==


class TestScoreFeatures:
    """§126 — exigem `ScoreState` afirmável."""

    def test_sem_a_familia_event_o_placar_nao_e_afirmavel(self) -> None:
        """§30 — não vira 0-0."""
        snapshot = extrair(
            entrada(families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})),
            families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP}),
        )
        for chave in ("score_home", "score_away", "score_difference"):
            computada = snapshot.value_of(chave)
            assert not computada.is_available
            assert computada.numeric is None

    def test_a_diferenca_de_placar_deriva_dos_dois_lados(self) -> None:
        snapshot = extrair()
        casa = snapshot.value_of("score_home").numeric
        fora = snapshot.value_of("score_away").numeric
        assert casa is not None
        assert fora is not None
        assert snapshot.value_of("score_difference").numeric == casa - fora


class TestManpowerFeatures:
    """§127, §32 — sem escalação NÃO se assume onze."""

    def test_sem_escalacao_o_campo_e_indisponivel(self) -> None:
        snapshot = extrair(
            entrada(
                lineups=(),
                families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}),
            ),
            families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}),
        )
        for chave in (
            "players_on_field_home",
            "players_on_field_away",
            "manpower_difference",
        ):
            assert not snapshot.value_of(chave).is_available

    def test_o_placar_sobrevive_a_falta_de_escalacao(self) -> None:
        """§158 — independência de componentes vale entre famílias."""
        snapshot = extrair(
            entrada(
                lineups=(),
                families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}),
            ),
            families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}),
        )
        assert snapshot.value_of("score_home").is_available
        assert snapshot.value_of("shots_home_5m").is_available

    def test_um_lado_indisponivel_torna_a_diferenca_indisponivel(self) -> None:
        """§65, §159 — nunca se preenche o lado ausente com zero."""
        parcial = escalacoes(titulares_casa=CASA_TITULARES[:10])
        snapshot = extrair(entrada(lineups=parcial))
        assert not snapshot.value_of("players_on_field_home").is_available
        assert snapshot.value_of("players_on_field_away").is_available
        assert not snapshot.value_of("manpower_difference").is_available


class TestDisciplineFeatures:
    """§128, §34 — zero com `EVENT` publicado é FATO."""

    def test_zero_cartao_com_event_publicado_e_disponivel(self) -> None:
        snapshot = extrair()
        computada = snapshot.value_of("yellow_cards_home")
        assert computada.is_available
        assert computada.numeric == 0

    def test_sem_event_a_disciplina_nao_e_afirmavel(self) -> None:
        sem_evento = frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})
        snapshot = extrair(entrada(families=sem_evento), families=sem_evento)
        for chave in ("yellow_cards_home", "dismissals_away", "substitutions_home"):
            computada = snapshot.value_of(chave)
            assert not computada.is_available
            assert computada.availability is FeatureAvailability.NOT_DECLARED


class TestRollingAvailability:
    """§59, §60, §129 — a janela exige `EVENT` e história suficiente."""

    def test_sem_event_publicado_a_janela_e_nao_declarada(self) -> None:
        """§156 — e nunca zero."""
        sem_evento = frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})
        snapshot = extrair(entrada(families=sem_evento), families=sem_evento)
        computada = snapshot.value_of("shots_home_5m")
        assert not computada.is_available
        assert computada.availability is FeatureAvailability.NOT_DECLARED
        assert computada.numeric is None

    def test_com_event_publicado_e_janela_vazia_o_zero_e_disponivel(self) -> None:
        """§51, §62, §156 — a ausência de fato é observável, e vale 0."""
        snapshot = extrair(entrada(eventos=segundo_tempo_ate_o_corte()))
        computada = snapshot.value_of("corners_away_5m")
        assert computada.is_available
        assert computada.numeric == 0
        assert computada.provenance.count == 0

    def test_no_intervalo_a_janela_nao_se_aplica(self) -> None:
        """§124 — `HALF_TIME` não tem cronômetro: a janela não tem eixo."""
        snapshot = extrair(as_of=FeatureAsOf.at(PARTIDA, Period.HALF_TIME))
        computada = snapshot.value_of("shots_home_5m")
        assert computada.availability is FeatureAvailability.NOT_APPLICABLE

    def test_na_disputa_de_penaltis_a_janela_nao_se_aplica(self) -> None:
        """§122 — a disputa fica fora das famílias móveis da V1."""
        snapshot = extrair(as_of=FeatureAsOf.at(PARTIDA, Period.PENALTY_SHOOTOUT))
        assert snapshot.value_of("goals_home_1m").availability is FeatureAvailability.NOT_APPLICABLE

    def test_no_pre_jogo_a_janela_vale_zero(self) -> None:
        """§123 — antes do apito, «nenhum chute» é observável e é um fato."""
        snapshot = extrair(as_of=FeatureAsOf.pre_match(PARTIDA))
        computada = snapshot.value_of("shots_home_10m")
        assert computada.is_available
        assert computada.numeric == 0


class TestShotsOnTarget:
    """§42, §43, §44, §158 — não se adivinha, e a contagem sobrevive."""

    def _com_chute_sem_detalhe(self) -> tuple[object, ...]:
        return (
            *segundo_tempo_ate_o_corte(),
            evento(
                "st-chute-62-sem-detalhe",
                tipo=EventType.SHOT,
                minuto=62,
                sequencia=25,
                sem_detalhe=True,
            ),
        )

    def test_chute_sem_detalhe_torna_o_no_alvo_parcial(self) -> None:
        snapshot = extrair(entrada(eventos=self._com_chute_sem_detalhe()))  # type: ignore[arg-type]
        computada = snapshot.value_of("shots_on_target_home_3m")
        assert not computada.is_available
        assert computada.availability is FeatureAvailability.PARTIAL_INPUT

    def test_a_contagem_de_chutes_continua_calculavel(self) -> None:
        """§158 — a independência vale DENTRO da família de finalizações."""
        snapshot = extrair(entrada(eventos=self._com_chute_sem_detalhe()))  # type: ignore[arg-type]
        computada = snapshot.value_of("shots_home_3m")
        assert computada.is_available
        assert computada.numeric == 3

    def test_a_janela_sem_o_chute_defeituoso_continua_afirmavel(self) -> None:
        """O defeito atinge a janela que o contém, e não todas."""
        snapshot = extrair(entrada(eventos=self._com_chute_sem_detalhe()))  # type: ignore[arg-type]
        assert snapshot.value_of("shots_on_target_home_1m").is_available

    def test_trave_e_bloqueio_nao_contam_como_no_alvo(self) -> None:
        eventos = (
            evento(
                "st-trave-62",
                tipo=EventType.SHOT,
                minuto=62,
                sequencia=40,
                outcome=ShotOutcome.POST,
                xg="0.10",
            ),
            evento(
                "st-bloqueio-63",
                tipo=EventType.SHOT,
                minuto=63,
                sequencia=41,
                outcome=ShotOutcome.BLOCKED,
                xg="0.10",
            ),
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert snapshot.value_of("shots_home_3m").numeric == 2
        assert snapshot.value_of("shots_on_target_home_3m").numeric == 0


class TestXg:
    """§46 ao §50, §157 — zero observado e ausente NÃO são a mesma coisa."""

    def test_xg_zero_observado_mantem_a_feature_disponivel(self) -> None:
        """§48 — `0.0` é um valor legítimo."""
        computada = extrair().value_of("xg_away_3m")
        assert computada.is_available
        assert computada.numeric == 0.0

    def test_xg_ausente_num_chute_torna_a_soma_indisponivel(self) -> None:
        """§49, §50 — soma parcial sem dizer seria um número menor com cara de total."""
        eventos = (
            *segundo_tempo_ate_o_corte(),
            evento("st-chute-62-sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=26),
        )
        snapshot = extrair(entrada(eventos=eventos))
        computada = snapshot.value_of("xg_home_3m")
        assert not computada.is_available
        assert computada.availability is FeatureAvailability.PARTIAL_INPUT

    def test_a_contagem_de_chutes_sobrevive_ao_xg_ausente(self) -> None:
        eventos = (
            *segundo_tempo_ate_o_corte(),
            evento("st-chute-62-sem-xg", tipo=EventType.SHOT, minuto=62, sequencia=26),
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert snapshot.value_of("shots_home_3m").is_available

    def test_a_soma_e_decimal_e_nao_acumula_erro_binario(self) -> None:
        """§47 — `0.1 + 0.2` não pode aparecer como `0.30000000000000004`."""
        eventos = tuple(
            evento(
                f"st-decimal-{n}",
                tipo=EventType.SHOT,
                minuto=62,
                sequencia=50 + n,
                xg=valor,
            )
            for n, valor in enumerate(("0.1", "0.2"))
        )
        snapshot = extrair(entrada(eventos=eventos))
        assert snapshot.value_of("xg_home_3m").numeric == 0.3

    def test_a_diferenca_de_xg_tambem_e_decimal(self) -> None:
        snapshot = extrair()
        assert snapshot.value_of("xg_diff_5m").numeric == 0.62


class TestGoalsECorners:
    def test_o_gol_e_creditado_ao_time_do_evento(self) -> None:
        """§53 — a mesma semântica de gol contra do PR-05.2."""
        contra = evento(
            "st-contra-62",
            tipo=EventType.GOAL,
            minuto=62,
            sequencia=60,
            time=FORA,
            jogador_id=CASA_TITULARES[2],
        )
        snapshot = extrair(entrada(eventos=(contra,)))
        assert snapshot.value_of("goals_away_3m").numeric == 1
        assert snapshot.value_of("goals_home_3m").numeric == 0

    def test_o_gol_nao_conta_como_finalizacao(self) -> None:
        """A decisão do catálogo, provada: `shots_*` conta `EventType.SHOT`."""
        snapshot = extrair(
            entrada(eventos=(evento("st-gol-62", tipo=EventType.GOAL, minuto=62, sequencia=61),))
        )
        assert snapshot.value_of("goals_home_3m").numeric == 1
        assert snapshot.value_of("shots_home_3m").numeric == 0

    def test_o_escanteio_e_contagem_pura(self) -> None:
        """§54 — nenhum cálculo de perigo."""
        assert extrair().value_of("corners_home_5m").numeric == 1


class TestProvenance:
    """§81 ao §87 — cada número carrega de onde veio."""

    def test_a_feature_movel_aponta_os_eventos_que_a_sustentam(self) -> None:
        """§83."""
        snapshot = extrair()
        procedencia = snapshot.value_of("shots_home_5m").provenance
        assert procedencia.count == 3
        assert {c.kind for c in procedencia.sample} == {"EVENT"}

    def test_o_xg_aponta_as_finalizacoes_usadas(self) -> None:
        """§85."""
        procedencia = extrair().value_of("xg_home_5m").provenance
        assert procedencia.count == 3

    def test_a_feature_zero_prova_que_nenhum_fato_a_sustenta(self) -> None:
        """§84 — ela não pode parecer ausente."""
        computada = extrair().value_of("corners_away_5m")
        assert computada.is_available
        assert computada.numeric == 0
        assert computada.provenance.count == 0
        assert computada.provenance.contribution_digest == ""

    def test_a_feature_indisponivel_nao_tem_procedencia_forjada(self) -> None:
        sem_evento = frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})
        computada = extrair(entrada(families=sem_evento), families=sem_evento).value_of(
            "shots_home_5m"
        )
        assert computada.provenance.count == 0
        assert computada.numeric is None

    def test_a_diferenca_herda_a_procedencia_dos_dois_lados(self) -> None:
        """§134 — perdê-la faria a diferença ser o único número sem defesa."""
        snapshot = extrair()
        casa = snapshot.value_of("shots_home_5m").provenance
        fora = snapshot.value_of("shots_away_5m").provenance
        diferenca = snapshot.value_of("shots_diff_5m").provenance
        assert diferenca.count == casa.count + fora.count

    def test_a_procedencia_declara_derivacao_canonica(self) -> None:
        procedencia = extrair().value_of("score_home").provenance
        assert procedencia.provenance_class is FeatureProvenanceClass.DERIVED_FROM_CANONICAL

    def test_a_procedencia_nao_carrega_milhares_de_ids(self) -> None:
        """§86 — o teto do contrato do PR-05.1 é respeitado."""
        muitos = tuple(
            evento(f"st-massa-{n}", tipo=EventType.SHOT, minuto=62, sequencia=100 + n)
            for n in range(60)
        )
        snapshot = extrair(entrada(eventos=muitos))
        procedencia = snapshot.value_of("shots_home_3m").provenance
        assert procedencia.count == 60
        assert len(procedencia.sample) == 16
        assert procedencia.sample_truncated


class TestOContextoDeExtracao:
    """§6, §7 — não se combinam artefatos de execuções diferentes."""

    def _build(self, as_of: FeatureAsOf | None = None) -> object:
        return HistoricalMatchStateBuilder(policy=TemporalAvailabilityPolicy.default()).build(
            entrada(),
            as_of=as_of or corte(),
            source=origem(families=TODAS_AS_FAMILIAS),
        )

    def test_o_contexto_conferido_e_construivel(self) -> None:
        assert contexto().state.identity.match_id == PARTIDA

    def test_corte_diferente_entre_estado_e_extracao_e_recusado(self) -> None:
        build = self._build()
        with pytest.raises(ValidationError, match="cortes semanticamente diferentes"):
            MatchFeatureExtractionContext(
                state=build.state,  # type: ignore[attr-defined]
                effective_events=build.projection,  # type: ignore[attr-defined]
                space=espaco(),
                catalog=catalogo(),
                as_of=corte(70),
                source=origem(families=TODAS_AS_FAMILIAS),
                policy=TemporalAvailabilityPolicy.default(),
            )

    def test_corpus_diferente_entre_estado_e_extracao_e_recusado(self) -> None:
        build = self._build()
        outro = origem(families=TODAS_AS_FAMILIAS, fingerprint="b" * 64)
        with pytest.raises(ValidationError, match="corpus"):
            MatchFeatureExtractionContext(
                state=build.state,  # type: ignore[attr-defined]
                effective_events=build.projection,  # type: ignore[attr-defined]
                space=espaco(),
                catalog=catalogo(),
                as_of=corte(),
                source=outro,
                policy=TemporalAvailabilityPolicy.default(),
            )

    def test_politica_diferente_entre_estado_e_extracao_e_recusada(self) -> None:
        build = self._build()
        with pytest.raises(ValidationError, match="política"):
            MatchFeatureExtractionContext(
                state=build.state,  # type: ignore[attr-defined]
                effective_events=build.projection,  # type: ignore[attr-defined]
                space=espaco(),
                catalog=catalogo(),
                as_of=corte(),
                source=origem(families=TODAS_AS_FAMILIAS),
                policy=TemporalAvailabilityPolicy.strict_observed(),
            )

    def test_espaco_e_catalogo_precisam_descrever_o_mesmo_conjunto(self) -> None:
        build = self._build()
        catalogo_reduzido = replace(catalogo(), specs=catalogo().specs[:10])
        with pytest.raises(ValidationError, match="ordens diferentes"):
            MatchFeatureExtractionContext(
                state=build.state,  # type: ignore[attr-defined]
                effective_events=build.projection,  # type: ignore[attr-defined]
                space=espaco(),
                catalog=catalogo_reduzido,
                as_of=corte(),
                source=origem(families=TODAS_AS_FAMILIAS),
                policy=TemporalAvailabilityPolicy.default(),
            )


class TestOTimeIrresoluvel:
    """§41 — um fato creditado a um time que não joga não é ignorado."""

    def test_finalizacao_de_time_estranho_torna_a_familia_parcial(self) -> None:
        intruso = TeamId.derive("pr053", "time-intruso")
        estranho = evento(
            "st-intruso-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=70,
            time=intruso,
            jogador_id=CASA_TITULARES[0],
            xg="0.10",
        )
        snapshot = extrair(entrada(eventos=(*segundo_tempo_ate_o_corte(), estranho)))
        for chave in ("shots_home_3m", "shots_away_3m", "shots_diff_3m"):
            assert snapshot.value_of(chave).availability is FeatureAvailability.PARTIAL_INPUT, chave

    def test_as_outras_familias_continuam_afirmaveis(self) -> None:
        intruso = TeamId.derive("pr053", "time-intruso")
        estranho = evento(
            "st-intruso-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=70,
            time=intruso,
            jogador_id=CASA_TITULARES[0],
            xg="0.10",
        )
        snapshot = extrair(entrada(eventos=(*segundo_tempo_ate_o_corte(), estranho)))
        assert snapshot.value_of("corners_home_3m").is_available
        assert snapshot.value_of("goals_home_10m").is_available


class TestOSnapshot:
    """§77 ao §80 — o contrato do PR-05.1, usado como está."""

    def test_a_ordem_do_snapshot_e_a_do_espaco(self) -> None:
        snapshot = extrair()
        assert tuple(f.definition_key for f in snapshot.features) == espaco().keys

    def test_a_mascara_e_derivada_e_nao_paralela(self) -> None:
        """§80."""
        snapshot = extrair()
        assert snapshot.mask.keys == espaco().keys
        assert snapshot.mask.available_count == 75

    def test_a_mascara_reflete_as_indisponibilidades(self) -> None:
        sem_evento = frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})
        snapshot = extrair(entrada(families=sem_evento), families=sem_evento)
        assert not snapshot.is_complete
        assert snapshot.mask.state_of("clock_minute") is FeatureAvailability.AVAILABLE
        assert snapshot.mask.state_of("shots_home_5m") is FeatureAvailability.NOT_DECLARED

    def test_o_snapshot_carrega_a_identidade_do_espaco_e_do_corpus(self) -> None:
        snapshot = extrair()
        canonico = snapshot.as_canonical()
        assert canonico["feature_space"]["name"] == "MATCH_STATE_RAW_V1"  # type: ignore[index]
        assert "source" in canonico

    def test_o_historico_completo_e_o_recortado_dao_o_mesmo_snapshot(self) -> None:
        """A história do corpus traz o futuro; o snapshot não pode vê-lo."""
        completo = extrair(entrada(eventos=historia()))
        recortado = extrair(entrada(eventos=(*primeiro_tempo(), *segundo_tempo_ate_o_corte())))
        assert completo.fingerprint == recortado.fingerprint
