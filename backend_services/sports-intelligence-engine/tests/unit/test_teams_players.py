"""Identidade independente de nome, e o vínculo temporal jogador↔time."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sports_intelligence.domain.players.models import Player, PlayerTeamTenure, team_at
from sports_intelligence.domain.players.positions import (
    Position,
    PositionLine,
    RoleCode,
    TacticalRole,
)
from sports_intelligence.domain.shared.identity import TeamId
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.teams.models import Team

T2019 = instant(datetime(2019, 1, 1, tzinfo=UTC))
T2022 = instant(datetime(2022, 1, 1, tzinfo=UTC))
T2026 = instant(datetime(2026, 1, 1, tzinfo=UTC))


class TestIdentidadeIndependenteDoNome:
    def test_grafias_diferentes_nao_produzem_identidades_por_derivacao(self) -> None:
        """O DEFEITO CENTRAL. `Team.derive("man city")` não existe — só
        `register`, que sorteia. Derivar do nome faria três grafias virarem
        três clubes, cada um com um terço do histórico."""
        assert not hasattr(Team, "derive")
        a = Team.register(canonical_name="Manchester City", country="GB")
        b = Team.register(canonical_name="Man City", country="GB")
        # Dois registros são dois clubes: uni-los é resolução de identidade,
        # uma etapa explícita — nunca um efeito colateral do nome.
        assert a.id != b.id

    def test_renomear_nao_muda_a_identidade(self) -> None:
        """O Red Bull Bragantino continua sendo o mesmo clube do Bragantino,
        com o mesmo histórico."""
        antes = Team.register(canonical_name="Bragantino", country="BR")
        depois = antes.rename("Red Bull Bragantino")
        assert depois.id == antes.id
        assert depois.canonical_name == "Red Bull Bragantino"

    def test_desativar_nao_apaga(self) -> None:
        """Remover a entidade orfanaria toda partida que o clube jogou."""
        time = Team.register(canonical_name="Clube X", country="BR").deactivate()
        assert not time.active
        assert time.canonical_name == "Clube X"

    def test_nome_de_jogador_tambem_nao_vira_identidade(self) -> None:
        """Homônimos são comuns no futebol; derivar do nome fundiria
        carreiras."""
        assert not hasattr(Player, "derive")
        a = Player.register(canonical_name="Rodrigo Silva")
        b = Player.register(canonical_name="Rodrigo Silva")
        assert a.id != b.id


class TestValidacaoDeCampos:
    @pytest.mark.parametrize("pais", ["BRA", "b", "br", "12"])
    def test_country_precisa_ser_iso_alpha2_maiusculo(self, pais: str) -> None:
        with pytest.raises(ValueError, match="country"):
            Team.register(canonical_name="X", country=pais)

    def test_nome_vazio_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="canonical_name"):
            Team.register(canonical_name="   ", country="BR")

    def test_jogador_aceita_campos_de_resolucao(self) -> None:
        """Data de nascimento e nacionalidade distinguem homônimos melhor que
        qualquer heurística sobre o nome."""
        jogador = Player.register(
            canonical_name="Gabriel Barbosa",
            date_of_birth=date(1996, 8, 30),
            nationality="BR",
            primary_position=Position.ST,
        )
        assert jogador.date_of_birth == date(1996, 8, 30)
        assert jogador.primary_position is Position.ST


class TestVinculoTemporal:
    def test_o_historico_nao_e_reinterpretado_com_o_time_atual(self) -> None:
        """O DEFEITO QUE `PlayerTeamTenure` IMPEDE. Guardar o clube no
        jogador faria um gol de 2019 contar para o clube de 2026 — e a média
        móvel daquele clube ganharia jogos que ele não jogou."""
        santos, flamengo = TeamId.new(), TeamId.new()
        jogador = Player.register(canonical_name="Jogador")
        vinculos = (
            PlayerTeamTenure(
                player_id=jogador.id, team_id=santos, valid_from=T2019, valid_to=T2022
            ),
            PlayerTeamTenure(player_id=jogador.id, team_id=flamengo, valid_from=T2022),
        )
        assert team_at(vinculos, instant(datetime(2020, 6, 1, tzinfo=UTC))) == santos
        assert team_at(vinculos, T2026) == flamengo

    def test_sem_vinculo_conhecido_a_resposta_e_none(self) -> None:
        """`None` é a resposta honesta. Devolver o clube atual como
        aproximação é exatamente o defeito."""
        jogador = Player.register(canonical_name="Jogador")
        vinculos = (PlayerTeamTenure(player_id=jogador.id, team_id=TeamId.new(), valid_from=T2022),)
        assert team_at(vinculos, T2019) is None

    def test_vinculo_nao_termina_antes_de_comecar(self) -> None:
        with pytest.raises(ValueError, match="antes de começar"):
            PlayerTeamTenure(
                player_id=Player.register(canonical_name="X").id,
                team_id=TeamId.new(),
                valid_from=T2022,
                valid_to=T2019,
            )

    def test_vinculo_corrente_nao_tem_fim(self) -> None:
        vinculo = PlayerTeamTenure(
            player_id=Player.register(canonical_name="X").id,
            team_id=TeamId.new(),
            valid_from=T2022,
        )
        assert vinculo.is_current
        assert vinculo.covers(T2026)

    def test_fechar_um_vinculo_ja_fechado_e_recusado(self) -> None:
        vinculo = PlayerTeamTenure(
            player_id=Player.register(canonical_name="X").id,
            team_id=TeamId.new(),
            valid_from=T2019,
            valid_to=T2022,
        )
        with pytest.raises(ValueError, match="já encerrado"):
            vinculo.close(T2026)

    def test_sobreposicao_desempata_deterministicamente(self) -> None:
        """Empréstimo mal fechado produz vínculos simultâneos. A escolha é
        explícita porque ordenação implícita muda entre execuções."""
        jogador = Player.register(canonical_name="X")
        antigo, novo = TeamId.new(), TeamId.new()
        vinculos = (
            PlayerTeamTenure(player_id=jogador.id, team_id=antigo, valid_from=T2019),
            PlayerTeamTenure(player_id=jogador.id, team_id=novo, valid_from=T2022),
        )
        assert team_at(vinculos, T2026) == novo
        assert team_at(tuple(reversed(vinculos)), T2026) == novo


class TestPosicaoEFuncao:
    def test_posicao_e_funcao_nao_sao_sinonimos(self) -> None:
        """Dois volantes em `DM` podem ser um que fica e um que chega na
        área, e a diferença muda como a partida se comporta."""
        assert Position.DM.line is PositionLine.MIDFIELD
        segurando = TacticalRole.known(RoleCode.HOLDING_MIDFIELDER)
        chegando = TacticalRole.known(RoleCode.BOX_TO_BOX)
        assert segurando != chegando

    def test_ala_conta_como_defesa(self) -> None:
        """Escolha declarada: alas ocupam a linha defensiva quando a equipe
        não tem a bola — o momento em que a contagem importa."""
        assert Position.LWB.line is PositionLine.DEFENCE
        assert Position.RWB.line is PositionLine.DEFENCE

    def test_funcao_desconhecida_entra_como_descrita(self) -> None:
        """Extensível e validado: o que a fonte disse entra normalizado, e
        não como dicionário livre."""
        papel = TacticalRole.described("false nine")
        assert not papel.is_known
        assert papel.extra == "FALSE_NINE"

    def test_funcao_nao_pode_ser_codigo_e_descricao(self) -> None:
        with pytest.raises(ValueError, match="nunca ambos"):
            TacticalRole(code=RoleCode.WINGER, extra="WINGER")

    def test_funcao_precisa_ser_alguma_coisa(self) -> None:
        with pytest.raises(ValueError, match="nunca ambos"):
            TacticalRole()
