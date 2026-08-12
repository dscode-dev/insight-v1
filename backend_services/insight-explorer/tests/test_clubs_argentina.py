"""Os clubes argentinos, e os três pares que quase viraram um só.

Um clube ausente do registro é recusado por nome e aparece no relatório. Um
APELIDO ERRADO une duas histórias diferentes sem erro nenhum, e o número de
linhas continua fechando — foi assim que `Ath Madrid` virou `athletic_bilbao`
e que `Parana` quase virou `athletico_paranaense`.

Estes testes existem para que a próxima expansão do registro não desfaça o
cuidado desta.
"""

from __future__ import annotations

import pytest

from explorer.clubs import resolve_club


class TestParesQueParecemOMesmoClube:
    """Cidades diferentes, clubes diferentes, histórias diferentes."""

    def test_san_martin_sao_dois_clubes(self):
        san_juan = resolve_club("San Martin S.J.")
        tucuman = resolve_club("San Martin T.")
        assert san_juan == "san_martin_san_juan"
        assert tucuman == "san_martin_tucuman"
        assert san_juan != tucuman

    def test_independiente_nao_engole_o_independiente_rivadavia(self):
        """Avellaneda e Mendoza. O prefixo é o mesmo e é só isso."""
        avellaneda = resolve_club("Independiente")
        mendoza = resolve_club("Ind. Rivadavia")
        assert avellaneda == "independiente"
        assert mendoza == "independiente_rivadavia"
        assert avellaneda != mendoza

    def test_gimnasia_sao_dois_clubes(self):
        la_plata = resolve_club("Gimnasia L.P.")
        mendoza = resolve_club("Gimnasia Mendoza")
        assert la_plata == "gimnasia_la_plata"
        assert mendoza == "gimnasia_mendoza"
        assert la_plata != mendoza


class TestApelidosDoArquivo:
    """Os nomes exatos como o ARG.csv os escreve."""

    @pytest.mark.parametrize(
        "nome,esperado",
        [
            ("Argentinos Jrs", "argentinos_juniors"),
            ("Atl. Tucuman", "atletico_tucuman"),
            ("Newells Old Boys", "newells_old_boys"),
            ("Lanus", "lanus"),
            ("Union de Santa Fe", "union_santa_fe"),
            ("Banfield", "banfield"),
            ("Belgrano", "belgrano"),
            ("Sarmiento Junin", "sarmiento_junin"),
            ("Aldosivi", "aldosivi"),
            ("Platense", "platense"),
            ("Barracas Central", "barracas_central"),
            ("Atl. Rafaela", "atletico_rafaela"),
            ("Quilmes", "quilmes"),
            ("Instituto", "instituto"),
            ("Temperley", "temperley"),
            ("Dep. Riestra", "deportivo_riestra"),
            ("All Boys", "all_boys"),
            ("Nueva Chicago", "nueva_chicago"),
            ("Chacarita Juniors", "chacarita_juniors"),
            ("Crucero del Norte", "crucero_del_norte"),
        ],
    )
    def test_resolve(self, nome, esperado):
        assert resolve_club(nome) == esperado


class TestNaoInventaClube:
    def test_nome_desconhecido_continua_sem_resolver(self):
        """Resolver por aproximação é o que produz o apelido errado. Um nome
        que ninguém cadastrou tem de voltar None e aparecer no relatório."""
        assert resolve_club("Clube Que Nao Existe") is None

    def test_argentinos_nao_resolvem_para_clubes_brasileiros(self):
        """`Independiente` e `Instituto` são prefixos de nada brasileiro, mas
        a checagem custa uma linha e o erro custou uma investigação."""
        for nome in ("Independiente", "Instituto", "Platense", "Belgrano"):
            resolvido = resolve_club(nome)
            assert resolvido is not None
            assert not resolvido.startswith(("athletico", "atletico_go", "atletico_mg"))


class TestColisaoEntreContinentes:
    """Um clube não pode ser absorvido por outro de país diferente.

    COMO ISTO FOI DESCOBERTO, e vale como método: a dimensão de distância de
    viagem do passo 4 reportou o campeonato argentino com máximo de 11.524 km.
    A Argentina tem 3.700 km de extensão. O número impossível denunciou o que
    "100% dos clubes resolvidos" tinha escondido — 352 partidas do Arsenal de
    Sarandí somadas ao histórico do Arsenal de Londres, e 76 da Portuguesa de
    Desportos somadas às de um clube venezuelano.

    O RESOLVEDOR NÃO ESTAVA ERRADO POR DESCUIDO. Ele já recusa quando dois
    clubes explicam um nome igualmente bem — foi assim que o Espanyol parou de
    virar Barcelona. Mas {arsenal} é subconjunto de {arsenal, sarandi} e era o
    ÚNICO candidato: não havia ambiguidade a detectar. "Balompié" é decoração,
    "Sarandí" é o que distingue dois clubes, e nenhuma regra de tokens sabe a
    diferença. Só o cadastro sabe.
    """

    @pytest.mark.parametrize(
        "nome,esperado",
        [
            ("Arsenal Sarandi", "arsenal_sarandi"),
            ("Arsenal", "arsenal"),
            ("Portuguesa", "portuguesa"),
        ],
    )
    def test_os_dois_casos_encontrados(self, nome, esperado):
        assert resolve_club(nome) == esperado

    def test_o_arsenal_de_londres_nao_recebe_o_de_sarandi(self):
        assert resolve_club("Arsenal Sarandi") != resolve_club("Arsenal")

    def test_a_portuguesa_do_brasileirao_nao_e_a_da_venezuela(self):
        """`portuguesa` FICOU com a brasileira, e a venezuelana ganhou id
        próprio: `club_id` também é chave de busca, então enquanto a
        venezuelana fosse `portuguesa` ela venceria o nome nu por construção.
        E as 76 partidas já gravadas sob esse id são todas da brasileira."""
        import json
        from explorer.clubs import _registry_path

        registro = json.loads(_registry_path().read_text("utf-8"))
        por_id = {c["club_id"]: c for c in registro["clubs"]}
        assert por_id["portuguesa"]["country"] == "BR"
        assert por_id["portuguesa_acarigua"]["country"] == "VE"

    def test_o_olimpo_nao_vira_o_bahia(self):
        """O terceiro caso, e o que ensina o método. `Olimpo Bahia Blanca`
        contém {bahia} e virava o Esporte Clube Bahia, de Salvador — 3.791 km
        de "viagem" dentro da Argentina."""
        assert resolve_club("Olimpo Bahia Blanca") == "olimpo"
        assert resolve_club("Bahia") == "bahia"

    def test_nome_argentino_resolve_para_clube_argentino(self):
        """A VARREDURA CERTA, e ela é por país de ORIGEM DO ARQUIVO.

        A primeira versão deste teste procurava nomes sul-americanos
        resolvendo para fora de BR e AR — e por isso não viu o Olimpo virar
        Bahia: um clube argentino virando brasileiro passa nesse filtro. Um
        nome do arquivo argentino tem de virar clube argentino, ponto.
        """
        import json

        from explorer.clubs import _registry_path

        registro = json.loads(_registry_path().read_text("utf-8"))
        pais = {c["club_id"]: c.get("country") for c in registro["clubs"]}

        argentinos = [
            "Arsenal Sarandi", "Olimpo Bahia Blanca", "Independiente",
            "Gimnasia L.P.", "San Martin S.J.", "San Martin T.",
            "Ind. Rivadavia", "Instituto", "Platense", "Belgrano",
            "Central Cordoba", "Colon Santa Fe", "San Lorenzo", "Lanus",
        ]
        brasileiros = [
            "Portuguesa", "Atletico GO", "Parana", "Bahia", "Vitoria",
            "Sport Recife", "Ponte Preta", "Santos", "Palmeiras",
        ]
        erradas = []
        for nomes, esperado in ((argentinos, "AR"), (brasileiros, "BR")):
            for nome in nomes:
                resolvido = resolve_club(nome)
                if resolvido and pais.get(resolvido) != esperado:
                    erradas.append((nome, resolvido, pais.get(resolvido), esperado))
        assert not erradas, erradas
