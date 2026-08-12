"""Zero e ausente: o defeito que o tipo torna impossível."""

from __future__ import annotations

import pytest

from sports_intelligence.domain.shared.feature_value import (
    FeatureMask,
    FeatureValue,
    MissingFeatureError,
    Unavailability,
)


class TestAusenteNaoViraZero:
    def test_ausente_nao_tem_conversao_para_float(self) -> None:
        """A AUSÊNCIA DE `__float__` É O CONTRATO. Com ela, `float(valor)`
        compilaria e devolveria zero — que é o defeito inteiro."""
        ausente = FeatureValue.absent(Unavailability.NOT_PUBLISHED)
        assert not hasattr(ausente, "__float__")
        with pytest.raises(TypeError):
            float(ausente)  # type: ignore[arg-type]

    def test_require_falha_dizendo_o_contexto_e_o_motivo(self) -> None:
        ausente = FeatureValue.absent(Unavailability.INSUFFICIENT_HISTORY)
        with pytest.raises(MissingFeatureError) as erro:
            ausente.require("home_shots_rate ao montar o vetor de estado")
        assert "home_shots_rate" in str(erro.value)
        assert erro.value.reason is Unavailability.INSUFFICIENT_HISTORY

    def test_or_default_exige_que_o_default_seja_escrito(self) -> None:
        """O default continua possível — o que ele não pode é ser invisível.
        Escrito, ele aparece no diff e alguém pode discordar."""
        assert FeatureValue.absent(Unavailability.NOT_PUBLISHED).or_default(0.5) == 0.5

    def test_zero_de_verdade_e_um_valor(self) -> None:
        """Zero chutes MEDIDOS é um fato; zero por ausência é uma invenção.
        Os dois precisam ser distinguíveis."""
        zero = FeatureValue.of(0.0)
        assert zero.is_available
        assert zero.require("teste") == 0.0
        assert zero.reason is None

    def test_map_propaga_a_ausencia(self) -> None:
        """Sem isto, toda transformação vira um if — e é no if esquecido que
        a ausência vira zero."""
        ausente = FeatureValue.absent(Unavailability.NOT_YET_OBSERVED)
        assert not ausente.map(lambda x: x * 2).is_available
        assert FeatureValue.of(3.0).map(lambda x: x * 2).require("t") == 6.0


class TestValoresImpossiveis:
    @pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")])
    def test_nao_finito_e_recusado(self, valor: float) -> None:
        """NaN e infinito envenenam toda média, desvio e distância a jusante,
        e o sintoma aparece longe da causa."""
        with pytest.raises(ValueError, match="finito"):
            FeatureValue.of(valor)

    def test_nao_pode_ser_valor_e_ausencia_ao_mesmo_tempo(self) -> None:
        with pytest.raises(ValueError, match="nunca ambos"):
            FeatureValue(_value=1.0, _reason=Unavailability.NOT_PUBLISHED)

    def test_nao_pode_ser_nenhum_dos_dois(self) -> None:
        with pytest.raises(ValueError, match="nunca ambos"):
            FeatureValue(_value=None, _reason=None)


class TestFeatureMask:
    def test_cobertura_e_a_fracao_presente(self) -> None:
        mascara = FeatureMask.from_values(
            {
                "a": FeatureValue.of(1.0),
                "b": FeatureValue.of(2.0),
                "c": FeatureValue.absent(Unavailability.NOT_PUBLISHED),
                "d": FeatureValue.absent(Unavailability.NOT_PUBLISHED),
            }
        )
        assert mascara.coverage == 0.5
        assert mascara.missing == frozenset({"c", "d"})

    def test_intersecao_e_o_unico_conjunto_comparavel(self) -> None:
        """Duas partidas com dimensões diferentes só se comparam honestamente
        sobre o que as duas têm."""
        a = FeatureMask(available=frozenset({"x", "y"}), total=frozenset({"x", "y", "z"}))
        b = FeatureMask(available=frozenset({"y", "z"}), total=frozenset({"x", "y", "z"}))
        assert a.intersect(b) == frozenset({"y"})

    def test_espaco_vazio_tem_cobertura_total(self) -> None:
        """Nada foi pedido, nada faltou."""
        assert FeatureMask(available=frozenset(), total=frozenset()).coverage == 1.0

    def test_nao_pode_declarar_disponivel_o_que_nao_existe(self) -> None:
        with pytest.raises(ValueError, match="não existem"):
            FeatureMask(available=frozenset({"fantasma"}), total=frozenset({"real"}))
