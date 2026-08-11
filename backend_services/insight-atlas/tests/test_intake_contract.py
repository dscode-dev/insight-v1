"""Every rule in atlas.match.v1, and the reason it exists.

Each test below names a way data actually got into the Atlas wrong. If one
of them ever has to be relaxed, the comment says what it was protecting.
"""

from __future__ import annotations

import copy

import pytest

from atlas.intake import contract
from atlas.intake.contract import example, validate

REGISTRO = frozenset({"arsenal", "chelsea", "atletico_madrid", "athletic_bilbao"})


def _com(**mudancas) -> dict:
    """The valid example, with a nested path overridden: `_com(**{"identity.season": ""})`."""
    payload = copy.deepcopy(example())
    for caminho, valor in mudancas.items():
        alvo = payload
        partes = caminho.split(".")
        for parte in partes[:-1]:
            alvo = alvo[parte]
        if valor is contract:  # sentinela: remover o campo
            alvo.pop(partes[-1], None)
        else:
            alvo[partes[-1]] = valor
    return payload


def _sem(caminho: str) -> dict:
    payload = copy.deepcopy(example())
    alvo = payload
    partes = caminho.split(".")
    for parte in partes[:-1]:
        alvo = alvo[parte]
    alvo.pop(partes[-1], None)
    return payload


class TestExemplo:
    def test_o_exemplo_passa(self):
        """Kept as code so it cannot drift: change a rule and this breaks."""
        veredito = validate(example(), registry=REGISTRO)
        assert veredito.accepted, [str(e) for e in veredito.errors]
        assert veredito.uid

    def test_o_uid_e_a_identidade_compartilhada(self):
        from atlas.match_identity import match_uid

        veredito = validate(example(), registry=REGISTRO)
        assert veredito.uid == match_uid(
            "premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12"
        )


class TestCampoAusente:
    """A missing field is the failure mode the whole contract exists for:
    the old reader dropped such a line without a word."""

    @pytest.mark.parametrize(
        "caminho",
        [
            "identity.competition", "identity.season", "identity.home_club_id",
            "identity.kickoff_utc", "result.home_goals", "result.home_goals_halftime",
            "market", "market.opening", "market.closing", "market.bookmaker",
            "stats", "stats.home", "stats.home.shots", "stats.away.corners",
            "provenance", "provenance.source", "provenance.collected_at",
        ],
    )
    def test_rejeita_e_nomeia_o_campo(self, caminho):
        veredito = validate(_sem(caminho), registry=REGISTRO)
        assert not veredito.accepted
        assert any(e.field == caminho for e in veredito.errors), (
            f"esperava um erro em {caminho}, veio {[str(e) for e in veredito.errors]}"
        )

    def test_reporta_todos_os_problemas_de_uma_vez(self):
        """Not the first one. Four problems reported one at a time is four
        round trips, and whoever is fixing starts guessing after the second."""
        quebrado = _sem("identity.season")
        del quebrado["market"]
        del quebrado["stats"]
        veredito = validate(quebrado, registry=REGISTRO)
        campos = {e.field for e in veredito.errors}
        assert {"identity.season", "market", "stats"} <= campos


class TestCompeticaoETemporada:
    """Both were accepted as empty strings by the old reader — producing a
    vector that no competition-filtered query would ever return, with the
    row count still adding up."""

    @pytest.mark.parametrize("valor", ["", " ", "Premier League", "PREMIER_LEAGUE"])
    def test_competicao_invalida(self, valor):
        veredito = validate(_com(**{"identity.competition": valor}), registry=REGISTRO)
        assert not veredito.accepted

    @pytest.mark.parametrize("valor", ["", "23-24", "2023/2024", "temporada"])
    def test_temporada_invalida(self, valor):
        veredito = validate(_com(**{"identity.season": valor}), registry=REGISTRO)
        assert not veredito.accepted

    @pytest.mark.parametrize("valor", ["2024", "2023-2024"])
    def test_temporada_valida_nos_dois_formatos(self, valor):
        """Sul-americanas cabem num ano; europeias atravessam dois."""
        assert validate(_com(**{"identity.season": valor}), registry=REGISTRO).accepted


class TestClube:
    def test_nome_de_exibicao_e_recusado(self):
        """The old reader fell back from club_id to the raw name, so
        "Arsenal FC" and "arsenal" became two clubs with half a history each."""
        veredito = validate(
            _com(**{"identity.home_club_id": "Arsenal FC"}), registry=REGISTRO
        )
        assert not veredito.accepted
        assert any("formato" in e.reason for e in veredito.errors)

    def test_clube_fora_do_registro_e_recusado(self):
        """A slug nobody has heard of passes the shape check and then never
        joins with anything — the silent half of the `Ath Madrid` bug."""
        veredito = validate(
            _com(**{"identity.home_club_id": "clube_inventado"}), registry=REGISTRO
        )
        assert not veredito.accepted
        assert any("não está no registro" in e.reason for e in veredito.errors)

    def test_registro_ausente_nao_vira_aprovacao(self):
        """An empty registry must not silently stop checking. Membership is
        skipped, the shape rules still apply."""
        veredito = validate(
            _com(**{"identity.home_club_id": "clube_inventado"}), registry=frozenset()
        )
        assert veredito.accepted  # forma ok, filiação não verificada
        veredito = validate(
            _com(**{"identity.home_club_id": "Clube Inventado"}), registry=frozenset()
        )
        assert not veredito.accepted  # forma continua sendo exigida

    def test_time_nao_joga_contra_si_mesmo(self):
        veredito = validate(
            _com(**{"identity.away_club_id": "arsenal"}), registry=REGISTRO
        )
        assert not veredito.accepted


class TestPlacar:
    def test_intervalo_maior_que_o_final_e_impossivel(self):
        veredito = validate(_com(**{"result.home_goals_halftime": 3}), registry=REGISTRO)
        assert not veredito.accepted
        assert any("halftime" in e.reason for e in veredito.errors)

    def test_gol_negativo(self):
        assert not validate(_com(**{"result.away_goals": -1}), registry=REGISTRO).accepted

    def test_so_partida_encerrada(self):
        """A scheduled fixture has no score; storing it as history would put
        a 0-0 into every baseline."""
        assert not validate(_com(**{"result.status": "scheduled"}), registry=REGISTRO).accepted


class TestMercado:
    def test_cotacao_abaixo_de_um_e_impossivel(self):
        """Decimal odds below 1.0 would pay less than the stake — the shape a
        mis-parsed or transposed column takes."""
        assert not validate(
            _com(**{"market.closing.home": 0.85}), registry=REGISTRO
        ).accepted

    def test_tres_cotacoes_incoerentes_sao_recusadas(self):
        """Each price is plausible on its own; together they are not a market.
        The per-field bound cannot see this — only the sum can."""
        payload = _com()
        payload["market"]["closing"] = {"home": 20.0, "draw": 25.0, "away": 30.0}
        veredito = validate(payload, registry=REGISTRO)
        assert not veredito.accepted
        assert any("mercado coerente" in e.reason for e in veredito.errors)

    def test_abertura_e_fechamento_sao_ambos_exigidos(self):
        """The DIFFERENCE is the signal. `line_movement` has been fixed at its
        neutral value in every vector ever written because a single snapshot
        cannot express it."""
        assert not validate(_sem("market.opening"), registry=REGISTRO).accepted
        assert not validate(_sem("market.closing"), registry=REGISTRO).accepted


class TestEstatistica:
    def test_no_alvo_maior_que_total_e_impossivel(self):
        payload = _com()
        payload["stats"]["home"]["shots_on_target"] = 20
        payload["stats"]["home"]["shots"] = 5
        assert not validate(payload, registry=REGISTRO).accepted

    def test_os_dois_lados_sao_exigidos(self):
        assert not validate(_sem("stats.away"), registry=REGISTRO).accepted


class TestTempo:
    def test_fuso_horario_e_obrigatorio(self):
        """`2023-08-12T15:00:00` without an offset parses in the SERVER's
        timezone, which moves a kickoff by hours depending on where the
        container runs — and the kickoff day is part of the match identity."""
        veredito = validate(
            _com(**{"identity.kickoff_utc": "2023-08-12T15:00:00"}), registry=REGISTRO
        )
        assert not veredito.accepted
        assert any("fuso" in e.reason for e in veredito.errors)

    def test_partida_encerrada_no_futuro_e_contradicao(self):
        assert not validate(
            _com(**{"identity.kickoff_utc": "2099-01-01T15:00:00Z"}), registry=REGISTRO
        ).accepted


class TestProcedencia:
    def test_fonte_e_declarada_nao_deduzida(self):
        """The old reader took the source from the third path segment, so
        moving a file changed who was said to have collected it — and the
        source decides whose number wins when two disagree on a score."""
        assert not validate(_sem("provenance.source"), registry=REGISTRO).accepted


class TestCampoDesconhecido:
    def test_campo_extra_e_recusado(self):
        """A typo'd field name would otherwise be accepted and ignored, which
        is how a value silently stops arriving."""
        payload = _com()
        payload["identity"]["kickoff"] = "2023-08-12T15:00:00Z"
        veredito = validate(payload, registry=REGISTRO)
        assert not veredito.accepted
        assert any(e.field == "identity.kickoff" for e in veredito.errors)


class TestMensagens:
    def test_toda_recusa_diz_o_campo_e_o_motivo_em_portugues(self):
        veredito = validate(_sem("market"), registry=REGISTRO)
        assert not veredito.accepted
        for erro in veredito.errors:
            assert erro.field and erro.reason
            assert "Field required" not in erro.reason

    def test_entrada_que_nem_e_objeto(self):
        assert not validate("uma string", registry=REGISTRO).accepted
        assert not validate([1, 2, 3], registry=REGISTRO).accepted
