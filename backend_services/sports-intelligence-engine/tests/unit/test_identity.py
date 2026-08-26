"""Identidade: o que separa uma coisa real da referência de um provedor."""

from __future__ import annotations

import uuid

import pytest

from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    ProviderId,
    ProviderRef,
    TeamId,
)


class TestDerivacaoDeterministica:
    def test_a_mesma_chave_da_o_mesmo_id(self) -> None:
        """É o que torna a reconstrução de um dataset idempotente:
        reprocessar a mesma entrada produz as mesmas linhas."""
        a = MatchId.derive("premier_league", "2024-2025", "arsenal", "chelsea")
        b = MatchId.derive("premier_league", "2024-2025", "arsenal", "chelsea")
        assert a == b

    def test_tipos_diferentes_nao_colidem_na_mesma_chave(self) -> None:
        """`liverpool` como time e como competição são coisas diferentes, e
        um namespace só faria as duas terem o mesmo id."""
        assert TeamId.derive("liverpool").value != CompetitionId.derive("liverpool").value

    def test_o_separador_nao_pode_estar_na_chave(self) -> None:
        """Sem esta regra, ("a|b", "c") e ("a", "b|c") derivam o mesmo id."""
        with pytest.raises(ValueError, match="separador"):
            MatchId.derive("premier|league", "2024")

    def test_parte_vazia_e_recusada(self) -> None:
        with pytest.raises(ValueError, match="vazia"):
            MatchId.derive("premier_league", "  ")

    def test_sem_partes_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="pelo menos uma parte"):
            MatchId.derive()


class TestIdsNovos:
    def test_dois_ids_novos_sao_diferentes(self) -> None:
        assert MatchId.new() != MatchId.new()

    def test_parse_recusa_texto_invalido(self) -> None:
        with pytest.raises(ValueError, match="MatchId"):
            MatchId.parse("nao-e-uuid")

    def test_construtor_recusa_o_que_nao_e_uuid(self) -> None:
        with pytest.raises(TypeError):
            MatchId("texto")  # type: ignore[arg-type]


class TestProviderRefNaoEIdentidade:
    def test_nao_existe_conversao_para_entity_id(self) -> None:
        """A AUSÊNCIA É O CONTRATO. Transformar a referência de um provedor
        na identidade do domínio é resolução de identidade — uma etapa com
        regras próprias e capaz de falhar. Um atalho a tornaria um cast."""
        ref = ProviderRef(provider=ProviderId("football_data"), external_id="fd-1")
        assert not hasattr(ref, "to_entity_id")
        assert not hasattr(ref, "as_match_id")

    def test_provedores_diferentes_com_o_mesmo_id_externo_sao_refs_diferentes(self) -> None:
        a = ProviderRef(provider=ProviderId("football_data"), external_id="1")
        b = ProviderRef(provider=ProviderId("statsbomb"), external_id="1")
        assert a != b

    def test_ref_sem_id_externo_e_recusada(self) -> None:
        with pytest.raises(ValueError, match="external_id"):
            ProviderRef(provider=ProviderId("espn"), external_id="   ")


class TestProviderId:
    @pytest.mark.parametrize("valor", ["football_data", "espn", "statsbomb"])
    def test_aceita_slug(self, valor: str) -> None:
        assert str(ProviderId(valor)) == valor

    @pytest.mark.parametrize("valor", ["", "Football-Data", "FOOTBALL", "1data", "a b"])
    def test_recusa_o_que_nao_e_slug(self, valor: str) -> None:
        with pytest.raises(ValueError, match="ProviderId"):
            ProviderId(valor)


class TestEstabilidadeDoNamespace:
    def test_o_id_derivado_nao_mudou(self) -> None:
        """TRAVA DE MIGRAÇÃO. Mudar o namespace re-chaveia tudo que já foi
        derivado; este teste faz essa mudança aparecer como quebra, e não
        como um conjunto de linhas novas indistinguível do anterior."""
        esperado = uuid.uuid5(MatchId.NAMESPACE, "premier_league|2024-2025|arsenal|chelsea")
        assert MatchId.derive("premier_league", "2024-2025", "arsenal", "chelsea").value == esperado
