"""A regra de identidade: o que faz dois registros serem a mesma partida.

O bug que ela fecha ficou invisível por meses. `atlas.intelligence.corpus`
chaveava a partida por (competição, temporada, mandante, visitante, dia)
enquanto `atlas.strength.lake` continuava chaveando pelo `external_id` da
fonte. Os dois rodavam, nenhum falhava, e Elo, confronto direto e tabela
dobravam ou triplicavam 1.554 partidas.

OS DOIS LEITORES DO LAKE SAÍRAM na limpeza (passo 7): a partida agora entra
por `atlas.match.v1` e o uid é derivado uma vez, na ingestão. A regra
sobreviveu a eles porque é ela que faz o reenvio do mesmo jogo virar
atualização em vez de duplicata — e o teste que comparava os dois leitores
virou o teste de que a regra em si não muda de resposta.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.match_identity import match_uid, match_uid_from


class TestRegra:
    def test_a_mesma_partida_da_o_mesmo_uid(self):
        assert match_uid(
            "premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12"
        ) == match_uid(
            "premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12"
        )

    def test_o_relogio_nao_muda_a_partida(self):
        """Football-Data escreve 00:00, openfootball os 19:30 reais. Mesmo
        jogo — e é por isso que o dia, e não o instante, entra na chave."""
        meia_noite = datetime(2023, 8, 12, 0, 0, tzinfo=timezone.utc)
        tarde = datetime(2023, 8, 12, 19, 30, tzinfo=timezone.utc)
        assert match_uid_from(
            "premier_league", "2023-2024", "arsenal", "chelsea", meia_noite
        ) == match_uid_from(
            "premier_league", "2023-2024", "arsenal", "chelsea", tarde
        )

    def test_o_dia_muda(self):
        """Um time da Champions pode receber o mesmo adversário na fase de
        grupos e de novo na semifinal. Sem a data, dois jogos viram um."""
        assert match_uid(
            "champions_league", "2023-2024", "a", "b", "2023-09-19"
        ) != match_uid("champions_league", "2023-2024", "a", "b", "2024-05-01")

    def test_mandante_e_visitante_nao_sao_intercambiaveis(self):
        assert match_uid(
            "premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12"
        ) != match_uid(
            "premier_league", "2023-2024", "chelsea", "arsenal", "2023-08-12"
        )

    def test_a_competicao_e_a_temporada_fazem_parte_da_identidade(self):
        base = ("arsenal", "chelsea", "2023-08-12")
        assert match_uid("premier_league", "2023-2024", *base) != match_uid(
            "champions_league", "2023-2024", *base
        )
        assert match_uid("premier_league", "2023-2024", *base) != match_uid(
            "premier_league", "2024-2025", *base
        )


class TestEstabilidade:
    def test_o_uid_e_estavel_entre_execucoes(self):
        """O uid é a chave primária de `atlas.match_record` e de
        `atlas.match_vector`. Mudar a forma de calculá-lo re-chaveia toda
        partida já ingerida e órfã todo vetor — este valor fixo é o que
        transforma essa mudança em um teste vermelho em vez de uma migração
        silenciosa."""
        assert (
            match_uid("premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12")
            == "97931c3b-32ce-54cc-bcfe-8f89d124919b"
        )
