"""A fusão: agrupamento, concordância, conflito e conjuntos de observação.

O ASSUNTO É O MESMO DA RESOLUÇÃO, do outro lado: o sistema prefere PRESERVAR
o desacordo a inventar um valor. Um campo em `CONFLICT_UNRESOLVED` é o
resultado DESEJÁVEL quando a política não sabe decidir — escolher por
desempate arbitrário produziria um número de aparência decidida que ninguém
revisaria.

E odds de casas diferentes nunca viram uma média: `(2.00 + 2.05) / 2 = 2.025`
é um preço que casa nenhuma ofereceu, e ele apaga justamente a dispersão que
é o sinal.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sports_intelligence.domain.fusion.models import (
    FusionGroup,
    FusionRule,
    Observation,
    ObservationSet,
    ResolvedSourceRecord,
)
from sports_intelligence.domain.fusion.policy import (
    DEFAULT_FUSION_POLICY,
    ConflictResolution,
    FieldPolicy,
    FusionPolicy,
)
from sports_intelligence.domain.fusion.runs import (
    FusedMatchCandidate,
    FusionRun,
    assert_not_historical_active,
)
from sports_intelligence.domain.resolution.versions import CURRENT_FUSION_POLICY_VERSION
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import DatasetId, MatchId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.sources.records import DatasetRecordRef
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.ingestion.fusion.engine import (
    FusionEngine,
    count_fusion,
    group_by_identity,
)

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
PARTIDA = MatchId.new()
DATASET = DatasetId.new()
A = ProviderId("fonte_a")
B = ProviderId("fonte_b")
C = ProviderId("fonte_c")


def _ref(n: int) -> DatasetRecordRef:
    return DatasetRecordRef(dataset_id=DATASET, file_id=str(DATASET), record_number=n)


def _registro(
    provedor: ProviderId,
    valores: dict[SemanticRole, str],
    *,
    partida: MatchId = PARTIDA,
    linha: int = 1,
    licenca: LicenseClass = LicenseClass.PUBLIC_DOMAIN,
    qualidade: float | None = None,
) -> ResolvedSourceRecord:
    return ResolvedSourceRecord(
        record_ref=_ref(linha),
        provider_id=provedor,
        source_type=SourceType.OPEN_DATA,
        license_class=licenca,
        canonical_entity_id=partida,
        resolution_decision_id=f"decisao-{provedor}",
        values=valores,
        quality=qualidade,
    )


def _grupo(*registros: ResolvedSourceRecord) -> FusionGroup:
    return FusionGroup.of(PARTIDA, registros)


class TestAgrupamento:
    def test_registros_da_mesma_partida_formam_um_grupo(self) -> None:
        grupos, descartados = group_by_identity(
            (
                _registro(A, {SemanticRole.HOME_SCORE: "2"}),
                _registro(B, {SemanticRole.HOME_SCORE: "2"}, linha=2),
            )
        )
        assert len(grupos) == 1
        assert grupos[0].is_multi_source
        assert not descartados

    def test_duas_linhas_da_mesma_fonte_nao_contam_como_duas_fontes(self) -> None:
        """Duplicata INTERNA da fonte, não confirmação.

        Contá-las como duas fontes inflaria a concordância: `EXACT_AGREEMENT`
        passaria a valer para um valor que uma fonte só disse duas vezes.
        """
        grupos, descartados = group_by_identity(
            (
                _registro(A, {SemanticRole.HOME_SCORE: "2"}, linha=1),
                _registro(A, {SemanticRole.HOME_SCORE: "2"}, linha=2),
            )
        )
        assert len(grupos) == 1
        assert len(grupos[0].records) == 1
        assert len(descartados) == 1

    def test_partidas_diferentes_nao_se_misturam(self) -> None:
        outra = MatchId.new()
        grupos, _ = group_by_identity(
            (
                _registro(A, {SemanticRole.HOME_SCORE: "2"}),
                _registro(B, {SemanticRole.HOME_SCORE: "1"}, partida=outra, linha=2),
            )
        )
        assert len(grupos) == 2

    def test_grupo_com_duas_entidades_e_recusado(self) -> None:
        """A guarda que impede fundir duas partidas num registro só."""
        with pytest.raises(ConflictError, match="entidades canônicas distintas"):
            FusionGroup.of(
                PARTIDA,
                (
                    _registro(A, {SemanticRole.HOME_SCORE: "2"}),
                    _registro(B, {SemanticRole.HOME_SCORE: "1"}, partida=MatchId.new(), linha=2),
                ),
            )

    def test_registro_sem_decisao_nao_se_constroi(self) -> None:
        """A ordem obrigatória vira ASSINATURA (ADR-0022).

        `ResolvedSourceRecord` não existe sem `resolution_decision_id`, então
        não há caminho de código que funda identidade não provada.
        """
        with pytest.raises(ValidationError, match="sem decisão"):
            ResolvedSourceRecord(
                record_ref=_ref(1),
                provider_id=A,
                source_type=SourceType.OPEN_DATA,
                license_class=LicenseClass.PUBLIC_DOMAIN,
                canonical_entity_id=PARTIDA,
                resolution_decision_id="  ",
                values={},
            )


class TestFusaoEscalar:
    def _motor(self, policy: FusionPolicy = DEFAULT_FUSION_POLICY) -> FusionEngine:
        return FusionEngine(policy)

    def test_concordancia_exata_registra_as_duas_fontes(self) -> None:
        """CENÁRIO: A=10, B=10 → 10, com AS DUAS fontes preservadas (§49).

        A concordância é EVIDÊNCIA. Um valor confirmado por três fontes não é
        o mesmo que um valor que só uma trouxe, e um `selected_from` único
        apagaria a diferença.
        """
        candidato = self._motor().fuse(
            _grupo(
                _registro(A, {SemanticRole.HOME_SHOTS: "10"}),
                _registro(B, {SemanticRole.HOME_SHOTS: "10"}, linha=2),
            )
        )
        campo = candidato.field("HOME_SHOTS")
        assert campo is not None
        assert campo.rule is FusionRule.EXACT_AGREEMENT
        assert campo.selected_value == "10"
        assert set(campo.agreeing_sources) == {A, B}
        assert campo.confidence > 0.9

    def test_fonte_unica_e_cobertura_e_nao_conflito(self) -> None:
        candidato = self._motor().fuse(_grupo(_registro(A, {SemanticRole.ATTENDANCE: "54000"})))
        campo = candidato.field("ATTENDANCE")
        assert campo is not None
        assert campo.rule is FusionRule.MOST_COMPLETE
        assert not campo.rule.had_conflict

    def test_conflito_sem_politica_fica_sem_valor(self) -> None:
        """CENÁRIO E: sem política suficiente → `CONFLICT_UNRESOLVED` (§89).

        E o campo fica SEM valor selecionado. Um valor aqui seria lido como
        se tivesse sido decidido — e ninguém revisaria.
        """
        candidato = self._motor().fuse(
            _grupo(
                _registro(A, {SemanticRole.HOME_SCORE: "2"}),
                _registro(B, {SemanticRole.HOME_SCORE: "3"}, linha=2),
            )
        )
        campo = candidato.field("HOME_SCORE")
        assert campo is not None
        assert campo.rule is FusionRule.CONFLICT_UNRESOLVED
        assert campo.selected_value is None
        # AS DUAS PRESERVADAS. É o que permite a alguém decidir depois.
        assert len(campo.contributions) == 2
        assert candidato.has_unresolved_conflict

    def test_conflito_com_fonte_preferida_resolve_e_guarda_a_outra(self) -> None:
        """CENÁRIO E: A=14, B=16 → selecionado, alternativa, regra, fonte."""
        politica = FusionPolicy(
            version=CURRENT_FUSION_POLICY_VERSION,
            fields={
                SemanticRole.HOME_SHOTS: FieldPolicy(
                    role=SemanticRole.HOME_SHOTS,
                    on_conflict=ConflictResolution.PREFER_SOURCE,
                    preferred_sources=(B,),
                )
            },
        )
        candidato = FusionEngine(politica).fuse(
            _grupo(
                _registro(A, {SemanticRole.HOME_SHOTS: "14"}),
                _registro(B, {SemanticRole.HOME_SHOTS: "16"}, linha=2),
            )
        )
        campo = candidato.field("HOME_SHOTS")
        assert campo is not None
        assert campo.rule is FusionRule.PREFERRED_SOURCE
        assert campo.selected_value == "16"
        assert campo.selected_from == B
        # A ALTERNATIVA FICA. Sem ela, ninguém saberia que A discordava.
        assert [c.value for c in campo.alternatives] == ["14"]

    def test_tolerancia_numerica_trata_arredondamento_como_acordo(self) -> None:
        """`59.8` e `60` são a mesma observação com precisão diferente.

        A tolerância é DECLARADA por campo: posse de bola tolera
        arredondamento; placar não, e é por isso que 2 contra 3 é conflito.
        """
        candidato = self._motor().fuse(
            _grupo(
                _registro(A, {SemanticRole.HOME_POSSESSION: "59.8"}),
                _registro(B, {SemanticRole.HOME_POSSESSION: "60"}, linha=2),
            )
        )
        campo = candidato.field("HOME_POSSESSION")
        assert campo is not None
        assert campo.selected_value is not None
        assert not campo.is_unresolved_conflict

    def test_media_exige_declaracao_explicita(self) -> None:
        """MÉDIA NUNCA É O DEFAULT (§50).

        A média de dois placares é um placar que nenhuma fonte observou. A
        política só a permite com tolerância declarada — e a validação recusa
        permitir média sem dizer a que distância dois valores ainda descrevem
        a mesma coisa.
        """
        with pytest.raises(ValidationError, match="tolerância declarada"):
            FieldPolicy(
                role=SemanticRole.HOME_XG,
                on_conflict=ConflictResolution.PREFER_PRECISION,
                allow_averaging=True,
            )

    def test_politica_sem_lista_de_preferencia_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem lista de preferência"):
            FieldPolicy(role=SemanticRole.HOME_SHOTS, on_conflict=ConflictResolution.PREFER_SOURCE)


class TestObservacoes:
    def test_odds_de_casas_diferentes_sao_duas_observacoes(self) -> None:
        """CENÁRIO: casa X @ 2.00, casa Y @ 2.05 → DUAS observações (§90).

        Nunca uma média. A dispersão entre casas é o sinal, e `2.025` é um
        preço que nenhuma delas ofereceu.
        """
        candidato = FusionEngine(DEFAULT_FUSION_POLICY).fuse(
            _grupo(
                _registro(
                    A,
                    {
                        SemanticRole.BOOKMAKER_NAME: "Casa X",
                        SemanticRole.ODDS_HOME: "2.00",
                    },
                ),
                _registro(
                    B,
                    {
                        SemanticRole.BOOKMAKER_NAME: "Casa Y",
                        SemanticRole.ODDS_HOME: "2.05",
                    },
                    linha=2,
                ),
            )
        )
        assert len(candidato.observation_sets) == 1
        conjunto = candidato.observation_sets[0]
        assert len(conjunto) == 2
        valores = {o.values[SemanticRole.ODDS_HOME.value] for o in conjunto.observations}
        assert valores == {"2.00", "2.05"}
        # E NENHUM CAMPO ESCALAR DE ODDS. Odds não entram em fusão escalar.
        assert candidato.field("ODDS_HOME") is None

    def test_a_mesma_casa_em_duas_fontes_e_deduplicada(self) -> None:
        conjunto = ObservationSet.deduplicated(
            "odds",
            (
                Observation(
                    discriminator="1X2|Casa X",
                    values={"ODDS_HOME": "2.00"},
                    record_ref=_ref(1),
                    provider_id=A,
                    license_class=LicenseClass.PUBLIC_DOMAIN,
                ),
                Observation(
                    discriminator="1X2|Casa X",
                    values={"ODDS_HOME": "2.00"},
                    record_ref=_ref(2),
                    provider_id=B,
                    license_class=LicenseClass.PUBLIC_DOMAIN,
                ),
            ),
        )
        assert len(conjunto) == 1

    def test_observacao_sem_discriminante_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem discriminante"):
            Observation(
                discriminator="  ",
                values={"ODDS_HOME": "2.00"},
                record_ref=_ref(1),
                provider_id=A,
                license_class=LicenseClass.PUBLIC_DOMAIN,
            )


class TestCenarioMultiFonte:
    def test_tres_fontes_produzem_um_candidato_com_procedencia(self) -> None:
        """CENÁRIO D: A traz chutes, B traz xG, C traz odds (§95).

        Um candidato, campos combinados, odds como observações, e cada valor
        sabendo de qual dataset, arquivo e linha veio.
        """
        candidato = FusionEngine(DEFAULT_FUSION_POLICY).fuse(
            _grupo(
                _registro(
                    A,
                    {SemanticRole.HOME_SCORE: "2", SemanticRole.HOME_SHOTS: "14"},
                    linha=10,
                ),
                _registro(
                    B,
                    {SemanticRole.HOME_SCORE: "2", SemanticRole.HOME_XG: "1.8"},
                    linha=20,
                ),
                _registro(
                    C,
                    {
                        SemanticRole.BOOKMAKER_NAME: "Casa Z",
                        SemanticRole.ODDS_HOME: "1.90",
                    },
                    linha=30,
                ),
            )
        )
        assert candidato.field("HOME_SHOTS") is not None
        assert candidato.field("HOME_XG") is not None
        assert len(candidato.observation_sets) == 1

        # PROCEDÊNCIA POR CAMPO (§55): dataset, arquivo e linha.
        chutes = candidato.field("HOME_SHOTS")
        assert chutes is not None
        assert chutes.contributions[0].record_ref.record_number == 10

        placar = candidato.field("HOME_SCORE")
        assert placar is not None
        assert placar.rule is FusionRule.EXACT_AGREEMENT
        assert set(placar.agreeing_sources) == {A, B}

    def test_licenca_mais_restritiva_governa_o_candidato(self) -> None:
        """O candidato herda a restrição do CONJUNTO (§76).

        Usar a licença permissiva porque ela contribuiu com mais campos seria
        contornar a restrição da outra pelo caminho de trás.
        """
        candidato = FusionEngine(DEFAULT_FUSION_POLICY).fuse(
            _grupo(
                _registro(
                    A,
                    {SemanticRole.HOME_SHOTS: "14"},
                    licenca=LicenseClass.PUBLIC_DOMAIN,
                ),
                _registro(
                    B,
                    {SemanticRole.HOME_XG: "1.8"},
                    linha=2,
                    licenca=LicenseClass.RESEARCH_ONLY,
                ),
            )
        )
        assert LicenseClass.RESEARCH_ONLY in candidato.licenses
        assert candidato.most_restrictive_license is LicenseClass.RESEARCH_ONLY


class TestReprodutibilidade:
    def test_a_impressao_e_estavel(self) -> None:
        """CENÁRIO F, segunda metade (§92).

        A mesma entrada com a mesma política produz a mesma saída, e a
        impressão prova isso comparando 64 caracteres em vez de percorrer
        campo a campo.
        """
        grupo = _grupo(
            _registro(A, {SemanticRole.HOME_SHOTS: "14"}),
            _registro(B, {SemanticRole.HOME_SHOTS: "14"}, linha=2),
        )
        motor = FusionEngine(DEFAULT_FUSION_POLICY)
        assert motor.fuse(grupo).fingerprint == motor.fuse(grupo).fingerprint

    def test_conteudo_diferente_muda_a_impressao(self) -> None:
        motor = FusionEngine(DEFAULT_FUSION_POLICY)
        um = motor.fuse(_grupo(_registro(A, {SemanticRole.HOME_SHOTS: "14"})))
        outro = motor.fuse(_grupo(_registro(A, {SemanticRole.HOME_SHOTS: "16"})))
        assert um.fingerprint != outro.fingerprint

    def test_a_ordem_das_fontes_nao_muda_a_saida(self) -> None:
        """A saída é ordenada por campo e por provedor, não pela ordem de
        processamento — senão a impressão não provaria nada."""
        motor = FusionEngine(DEFAULT_FUSION_POLICY)
        a = _registro(A, {SemanticRole.HOME_SHOTS: "14"})
        b = _registro(B, {SemanticRole.HOME_SHOTS: "14"}, linha=2)
        assert motor.fuse(_grupo(a, b)).as_canonical() == motor.fuse(_grupo(b, a)).as_canonical()


class TestExecucaoDeFusao:
    def _execucao(self) -> FusionRun:
        return FusionRun.start(
            input_resolution_run_ids=("run-1",),
            policy_version=CURRENT_FUSION_POLICY_VERSION,
            at=AGORA,
            triggered_by=Actor.service("historical-fusion-worker"),
        )

    def test_conflito_nao_resolvido_leva_a_completed_with_review(self) -> None:
        from sports_intelligence.domain.fusion.runs import FusionCounts
        from sports_intelligence.domain.resolution.runs import RunStatus

        concluida = self._execucao().complete(
            counts=FusionCounts(groups=1, fields_selected=2, conflicts=1, unresolved_conflicts=1),
            at=AGORA,
        )
        assert concluida.status is RunStatus.COMPLETED_WITH_REVIEW

    def test_execucao_concluida_e_imutavel(self) -> None:
        """ADR-0020: política nova produz execução nova."""
        from sports_intelligence.domain.fusion.runs import FusionCounts

        concluida = self._execucao().complete(counts=FusionCounts(groups=1), at=AGORA)
        with pytest.raises(ConflictError, match="já terminou"):
            concluida.complete(counts=FusionCounts(groups=2), at=AGORA)

    def test_execucao_sem_entrada_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem entrada"):
            FusionRun.start(
                input_resolution_run_ids=(),
                policy_version=CURRENT_FUSION_POLICY_VERSION,
                at=AGORA,
                triggered_by=Actor.service("worker"),
            )

    def test_a_mesma_execucao_de_entrada_duas_vezes_e_recusada(self) -> None:
        """Os registros dela entrariam duplicados e inflariam a concordância."""
        with pytest.raises(ValidationError, match="duas vezes"):
            FusionRun.start(
                input_resolution_run_ids=("run-1", "run-1"),
                policy_version=CURRENT_FUSION_POLICY_VERSION,
                at=AGORA,
                triggered_by=Actor.service("worker"),
            )


class TestLimiteHistorico:
    def test_candidato_fundido_nao_e_historico_ativo(self) -> None:
        """A guarda do limite deste PR, e ela recusa SEMPRE (§101).

        Entre o candidato e o índice histórico estão a avaliação de qualidade
        e a construção canônica — o PR-04 — mais a barreira do ADR-0007.
        """
        candidato = FusionEngine(DEFAULT_FUSION_POLICY).fuse(
            _grupo(_registro(A, {SemanticRole.HOME_SHOTS: "14"}))
        )
        with pytest.raises(InvariantViolationError, match="não conhecimento histórico"):
            assert_not_historical_active(candidato)

    def test_contagens_de_fusao(self) -> None:
        motor = FusionEngine(DEFAULT_FUSION_POLICY)
        grupo = _grupo(
            _registro(A, {SemanticRole.HOME_SCORE: "2"}),
            _registro(B, {SemanticRole.HOME_SCORE: "3"}, linha=2),
        )
        contagens = count_fusion((motor.fuse(grupo),), (grupo,))
        assert contagens.groups == 1
        assert contagens.multi_source_groups == 1
        assert contagens.unresolved_conflicts == 1
        assert contagens.conflict_rate is not None


class TestSaidaCanonica:
    def test_a_saida_nao_carrega_valor_escolhido_em_conflito(self) -> None:
        candidato = FusionEngine(DEFAULT_FUSION_POLICY).fuse(
            _grupo(
                _registro(A, {SemanticRole.HOME_SCORE: "2"}),
                _registro(B, {SemanticRole.HOME_SCORE: "3"}, linha=2),
            )
        )
        campo = next(f for f in candidato.as_canonical()["fields"] if f["name"] == "HOME_SCORE")
        assert campo["selected_value"] is None
        assert campo["rule"] == "CONFLICT_UNRESOLVED"
        # AS DUAS FONTES APARECEM, com valor e referência de registro.
        assert len(campo["sources"]) == 2

    def test_campo_fundido_duas_vezes_e_recusado(self) -> None:
        motor = FusionEngine(DEFAULT_FUSION_POLICY)
        candidato = motor.fuse(_grupo(_registro(A, {SemanticRole.HOME_SHOTS: "14"})))
        with pytest.raises(ValidationError, match="fundido duas vezes"):
            FusedMatchCandidate(
                canonical_match_id=PARTIDA,
                group_id=candidato.group_id,
                fields=(candidato.fields[0], candidato.fields[0]),
            )
