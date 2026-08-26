"""A linha materializada, os dois digestos, a versão e o manifesto.

O QUE ESTES TESTES PROVAM:

    o digesto da linha é RECONSTRUTÍVEL   da forma canônica e de mais nada
    ele MUDA quando o valor muda          e quando a disponibilidade muda
    ele NÃO muda entre execuções          duas construções, um número
    a impressão é ORDENADA                inverter duas linhas muda o resultado
    ela RECUSA chave fora de ordem        em vez de aceitar e imprimir errado
    ela inclui a CONTAGEM                 truncar o dataset aparece
    ela inclui as POLÍTICAS               mesmas linhas, grades diferentes,
                                          impressões diferentes
    `READY` exige prova                   impressão, manifesto e linha > 0
    o manifesto NÃO se contradiz          objetos e contagem têm de fechar

O PRIMEIRO É O MAIS IMPORTANTE. Se o digesto dependesse do `FeatureSnapshot`,
conferir um Parquet exigiria reconstruir o estado da partida — e a validação
deixaria de ser uma leitura para virar um build.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sports_intelligence.adapters.postgres.feature_dataset import _para_spec
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    ExtraTimeRule,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.features.dataset.manifest import (
    FEATURE_MANIFEST_SCHEMA_VERSION,
    AvailabilitySummary,
    FeatureObjectRef,
    HistoricalFeatureDatasetManifest,
)
from sports_intelligence.domain.features.dataset.rows import (
    CONTENT_FINGERPRINT_ALGORITHM,
    ROW_DIGEST_ALGORITHM,
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
    MaterializedObjectContent,
    OrderedRowFingerprint,
    availability_tally,
    rebuild_content_fingerprint,
)
from sports_intelligence.domain.features.dataset.split import (
    DatasetSplit,
    FeatureDatasetSplitPolicy,
    SplitCounts,
)
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
    FeatureDatasetSpec,
    HistoricalFeatureDataset,
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.values import ComputedFeature
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.canonical import instant_text
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.support.dataset_fixtures import (
    FRONTEIRA,
    apito_de,
    divisao,
    grade,
    id_de_partida,
    origem_do_cenario,
)
from tests.support.v2_fixtures import extrair_v2

AGORA = instant(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
ATOR = Actor.service("pr0551")
IMPRESSAO_DO_CORPUS = ContentHash("b" * 64)


def _linha(
    *,
    indice: int = 0,
    split: DatasetSplit = DatasetSplit.REFERENCE,
    problemas: int = 0,
) -> MaterializedFeatureRow:
    """Uma linha do cenário V2, com coordenadas de materialização."""
    snapshot = extrair_v2()
    return MaterializedFeatureRow(
        key=HistoricalFeatureSnapshotKey(match_key=str(snapshot.as_of.match_id), grid_index=indice),
        snapshot=snapshot,
        split=split,
        competition_code="PREMIER_LEAGUE",
        season_label="2025/26",
        kickoff=apito_de(0),
        grid_label=f"2H_{indice:03d}",
        state_issue_count=problemas,
    )


class TestAChaveDaLinha:
    def test_ela_ordena_por_partida_e_depois_por_indice(self) -> None:
        a = HistoricalFeatureSnapshotKey(match_key="aaa", grid_index=90)
        b = HistoricalFeatureSnapshotKey(match_key="bbb", grid_index=0)
        assert a < b

    def test_o_indice_e_zero_a_esquerda_no_texto(self) -> None:
        """Sem isso, `#9` viria depois de `#10` em qualquer ordenação textual."""
        chave = HistoricalFeatureSnapshotKey(match_key="x", grid_index=9)
        assert chave.text == "x#0009"

    def test_indice_negativo_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="negativo"):
            HistoricalFeatureSnapshotKey.of(id_de_partida(0), grid_index=-1)


class TestODigestoDaLinha:
    def test_a_forma_canonica_declara_o_algoritmo(self) -> None:
        """Dois hex de 64 caracteres de métodos diferentes são
        indistinguíveis — o nome dentro da forma é o que os separa."""
        assert _linha().as_canonical()["algorithm"] == ROW_DIGEST_ALGORITHM

    def test_ele_e_estavel_entre_construcoes(self) -> None:
        assert _linha().digest == _linha().digest

    def test_ele_muda_quando_a_metade_muda(self) -> None:
        """A metade é conteúdo da linha, e não uma etiqueta do arquivo."""
        assert _linha().digest != _linha(split=DatasetSplit.EVALUATION).digest

    def test_ele_muda_quando_o_indice_da_grade_muda(self) -> None:
        assert _linha(indice=0).digest != _linha(indice=1).digest

    def test_ele_muda_quando_a_contagem_de_problemas_muda(self) -> None:
        assert _linha().digest != _linha(problemas=2).digest

    def test_ele_muda_quando_um_valor_muda(self) -> None:
        linha = _linha()
        primeira = linha.snapshot.features[0]
        alterada = ComputedFeature.available(
            definition_key=primeira.definition_key,
            definition_fingerprint=primeira.definition_fingerprint,
            as_of=primeira.as_of,
            value=(primeira.numeric or 0) + 7,
            provenance=primeira.provenance,
        )
        outro = replace(linha.snapshot, features=(alterada, *linha.snapshot.features[1:]))
        assert (
            MaterializedFeatureRow(
                key=linha.key,
                snapshot=outro,
                split=linha.split,
                competition_code=linha.competition_code,
                season_label=linha.season_label,
                kickoff=linha.kickoff,
                grid_label=linha.grid_label,
            ).digest
            != linha.digest
        )

    def test_indisponivel_sai_como_nulo_e_nunca_como_zero(self) -> None:
        linha = _linha()
        valores = linha.values()
        disponibilidades = linha.availabilities()
        ausentes = [k for k, v in disponibilidades.items() if v != "AVAILABLE"]
        assert ausentes, "o cenário precisa ter alguma dimensão indisponível"
        assert all(valores[k] is None for k in ausentes)

    def test_a_chave_da_linha_tem_de_ser_a_da_partida_do_snapshot(self) -> None:
        linha = _linha()
        with pytest.raises(ValidationError, match="ordenaria pela partida errada"):
            replace(
                linha,
                key=HistoricalFeatureSnapshotKey(match_key="outra", grid_index=0),
            )

    def test_particao_vazia_e_recusada(self) -> None:
        linha = _linha()
        with pytest.raises(ValidationError, match="sem competição"):
            replace(linha, competition_code="  ")

    def test_o_motivo_de_recusa_so_aparece_onde_existe(self) -> None:
        """105 colunas quase sempre nulas para carregar um punhado de valores."""
        linha = _linha()
        motivos = linha.unavailable_reasons()
        temporais = {
            f.definition_key
            for f in linha.snapshot.features
            if f.availability is FeatureAvailability.TEMPORALLY_UNAVAILABLE
        }
        assert set(motivos) == temporais

    def test_a_contagem_por_estado_soma_todas_as_dimensoes(self) -> None:
        linha = _linha()
        contagem = availability_tally([linha])
        assert sum(contagem.values()) == len(linha.snapshot.features)


class TestAImpressaoDeConteudo:
    def _acumulador(self, **trocas: str) -> OrderedRowFingerprint:
        base = {
            "space_name": "MATCH_STATE_RAW_V2",
            "space_version": "2.0",
            "grid_fingerprint": DEFAULT_SNAPSHOT_GRID.fingerprint,
            "split_fingerprint": divisao().fingerprint,
        }
        base.update(trocas)
        return OrderedRowFingerprint(**base)

    def test_o_algoritmo_declara_que_a_ordem_faz_parte_dele(self) -> None:
        assert "ORDERED" in CONTENT_FINGERPRINT_ALGORITHM

    def test_duas_cadeias_iguais_produzem_a_mesma_impressao(self) -> None:
        linhas = [(HistoricalFeatureSnapshotKey("a", i), f"d{i}") for i in range(5)]
        primeira = self._acumulador()
        segunda = self._acumulador()
        for chave, digesto in linhas:
            primeira.update(chave, digesto)
            segunda.update(chave, digesto)
        assert primeira.finalize() == segunda.finalize()

    def test_uma_chave_fora_de_ordem_e_RECUSADA(self) -> None:
        """Somar ou fazer XOR dos digestos ficaria comutativo — e permutação é
        exatamente um dos defeitos que a impressão existe para pegar."""
        acumulador = self._acumulador()
        acumulador.update(HistoricalFeatureSnapshotKey("a", 5), "d5")
        with pytest.raises(ValidationError, match="impressão de conteúdo é ordenada"):
            acumulador.update(HistoricalFeatureSnapshotKey("a", 4), "d4")

    def test_a_mesma_chave_duas_vezes_e_recusada(self) -> None:
        acumulador = self._acumulador()
        acumulador.update(HistoricalFeatureSnapshotKey("a", 1), "d")
        with pytest.raises(ValidationError):
            acumulador.update(HistoricalFeatureSnapshotKey("a", 1), "d")

    def test_a_contagem_entra_na_impressao(self) -> None:
        """Truncar o dataset tem de aparecer."""
        completa = self._acumulador()
        truncada = self._acumulador()
        for i in range(5):
            completa.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        for i in range(4):
            truncada.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        assert completa.finalize() != truncada.finalize()

    def test_a_grade_entra_na_impressao(self) -> None:
        """As MESMAS linhas sob grades diferentes não são o mesmo dataset."""
        outra = SnapshotGridPolicy(extra_time=ExtraTimeRule.NEVER).fingerprint
        primeira = self._acumulador()
        segunda = self._acumulador(grid_fingerprint=outra)
        for i in range(3):
            primeira.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
            segunda.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        assert primeira.finalize() != segunda.finalize()

    def test_a_divisao_entra_na_impressao(self) -> None:
        outra = FeatureDatasetSplitPolicy(
            reference_end_exclusive=instant(datetime(2026, 6, 1, tzinfo=UTC))
        ).fingerprint
        primeira = self._acumulador()
        segunda = self._acumulador(split_fingerprint=outra)
        for i in range(3):
            primeira.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
            segunda.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        assert primeira.finalize() != segunda.finalize()

    def test_a_reconstrucao_chega_ao_mesmo_numero(self) -> None:
        """É esta igualdade que a validação usa: uma impressão calculada ao
        escrever, outra calculada ao LER."""
        linhas = [(HistoricalFeatureSnapshotKey("a", i), f"d{i}") for i in range(6)]
        acumulador = self._acumulador()
        for chave, digesto in linhas:
            acumulador.update(chave, digesto)
        assert acumulador.finalize() == rebuild_content_fingerprint(
            linhas,
            space_name="MATCH_STATE_RAW_V2",
            space_version="2.0",
            grid_fingerprint=DEFAULT_SNAPSHOT_GRID.fingerprint,
            split_fingerprint=divisao().fingerprint,
        )


class TestOConteudoLidoDeUmObjeto:
    def test_linhas_em_ordem_nao_produzem_denuncia(self) -> None:
        conteudo = MaterializedObjectContent(
            object_key="k",
            sha256="0" * 64,
            size_bytes=10,
            rows=tuple((HistoricalFeatureSnapshotKey("a", i), f"d{i}") for i in range(4)),
        )
        assert conteudo.out_of_order() == ()
        assert conteudo.row_count == 4

    def test_linhas_invertidas_sao_denunciadas(self) -> None:
        conteudo = MaterializedObjectContent(
            object_key="k",
            sha256="0" * 64,
            size_bytes=10,
            rows=(
                (HistoricalFeatureSnapshotKey("a", 3), "d3"),
                (HistoricalFeatureSnapshotKey("a", 1), "d1"),
            ),
        )
        assert len(conteudo.out_of_order()) == 1


class TestAEspecificacaoDaVersao:
    def _spec(self) -> FeatureDatasetSpec:
        return FeatureDatasetSpec.of(
            space=match_state_raw_space_v2(), grid=grade(), split=divisao()
        )

    def test_ela_carrega_as_tres_impressoes(self) -> None:
        spec = self._spec()
        assert spec.grid_fingerprint == grade().fingerprint
        assert spec.split_fingerprint == divisao().fingerprint
        assert spec.space_fingerprint == match_state_raw_space_v2().fingerprint

    def test_duas_specs_iguais_sao_comparaveis(self) -> None:
        assert self._spec().is_comparable_with(self._spec())

    def test_grades_diferentes_tornam_as_versoes_incomparaveis(self) -> None:
        outra = FeatureDatasetSpec.of(
            space=match_state_raw_space_v2(),
            grid=SnapshotGridPolicy(extra_time=ExtraTimeRule.NEVER),
            split=divisao(),
        )
        assert not self._spec().is_comparable_with(outra)

    def test_impressao_de_espaco_truncada_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="64"):
            replace(self._spec(), space_fingerprint="abc")

    def test_a_especificacao_volta_da_forma_canonica_com_os_parametros(self) -> None:
        """NOME E VERSÃO NÃO BASTAM: uma grade de cinco cortes reconstruída
        deles voltaria com noventa e um."""
        reduzida = SnapshotGridPolicy(
            name="GRADE_CURTA_V1", first_half_last_minute=2, second_half_last_minute=4
        )
        original = FeatureDatasetSpec.of(
            space=match_state_raw_space_v2(), grid=reduzida, split=divisao()
        )
        de_volta = FeatureDatasetSpec.from_canonical(original.as_canonical())
        assert de_volta == original
        assert de_volta.grid.regulation_size == 5
        assert de_volta.split.reference_end_exclusive == FRONTEIRA

    def test_parametros_adulterados_no_documento_sao_recusados(self) -> None:
        """A impressão gravada e a recalculada têm de fechar — senão o
        documento descreve uma política que ninguém declarou."""
        documento = self._spec().as_canonical()
        grade = documento["grid"]
        assert isinstance(grade, dict)
        adulterada = {**grade, "second_half_last_minute": 60}
        with pytest.raises(ValidationError, match="impressão diferente da gravada"):
            FeatureDatasetSpec.from_canonical({**documento, "grid": adulterada})


class TestOCruzamentoEntreDocumentoEColunas:
    """§32. O adaptador guarda a política em dois lugares, e confere os dois.

    O `jsonb` RECONSTRÓI e as colunas CONSULTAM. Se um lado for adulterado, o
    adaptador tem de RECUSAR — escolher um dos dois em silêncio faria a consulta
    «quais versões são comparáveis com esta?» apontar para outra política sem
    que nada denunciasse.
    """

    def _linha(self, **trocas: object) -> dict[str, object]:
        spec = FeatureDatasetSpec.of(
            space=match_state_raw_space_v2(), grid=grade(), split=divisao()
        )
        base: dict[str, object] = {
            "spec": json.dumps(spec.as_canonical(), sort_keys=True),
            "grid_fingerprint": spec.grid_fingerprint,
            "split_fingerprint": spec.split_fingerprint,
            "space_fingerprint": spec.space_fingerprint,
            "reference_end_exclusive": spec.reference_end_exclusive,
        }
        return {**base, **trocas}

    def test_documento_e_colunas_coerentes_passam(self) -> None:
        spec = _para_spec(self._linha())
        assert spec.grid == grade()
        assert spec.split == divisao()

    @pytest.mark.parametrize(
        "coluna",
        ["grid_fingerprint", "split_fingerprint", "space_fingerprint"],
    )
    def test_impressao_de_coluna_adulterada_e_recusada(self, coluna: str) -> None:
        with pytest.raises(ConflictError, match="discorda do documento"):
            _para_spec(self._linha(**{coluna: "f" * 64}))

    def test_fronteira_de_coluna_adulterada_e_recusada(self) -> None:
        """Ela é coluna para responder «que datasets têm avaliação depois de
        junho?», e uma coluna divergente selecionaria a versão errada."""
        outra = instant(datetime(2027, 1, 1, tzinfo=UTC))
        with pytest.raises(ConflictError, match="discorda do documento"):
            _para_spec(self._linha(reference_end_exclusive=outra))

    def test_parametro_adulterado_no_documento_e_recusado_antes_das_colunas(
        self,
    ) -> None:
        """A impressão do próprio documento não fecharia: os parâmetros não são
        os que produziram aquela impressão."""
        spec = FeatureDatasetSpec.of(
            space=match_state_raw_space_v2(), grid=grade(), split=divisao()
        )
        documento = spec.as_canonical()
        grade_doc = documento["grid"]
        assert isinstance(grade_doc, dict)
        adulterado = {
            **documento,
            "grid": {**grade_doc, "second_half_last_minute": 60},
        }
        with pytest.raises(ValidationError, match="impressão diferente da gravada"):
            _para_spec(
                {
                    "spec": json.dumps(adulterado, sort_keys=True),
                    "grid_fingerprint": spec.grid_fingerprint,
                    "split_fingerprint": spec.split_fingerprint,
                    "space_fingerprint": spec.space_fingerprint,
                    "reference_end_exclusive": spec.reference_end_exclusive,
                }
            )


class TestAVersaoDoDataset:
    def _versao(self, **trocas: object) -> HistoricalFeatureDatasetVersion:
        base = HistoricalFeatureDatasetVersion.draft(
            dataset_id="ds",
            version=DatasetVersion(major=1, minor=0),
            source_version_id=origem_do_cenario().version_id,
            source_version=DatasetVersion(major=1, minor=0),
            source_corpus_fingerprint=IMPRESSAO_DO_CORPUS,
            spec=FeatureDatasetSpec.of(
                space=match_state_raw_space_v2(), grid=grade(), split=divisao()
            ),
            at=AGORA,
            created_by=ATOR,
        )
        return replace(base, **trocas)  # type: ignore[arg-type]

    def test_ela_nasce_em_draft(self) -> None:
        assert self._versao().status is DatasetVersionStatus.DRAFT

    def test_draft_para_ready_nao_existe(self) -> None:
        """Um dataset publicado sem construir nem conferir seria um nome
        apontando para nada."""
        with pytest.raises(ValidationError, match="publicar sem validar"):
            self._versao().require_transition(DatasetVersionStatus.READY)

    def test_o_caminho_completo_e_permitido_passo_a_passo(self) -> None:
        versao = self._versao()
        assert versao.can_move_to(DatasetVersionStatus.BUILDING)
        assert replace(versao, status=DatasetVersionStatus.BUILDING).can_move_to(
            DatasetVersionStatus.VALIDATING
        )
        assert replace(versao, status=DatasetVersionStatus.VALIDATING).can_move_to(
            DatasetVersionStatus.READY
        )

    def test_ready_sem_impressao_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem impressão"):
            self._versao(
                status=DatasetVersionStatus.READY,
                manifest_id="m",
                row_count=91,
                completed_at=AGORA,
            )

    def test_ready_sem_manifesto_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem manifesto"):
            self._versao(
                status=DatasetVersionStatus.READY,
                raw_content_fingerprint=ContentHash("c" * 64),
                row_count=91,
                completed_at=AGORA,
            )

    def test_ready_com_zero_linhas_e_recusada(self) -> None:
        """Quem a consultasse receberia «sem vizinhos» em vez de um erro."""
        with pytest.raises(ValidationError, match=r"publicada com 0 linhas"):
            self._versao(
                status=DatasetVersionStatus.READY,
                raw_content_fingerprint=ContentHash("c" * 64),
                manifest_id="m",
                row_count=0,
                completed_at=AGORA,
            )

    def test_contagens_que_nao_fecham_sao_recusadas(self) -> None:
        with pytest.raises(ValidationError, match="se contradizer"):
            self._versao(
                row_count=100,
                counts=SplitCounts(reference_rows=50, evaluation_rows=40),
            )

    def test_superseded_sem_sucessor_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem o sucessor"):
            self._versao(
                status=DatasetVersionStatus.SUPERSEDED,
                raw_content_fingerprint=ContentHash("c" * 64),
                manifest_id="m",
                row_count=91,
                completed_at=AGORA,
            )

    def test_a_identidade_logica_recusa_barra_no_nome(self) -> None:
        with pytest.raises(ValidationError, match="inválido"):
            HistoricalFeatureDataset.create(name="match/state", at=AGORA, created_by=ATOR)

    def test_o_nome_de_producao_e_declarado(self) -> None:
        assert DEFAULT_FEATURE_DATASET_NAME == "match-state-raw"

    def test_a_forma_semantica_nao_carrega_id_de_execucao(self) -> None:
        """Duas construções independentes do mesmo conteúdo são o mesmo
        dataset — incluir os ids faria a impressão dizer «diferente»."""
        forma = self._versao().semantic_form()
        assert "source_version_id" not in forma
        assert "source_version_id" in self._versao().as_canonical()


class TestOManifesto:
    def _manifesto(self, **trocas: object) -> HistoricalFeatureDatasetManifest:
        base = HistoricalFeatureDatasetManifest(
            id="m",
            schema_version=FEATURE_MANIFEST_SCHEMA_VERSION,
            dataset_id="ds",
            dataset_name="match-state-raw",
            dataset_version=DatasetVersion(major=1, minor=0),
            dataset_version_id="v",
            source_version_id=origem_do_cenario().version_id,
            source_version=DatasetVersion(major=1, minor=0),
            source_corpus_fingerprint=IMPRESSAO_DO_CORPUS,
            spec=FeatureDatasetSpec.of(
                space=match_state_raw_space_v2(), grid=grade(), split=divisao()
            ),
            counts=SplitCounts(
                reference_matches=1,
                evaluation_matches=1,
                reference_rows=91,
                evaluation_rows=91,
            ),
            match_count=2,
            row_count=182,
            availability=AvailabilitySummary(total_values=210, by_state={"AVAILABLE": 210}),
            raw_content_fingerprint=ContentHash("d" * 64),
            created_at=AGORA,
        )
        return replace(base, **trocas)  # type: ignore[arg-type]

    def test_o_documento_e_deterministico(self) -> None:
        assert self._manifesto().to_json() == self._manifesto().to_json()

    def test_as_duas_impressoes_sao_diferentes_e_nomeadas(self) -> None:
        manifesto = self._manifesto()
        assert manifesto.manifest_sha256 != manifesto.raw_content_fingerprint.value

    def test_o_carimbo_muda_os_bytes_e_nao_o_conteudo(self) -> None:
        outro = self._manifesto(created_at=instant(datetime(2027, 1, 1, tzinfo=UTC)))
        assert outro.manifest_sha256 != self._manifesto().manifest_sha256
        assert outro.raw_content_fingerprint == self._manifesto().raw_content_fingerprint

    def test_o_catalogo_de_exclusoes_esta_no_documento(self) -> None:
        """«O que não está aqui» é pergunta de manifesto tanto quanto «o que está»."""
        assert self._manifesto().as_canonical()["grid_exclusions"]

    def test_objetos_que_nao_somam_o_declarado_sao_recusados(self) -> None:
        objeto = FeatureObjectRef(
            object_key="k",
            split=DatasetSplit.REFERENCE,
            competition="EPL",
            season="2025/26",
            sha256=ContentHash("e" * 64),
            size_bytes=10,
            row_count=90,
        )
        with pytest.raises(ValidationError, match="reconciliação"):
            self._manifesto(objects=(objeto,))

    def test_um_schema_desconhecido_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="schema"):
            self._manifesto(schema_version="9.9")

    def test_a_cobertura_e_uma_razao_e_nao_um_veredito(self) -> None:
        resumo = AvailabilitySummary(
            total_values=100,
            by_state={"AVAILABLE": 70, "TEMPORALLY_UNAVAILABLE": 30},
        )
        assert resumo.available == 70
        assert resumo.coverage == pytest.approx(0.70)

    def test_a_fronteira_da_divisao_aparece_no_documento(self) -> None:
        """Sem ela, «de onde vem a metade desta linha» exigiria reconstruir a
        política de seis meses atrás."""
        spec = self._manifesto().as_canonical()["spec"]
        assert isinstance(spec, dict)
        divisao_documentada = spec["split"]
        assert isinstance(divisao_documentada, dict)
        assert divisao_documentada["reference_end_exclusive"] == instant_text(FRONTEIRA)
        assert divisao_documentada["fingerprint"] == divisao().fingerprint
