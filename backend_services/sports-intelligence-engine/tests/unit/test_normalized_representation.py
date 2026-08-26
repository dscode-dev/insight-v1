"""A representação normalizada — travessia numérica, linha, identidade.

O QUE ESTES TESTES PROVAM, e cada item é uma forma de a representação mentir:

    a travessia          `float → Decimal` é a EXATA, e é declarada
    o não finito         `NaN` e infinito são RECUSADOS nas duas pontas
    a célula             número sob estado negativo é impossível
    o digesto            usa os BYTES do `float64`, e não texto
    a impressão          é ORDENADA e recusa a inversão
    a representação      só é comparável quando as quatro decisões fecham
    o contrato 1:1       uma versão com menos linhas que a crua não publica

O DIGESTO POR BYTES É O QUE MENOS PARECE IMPORTAR e é o que mais dura.
`repr(float)` já mudou entre versões de Python; a identidade de uma linha
publicada não pode depender da rotina de formatação do interpretador que a
gravou.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.normalized.bridge import (
    DecimalToFloatEncoding,
    FloatToDecimalBridge,
    NumericBridge,
    float64_bytes,
)
from sports_intelligence.domain.features.normalized.ordering import partition_of
from sports_intelligence.domain.features.normalized.plan import normalization_plan_v1
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
    NormalizedCell,
    NormalizedContentAccumulator,
    NormalizedFeatureRow,
    rebuild_normalized_content,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
    NormalizedHistoricalFeatureDataset,
    NormalizedHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

ATOR = Actor.system("test")
AGORA = instant(datetime(2025, 6, 1, tzinfo=UTC))
IMPRESSAO = "a" * 64
OUTRA = "b" * 64


def celula(chave: str, valor: float | None = 1.0) -> NormalizedCell:
    if valor is None:
        return NormalizedCell.unavailable(
            feature_key=chave,
            availability=NormalizationAvailability.SOURCE_VALUE_UNAVAILABLE,
            source_availability="SOURCE_UNAVAILABLE",
        )
    return NormalizedCell.available(feature_key=chave, value=valor, source_availability="AVAILABLE")


def linha(
    *,
    match: str = "m1",
    indice: int = 0,
    split: DatasetSplit = DatasetSplit.REFERENCE,
    valor: float | None = 1.0,
) -> NormalizedFeatureRow:
    return NormalizedFeatureRow(
        key=HistoricalFeatureSnapshotKey(match_key=match, grid_index=indice),
        split=split,
        competition="PREMIER",
        season="2024-25",
        grid_index=indice,
        grid_label=f"MIN_{indice:02d}",
        period="FIRST_HALF",
        minute=indice,
        source_row_digest="d" * 64,
        representation_fingerprint=IMPRESSAO,
        plan_fingerprint=IMPRESSAO,
        artifact_set_fingerprint=IMPRESSAO,
        competition_bundle_fingerprint=IMPRESSAO,
        cells=(celula("xg_home_5m", valor), celula("shots_home_5m", 3.0)),
    )


class TestATravessiaNumerica:
    """§39 ao §41 — a escolha é um CONTRATO, e não um detalhe."""

    def test_a_ponte_da_v1_e_a_exata(self) -> None:
        """`Decimal.from_float(0.1)` NÃO é `Decimal("0.1")`.

        AS DUAS SÃO DEFENSÁVEIS e é por isso que a escolha é declarada: duas
        execuções que escolhessem diferente produziriam medianas diferentes
        sobre os mesmos dados, e nada no artefato diria qual foi.
        """
        exata = FloatToDecimalBridge.IEEE754_EXACT.to_decimal(0.1)
        curta = FloatToDecimalBridge.SHORTEST_REPR.to_decimal(0.1)
        assert exata != curta
        assert curta == Decimal("0.1")
        assert str(exata).startswith("0.1000000000000000055511151231")

    @pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
    def test_a_entrada_recusa_nao_finito(self, valor: float) -> None:
        with pytest.raises(ValidationError, match="não finito"):
            FloatToDecimalBridge.IEEE754_EXACT.to_decimal(valor)

    def test_a_saida_recusa_o_que_nao_cabe_em_float64(self) -> None:
        """Um `Decimal` gigante vira `inf`, e um `inf` gravado seria lido como
        valor. O caso real é dividir por um IQR minúsculo."""
        with pytest.raises(ValidationError, match="não cabe"):
            DecimalToFloatEncoding.FLOAT64.to_float(Decimal("1e400"))

    def test_ausente_continua_ausente_nas_duas_pontas(self) -> None:
        ponte = NumericBridge()
        assert ponte.inbound(None) is None
        assert ponte.outbound(None) is None

    def test_a_ponte_declara_a_politica_na_forma_canonica(self) -> None:
        ponte = NumericBridge()
        assert ponte.input_bridge.as_canonical() == {
            "policy": "IEEE754_FLOAT64_EXACT_TO_DECIMAL_V1"
        }
        assert ponte.output_encoding.as_canonical()["policy"] == "NORMALIZED_FLOAT64_V1"
        assert set(ponte.as_canonical()) == {"input", "output"}


class TestOsBytesDoDigesto:
    """§70 — a identidade não depende da rotina de formatação."""

    def test_sao_os_oito_bytes_big_endian(self) -> None:
        assert float64_bytes(1.5) == struct.pack(">d", 1.5)

    def test_o_zero_negativo_e_o_zero_positivo_dao_os_mesmos_bytes(self) -> None:
        """`-0.0 == 0.0` é verdadeiro e os bytes são diferentes.

        DUAS EXECUÇÕES QUE CHEGAM A ZERO POR CAMINHOS DIFERENTES produziriam
        digestos diferentes para o mesmo número.
        """
        assert float64_bytes(-0.0) == float64_bytes(0.0)

    def test_nao_finito_e_recusado_tambem_no_digesto(self) -> None:
        with pytest.raises(ValidationError):
            float64_bytes(math.nan)


class TestACelula:
    """§64 — número sob estado negativo é impossível de construir."""

    def test_disponivel_sem_numero_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem valor"):
            NormalizedCell(feature_key="x", availability=NormalizationAvailability.AVAILABLE)

    def test_indisponivel_com_numero_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="ignorar"):
            NormalizedCell(
                feature_key="x",
                availability=NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE,
                value=1.0,
            )

    def test_os_cinco_estados_sao_o_catalogo_fechado(self) -> None:
        assert {e.name for e in NormalizationAvailability} == {
            "AVAILABLE",
            "SOURCE_VALUE_UNAVAILABLE",
            "ARTIFACT_INSUFFICIENT_SAMPLES",
            "ARTIFACT_DEGENERATE_SCALE",
            "ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION",
        }

    def test_a_disponibilidade_de_origem_viaja_junto(self) -> None:
        """§62 — sem ela, «não havia valor» e «não havia escala» são o mesmo."""
        sem_escala = NormalizedCell.unavailable(
            feature_key="xg_home_5m",
            availability=NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE,
            source_availability="AVAILABLE",
        )
        assert sem_escala.source_availability == "AVAILABLE"
        assert not sem_escala.availability.is_available


class TestALinha:
    def test_o_digesto_e_estavel_e_memoizado(self) -> None:
        uma = linha()
        assert uma.digest == uma.digest
        assert uma.digest == linha().digest

    def test_um_valor_diferente_muda_o_digesto(self) -> None:
        assert linha(valor=1.0).digest != linha(valor=1.0000000000000002).digest

    def test_um_eixo_repetido_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="repetido"):
            NormalizedFeatureRow(
                key=HistoricalFeatureSnapshotKey(match_key="m1", grid_index=0),
                split=DatasetSplit.REFERENCE,
                competition="PREMIER",
                season="2024-25",
                grid_index=0,
                grid_label="MIN_00",
                period="PRE_MATCH",
                minute=0,
                source_row_digest="d" * 64,
                representation_fingerprint=IMPRESSAO,
                plan_fingerprint=IMPRESSAO,
                artifact_set_fingerprint=IMPRESSAO,
                competition_bundle_fingerprint=IMPRESSAO,
                cells=(celula("xg_home_5m"), celula("xg_home_5m", 2.0)),
            )

    def test_uma_linha_sem_celula_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem célula"):
            NormalizedFeatureRow(
                key=HistoricalFeatureSnapshotKey(match_key="m1", grid_index=0),
                split=DatasetSplit.REFERENCE,
                competition="PREMIER",
                season="2024-25",
                grid_index=0,
                grid_label="MIN_00",
                period="PRE_MATCH",
                minute=0,
                source_row_digest="d" * 64,
                representation_fingerprint=IMPRESSAO,
                plan_fingerprint=IMPRESSAO,
                artifact_set_fingerprint=IMPRESSAO,
                competition_bundle_fingerprint=IMPRESSAO,
                cells=(),
            )


def _canonicas(
    linhas: Sequence[NormalizedFeatureRow],
) -> list[NormalizedFeatureRow]:
    return sorted(linhas, key=lambda r: (r.split.value, r.competition, r.season, r.key))


class TestAsTresImpressoes:
    """§35 — a do meio é a que sustenta o PR."""

    def _acumular(self, *linhas: NormalizedFeatureRow) -> object:
        """As linhas na ORDEM CANÔNICA — partição primeiro, chave depois.

        `EVALUATION` VEM ANTES DE `REFERENCE` porque as chaves de objeto são
        ordenadas como texto, e é assim que o leitor as entrega. Escrever os
        cenários na ordem «referência, depois avaliação» produziria um fluxo
        que a produção nunca gera.
        """
        acumulador = NormalizedContentAccumulator(
            representation_fingerprint=IMPRESSAO,
            plan_fingerprint=IMPRESSAO,
            artifact_set_fingerprint=IMPRESSAO,
        )
        for uma in _canonicas(linhas):
            acumulador.update(uma)
        return acumulador.finalize()

    def test_as_tres_sao_diferentes_entre_si(self) -> None:
        identidade = self._acumular(
            linha(match="m1", split=DatasetSplit.REFERENCE),
            linha(match="m2", split=DatasetSplit.EVALUATION),
        )
        assert identidade.fingerprint != identidade.reference_fingerprint  # type: ignore[attr-defined]
        assert identidade.reference_fingerprint != identidade.evaluation_fingerprint  # type: ignore[attr-defined]

    def test_acrescentar_avaliacao_nao_muda_a_de_referencia(self) -> None:
        so_referencia = self._acumular(linha(match="m1"))
        com_avaliacao = self._acumular(
            linha(match="m1"),
            linha(match="m2", split=DatasetSplit.EVALUATION),
        )
        assert (
            so_referencia.reference_fingerprint  # type: ignore[attr-defined]
            == com_avaliacao.reference_fingerprint  # type: ignore[attr-defined]
        )
        assert so_referencia.fingerprint != com_avaliacao.fingerprint  # type: ignore[attr-defined]

    def test_a_ordem_invertida_e_recusada(self) -> None:
        acumulador = NormalizedContentAccumulator(
            representation_fingerprint=IMPRESSAO,
            plan_fingerprint=IMPRESSAO,
            artifact_set_fingerprint=IMPRESSAO,
        )
        acumulador.update(linha(match="m2"))
        with pytest.raises(ValidationError, match="ordenada"):
            acumulador.update(linha(match="m1"))

    def test_a_reconstrucao_confere_com_a_construcao(self) -> None:
        """A construção calcula ESCREVENDO; a validação recalcula LENDO."""
        linhas = _canonicas([linha(match="m1"), linha(match="m2", split=DatasetSplit.EVALUATION)])
        construida = self._acumular(*linhas)
        reconstruida = rebuild_normalized_content(
            [
                (
                    partition_of(
                        split=uma.split.value,
                        competition=uma.competition,
                        season=uma.season,
                    ),
                    uma.key,
                    uma.split,
                    uma.digest,
                )
                for uma in linhas
            ],
            representation_fingerprint=IMPRESSAO,
            plan_fingerprint=IMPRESSAO,
            artifact_set_fingerprint=IMPRESSAO,
        )
        assert reconstruida.fingerprint == construida.fingerprint  # type: ignore[attr-defined]
        assert (
            reconstruida.reference_fingerprint == construida.reference_fingerprint  # type: ignore[attr-defined]
        )


class TestARepresentacao:
    """§58, §59 — quatro decisões, e a identidade que as amarra."""

    def _spec(self, *, artefatos: str = IMPRESSAO) -> NormalizedFeatureRepresentationSpec:
        return NormalizedFeatureRepresentationSpec.of(
            plan=normalization_plan_v1(),
            artifact_set_id="00000000-0000-0000-0000-000000000001",
            artifact_set_fingerprint=artefatos,
        )

    def test_o_id_do_conjunto_nao_entra_na_identidade(self) -> None:
        """Dois ajustes independentes com os mesmos números são o mesmo."""
        um = self._spec()
        outro = NormalizedFeatureRepresentationSpec.of(
            plan=normalization_plan_v1(),
            artifact_set_id="00000000-0000-0000-0000-000000000002",
            artifact_set_fingerprint=IMPRESSAO,
        )
        assert um.fingerprint == outro.fingerprint
        assert um.artifact_set_id != outro.artifact_set_id

    def test_trocar_o_ajuste_torna_incomparavel(self) -> None:
        with pytest.raises(ValidationError, match="incomparáveis"):
            self._spec().assert_comparable_with(self._spec(artefatos=OUTRA))

    def test_a_impressao_truncada_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="64"):
            self._spec(artefatos="abc")

    def test_a_representacao_sem_id_de_conjunto_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="id de conjunto"):
            NormalizedFeatureRepresentationSpec.of(
                plan=normalization_plan_v1(),
                artifact_set_id="  ",
                artifact_set_fingerprint=IMPRESSAO,
            )

    def test_a_forma_persistida_volta_igual(self) -> None:
        original = self._spec()
        de_volta = NormalizedFeatureRepresentationSpec.from_canonical(original.as_document())
        assert de_volta.fingerprint == original.fingerprint
        assert de_volta.artifact_set_id == original.artifact_set_id


class TestOContrato1Para1:
    """§94 — uma linha a menos é uma partida fora do conjunto de comparação."""

    def _versao(
        self, *, linhas: int, cruas: int, status: DatasetVersionStatus
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        return NormalizedHistoricalFeatureDatasetVersion(
            id="00000000-0000-0000-0000-000000000010",
            dataset_id="00000000-0000-0000-0000-000000000011",
            version=DatasetVersion(major=1, minor=0),
            source_version_id="00000000-0000-0000-0000-000000000012",
            source_version=DatasetVersion(major=1, minor=0),
            source_raw_content_fingerprint=ContentHash(IMPRESSAO),
            source_row_count=cruas,
            representation=NormalizedFeatureRepresentationSpec.of(
                plan=normalization_plan_v1(),
                artifact_set_id="00000000-0000-0000-0000-000000000013",
                artifact_set_fingerprint=IMPRESSAO,
            ),
            status=status,
            created_at=AGORA,
            created_by=ATOR,
            normalized_content_fingerprint=ContentHash(IMPRESSAO),
            normalized_reference_content_fingerprint=ContentHash(OUTRA),
            normalized_evaluation_content_fingerprint=ContentHash(IMPRESSAO),
            manifest_id="00000000-0000-0000-0000-000000000014",
            row_count=linhas,
            completed_at=AGORA,
        )

    def test_publicar_com_menos_linhas_que_o_cru_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="não filtra"):
            self._versao(linhas=90, cruas=91, status=DatasetVersionStatus.READY)

    def test_publicar_com_a_mesma_cardinalidade_passa(self) -> None:
        versao = self._versao(linhas=91, cruas=91, status=DatasetVersionStatus.READY)
        assert versao.row_count == versao.source_row_count

    def test_publicar_sem_a_impressao_de_referencia_e_recusado(self) -> None:
        from dataclasses import replace

        pronta = self._versao(linhas=91, cruas=91, status=DatasetVersionStatus.VALIDATING)
        with pytest.raises(ValidationError, match="REFERÊNCIA"):
            replace(
                pronta,
                status=DatasetVersionStatus.READY,
                normalized_reference_content_fingerprint=None,
            )

    def test_duas_versoes_com_a_mesma_referencia_se_reconhecem(self) -> None:
        uma = self._versao(linhas=91, cruas=91, status=DatasetVersionStatus.READY)
        outra = self._versao(linhas=91, cruas=91, status=DatasetVersionStatus.READY)
        assert uma.has_same_reference_as(outra)

    def test_as_contagens_por_metade_tem_de_fechar(self) -> None:
        from dataclasses import replace

        base = self._versao(linhas=91, cruas=91, status=DatasetVersionStatus.READY)
        with pytest.raises(ValidationError, match="contradizer"):
            replace(base, counts=SplitCounts(reference_rows=50, evaluation_rows=50))


class TestAIdentidadeLogica:
    def test_o_nome_vira_caminho_e_recusa_barra(self) -> None:
        with pytest.raises(ValidationError, match="inválido"):
            NormalizedHistoricalFeatureDataset.create(
                name="a/b",
                source_dataset_id="00000000-0000-0000-0000-000000000001",
                at=AGORA,
                created_by=ATOR,
            )

    def test_sem_dataset_de_origem_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="origem"):
            NormalizedHistoricalFeatureDataset.create(
                name="normalizado", source_dataset_id=" ", at=AGORA, created_by=ATOR
            )
