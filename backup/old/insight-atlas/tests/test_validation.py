"""A medida de uma lente numa competição, e as quatro respostas possíveis.

O que estes testes protegem: que "não medida", "não demonstrada" e "pior que
a taxa base" nunca sejam colapsados em um estado só. São três coisas
diferentes, e a rede social publica um post por lente — a diferença entre
elas é a diferença entre publicar uma descrição e publicar uma frase que a
régua já sabe ser pior que o palpite trivial.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.vector.validation import MINIMO_AVALIADAS, Medida, nao_medida


def _medida(**mudancas) -> Medida:
    base = dict(
        lente="resultado",
        competicao="premier_league",
        concordancia=0.557,
        taxa_base=0.433,
        ganho=0.124,
        margem=0.032,
        avaliadas=900,
        corpus=15628,
        medida_em=datetime(2026, 8, 11, tzinfo=timezone.utc),
        versao_espaco="atlas.vector.v1",
    )
    base.update(mudancas)
    return Medida(**base)  # type: ignore[arg-type]


class TestOsQuatroEstados:
    def test_conclusiva_a_favor(self):
        m = _medida()
        assert m.conclusiva
        assert m.descreve_desfecho
        assert not m.pior_que_a_base

    def test_dentro_da_margem_nao_e_a_favor_nem_contra(self):
        """O caso do Brasileirão em `resultado`: +0,9% com margem de 3,3%.
        Não há nada contra a lente ali — só não há nada a favor."""
        m = _medida(competicao="brasileirao", ganho=0.009, margem=0.033)
        assert not m.conclusiva
        assert not m.descreve_desfecho
        assert not m.pior_que_a_base

    def test_conclusiva_contra_e_um_estado_proprio(self):
        """`gols` no Brasileirão: -5,8% com margem de 3,2%. Tratar isso como
        'não demonstrada' esconderia que a régua tem uma resposta, e a
        resposta é que a lente descreve pior que chutar o mais comum."""
        m = _medida(lente="gols", competicao="brasileirao", ganho=-0.058, margem=0.032)
        assert m.conclusiva
        assert not m.descreve_desfecho
        assert m.pior_que_a_base

    def test_nao_medida_tem_a_mesma_forma_do_medido(self):
        """E não a AUSÊNCIA do bloco: quem consome leria a ausência como
        'sem ressalvas', que é o oposto do que ela significa."""
        bloco = nao_medida("resultado", "libertadores")
        medido = _medida().as_dict()
        assert set(bloco) <= set(medido)
        assert bloco["ganho"] is None
        assert bloco["conclusiva"] is False
        assert bloco["descreve_desfecho"] is False
        assert "nunca foi medida" in bloco["leitura"]
        assert "libertadores" in bloco["leitura"]


class TestAmostra:
    def test_amostra_pequena_nunca_e_conclusiva(self):
        """Por mais extremo que o ganho pareça. A margem já cresce com a
        amostra, e isto fecha a borda: 12 consultas com +40% é ruído."""
        m = _medida(avaliadas=12, ganho=0.40, margem=0.28)
        assert not m.suficiente
        assert not m.conclusiva
        assert not m.descreve_desfecho
        assert not m.pior_que_a_base

    def test_a_borda_do_minimo(self):
        assert not _medida(avaliadas=MINIMO_AVALIADAS - 1).conclusiva
        assert _medida(avaliadas=MINIMO_AVALIADAS).conclusiva


class TestLeitura:
    """A frase é GERADA dos números.

    Escrita à mão ela envelhece separada deles — os textos antigos ainda
    diziam "a lente mais forte das cinco" depois de a lente virar negativa
    sobre o corpus novo.
    """

    def test_diz_a_competicao_e_o_tamanho_da_amostra(self):
        leitura = _medida().leitura
        assert "premier_league" in leitura
        assert "900 consultas" in leitura

    def test_a_favor_nao_usa_a_palavra_abaixo(self):
        assert "ABAIXO" not in _medida().leitura

    def test_contra_diz_abaixo_e_retido(self):
        leitura = _medida(ganho=-0.058, margem=0.032).leitura
        assert "ABAIXO" in leitura
        assert "retida" in leitura

    def test_inconclusiva_diz_que_nao_foi_demonstrada(self):
        leitura = _medida(ganho=0.009, margem=0.033).leitura
        assert "NÃO foi demonstrada" in leitura
        assert "margem de erro" in leitura

    def test_a_leitura_nunca_promete_a_partida_consultada(self):
        """Descritivo, nunca preditivo — a regra de fundação do Atlas, e a
        frase da validação é o texto mais lido de toda a resposta."""
        for m in (
            _medida(),
            _medida(ganho=-0.058, margem=0.032),
            _medida(ganho=0.009, margem=0.033),
            _medida(avaliadas=12),
        ):
            leitura = m.leitura.lower()
            for proibida in ("vai ", "irá", "probabilidade de", "chance de", "prevê"):
                assert proibida not in leitura, f"{proibida!r} em {leitura!r}"


class TestSerializacao:
    def test_o_dicionario_carrega_o_que_a_resposta_precisa(self):
        d = _medida().as_dict()
        for chave in (
            "competicao", "ganho", "margem", "taxa_base", "avaliadas",
            "conclusiva", "descreve_desfecho", "pior_que_a_base", "leitura",
        ):
            assert chave in d, chave

    def test_a_versao_do_espaco_viaja_junto(self):
        """Reconstruir o vetor invalida a medida. Sem esta chave, um número
        de um espaço que não existe mais seria servido sem nada denunciando."""
        assert _medida().as_dict()["versao_espaco"] == "atlas.vector.v1"
