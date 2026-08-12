"""A mesma partida, pelos dois caminhos, tem de ser a mesma partida.

O DEFEITO QUE ISTO FECHA. Existem duas regras de identidade no Atlas:

                  match_uid (corpus)        canonical_match_id (ao vivo)
    namespace     ...a71a5dee               6f1c2d34...
    competição    slug: premier_league      UUID
    clubes        club_id: arsenal          nome normalizado
    tempo         dia UTC                   hora arredondada
    temporada     presente                  ausente

Elas nunca podem produzir o mesmo valor, e não é bug: respondem perguntas
diferentes. `canonical_match_id` identifica uma partida AO VIVO entre
provedores que a chamam de nomes diferentes; `match_uid` identifica um
REGISTRO histórico entre fontes que a publicam com ids diferentes.

A consequência era concreta: a sonda ao vivo não tinha como achar a partida
no corpus, e por não ter passou a casar ESTADO EM JOGO contra vetores de
PRÉ-JOGO — a dimensão de pressão de mercado recebendo pressão em campo.

A ponte não é entre os ids, é PELOS CAMPOS. E é isto que estes testes travam.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.match_identity import match_uid_from
from atlas.vector.identidade_ao_vivo import (
    Falha,
    IdentidadeDaPartida,
    ResolvedorAoVivo,
    _normalizar,
)

KICKOFF = datetime(2024, 5, 12, 19, 30, tzinfo=timezone.utc)


class _SessaoFalsa:
    """Devolve a temporada que o corpus conteria para aquela data."""

    def __init__(self, temporada: str | None) -> None:
        self._temporada = temporada

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_args, **_kwargs):
        temporada = self._temporada

        class _Resultado:
            def first(self):
                return (temporada,) if temporada else None

        return _Resultado()


def _fabrica(temporada: str | None):
    def _criar():
        return _SessaoFalsa(temporada)

    return _criar


class TestAPonteFechaOCirculo:
    @pytest.mark.asyncio
    async def test_o_uid_do_vivo_e_o_uid_do_corpus(self):
        """O TESTE QUE É O PASSO INTEIRO.

        Uma partida que chega ao vivo e a mesma partida já gravada no corpus
        precisam produzir a MESMA chave. Se não produzirem, a sonda procura
        uma vizinha de si própria e nunca se reconhece.
        """
        resolvedor = ResolvedorAoVivo(_fabrica("2023-2024"))
        resolvedor._apelidos = {"arsenal": "arsenal", "chelsea": "chelsea"}

        identidade = await resolvedor.resolver(
            competition="premier_league",
            home_name="Arsenal",
            away_name="Chelsea",
            kickoff=KICKOFF,
        )
        assert isinstance(identidade, IdentidadeDaPartida)
        assert identidade.uid == match_uid_from(
            "premier_league", "2023-2024", "arsenal", "chelsea", KICKOFF
        )

    @pytest.mark.asyncio
    async def test_o_relogio_nao_separa_a_mesma_partida(self):
        """O corpus trunca no DIA. Duas leituras do mesmo jogo com horários
        diferentes — que é o normal entre provedores — continuam sendo uma."""
        resolvedor = ResolvedorAoVivo(_fabrica("2023-2024"))
        resolvedor._apelidos = {"arsenal": "arsenal", "chelsea": "chelsea"}

        cedo = await resolvedor.resolver(
            competition="premier_league", home_name="Arsenal",
            away_name="Chelsea", kickoff=KICKOFF.replace(hour=14),
        )
        tarde = await resolvedor.resolver(
            competition="premier_league", home_name="Arsenal",
            away_name="Chelsea", kickoff=KICKOFF.replace(hour=21),
        )
        assert cedo.uid == tarde.uid


class TestFalhaComNome:
    """Falha é um VALOR, não exceção: a ingestão do evento ao vivo não pode
    cair porque um provedor mandou um nome novo. E ela diz qual campo faltou,
    porque "a sonda não achou nada" não conserta nada."""

    @pytest.mark.asyncio
    async def test_clube_desconhecido_nao_vira_palpite(self):
        resolvedor = ResolvedorAoVivo(_fabrica("2023-2024"))
        resolvedor._apelidos = {"arsenal": "arsenal"}

        falha = await resolvedor.resolver(
            competition="premier_league", home_name="Arsenal",
            away_name="Clube Que Nao Existe", kickoff=KICKOFF,
        )
        assert isinstance(falha, Falha)
        assert falha.campo == "away_club_id"
        assert "Clube Que Nao Existe" in falha.motivo

    @pytest.mark.asyncio
    async def test_temporada_nao_encontrada_e_recusa_e_nao_chute(self):
        """Uma regra do tipo "julho a junho" acerta a Europa e erra o Brasil;
        "ano civil" faz o inverso. Não achando a janela no corpus, a resposta
        é dizer que não achou."""
        resolvedor = ResolvedorAoVivo(_fabrica(None))
        resolvedor._apelidos = {"arsenal": "arsenal", "chelsea": "chelsea"}

        falha = await resolvedor.resolver(
            competition="premier_league", home_name="Arsenal",
            away_name="Chelsea", kickoff=KICKOFF,
        )
        assert isinstance(falha, Falha)
        assert falha.campo == "season"

    @pytest.mark.asyncio
    async def test_sem_pontape_nao_ha_temporada_a_procurar(self):
        resolvedor = ResolvedorAoVivo(_fabrica("2023-2024"))
        falha = await resolvedor.resolver(
            competition="premier_league", home_name="Arsenal",
            away_name="Chelsea", kickoff=None,
        )
        assert isinstance(falha, Falha)
        assert falha.campo == "kickoff"


class TestNomes:
    def test_a_dobra_ignora_acento_e_pontuacao(self):
        assert _normalizar("Atlético Mineiro") == _normalizar("Atletico Mineiro")
        assert _normalizar("Newell's Old Boys") == _normalizar("Newells Old Boys")

    @pytest.mark.asyncio
    async def test_so_casamento_exato_e_nao_por_subconjunto(self):
        """SEM FALLBACK POR TOKENS, e isto é deliberado. No caminho offline
        ele fez `Olimpo Bahia Blanca` virar o Bahia de Salvador e `Arsenal
        Sarandi` virar o Arsenal de Londres. Ao vivo o erro seria pior: a
        partida seria descrita com o histórico de outro clube, em tempo real
        e sem ninguém conferindo depois."""
        resolvedor = ResolvedorAoVivo(_fabrica("2024"))
        resolvedor._apelidos = {"bahia": "bahia", "gremio": "gremio"}

        falha = await resolvedor.resolver(
            competition="brasileirao", home_name="Olimpo Bahia Blanca",
            away_name="Gremio", kickoff=KICKOFF,
        )
        assert isinstance(falha, Falha)
        assert falha.campo == "home_club_id"


class TestOCampoDePrimeiraClasse:
    def test_a_sonda_le_o_campo_antes_do_dicionario(self):
        """`TrendInputs.identity` é o contrato; as quatro grafias no `context`
        são a rampa dos produtores que ainda não migraram. Procurar por várias
        grafias é o mesmo que não ter contrato: quando alguém escolher uma
        quinta, nada quebra e a sonda fica inerte em silêncio."""
        from uuid import uuid4

        from atlas.trends.models import TrendInputs
        from atlas.trends.similarity_probe import identidade_de

        identidade = IdentidadeDaPartida(
            competition="premier_league",
            season="2023-2024",
            home_club_id="arsenal",
            away_club_id="chelsea",
            kickoff_utc=KICKOFF,
        )
        # O `context` diz outra coisa de propósito: o campo tem de vencer.
        inputs = TrendInputs(
            canonical_match_id=uuid4(),
            identity=identidade,
            context={"competition": "outra_liga", "season": "1999"},
        )
        achada = identidade_de(inputs)
        assert achada == {
            "competition": "premier_league",
            "season": "2023-2024",
            "home_club_id": "arsenal",
            "away_club_id": "chelsea",
        }

    def test_sem_o_campo_a_rampa_ainda_funciona(self):
        from uuid import uuid4

        from atlas.trends.models import TrendInputs
        from atlas.trends.similarity_probe import identidade_de

        inputs = TrendInputs(
            canonical_match_id=uuid4(),
            context={
                "competition": "brasileirao",
                "season": "2024",
                "home_club_id": "gremio",
                "away_club_id": "internacional",
            },
        )
        assert identidade_de(inputs)["competition"] == "brasileirao"

    def test_identidade_parcial_no_campo_nao_e_aceita(self):
        """Meia identidade encontra a partida errada, e a resposta parece
        boa. A rampa do `context` assume, e se ela também não tiver, a sonda
        diz o que faltou."""
        from uuid import uuid4

        from atlas.trends.models import TrendInputs
        from atlas.trends.similarity_probe import identidade_de

        class _Parcial:
            competition = "premier_league"
            season = None
            home_club_id = "arsenal"
            away_club_id = "chelsea"

        inputs = TrendInputs(canonical_match_id=uuid4(), identity=_Parcial())
        assert identidade_de(inputs) is None
