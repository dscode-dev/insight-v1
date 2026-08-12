"""Every rule in atlas.match.v1, and the reason it exists.

Each test below names a way data actually got into the Atlas wrong. If one
of them ever has to be relaxed, the comment says what it was protecting.
"""

from __future__ import annotations

import copy

import pytest

from atlas.intake import contract
from atlas.intake.contract import example, example_parcial, validate

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
            "identity.kickoff_utc", "result.home_goals",
            "market.bookmaker", "stats.home", "stats.home.shots",
            "stats.away.corners", "provenance", "provenance.source",
            "provenance.collected_at", "provenance.profile", "provenance.timezone",
        ],
    )
    def test_rejeita_e_nomeia_o_campo(self, caminho):
        veredito = validate(_sem(caminho), registry=REGISTRO)
        assert not veredito.accepted
        assert any(e.field == caminho for e in veredito.errors), (
            f"esperava um erro em {caminho}, veio {[str(e) for e in veredito.errors]}"
        )

    @pytest.mark.parametrize(
        "caminho,bloco",
        [
            ("market", "market_close"),
            ("market.opening", "market_open"),
            ("market.closing", "market_close"),
            ("stats", "stats"),
        ],
    )
    def test_bloco_declarado_e_ausente_e_recusado(self, caminho, bloco):
        """Um bloco só é opcional quando NÃO é declarado. Declarado e ausente
        continua sendo a mesma recusa de sempre — só que o erro agora nomeia o
        bloco, que é o que o remetente precisa corrigir."""
        veredito = validate(_sem(caminho), registry=REGISTRO)
        assert not veredito.accepted
        assert any(bloco in e.reason for e in veredito.errors), (
            f"esperava o bloco {bloco} nomeado, veio {[str(e) for e in veredito.errors]}"
        )

    def test_reporta_todos_os_problemas_de_uma_vez(self):
        """Not the first one. Four problems reported one at a time is four
        round trips, and whoever is fixing starts guessing after the second."""
        quebrado = _sem("identity.season")
        del quebrado["stats"]["home"]["shots"]
        del quebrado["market"]["closing"]["home"]
        veredito = validate(quebrado, registry=REGISTRO)
        campos = {e.field for e in veredito.errors}
        assert {
            "identity.season", "stats.home.shots", "market.closing.home"
        } <= campos


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


class TestPerfilDeclarado:
    """A regra que destrava o cruzamento de fontes, e o que a segura.

    Nenhuma fonte pública gratuita traz os quatro blocos: o CSV do
    football-data traz placar e mercado e nenhum chute; uma raspagem traz
    chutes e nenhum mercado. Exigir tudo de cada linha tornava a composição
    inalcançável — as únicas fontes que podiam compor eram as que não
    precisavam. Então a contribuição declara o que traz, e precisa estar
    completa PARA AQUILO.
    """

    def test_contribuicao_parcial_declarada_e_aceita(self):
        csv_publico, raspagem = example_parcial()
        for parcial in (csv_publico, raspagem):
            veredito = validate(parcial, registry=REGISTRO)
            assert veredito.accepted, [str(e) for e in veredito.errors]

    def test_as_duas_parciais_falam_da_mesma_partida(self):
        """Se os uids divergissem, compor juntaria dois jogos diferentes —
        que é pior que não compor nada."""
        csv_publico, raspagem = example_parcial()
        a = validate(csv_publico, registry=REGISTRO)
        b = validate(raspagem, registry=REGISTRO)
        assert a.uid == b.uid

    def test_declarar_um_bloco_e_nao_traze_lo_e_recusado(self):
        """Ausência é afirmação, não esquecimento — a regra não mudou, só
        mudou de nível."""
        payload = _com()
        del payload["stats"]
        veredito = validate(payload, registry=REGISTRO)
        assert not veredito.accepted
        assert any("stats" in e.reason for e in veredito.errors)

    def test_trazer_um_bloco_sem_declarar_tambem_e_recusado(self):
        """A composição usa o perfil para saber o que ainda falta procurar.
        Um bloco que chega sem declaração entraria na partida sem entrar na
        contabilidade de quem trouxe o quê."""
        csv_publico, _ = example_parcial()
        csv_publico["stats"] = example()["stats"]
        veredito = validate(csv_publico, registry=REGISTRO)
        assert not veredito.accepted
        assert any("sem declará-lo" in e.reason for e in veredito.errors)

    def test_perfil_sem_core_e_recusado(self):
        """Mercado sozinho não sabe de que jogo está falando."""
        payload = _com(**{"provenance.profile": ["market_close"]})
        assert not validate(payload, registry=REGISTRO).accepted

    def test_perfil_vazio_e_recusado(self):
        assert not validate(
            _com(**{"provenance.profile": []}), registry=REGISTRO
        ).accepted

    @pytest.mark.parametrize("valor", [["core", "gols"], ["core", "Core"], ["core", ""]])
    def test_bloco_inventado_e_recusado(self, valor):
        veredito = validate(
            _com(**{"provenance.profile": valor}), registry=REGISTRO
        )
        assert not veredito.accepted

    def test_bloco_declarado_duas_vezes_e_recusado(self):
        """Duplicata é sinal de perfil montado à mão sem conferir, e passaria
        despercebida porque o conjunto ainda bateria com o documento."""
        payload = _com()
        payload["provenance"]["profile"] = ["core", "core", "market_close",
                                            "market_open", "stats"]
        assert not validate(payload, registry=REGISTRO).accepted

    def test_meio_mercado_e_um_bloco_legitimo(self):
        """`market_open` e `market_close` são separados porque fontes reais
        publicam só o fechamento — e a diferença entre os dois é o sinal de
        movimento de linha, que um instantâneo só não expressa."""
        payload = _com(
            **{
                "provenance.profile": [
                    "core", "result_halftime", "market_close", "market_spread",
                    "market_totals", "market_handicap", "stats",
                ]
            }
        )
        del payload["market"]["opening"]
        veredito = validate(payload, registry=REGISTRO)
        assert veredito.accepted, [str(e) for e in veredito.errors]

    def test_o_intervalo_e_um_bloco_e_nao_parte_do_nucleo(self):
        """Os arquivos sul-americanos não publicam o placar do intervalo, e
        ele não alimenta nenhuma das 25 dimensões. Exigi-lo no núcleo
        recusaria 11.828 partidas por um dado que ninguém usa."""
        payload = _com(
            **{
                "provenance.profile": [
                    "core", "market_close", "market_open", "market_spread",
                    "market_totals", "market_handicap", "stats",
                ]
            }
        )
        del payload["result"]["home_goals_halftime"]
        del payload["result"]["away_goals_halftime"]
        veredito = validate(payload, registry=REGISTRO)
        assert veredito.accepted, [str(e) for e in veredito.errors]

    def test_declarar_o_intervalo_e_nao_traze_lo_e_recusado(self):
        payload = _com()
        del payload["result"]["home_goals_halftime"]
        del payload["result"]["away_goals_halftime"]
        veredito = validate(payload, registry=REGISTRO)
        assert not veredito.accepted
        assert any("result_halftime" in e.reason for e in veredito.errors)

    def test_o_intervalo_pela_metade_e_recusado(self):
        """Um lado sem o outro não descreve nada, e passaria por 'tem o
        bloco' se só a presença de um campo fosse checada."""
        payload = _com()
        del payload["result"]["away_goals_halftime"]
        assert not validate(payload, registry=REGISTRO).accepted


class TestFusoDeclarado:
    """O defeito que colocou 210 partidas no dia errado.

    football-data.co.uk publica em hora do Reino Unido e não escreve o fuso
    em lugar nenhum do arquivo. Lidas como UTC, 210 de 1.785 partidas
    brasileiras caíam no dia de calendário seguinte — e o dia entra na
    identidade, então cada uma teria virado uma partida fantasma em vez de se
    juntar à que já existia.
    """

    @pytest.mark.parametrize(
        "fuso", ["America/Sao_Paulo", "Europe/London", "UTC", "America/Argentina/Buenos_Aires"]
    )
    def test_fuso_iana_valido(self, fuso):
        veredito = validate(_com(**{"provenance.timezone": fuso}), registry=REGISTRO)
        assert veredito.accepted, [str(e) for e in veredito.errors]

    @pytest.mark.parametrize(
        "fuso",
        [
            "BRT",              # abreviação ambígua: existem duas "BST"
            "GMT-3",            # sinal invertido em relação ao esperado
            "-03:00",           # deslocamento não é fuso: não sabe de horário de verão
            "Sao_Paulo",
            "America/Nao_Existe",
            "",
        ],
    )
    def test_fuso_invalido_e_recusado(self, fuso):
        veredito = validate(_com(**{"provenance.timezone": fuso}), registry=REGISTRO)
        assert not veredito.accepted

    def test_o_fuso_nao_tem_padrao(self):
        """Um padrão silencioso é exatamente como o defeito entrou: ninguém
        declarou nada e o leitor supôs UTC."""
        assert not validate(_sem("provenance.timezone"), registry=REGISTRO).accepted


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


class TestDispersaoDoMercado:
    """A média do mercado e o melhor preço, e a régua diferente de cada um.

    ERRO COMETIDO E MEDIDO: a primeira versão exigia do `best` a mesma soma
    de probabilidades implícitas de um livro de casa única (1,00 a 1,40) — e
    recusou 7.395 linhas boas. O melhor preço de cada saída vem de casas
    diferentes; ele soma abaixo de 1,0 sempre que há arbitragem entre elas, o
    que acontece em 47,3% das 15.627 partidas do corpus.
    """

    def _com_spread(self, consensus: dict, best: dict) -> dict:
        payload = _com()
        payload["market"]["spread"] = {"consensus": consensus, "best": best}
        return payload

    def test_melhor_preco_abaixo_de_um_e_normal(self):
        """Arbitragem entre casas. Quase metade do corpus está aqui."""
        veredito = validate(
            self._com_spread(
                {"home": 1.98, "draw": 3.55, "away": 3.90},
                {"home": 2.20, "draw": 3.90, "away": 4.30},  # soma ~0,96
            ),
            registry=REGISTRO,
        )
        assert veredito.accepted, [str(e) for e in veredito.errors]

    def test_arbitragem_grande_demais_e_coluna_mal_lida(self):
        """0,311 foi o mínimo observado no arquivo — uma arbitragem de 69%
        não existe em mercado líquido."""
        veredito = validate(
            self._com_spread(
                {"home": 1.98, "draw": 3.55, "away": 3.90},
                {"home": 6.00, "draw": 12.0, "away": 14.0},
            ),
            registry=REGISTRO,
        )
        assert not veredito.accepted

    def test_melhor_preco_pior_que_a_media_e_coluna_trocada(self):
        """Max é sempre >= Avg em cada saída, por definição. Se não for, as
        colunas vieram invertidas — e a dispersão sairia NEGATIVA sem nada
        denunciar."""
        # Os dois lados passam nas próprias faixas — o consenso soma 1,066 e
        # o "melhor" soma 1,113. O que os recusa é a relação entre eles, que
        # é justamente a regra que pega a inversão.
        veredito = validate(
            self._com_spread(
                {"home": 1.98, "draw": 3.55, "away": 3.90},
                {"home": 1.90, "draw": 3.40, "away": 3.80},
            ),
            registry=REGISTRO,
        )
        assert not veredito.accepted
        assert any("trocadas" in e.reason for e in veredito.errors)

    def test_o_consenso_continua_sendo_um_livro_de_casa(self):
        """`Avg` é a média de livros reais e tem a margem de um: 0% do corpus
        fica abaixo de 1,0. A regra de casa única vale para ele."""
        veredito = validate(
            self._com_spread(
                {"home": 2.20, "draw": 3.90, "away": 4.30},  # soma ~0,96
                {"home": 2.30, "draw": 4.00, "away": 4.40},
            ),
            registry=REGISTRO,
        )
        assert not veredito.accepted


class TestTotaisEHandicap:
    def test_a_linha_do_total_e_lida_e_nao_suposta(self):
        payload = _com()
        payload["market"]["totals"]["line"] = 3.5
        assert validate(payload, registry=REGISTRO).accepted

    def test_over_e_under_precisam_formar_um_mercado(self):
        payload = _com()
        payload["market"]["totals"] = {"line": 2.5, "over": 5.0, "under": 5.0}
        assert not validate(payload, registry=REGISTRO).accepted

    def test_handicap_zero_e_uma_linha_legitima(self):
        """Jogo equilibrado. Tratar 0 como ausente jogaria fora exatamente as
        partidas mais parelhas."""
        payload = _com()
        payload["market"]["handicap"] = {"line": 0.0, "home": 1.95, "away": 1.95}
        assert validate(payload, registry=REGISTRO).accepted

    def test_handicap_negativo_e_positivo_sao_os_dois_validos(self):
        """O sinal aponta para o MANDANTE: negativo é mandante favorito."""
        for linha in (-1.5, -0.25, 0.75, 2.0):
            payload = _com()
            payload["market"]["handicap"]["line"] = linha
            assert validate(payload, registry=REGISTRO).accepted, linha
