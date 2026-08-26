"""Catálogo fechado, temporada coerente, regime e fase."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sports_intelligence.domain.competitions.catalog import (
    CATALOG,
    CompetitionCode,
    CompetitionType,
    resolve_code,
)
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import instant

INICIO = instant(datetime(2024, 8, 1, tzinfo=UTC))
FIM = instant(datetime(2025, 5, 31, tzinfo=UTC))

REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(2020, 1, 1, tzinfo=UTC)),
    regulation_version="2024/25",
)


class TestCatalogoFechado:
    def test_as_cinco_da_v1_existem(self) -> None:
        assert set(CATALOG) == {
            CompetitionCode.BRA_SERIE_A,
            CompetitionCode.CONMEBOL_LIBERTADORES,
            CompetitionCode.PREMIER_LEAGUE,
            CompetitionCode.UEFA_CHAMPIONS_LEAGUE,
            CompetitionCode.LA_LIGA,
        }

    def test_string_arbitraria_nao_cria_competicao(self) -> None:
        """O defeito que o catálogo fechado impede: `premier leage` na
        segunda-feira e duas Premier Leagues com metade do histórico cada."""
        with pytest.raises(ValidationError) as erro:
            resolve_code("premier leage")
        assert "PREMIER_LEAGUE" in erro.value.context["supported"]

    def test_normaliza_grafias_equivalentes(self) -> None:
        for texto in ("premier_league", "PREMIER-LEAGUE", " premier league "):
            assert resolve_code(texto) is CompetitionCode.PREMIER_LEAGUE

    def test_a_identidade_vem_do_codigo_e_nao_do_nome(self) -> None:
        """O nome muda com patrocinador e tradução; o código não. Uma
        identidade derivada do nome re-chavearia o histórico sozinha."""
        entrada = CATALOG[CompetitionCode.LA_LIGA]
        competicao = Competition.from_code(CompetitionCode.LA_LIGA)
        assert competicao.id == entrada.id
        # O mesmo código dá o mesmo id em qualquer execução.
        assert Competition.from_code(CompetitionCode.LA_LIGA).id == competicao.id

    def test_competicoes_diferentes_tem_ids_diferentes(self) -> None:
        ids = {Competition.from_code(c).id for c in CompetitionCode}
        assert len(ids) == len(CompetitionCode)

    def test_liga_e_torneio_sao_distinguidos(self) -> None:
        """A distinção governa a estrutura de fases, não é rótulo."""
        assert (
            Competition.from_code(CompetitionCode.PREMIER_LEAGUE).competition_type
            is CompetitionType.DOMESTIC_LEAGUE
        )
        assert (
            Competition.from_code(CompetitionCode.UEFA_CHAMPIONS_LEAGUE).competition_type
            is CompetitionType.CONTINENTAL_CLUB
        )


class TestRegime:
    def test_regime_precisa_de_versao_de_regulamento(self) -> None:
        """Duas temporadas do mesmo formato podem ter regras diferentes —
        número de substituições, por exemplo."""
        with pytest.raises(ValueError, match="regulation_version"):
            CompetitionRegime(
                code=RegimeCode.DOUBLE_ROUND_ROBIN,
                effective_from=INICIO,
                regulation_version="  ",
            )

    def test_regime_vigente_nao_tem_fim(self) -> None:
        assert REGIME.is_current

    def test_regime_cobre_o_periodo_declarado(self) -> None:
        encerrado = CompetitionRegime(
            code=RegimeCode.GROUP_STAGE_KNOCKOUT,
            effective_from=instant(datetime(2003, 1, 1, tzinfo=UTC)),
            effective_to=instant(datetime(2024, 6, 30, tzinfo=UTC)),
            regulation_version="2003-2024",
        )
        assert encerrado.covers(instant(datetime(2020, 3, 1, tzinfo=UTC)))
        assert not encerrado.covers(instant(datetime(2025, 3, 1, tzinfo=UTC)))
        assert not encerrado.is_current

    def test_a_champions_mudou_de_formato_e_o_modelo_sabe(self) -> None:
        """A razão de `CompetitionRegime` existir: a Champions de 2020 tinha
        grupos de 32; a de 2025 tem league phase de 36. Comparar as duas como
        'a mesma competição' compara coisas incomparáveis."""
        antigo = CompetitionRegime(
            code=RegimeCode.GROUP_STAGE_KNOCKOUT,
            effective_from=instant(datetime(2003, 7, 1, tzinfo=UTC)),
            effective_to=instant(datetime(2024, 6, 30, tzinfo=UTC)),
            regulation_version="UEFA-2003",
        )
        novo = CompetitionRegime(
            code=RegimeCode.LEAGUE_PHASE_KNOCKOUT,
            effective_from=instant(datetime(2024, 7, 1, tzinfo=UTC)),
            regulation_version="UEFA-2024",
        )
        assert antigo.code is not novo.code


class TestSeason:
    def _season(self, **mudancas: object) -> Season:
        campos: dict[str, object] = {
            "competition_id": Competition.from_code(CompetitionCode.PREMIER_LEAGUE).id,
            "label": "2024-2025",
            "starts_at": INICIO,
            "ends_at": FIM,
            "regime": REGIME,
        }
        campos.update(mudancas)
        return Season.create(**campos)  # type: ignore[arg-type]

    def test_o_id_e_deterministico(self) -> None:
        """Reingerir a mesma temporada não pode criar uma segunda."""
        assert self._season().id == self._season().id

    def test_temporada_nao_termina_antes_de_comecar(self) -> None:
        with pytest.raises(ValueError, match="antes de começar"):
            self._season(starts_at=FIM, ends_at=INICIO)

    def test_o_regime_precisa_cobrir_a_temporada_inteira(self) -> None:
        """Uma temporada que atravessa dois regimes é duas coisas diferentes,
        e tratá-la como uma faria o histórico comparar formatos distintos."""
        curto = CompetitionRegime(
            code=RegimeCode.DOUBLE_ROUND_ROBIN,
            effective_from=INICIO,
            effective_to=instant(datetime(2024, 12, 31, tzinfo=UTC)),
            regulation_version="parcial",
        )
        with pytest.raises(ValueError, match="não cobre o fim"):
            self._season(regime=curto)

    def test_contains(self) -> None:
        temporada = self._season()
        assert temporada.contains(instant(datetime(2025, 1, 15, tzinfo=UTC)))
        assert not temporada.contains(instant(datetime(2025, 8, 15, tzinfo=UTC)))


class TestStage:
    def test_nem_toda_competicao_tem_a_mesma_estrutura(self) -> None:
        """Uma liga tem rodada; a Libertadores tem qualificatória, grupos e
        quatro rodadas de mata-mata."""
        Stage(type=StageType.LEAGUE, round_number=20)
        Stage(type=StageType.GROUP_STAGE, group_label="B")
        Stage(type=StageType.FINAL)

    def test_mata_mata_nao_tem_rodada_de_liga(self) -> None:
        """'Quartas de final, rodada 12' é dado de duas competições
        misturado."""
        with pytest.raises(ValueError, match="mata-mata"):
            Stage(type=StageType.QUARTER_FINAL, round_number=12)

    def test_so_a_fase_de_grupos_tem_grupo(self) -> None:
        with pytest.raises(ValueError, match="não tem grupo"):
            Stage(type=StageType.LEAGUE, group_label="A")

    def test_rodada_precisa_ser_positiva(self) -> None:
        with pytest.raises(ValueError, match="positiva"):
            Stage(type=StageType.LEAGUE, round_number=0)

    def test_mata_mata_e_reconhecido(self) -> None:
        """Um empate na 20ª rodada e um empate numa semifinal são situações
        opostas."""
        assert StageType.SEMI_FINAL.is_knockout
        assert not StageType.LEAGUE.is_knockout
        assert not StageType.LEAGUE_PHASE.is_knockout


class TestRegimeEIntervalos:
    def test_regime_nao_termina_antes_de_comecar(self) -> None:
        with pytest.raises(ValueError, match="anterior"):
            CompetitionRegime(
                code=RegimeCode.DOUBLE_ROUND_ROBIN,
                effective_from=FIM,
                effective_to=INICIO,
                regulation_version="x",
            )

    def test_a_borda_do_periodo_esta_incluida(self) -> None:
        regime = CompetitionRegime(
            code=RegimeCode.DOUBLE_ROUND_ROBIN,
            effective_from=INICIO,
            effective_to=FIM,
            regulation_version="x",
        )
        assert regime.covers(INICIO)
        assert regime.covers(FIM)
        assert not regime.covers(instant(FIM + timedelta(seconds=1)))
