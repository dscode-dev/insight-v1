"""A sonda que liga a partida ao vivo à memória histórica.

O que ela devolve hoje é None, sempre — e isso é o assunto destes testes, não
uma lacuna deles. A versão anterior devolvia vizinhos casando o estado EM JOGO
do tick (pressão, momento, densidade de sinal) contra um corpus que descreve o
PRÉ-JOGO, tirados de uma tabela com 14 dimensões constantes. O que se trava
aqui é que ela parou de fazer isso, e que o motivo de não devolver nada é
nomeado em vez de silencioso.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas.trends.models import TrendInputs
from atlas.trends.similarity_probe import (
    OnlineSimilarityProbe,
    _features_conhecidas,
    identidade_de,
)


def _tick(**contexto) -> TrendInputs:
    return TrendInputs(canonical_match_id=uuid4(), context=contexto or None)


class TestIdentidade:
    def test_reconhece_a_identidade_completa(self):
        identidade = identidade_de(
            _tick(
                competition="premier_league",
                season="2024-2025",
                home_club_id="arsenal",
                away_club_id="chelsea",
            )
        )
        assert identidade == {
            "competition": "premier_league",
            "season": "2024-2025",
            "home_club_id": "arsenal",
            "away_club_id": "chelsea",
        }

    def test_aceita_grafias_alternativas(self):
        """O caminho canônico ainda não fixou os nomes; listar as plausíveis
        é melhor que exigir uma que talvez nunca chegue."""
        identidade = identidade_de(
            _tick(
                competition_key="la_liga",
                season="2024",
                home_team="barcelona",
                away_team="real_madrid",
            )
        )
        assert identidade is not None
        assert identidade["competition"] == "la_liga"
        assert identidade["home_club_id"] == "barcelona"

    @pytest.mark.parametrize(
        "faltando", ["competition", "season", "home_club_id", "away_club_id"]
    )
    def test_identidade_parcial_e_recusada(self, faltando):
        """Um vizinho encontrado a partir de identidade parcial descreve
        OUTRA partida. Preencher o que falta com o que sobrou foi exatamente
        como a versão anterior chegou a casar estado em jogo com pré-jogo."""
        completo = {
            "competition": "premier_league",
            "season": "2024-2025",
            "home_club_id": "arsenal",
            "away_club_id": "chelsea",
        }
        del completo[faltando]
        assert identidade_de(_tick(**completo)) is None

    def test_tick_sem_contexto_nenhum(self):
        assert identidade_de(TrendInputs(canonical_match_id=uuid4())) is None


@pytest.mark.asyncio
class TestSonda:
    async def test_sem_identidade_devolve_nada(self):
        """E é o estado de hoje: o contexto do tick não carrega competição,
        temporada nem clubes."""
        assert await OnlineSimilarityProbe().probe(_tick()) is None

    async def test_sem_servico_de_consulta_fica_inerte(self):
        """O serviço sobe mesmo sem memória vetorial construída — a sonda
        fica inerte em vez de derrubar o boot."""
        sonda = OnlineSimilarityProbe()
        assert (
            await sonda.probe(
                _tick(
                    competition="premier_league",
                    season="2024-2025",
                    home_club_id="arsenal",
                    away_club_id="chelsea",
                )
            )
            is None
        )

    async def test_com_identidade_e_servico_consulta_o_espaco_novo(self):
        """A sonda passa a lente `resultado` sobre `atlas.match_vector` — a
        MESMA consulta que a tela do console e o fluxo de produção usam."""
        vistas: list = []

        class _ValidacoesFalsas:
            async def para(self, lente, competicao):
                return None

        class _ServicoFalso:
            # A sonda busca a taxa base da competição para o detector poder
            # julgar concordância. Sem ela, o portão cai no padrão declarado.
            validacoes = _ValidacoesFalsas()

            async def vizinhos(self, consulta):
                vistas.append(consulta)
                return [], object(), 0.0

        sonda = OnlineSimilarityProbe(_ServicoFalso())
        await sonda.probe(
            _tick(
                competition="premier_league",
                season="2024-2025",
                home_club_id="arsenal",
                away_club_id="chelsea",
            )
        )
        assert len(vistas) == 1
        assert vistas[0].categoria == "resultado"
        assert vistas[0].home_club_id == "arsenal"

    async def test_nao_toca_mais_a_memoria_vetorial_antiga(self):
        """A sonda era o último leitor de `atlas.atlas_vector_memory` fora do
        pacote que a define. Ela consulta `atlas.vector.service`, que lê
        `atlas.match_vector` — e é isso que liberou a tabela para ser
        apagada."""
        import inspect

        from atlas.trends import similarity_probe

        corpo = inspect.getsource(similarity_probe).split('"""', 2)[2]
        assert "SimilarityRepository" not in corpo
        assert "atlas_vector_memory" not in corpo
        assert "atlas.vector.bridge" in corpo


class TestMercado:
    def test_extrai_probabilidades_implicitas_do_ultimo_tick_de_odds(self):
        """A interseção real entre o tick ao vivo e o espaço histórico é o
        mercado: cotação existe nos dois lados e é comparável."""

        class _Tick:
            home, draw, away = 2.0, 3.4, 4.0

        entrada = TrendInputs(canonical_match_id=uuid4(), odds_history=[_Tick()])
        features = _features_conhecidas(entrada)
        soma = (
            features["implied_home"] + features["implied_draw"] + features["implied_away"]
        )
        assert abs(soma - 1.0) < 1e-9
        assert features["overround"] > 0

    def test_sem_odds_nao_inventa_nada(self):
        assert _features_conhecidas(TrendInputs(canonical_match_id=uuid4())) == {}

    def test_cotacao_impossivel_e_ignorada(self):
        class _Tick:
            home, draw, away = 0.5, 3.4, 4.0

        entrada = TrendInputs(canonical_match_id=uuid4(), odds_history=[_Tick()])
        assert _features_conhecidas(entrada) == {}
