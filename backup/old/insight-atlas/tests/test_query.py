"""As cinco lentes, e a propriedade que as torna cinco e não uma.

Se duas categorias devolvem a mesma vizinhança para a mesma partida, elas não
são categorias — são a mesma consulta com textos diferentes, que é exatamente
o que havia antes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.vector.features import NOMES
from atlas.vector.lenses import LENTES, lente
from atlas.vector.query import (
    MINIMO_VIZINHOS,
    Consulta,
    Vizinho,
    _cosseno_com_pesos,
    descrever,
)
from atlas.vector.space import ajustar
from atlas.vector.validation import Medida


def _espaco():
    conjuntos = [
        {nome: float((i * 7 + j) % 11) for j, nome in enumerate(NOMES)}
        for i in range(120)
    ]
    return ajustar(conjuntos)


def _vizinho(uid: str, label: str, **features) -> Vizinho:
    base = {nome: 0.0 for nome in NOMES}
    base.update(features)
    return Vizinho(
        uid=uid,
        competition="premier_league",
        season="2023-2024",
        kickoff=datetime(2023, 5, 1, tzinfo=timezone.utc),
        home="arsenal",
        away="chelsea",
        label=label,
        similaridade=0.5,
        features=base,
    )


def _consulta(categoria: str, **features) -> Consulta:
    """Uma consulta informada, como a produção manda.

    As features entram TODAS por padrão, e não vazias: uma consulta que não
    informa nada tem `peso_util` zero, e a resposta correta para ela é
    recusar-se a descrever — o que tem teste próprio em
    `TestConsultaQueNaoInforma`. Usar isso como fixture geral testaria o
    caminho da recusa disfarçado de caminho normal.
    """
    base = {nome: 0.0 for nome in NOMES}
    base.update(features)
    return Consulta(
        categoria=categoria,
        competition="premier_league",
        season="2023-2024",
        home_club_id="arsenal",
        away_club_id="chelsea",
        as_of=datetime(2024, 1, 1, tzinfo=timezone.utc),
        features=base,
    )


def _medida(lente_: str, *, ganho: float, margem: float, avaliadas: int = 900):
    """Uma medida como a régua a produz, para a competição da fixture."""
    from datetime import datetime as _dt

    return Medida(
        lente=lente_,
        competicao="premier_league",
        concordancia=0.438 + ganho,
        taxa_base=0.438,
        ganho=ganho,
        margem=margem,
        avaliadas=avaliadas,
        corpus=15628,
        medida_em=_dt(2026, 8, 11, tzinfo=timezone.utc),
        versao_espaco="atlas.vector.v1",
    )


def _consulta_crua(categoria: str, **features) -> Consulta:
    """Só o que for passado — para exercitar a falta de dimensão."""
    return Consulta(
        categoria=categoria,
        competition="premier_league",
        season="2023-2024",
        home_club_id="arsenal",
        away_club_id="chelsea",
        as_of=datetime(2024, 1, 1, tzinfo=timezone.utc),
        features=features,
    )


class TestLentes:
    def test_sao_cinco(self):
        assert set(LENTES) == {
            "resultado", "gols", "desempenho_time", "confronto", "contexto"
        }

    def test_cada_lente_usa_um_conjunto_proprio(self):
        """Duas lentes com as mesmas dimensões e os mesmos pesos respondem
        igual — e aí não são duas."""
        assinaturas = {
            nome: tuple(sorted(l.pesos.items())) for nome, l in LENTES.items()
        }
        assert len(set(assinaturas.values())) == len(LENTES)

    def test_toda_dimensao_citada_existe_no_vetor(self):
        """Um peso sobre dimensão inexistente é ignorado em silêncio pelo
        cosseno — a lente pareceria olhar algo que não olha."""
        for l in LENTES.values():
            for nome in l.pesos:
                assert nome in NOMES, f"{l.categoria} cita {nome}, que não é dimensão"

    def test_confronto_filtra_pelo_par_e_e_a_unica(self):
        """Confronto direto que 'encontra' jogos de outros times por
        proximidade é a pergunta `resultado` com outro nome."""
        assert "mesmo_par" in lente("confronto").filtros
        assert [n for n, l in LENTES.items() if "mesmo_par" in l.filtros] == ["confronto"]

    def test_categoria_desconhecida_diz_quais_existem(self):
        with pytest.raises(ValueError) as erro:
            lente("chutometro")
        assert "resultado" in str(erro.value)


class TestSimilaridadePorLente:
    def test_a_mesma_partida_e_vizinha_diferente_em_lentes_diferentes(self):
        """A propriedade central, dita com precisão: mexer numa dimensão que
        pertence a uma lente e não à outra tem de mudar a similaridade da
        primeira e deixar a segunda EXATAMENTE igual.

        `expected_goals_total` está em `gols` e não em `resultado`.
        """
        espaco = _espaco()
        a = {nome: 0.0 for nome in NOMES}
        b = dict(a)
        b["expected_goals_total"] = -3.0

        assert _cosseno_com_pesos(a, b, lente("gols"), espaco) != pytest.approx(
            _cosseno_com_pesos(a, a, lente("gols"), espaco)
        )
        assert _cosseno_com_pesos(a, b, lente("resultado"), espaco) == pytest.approx(
            _cosseno_com_pesos(a, a, lente("resultado"), espaco)
        )

    def test_e_vale_no_sentido_inverso(self):
        """`line_movement` está em `resultado` e não em `desempenho_time`."""
        espaco = _espaco()
        a = {nome: 0.0 for nome in NOMES}
        b = dict(a)
        b["line_movement"] = 2.5

        assert _cosseno_com_pesos(a, b, lente("resultado"), espaco) != pytest.approx(
            _cosseno_com_pesos(a, a, lente("resultado"), espaco)
        )
        assert _cosseno_com_pesos(
            a, b, lente("desempenho_time"), espaco
        ) == pytest.approx(_cosseno_com_pesos(a, a, lente("desempenho_time"), espaco))

    def test_dimensao_fora_da_lente_nao_afeta_a_similaridade(self):
        espaco = _espaco()
        a = {nome: 0.0 for nome in NOMES}
        b = dict(a)
        # `season_progress` não entra na lente `gols`.
        b["season_progress"] = 99.0
        assert _cosseno_com_pesos(a, a, lente("gols"), espaco) == pytest.approx(
            _cosseno_com_pesos(a, b, lente("gols"), espaco)
        )


class TestResposta:
    def test_vizinhanca_rasa_nao_vira_descricao(self):
        """Média de três jogos apresentada como descrição é pior que
        silêncio: tem a mesma forma de uma resposta boa."""
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(MINIMO_VIZINHOS - 1)],
            _espaco(),
            0.0,
        )
        assert resposta["descricao"] is None
        assert resposta["incerteza"]["score"] == 1.0
        assert "mínimo" in resposta["incerteza"]["motivo"]

    def test_a_escala_viaja_junto_com_o_score(self):
        """Sem a mediana dos pares aleatórios, 0,78 é número sem régua — foi
        assim que 0,886 virou 'bom resultado'."""
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            -0.01,
        )
        escala = resposta["vizinhanca"]["escala"]
        assert escala["mediana_entre_pares_aleatorios"] == -0.01
        assert "sorteadas ao acaso" in escala["leitura"]

    def test_descreve_o_passado_e_diz_que_e_o_passado(self):
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN" if i % 2 else "DRAW") for i in range(20)],
            _espaco(),
            0.0,
        )
        desfechos = resposta["descricao"]["desfechos"]
        assert desfechos["HOME_WIN"]["partidas"] + desfechos["DRAW"]["partidas"] == 20
        assert "não o que vai acontecer" in resposta["descricao"]["nota"]

    def test_a_incerteza_nomeia_o_que_faltou(self):
        """Percentual solto não ajuda ninguém; o que falta, sim.

        Aqui a consulta informa quase tudo e deixa uma dimensão de fora — o
        caso em que a lente ainda descreve e precisa dizer sobre o quê não
        olhou. Faltar muito é outro caminho, em `TestConsultaQueNaoInforma`.
        """
        quase_tudo = {
            nome: 0.1 for nome in lente("resultado").pesos if nome != "elo_delta"
        }
        resposta = descrever(
            _consulta_crua("resultado", **quase_tudo),
            [_vizinho(f"m{i}", "DRAW") for i in range(25)],
            _espaco(),
            0.0,
        )
        ausentes = resposta["incerteza"]["dimensoes_ausentes"]
        assert "implied_home" not in ausentes
        assert "elo_delta" in ausentes
        assert resposta["incerteza"]["score"] > 0
        assert resposta["descricao"] is not None

    def test_lente_completa_e_vizinhanca_cheia_zeram_a_incerteza(self):
        cheia = {nome: 0.1 for nome in lente("resultado").pesos}
        resposta = descrever(
            _consulta("resultado", **cheia),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.0,
        )
        assert resposta["incerteza"]["score"] == 0.0
        assert resposta["incerteza"]["dimensoes_ausentes"] == []

    def test_gols_descreve_gols_e_nao_desfecho(self):
        resposta = descrever(
            _consulta("gols"),
            [_vizinho(f"m{i}", "HOME_WIN", expected_goals_total=2.0) for i in range(25)],
            _espaco(),
            0.0,
        )
        assert "media_de_gols_esperada_pelos_vizinhos" in resposta["descricao"]
        assert "desfechos" not in resposta["descricao"]

    def test_desempenho_separa_os_dois_lados(self):
        resposta = descrever(
            _consulta("desempenho_time"),
            [_vizinho(f"m{i}", "DRAW", home_form=2.0, away_form=1.0) for i in range(25)],
            _espaco(),
            0.0,
        )
        assert resposta["descricao"]["mandante"]["forma"] == 2.0
        assert resposta["descricao"]["visitante"]["forma"] == 1.0


class TestContratoDeConsulta:
    def test_exige_os_campos_de_identificacao(self):
        with pytest.raises(ValueError) as erro:
            Consulta.from_dict({"categoria": "resultado"})
        assert "competition" in str(erro.value)

    def test_as_of_precisa_de_fuso(self):
        """Sem fuso, o instante é lido no timezone do servidor — e ele é o
        corte que separa passado de futuro na consulta."""
        with pytest.raises(ValueError):
            Consulta.from_dict(
                {
                    "categoria": "resultado",
                    "competition": "premier_league",
                    "season": "2023-2024",
                    "home_club_id": "arsenal",
                    "away_club_id": "chelsea",
                    "as_of": "2024-01-01T00:00:00",
                }
            )

    def test_as_of_ausente_vira_agora(self):
        consulta = Consulta.from_dict(
            {
                "categoria": "resultado",
                "competition": "premier_league",
                "season": "2023-2024",
                "home_club_id": "arsenal",
                "away_club_id": "chelsea",
            }
        )
        assert consulta.as_of.tzinfo is not None


class TestConsultaQueNaoInforma:
    """Uma consulta sem dimensão não recebe uma descrição mais fraca.

    Medido contra a produção antes de existir este portão: uma consulta sem
    features nenhuma casava com similaridade EXATAMENTE ZERO contra tudo,
    devolvia as 25 partidas mais recentes como "as mais parecidas", e ainda
    assim renderizava a distribuição de desfechos com a validação medida ao
    lado. A resposta tinha a forma exata de uma boa.
    """

    def test_consulta_vazia_nao_descreve(self):
        resposta = descrever(
            _consulta_crua("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
        )
        assert resposta["descricao"] is None
        assert resposta["incerteza"]["score"] == 1.0
        assert "peso" in resposta["incerteza"]["motivo"]
        assert resposta["vizinhanca"]["peso_util"] == 0.0

    def test_o_peso_util_esta_sempre_na_resposta(self):
        """Inclusive quando é 1,0. Um campo que só aparece quando há problema
        ensina quem lê a não procurá-lo."""
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
        )
        assert resposta["vizinhanca"]["peso_util"] == 1.0
        assert resposta["vizinhanca"]["dimensoes_ausentes"] == []
        assert resposta["descricao"] is not None

    def test_partida_sem_estatistica_ainda_responde_as_cinco_lentes(self):
        """O caso do Brasileirão, que é o motivo da barra por competição.

        Sem estatística e sem abertura sobra 63,6% do peso no pior caso
        (`gols`) — acima do mínimo. Se este teste quebrar, a decisão de
        deixar essas 11.828 partidas entrarem deixou de se sustentar.
        """
        sem_stats = {
            nome: 0.0
            for nome in NOMES
            if nome
            not in {
                "home_shots_rate", "away_shots_rate",
                "home_accuracy", "away_accuracy",
                "home_corners_rate", "away_corners_rate",
                "home_discipline", "away_discipline",
                "line_movement",
            }
        }
        for categoria in ("resultado", "gols", "desempenho_time", "confronto", "contexto"):
            resposta = descrever(
                _consulta_crua(categoria, **sem_stats),
                [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
                _espaco(),
                0.03,
            )
            assert resposta["descricao"] is not None, (
                f"{categoria} deixou de responder com {resposta['vizinhanca']['peso_util']}"
                " do peso"
            )
            assert resposta["vizinhanca"]["peso_util"] >= 0.60


class TestValidacao:
    """A medida viaja na resposta, e agora é POR COMPETIÇÃO.

    Era um número por lente, escrito à mão em `lenses.py`. Sobre o corpus de
    15.628 partidas ele deixou de ser escrevível: `resultado` mede +10,9% na
    Europa e -4,8% no Brasileirão, e um número só mente sobre um dos dois.
    """

    def test_nenhuma_lente_carrega_medicao_propria(self):
        """A lente define a PERGUNTA; a competição define quanto ela vale.
        Um número na lente voltaria a valer para todos os campeonatos."""
        for l in LENTES.values():
            assert not hasattr(l, "validacao")

    def test_sem_medida_a_resposta_diz_que_nao_ha_medida(self):
        """E não omite o bloco: ausência seria lida como 'sem ressalvas'."""
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
        )
        validacao = resposta["validacao"]
        assert validacao["ganho"] is None
        assert validacao["conclusiva"] is False
        assert validacao["descreve_desfecho"] is False
        assert "nunca foi medida" in validacao["leitura"]
        # A descrição continua: a vizinhança é observável, só não há nada
        # apurado sobre ela descrever.
        assert resposta["descricao"] is not None

    def test_a_medida_da_competicao_chega_na_resposta(self):
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
            _medida("resultado", ganho=0.109, margem=0.056),
        )
        validacao = resposta["validacao"]
        assert validacao["competicao"] == "premier_league"
        assert validacao["conclusiva"] is True
        assert validacao["descreve_desfecho"] is True
        assert "premier_league" in validacao["leitura"]

    def test_lente_pior_que_a_base_nao_descreve_desfecho(self):
        """O caso de `gols` e `contexto` sobre o corpus atual. A régua já
        sabe que a lente descreve pior que o palpite trivial ali; servir a
        distribuição assim mesmo entregaria um número ruim com a forma de um
        bom. Os vizinhos ficam, a leitura de desfecho não."""
        resposta = descrever(
            _consulta("gols"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
            _medida("gols", ganho=-0.058, margem=0.055),
        )
        assert resposta["descricao"] is None
        assert resposta["incerteza"]["score"] == 1.0
        assert "PIOR" in resposta["incerteza"]["motivo"]
        # E a evidência continua: ela é observável e verdadeira.
        assert len(resposta["evidencia"]) == 8

    def test_nao_demonstrada_ainda_descreve_mas_avisa(self):
        """Dentro da margem não é o mesmo que pior que a base: não há nada
        contra a lente, só não há nada a favor."""
        resposta = descrever(
            _consulta("resultado"),
            [_vizinho(f"m{i}", "HOME_WIN") for i in range(25)],
            _espaco(),
            0.03,
            _medida("resultado", ganho=0.009, margem=0.056),
        )
        assert resposta["descricao"] is not None
        assert resposta["validacao"]["conclusiva"] is False
        assert "NÃO foi demonstrada" in resposta["validacao"]["leitura"]

    def test_confronto_pior_que_a_base_ainda_devolve_o_retrospecto(self):
        """Ela nunca descreveu desfecho — devolve o registro dos encontros.
        Reter isso por causa de uma medida de desfecho seria reter a resposta
        certa por causa da pergunta errada."""
        resposta = descrever(
            _consulta("confronto"),
            [_vizinho(f"m{i}", "HOME_WIN" if i % 3 else "DRAW") for i in range(9)],
            _espaco(),
            0.0,
            _medida("confronto", ganho=-0.064, margem=0.063),
        )
        assert resposta["descricao"] is not None
        assert "retrospecto" in resposta["descricao"]

    def test_confronto_devolve_retrospecto_e_nao_fracao_de_desfecho(self):
        """A forma da resposta é o que impede a leitura errada: sem `fracao`,
        não há número convidando a ser lido como probabilidade."""
        resposta = descrever(
            _consulta("confronto"),
            [_vizinho(f"m{i}", "HOME_WIN" if i % 3 else "DRAW") for i in range(9)],
            _espaco(),
            0.0,
        )
        descricao = resposta["descricao"]
        assert descricao["encontros"] == 9
        assert "retrospecto" in descricao
        assert "desfechos" not in descricao
        assert "NÃO é uma descrição" in descricao["nota"]
