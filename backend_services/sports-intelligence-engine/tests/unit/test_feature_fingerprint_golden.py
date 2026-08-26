"""As impressões PREGADAS — o contrato dourado do PR-05.1 (§132 ao §135).

O QUE ESTE ARQUIVO FAZ, e por que ele parece frágil de propósito. Os outros
testes provam que a impressão é DETERMINÍSTICA: duas execuções do mesmo objeto
dão o mesmo hash. Isso não impede que a serialização mude — se o campo `unit`
deixar de entrar na forma canônica, os dois lados mudam juntos e o teste
continua verde.

Aqui os valores estão ESCRITOS. Qualquer mudança na serialização quebra este
arquivo, e quebrar é a função dele: a pessoa que mudou precisa decidir,
conscientemente, entre

    (a) a mudança é acidental          → desfaz
    (b) a mudança é intencional        → sobe a versão do contrato e atualiza
                                         estes valores no mesmo commit

O QUE UM HASH PREGADO PROTEGE NA PRÁTICA. Snapshots calculados hoje serão
comparados com snapshots calculados daqui a um ano. Se a serialização mudar
sem versão nova, os dois lados terão impressões diferentes para o MESMO
conteúdo — e a comparação vai dizer «estados diferentes» sobre estados
idênticos, sem nada explicar.

ELES NÃO SÃO ARBITRÁRIOS: cada um vem de um objeto construído pelos fixtures
deste repositório, e o teste mostra qual.
"""

from __future__ import annotations

from typing import Final

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.normalization import DEFAULT_V1_NORMALIZER
from sports_intelligence.domain.features.provenance import FeatureProvenance
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.values import ComputedFeature
from tests.support.feature_fixtures import (
    corte,
    definicao_de_teste,
    espaco_de_teste,
    origem,
)

#: `test_event_count@v1.0` com `window_minutes = 5`.
DEFINICAO_DOURADA: Final[str] = "cbfbcfaf3619de52bd1d069de446da99127bd83cb52080c664874c042eff437e"

#: O espaço `test-space@v1.0` com aquela única feature, `live_comparable`.
ESPACO_DOURADO: Final[str] = "559236b64aa7c9023fa22e2352f77fe55a8e2dc023f09070cc2eee994bda6ef7"

#: A política temporal padrão da V1.
POLITICA_DOURADA: Final[str] = "4fdb7c96c9980bf908281a1b8fd22796d033d2e0943fc2ae3dfc01f3fdd5e7fb"

#: `competition_median_iqr@v1.0`.
NORMALIZADOR_DOURADO: Final[str] = (
    "368321b372fa3b5bbe283d83e848e027846eddcd5969aac01a2c50aa3ca976c9"
)

#: O snapshot do corte de 63' com `test_event_count = 4`.
SNAPSHOT_DOURADO: Final[str] = "c3c0dfeaa2466866b6201c453f906f15942cacf4594a49ce94e7fa392f09a976"

_QUEBROU = (
    "a serialização canônica mudou. Se foi intencional, suba a versão do "
    "contrato e atualize este valor no MESMO commit; se não foi, desfaça — "
    "snapshots antigos deixariam de casar com os novos sem nada explicar"
)


def _definicao() -> FeatureDefinition:
    return definicao_de_teste(parameters={"window_minutes": 5})


class TestOContratoDourado:
    def test_a_impressao_da_definicao_esta_pregada(self) -> None:
        """§132."""
        assert _definicao().fingerprint == DEFINICAO_DOURADA, _QUEBROU

    def test_a_impressao_do_espaco_esta_pregada(self) -> None:
        """§133. Ela cobre a ORDEM: mudar a posição de uma feature quebra."""
        assert espaco_de_teste(_definicao()).fingerprint == ESPACO_DOURADO, _QUEBROU

    def test_a_impressao_da_politica_temporal_esta_pregada(self) -> None:
        """§134. Mudar a classificação de uma família quebra — e deve."""
        assert TemporalAvailabilityPolicy.default().fingerprint == POLITICA_DOURADA, _QUEBROU

    def test_a_impressao_do_normalizador_esta_pregada(self) -> None:
        """§135."""
        assert DEFAULT_V1_NORMALIZER.fingerprint == NORMALIZADOR_DOURADO, _QUEBROU

    def test_a_impressao_do_snapshot_esta_pregada(self) -> None:
        """§140. Ela depende das quatro identidades — corpus, espaço, política
        e corte —, então este valor cobre as quatro de uma vez."""
        definicao = _definicao()
        snapshot = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco_de_teste(definicao),
            source=origem(),
            policy=TemporalAvailabilityPolicy.default(),
            features=(
                ComputedFeature.available(
                    definition_key=definicao.key,
                    definition_fingerprint=definicao.fingerprint,
                    as_of=corte(),
                    value=4,
                    provenance=FeatureProvenance.none(),
                ),
            ),
        )
        assert snapshot.fingerprint == SNAPSHOT_DOURADO, _QUEBROU

    def test_todas_as_impressoes_tem_sessenta_e_quatro_hex(self) -> None:
        """Uma impressão truncada por acidente passaria pelos testes de
        determinismo — os dois lados truncariam igual."""
        for dourada in (
            DEFINICAO_DOURADA,
            ESPACO_DOURADO,
            POLITICA_DOURADA,
            NORMALIZADOR_DOURADO,
            SNAPSHOT_DOURADO,
        ):
            assert len(dourada) == 64
            assert set(dourada) <= set("0123456789abcdef")
