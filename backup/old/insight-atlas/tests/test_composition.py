"""Compor uma partida de várias fontes sem que uma apague a outra.

O defeito que isto fecha seria silencioso: `match_record` era escrita com
`document = EXCLUDED.document`, então a segunda fonte substituía o documento
inteiro. Cruzar o CSV público do Brasileirão (placar + mercado, sem chutes)
com uma raspagem (chutes, sem mercado) apagaria um dos dois blocos, e a linha
continuaria parecendo completa.
"""

from __future__ import annotations

import copy

import pytest

from atlas.intake.composition import (
    BLOCOS,
    PRECEDENCIA,
    Contribuicao,
    compor,
    perfil_de,
)
from atlas.intake.contract import example


def _core_e_mercado(source="football_data") -> Contribuicao:
    """O que o CSV público do Brasileirão traz: identidade, placar, mercado."""
    doc = copy.deepcopy(example())
    del doc["stats"]
    doc["provenance"]["source"] = source
    doc["provenance"]["profile"] = ["core", "market_close", "market_open"]
    return Contribuicao(source=source, profile=(), document=doc)


def _so_estatistica(source="espn") -> Contribuicao:
    """O que uma raspagem traria: identidade e chutes, sem mercado."""
    doc = copy.deepcopy(example())
    del doc["market"]
    doc["provenance"]["source"] = source
    doc["provenance"]["profile"] = ["core", "stats"]
    return Contribuicao(source=source, profile=(), document=doc)


class TestPerfil:
    def test_deduz_os_blocos_do_documento(self):
        assert perfil_de(example()) == BLOCOS

    def test_documento_sem_estatistica_nao_declara_stats(self):
        doc = copy.deepcopy(example())
        del doc["stats"]
        assert "stats" not in perfil_de(doc)
        assert "market_close" in perfil_de(doc)

    def test_mercado_so_de_fechamento(self):
        doc = copy.deepcopy(example())
        del doc["market"]["opening"]
        perfil = perfil_de(doc)
        assert "market_close" in perfil
        assert "market_open" not in perfil

    def test_o_perfil_e_deduzido_e_nao_declarado(self):
        """Um perfil digitado pode dizer `stats` sobre um documento sem
        estatística — e aí a composição acreditaria numa contribuição vazia
        e não procuraria a de verdade."""
        doc = copy.deepcopy(example())
        del doc["stats"]
        mentiroso = Contribuicao(source="x", profile=("core", "stats"), document=doc)
        assert "stats" not in perfil_de(mentiroso.document)


class TestComposicao:
    def test_duas_fontes_parciais_viram_uma_partida_completa(self):
        """O caso que motiva tudo: nenhuma fonte pública traz uma partida
        inteira, e as duas juntas trazem."""
        composicao = compor([_core_e_mercado(), _so_estatistica()])
        assert composicao is not None
        assert composicao.perfil == BLOCOS
        assert composicao.document["market"]["closing"]["home"] == 1.95
        assert composicao.document["stats"]["home"]["shots"] == 14

    def test_a_segunda_fonte_nao_apaga_o_bloco_da_primeira(self):
        """A regressão exata que o `document = EXCLUDED.document` causava."""
        composicao = compor([_so_estatistica(), _core_e_mercado()])
        assert composicao is not None
        assert "market" in composicao.document
        assert "stats" in composicao.document

    def test_a_ordem_de_chegada_nao_muda_o_resultado(self):
        """Composição por precedência, não por quem chegou primeiro — senão
        reingerir uma fonte mudaria a partida."""
        a = compor([_core_e_mercado(), _so_estatistica()])
        b = compor([_so_estatistica(), _core_e_mercado()])
        assert a is not None and b is not None
        assert a.document == b.document
        assert a.origem == b.origem

    def test_registra_de_onde_veio_cada_bloco(self):
        """'De onde veio o placar desta partida' passa a ter resposta sem
        reprocessar nada."""
        composicao = compor([_core_e_mercado(), _so_estatistica()])
        assert composicao is not None
        assert composicao.origem["core"] == "football_data"
        assert composicao.origem["market_close"] == "football_data"
        assert composicao.origem["stats"] == "espn"

    def test_sem_nucleo_nao_ha_partida(self):
        """Mercado sozinho não sabe de que jogo está falando."""
        doc = {"market": {"bookmaker": "bet365", "closing": {"home": 2.0}}}
        assert compor([Contribuicao("x", (), doc)]) is None

    def test_mercado_de_abertura_e_de_fechamento_de_fontes_diferentes(self):
        """As duas metades vivem sob a mesma chave `market`. Quem chega
        depois preenche só o que falta, em vez de trocar o objeto e levar a
        outra metade junto."""
        so_fecha = copy.deepcopy(example())
        del so_fecha["market"]["opening"]
        del so_fecha["stats"]
        so_abre = copy.deepcopy(example())
        del so_abre["market"]["closing"]
        del so_abre["stats"]

        composicao = compor(
            [
                Contribuicao("football_data", (), so_fecha),
                Contribuicao("espn", (), so_abre),
            ]
        )
        assert composicao is not None
        assert "closing" in composicao.document["market"]
        assert "opening" in composicao.document["market"]


class TestPrecedencia:
    def test_a_fonte_mais_confiavel_vence_o_bloco(self):
        melhor = copy.deepcopy(example())
        melhor["result"]["home_goals"] = 2
        pior = copy.deepcopy(example())
        pior["result"]["home_goals"] = 5

        composicao = compor(
            [
                Contribuicao("espn", (), pior),
                Contribuicao("football_data", (), melhor),
            ]
        )
        assert composicao is not None
        assert composicao.document["result"]["home_goals"] == 2
        assert composicao.origem["core"] == "football_data"

    def test_fonte_desconhecida_contribui_mas_nao_vence(self):
        """Ela ainda traz o bloco que ninguém trouxe — só não ganha de uma
        fonte declarada."""
        conhecida = _core_e_mercado("football_data")
        desconhecida = _so_estatistica("uma_fonte_nova")
        composicao = compor([desconhecida, conhecida])
        assert composicao is not None
        assert composicao.origem["core"] == "football_data"
        assert composicao.origem["stats"] == "uma_fonte_nova"

    def test_a_precedencia_e_declarada_e_estavel(self):
        """Ajustá-la por qual fonte acerta mais no corpus atual faria a
        resposta a 'de quem é este placar' mudar quando o corpus muda."""
        assert PRECEDENCIA.index("statsbomb") < PRECEDENCIA.index("football_data")
        assert PRECEDENCIA.index("football_data") < PRECEDENCIA.index("espn")
        assert PRECEDENCIA.index("espn") < PRECEDENCIA.index("wikipedia")


class TestConflito:
    def test_placares_diferentes_viram_conflito_registrado(self):
        """Duas fontes discordando de um placar significa que uma está
        errada. A precedência resolve; o desacordo fica."""
        a = copy.deepcopy(example())
        b = copy.deepcopy(example())
        b["result"]["away_goals"] = 4

        composicao = compor(
            [Contribuicao("football_data", (), a), Contribuicao("espn", (), b)]
        )
        assert composicao is not None
        assert len(composicao.conflitos) == 1
        conflito = composicao.conflitos[0]
        assert conflito.field == "result.away_goals"
        assert conflito.winning_source == "football_data"
        assert conflito.winning_value == 1
        assert conflito.losing_value == 4
        # E o vencedor é o que fica no documento.
        assert composicao.document["result"]["away_goals"] == 1

    def test_cotacoes_diferentes_NAO_sao_conflito(self):
        """Duas casas com preços diferentes não estão em desacordo — estão
        medindo coisas diferentes. Tratar isso como conflito encheria a
        tabela de ruído e esconderia o desacordo que importa."""
        a = copy.deepcopy(example())
        b = copy.deepcopy(example())
        b["market"]["closing"]["home"] = 2.60
        b["market"]["bookmaker"] = "pinnacle"

        composicao = compor(
            [Contribuicao("football_data", (), a), Contribuicao("espn", (), b)]
        )
        assert composicao is not None
        assert composicao.conflitos == []

    def test_horario_diferente_e_conflito(self):
        """O dia do pontapé entra na identidade da partida. Fontes que
        discordam dele são o caso que produziu 210 partidas duplicadas antes
        de o fuso do CSV ser convertido."""
        a = copy.deepcopy(example())
        b = copy.deepcopy(example())
        b["identity"]["kickoff_utc"] = "2023-08-12T18:00:00Z"

        composicao = compor(
            [Contribuicao("football_data", (), a), Contribuicao("espn", (), b)]
        )
        assert composicao is not None
        assert any(c.field == "identity.kickoff_utc" for c in composicao.conflitos)

    def test_sem_desacordo_nao_ha_conflito(self):
        composicao = compor([_core_e_mercado(), _so_estatistica()])
        assert composicao is not None
        assert composicao.conflitos == []


class TestContratoAindaVale:
    def test_a_composicao_completa_passa_no_contrato(self):
        """Compor não afrouxa nada: o documento resultante é validado como
        qualquer outro."""
        from atlas.intake.contract import validate

        composicao = compor([_core_e_mercado(), _so_estatistica()])
        assert composicao is not None
        veredito = validate(
            composicao.document, registry=frozenset({"arsenal", "chelsea"})
        )
        assert veredito.accepted, [str(e) for e in veredito.errors]

    def test_composicao_incompleta_e_valida_mas_nao_e_uma_partida(self):
        """Os dois níveis, no mesmo teste.

        A composição parcial passa no contrato — ela é uma contribuição
        honesta, declarando exatamente o que tem. O que ela NÃO é é uma
        partida: o perfil não fecha os quatro blocos, e é isso que impede o
        repositório de derivá-la para `match_record` e vetorizá-la com uma
        dimensão inventada no lugar de uma ausente.
        """
        from atlas.intake.contract import validate

        composicao = compor([_core_e_mercado()])
        assert composicao is not None
        veredito = validate(
            composicao.document, registry=frozenset({"arsenal", "chelsea"})
        )
        assert veredito.accepted, [str(e) for e in veredito.errors]
        assert composicao.perfil != BLOCOS
        assert "stats" not in composicao.perfil

    def test_o_perfil_da_procedencia_composta_e_o_da_composicao(self):
        """Senão o documento sai inconsistente consigo mesmo: traria a
        estatística que a outra fonte deu, declarando não trazê-la — e seria
        recusado pelo contrato que o gerou."""
        composicao = compor([_core_e_mercado(), _so_estatistica()])
        assert composicao is not None
        assert composicao.document["provenance"]["profile"] == list(BLOCOS)
