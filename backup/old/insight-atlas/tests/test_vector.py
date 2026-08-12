"""As duas propriedades que, se quebrarem, tornam o vetor inútil em silêncio.

A primeira é o vazamento: se as features de uma partida enxergarem o próprio
resultado, o vetor fica excelente em toda medida e não descreve nada. A
segunda é a escala: se o espaço não for o mesmo entre o corpus e a consulta,
a similaridade compara coisas em réguas diferentes — sem erro, com números
plausíveis.
"""

from __future__ import annotations

import copy

from atlas.vector.features import JANELA, NOMES, construir
from atlas.vector.space import ajustar


def _partida(
    home: str, away: str, dia: str, *, gols=(1, 0), chutes=(10, 5), fechamento=(2.0, 3.4, 4.0)
) -> dict:
    return {
        "__uid__": f"{home}-{away}-{dia}",
        "identity": {
            "competition": "premier_league",
            "season": "2023-2024",
            "home_club_id": home,
            "away_club_id": away,
            "kickoff_utc": f"2023-08-{dia}T15:00:00Z",
        },
        "result": {
            "status": "finished",
            "home_goals": gols[0], "away_goals": gols[1],
            "home_goals_halftime": 0, "away_goals_halftime": 0,
        },
        "market": {
            "bookmaker": "bet365",
            "opening": {"home": 2.10, "draw": 3.40, "away": 3.75},
            "closing": {"home": fechamento[0], "draw": fechamento[1], "away": fechamento[2]},
        },
        "stats": {
            lado: {
                "shots": chutes[i], "shots_on_target": chutes[i] // 2, "corners": 5,
                "fouls": 10, "yellow_cards": 1, "red_cards": 0,
            }
            for i, lado in enumerate(("home", "away"))
        },
        "provenance": {
            "source": "football_data", "source_match_id": f"x-{dia}",
            "collected_at": "2026-08-11T00:00:00Z", "url": "https://exemplo",
        },
    }


class TestVazamento:
    def test_a_primeira_partida_de_um_clube_nao_sabe_nada_dele(self):
        """Estreia: nenhuma janela tem conteúdo, e é isso que prova que o
        estado é lido ANTES de a partida ser aplicada."""
        linhas = list(construir([_partida("arsenal", "chelsea", "12")]))
        f = linhas[0].features
        assert f["home_attack"] == 0.0
        assert f["home_form"] == 0.0
        assert f["elo_delta"] == 0.0
        # Chutes na estreia são AUSENTES, não zero. Zero chutes por jogo é o
        # extremo inferior da escala, e gravá-lo faria toda estreia — e toda
        # partida de competição sem estatística — parecer um outlier idêntico
        # aos outros, por um motivo que não existe.
        assert "home_shots_rate" not in f
        assert "away_shots_rate" not in f

    def test_o_resultado_da_partida_nao_entra_nas_features_dela(self):
        """Trocar o placar de uma partida NÃO pode mudar as features dela —
        só as das seguintes. Se mudar, o vetor está se descrevendo com a
        resposta e toda medida de qualidade vira ilusão."""
        base = [
            _partida("arsenal", "chelsea", "12"),
            _partida("arsenal", "liverpool", "19"),
        ]
        alterado = copy.deepcopy(base)
        alterado[1]["result"]["home_goals"] = 9
        alterado[1]["stats"]["home"]["shots"] = 40

        antes = list(construir(base))
        depois = list(construir(alterado))
        assert antes[1].features == depois[1].features

    def test_mas_a_partida_seguinte_enxerga(self):
        base = [
            _partida("arsenal", "chelsea", "12"),
            _partida("arsenal", "liverpool", "19"),
            _partida("arsenal", "everton", "26"),
        ]
        alterado = copy.deepcopy(base)
        alterado[1]["result"]["home_goals"] = 9

        antes = list(construir(base))
        depois = list(construir(alterado))
        assert antes[2].features["home_attack"] != depois[2].features["home_attack"]

    def test_a_janela_movel_esquece(self):
        """Uma janela que não esquece é um acumulador, e a forma de um clube
        em agosto não descreve o clube em maio."""
        jogos = [
            _partida("arsenal", f"rival_{i}", f"{10 + i:02d}", gols=(5, 0))
            for i in range(JANELA + 2)
        ]
        jogos.append(_partida("arsenal", "chelsea", "28", gols=(0, 0)))
        linhas = list(construir(jogos))
        # Depois de JANELA vitórias por 5-0, o ataque satura no tamanho da
        # janela e não cresce indefinidamente.
        assert linhas[-1].features["home_attack"] == 5.0


class TestMercado:
    def test_probabilidades_implicitas_somam_um(self):
        linhas = list(construir([_partida("arsenal", "chelsea", "12")]))
        f = linhas[0].features
        soma = f["implied_home"] + f["implied_draw"] + f["implied_away"]
        assert abs(soma - 1.0) < 1e-9

    def test_a_margem_da_casa_sai_como_dimensao_propria(self):
        """Normalizar remove a margem das probabilidades; ela vira dimensão
        porque também diz algo — mercado raso cobra mais."""
        linhas = list(construir([_partida("arsenal", "chelsea", "12")]))
        assert linhas[0].features["overround"] > 0

    def test_line_movement_e_diferente_de_zero_quando_a_linha_anda(self):
        """A dimensão que estava fixa no valor neutro em TODOS os 7.261
        vetores antigos, porque uma cotação só não expressa movimento."""
        parada = _partida("arsenal", "chelsea", "12", fechamento=(2.10, 3.40, 3.75))
        andou = _partida("arsenal", "chelsea", "12", fechamento=(1.60, 3.90, 5.50))
        assert abs(list(construir([parada]))[0].features["line_movement"]) < 1e-9
        assert list(construir([andou]))[0].features["line_movement"] > 0.05


class TestEspaco:
    def test_padronizar_centra_o_corpus_em_zero(self):
        conjuntos = [{nome: float(i % 7) for nome in NOMES} for i in range(200)]
        espaco = ajustar(conjuntos)
        # A média do corpus, transformada, é o vetor nulo: é isso que tira
        # todos os vetores do mesmo octante positivo.
        media = {nome: espaco.medias[i] for i, nome in enumerate(espaco.dimensoes)}
        assert all(abs(v) < 1e-9 for v in espaco.transformar(media))

    def test_feature_ausente_entra_como_media_e_nao_como_zero(self):
        """Zero cru diria 'valor baixo' — uma afirmação que ninguém fez.
        A média padroniza para zero, que é 'não informa nada'."""
        conjuntos = [{nome: 10.0 + i for nome in NOMES} for i in range(50)]
        espaco = ajustar(conjuntos)
        completo = {nome: espaco.medias[i] for i, nome in enumerate(espaco.dimensoes)}
        parcial = dict(completo)
        del parcial[NOMES[0]]
        assert espaco.transformar(parcial) == espaco.transformar(completo)

    def test_dimensao_constante_nao_explode_na_divisao(self):
        conjuntos = [{**{n: float(i) for n in NOMES}, NOMES[0]: 3.0} for i in range(20)]
        espaco = ajustar(conjuntos)
        vetor = espaco.transformar(conjuntos[0])
        assert all(v == v for v in vetor)  # nenhum NaN

    def test_o_espaco_sobrevive_a_ida_e_volta(self):
        """Ele é gravado e relido para padronizar a consulta ao vivo com as
        MESMAS constantes; um round-trip que perde precisão põe consulta e
        corpus em réguas diferentes."""
        conjuntos = [{nome: float(i % 5) for nome in NOMES} for i in range(60)]
        espaco = ajustar(conjuntos)
        from atlas.vector.space import EspacoVetorial

        de_volta = EspacoVetorial.from_dict(espaco.as_dict())
        assert de_volta.transformar(conjuntos[0]) == espaco.transformar(conjuntos[0])


class TestContextoDeTabela:
    """Posição, o que está em jogo e distância — as dimensões do passo 4.

    POR QUE ELAS EXISTEM, medido: o mercado separa as partidas argentinas 38%
    menos que as inglesas, e a ordem desse desvio é exatamente a ordem do
    desempenho das lentes. Num campeonato equilibrado o que distingue duas
    partidas não é qualidade — é contexto, e o mercado precifica qualidade.
    """

    def test_a_posicao_e_lida_antes_da_partida(self):
        """A regra walk-forward, aplicada à classificação. Se a tabela
        avançasse antes do `yield`, a posição do clube já conteria o
        resultado do jogo que ela deveria descrever."""
        jogos = [
            _partida("arsenal", "chelsea", "12", gols=(3, 0)),
            _partida("arsenal", "everton", "13", gols=(3, 0)),
        ]
        linhas = list(construir(jogos))
        # Na estreia ninguém está na tabela: a dimensão é AUSENTE, não 0,5.
        # "Meio da tabela" é uma afirmação sobre um clube que não jogou.
        assert "table_position_home" not in linhas[0].features
        # No segundo jogo o Arsenal já lidera, com o resultado do PRIMEIRO.
        assert linhas[1].features["table_position_home"] == 0.0

    def test_a_distancia_e_simetrica_e_zero_na_mesma_cidade(self):
        from atlas.vector.contexto import distancia_km

        mapa = {
            "flamengo": (-22.91, -43.17),
            "fluminense": (-22.91, -43.17),
            "gremio": (-30.03, -51.23),
            "fortaleza": (-3.73, -38.52),
        }
        # Clássico carioca: viagem nenhuma, e zero é a resposta certa.
        assert distancia_km("flamengo", "fluminense", mapa) == 0.0
        # Grêmio–Fortaleza atravessa o país.
        km = distancia_km("gremio", "fortaleza", mapa)
        assert 3_000 < km < 4_000, km
        assert km == distancia_km("fortaleza", "gremio", mapa)

    def test_clube_sem_coordenada_omite_a_dimensao(self):
        """Ausente, e nunca zero: zero quer dizer "mesma cidade", que é uma
        afirmação sobre uma viagem que não foi medida."""
        from atlas.vector.contexto import distancia_km

        assert distancia_km("gremio", "desconhecido", {"gremio": (-30.0, -51.2)}) is None

    def test_competicao_sem_zonas_declaradas_nao_recebe_stakes(self):
        """O futebol argentino mudou de formato quase todo ano no período que
        temos — de 190 a 510 partidas por temporada. Inventar uma zona ali
        produziria um número descrevendo um campeonato que não existiu."""
        from atlas.vector.contexto import ZONAS, _Tabela, em_jogo

        tabela = _Tabela(total_de_partidas=380)
        for i in range(10):
            tabela.aplicar(f"c{i}", f"c{i + 10}", 2, 0)
        assert "argentina_liga_profesional" not in ZONAS
        assert em_jogo(tabela, "c0", "argentina_liga_profesional") is None
        assert em_jogo(tabela, "c0", "brasileirao") is not None

    def test_temporada_no_comeco_nao_tem_nada_em_jogo(self):
        """Um clube colado na fronteira na 3ª rodada ainda tem temporada
        inteira para corrigir; na 35ª, não tem."""
        from atlas.vector.contexto import _Tabela, em_jogo

        cedo = _Tabela(total_de_partidas=380)
        for i in range(10):
            cedo.aplicar(f"c{i}", f"c{i + 10}", 2, 0)
        tarde = _Tabela(total_de_partidas=380)
        for _ in range(36):
            for i in range(10):
                tarde.aplicar(f"c{i}", f"c{i + 10}", 2, 0)

        assert em_jogo(cedo, "c0", "brasileirao") < em_jogo(tarde, "c0", "brasileirao")

    def test_a_fracao_da_temporada_usa_o_tamanho_real(self):
        """Dividia por 380 fixo. As temporadas argentinas do corpus vão de
        190 a 510, então `season_progress` estava comprimida a um terço da
        escala lá — e é a dimensão de maior peso de `contexto`."""
        curta = [
            _partida("arsenal", "chelsea", "12", gols=(1, 0)),
            _partida("everton", "liverpool", "13", gols=(1, 0)),
            _partida("arsenal", "everton", "14", gols=(1, 0)),
            _partida("chelsea", "liverpool", "15", gols=(1, 0)),
        ]
        linhas = list(construir(curta))
        # Quatro partidas na temporada: a última está em 3/4 do caminho.
        assert linhas[-1].features["season_progress"] == 0.75
