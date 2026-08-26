"""Relatório, severidades, teto de issues, manifesto e impressão.

O ASSUNTO DESTE ARQUIVO É UM SÓ: o relatório não pode mentir. Ele mente de
três formas conhecidas, e cada uma tem teste aqui:

    dizendo que passou quando há impeditivo
    dizendo quantos achados houve quando truncou a amostra
    descartando o impeditivo por ter enchido o teto com avisos
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.manifest import DatasetManifest
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.schema import (
    ColumnObservation,
    DatasetSchemaContract,
    DatasetSchemaObservation,
    DetectedType,
)
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.datasets.validation import (
    CURRENT_VALIDATOR_VERSION,
    DatasetValidationIssue,
    DatasetValidationReport,
    IssueCode,
    IssueCollector,
    IssueSeverity,
    ValidationStatus,
)
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
DEPOIS: Instant = instant(datetime(2026, 8, 13, 12, 1, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)


def _dataset(arquivos: tuple[DatasetFile, ...] = ()) -> Dataset:
    d = Dataset.register(
        name="premier-league-2019",
        version=V1,
        source=DatasetSource(
            source_name="football-data.co.uk",
            source_type=SourceType.OPEN_DATA,
            license_class=LicenseClass.ATTRIBUTION_REQUIRED,
            retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
            provider_id=ProviderId("football_data"),
        ),
        declared_competitions=frozenset({CompetitionCode.PREMIER_LEAGUE}),
        declared_seasons=("2019-2020",),
        created_at=AGORA,
        created_by="darlan",
    )
    return d.with_files(arquivos)


def _arquivo(conteudo: bytes, nome: str = "e0.csv") -> DatasetFile:
    base = _dataset()
    return DatasetFile.intent(
        dataset_id=base.id,
        version=V1,
        original_filename=nome,
        file_format=DatasetFormat.CSV,
        content_hash=ContentHash.of(conteudo),
        size_bytes=len(conteudo),
        uploaded_at=AGORA,
        uploaded_by="darlan",
        provenance=base.source.to_provenance(ingested_at=AGORA),
    ).confirm_stored()


def _relatorio(*issues: DatasetValidationIssue, **extra: object) -> DatasetValidationReport:
    padrao: dict[str, object] = {
        "dataset_id": _dataset().id,
        "dataset_version": V1,
        "started_at": AGORA,
        "generated_at": DEPOIS,
        "files_checked": 1,
        "rows_observed": 100,
        "issues": issues,
    }
    padrao.update(extra)
    return DatasetValidationReport.build(**padrao)  # type: ignore[arg-type]


class TestSeveridade:
    def test_so_blocking_impede_staging(self) -> None:
        """A linha está entre ERROR e BLOCKING, e ela separa dano LOCAL de
        dano TOTAL. Doze linhas malformadas em cem mil não são o mesmo que um
        Parquet declarado como CSV."""
        assert IssueSeverity.BLOCKING.blocks_staging
        for menor in (IssueSeverity.INFO, IssueSeverity.WARNING, IssueSeverity.ERROR):
            assert not menor.blocks_staging

    def test_severidade_e_ordenavel(self) -> None:
        assert (
            IssueSeverity.INFO
            < IssueSeverity.WARNING
            < IssueSeverity.ERROR
            < IssueSeverity.BLOCKING
        )

    def test_severidade_padrao_vem_do_codigo_e_nao_de_quem_emite(self) -> None:
        """Se cada lugar escolhesse, o mesmo defeito seria impeditivo num
        arquivo e aviso em outro, dependendo de qual caminho o encontrou."""
        assert IssueCode.EMPTY_FILE.default_severity is IssueSeverity.BLOCKING
        assert IssueCode.UNEXPECTED_COLUMN.default_severity is IssueSeverity.WARNING
        assert IssueCode.MALFORMED_ROW.default_severity is IssueSeverity.ERROR

    def test_todo_codigo_tem_severidade_declarada(self) -> None:
        """Cobre o código NOVO que alguém acrescentar sem decidir a gravidade."""
        for codigo in IssueCode:
            assert isinstance(codigo.default_severity, IssueSeverity)

    def test_licenca_desconhecida_e_informativa_e_nao_bloqueia(self) -> None:
        assert IssueCode.LICENSE_REVIEW_REQUIRED.default_severity is IssueSeverity.INFO


class TestRelatorio:
    def test_status_e_derivado_e_nunca_informado(self) -> None:
        assert _relatorio().status is ValidationStatus.PASSED
        assert (
            _relatorio(DatasetValidationIssue.of(IssueCode.UNEXPECTED_COLUMN, "x")).status
            is ValidationStatus.PASSED_WITH_WARNINGS
        )
        assert (
            _relatorio(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x")).status
            is ValidationStatus.PASSED_WITH_ERRORS
        )
        assert (
            _relatorio(DatasetValidationIssue.of(IssueCode.EMPTY_FILE, "x")).status
            is ValidationStatus.BLOCKED
        )

    def test_erro_localizado_nao_impede_staging(self) -> None:
        """A distinção que `is_valid = True/False` apagava.

        Doze linhas perdidas em cem mil é decisão do operador, não do
        validador — e o relatório precisa deixar essa decisão possível.
        """
        r = _relatorio(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x"))
        assert r.status is ValidationStatus.PASSED_WITH_ERRORS
        assert not r.has_blocking_issues

    def test_issues_saem_ordenadas_pela_gravidade(self) -> None:
        """Quem lê um relatório em terminal lê as primeiras linhas.

        Com a ordem de descoberta, o impeditivo apareceria depois de quarenta
        avisos e ninguém o veria.
        """
        r = _relatorio(
            DatasetValidationIssue.of(IssueCode.UNEXPECTED_COLUMN, "aviso"),
            DatasetValidationIssue.of(IssueCode.EMPTY_FILE, "impeditivo"),
            DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "erro"),
        )
        assert [i.severity for i in r.issues] == [
            IssueSeverity.BLOCKING,
            IssueSeverity.ERROR,
            IssueSeverity.WARNING,
        ]

    def test_contagem_total_nunca_e_menor_que_a_amostra(self) -> None:
        with pytest.raises(ValidationError, match="menor que as issues guardadas"):
            _relatorio(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x"), issue_count=0)

    def test_truncado_sem_ter_perdido_nada_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="truncado"):
            _relatorio(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x"), truncated=True)

    def test_relatorio_gerado_antes_de_comecar_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="antes de começar"):
            _relatorio(started_at=DEPOIS, generated_at=AGORA)

    def test_versao_do_validador_viaja_no_relatorio(self) -> None:
        """Um arquivo aprovado pela v1.0 e reprovado pela v1.1 não mudou.

        Sem a versão gravada, a diferença entre dois relatórios pareceria
        mudança no arquivo, e alguém iria procurar o que não existe.
        """
        assert _relatorio().validator_version == CURRENT_VALIDATOR_VERSION

    def test_contagem_por_severidade_soma_ocorrencias(self) -> None:
        r = _relatorio(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x", occurrences=40))
        assert r.count_by_severity()[IssueSeverity.ERROR] == 40


class TestTetoDeIssues:
    def test_amostra_e_limitada_e_o_total_continua_contado(self) -> None:
        """Só a amostra mentiria sobre a extensão; só o total não deixaria
        ninguém entender o problema. Guardamos os dois, e dizemos que houve
        truncamento."""
        coletor = IssueCollector(max_issues=5)
        for i in range(200):
            coletor.add(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, f"linha {i}"))
        assert len(coletor.issues) == 5
        assert coletor.total == 200
        assert coletor.truncated

    def test_impeditivo_nunca_e_descartado_por_teto(self) -> None:
        """O caso que estraga o relatório e passa despercebido.

        O teto enche de avisos, o impeditivo chega depois, e o relatório sai
        sem CONTER o motivo pelo qual o dataset não sobe — apenas contando-o.
        """
        coletor = IssueCollector(max_issues=3)
        for i in range(10):
            coletor.add(DatasetValidationIssue.of(IssueCode.UNEXPECTED_COLUMN, f"c{i}"))
        coletor.add(DatasetValidationIssue.of(IssueCode.EMPTY_FILE, "vazio"))
        assert any(i.severity.blocks_staging for i in coletor.issues)

    def test_sem_truncamento_quando_cabe(self) -> None:
        coletor = IssueCollector(max_issues=10)
        coletor.add(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x"))
        assert not coletor.truncated
        assert coletor.total == 1

    def test_ocorrencias_contam_para_o_total(self) -> None:
        coletor = IssueCollector(max_issues=10)
        coletor.add(DatasetValidationIssue.of(IssueCode.MALFORMED_ROW, "x", occurrences=99))
        assert coletor.total == 99


class TestContratoDeSchema:
    def _observado(self, *colunas: str) -> DatasetSchemaObservation:
        return DatasetSchemaObservation(
            file_id="f1",
            row_count=10,
            columns=tuple(
                ColumnObservation(name=c, detected_type=DetectedType.STRING) for c in colunas
            ),
        )

    def test_coluna_obrigatoria_ausente_e_detectada(self) -> None:
        contrato = DatasetSchemaContract(required_columns=frozenset({"HomeTeam", "Date"}))
        assert contrato.missing_required(self._observado("Date", "FTHG")) == ("HomeTeam",)

    def test_comparacao_ignora_caixa(self) -> None:
        """`HomeTeam` e `hometeam` são a mesma coluna para quem declarou.

        Tratá-las como diferentes produziria um impeditivo falso.
        """
        contrato = DatasetSchemaContract(required_columns=frozenset({"hometeam"}))
        assert contrato.missing_required(self._observado("HomeTeam")) == ()

    def test_coluna_inesperada_e_so_aviso(self) -> None:
        """Fonte pública acrescenta coluna sem avisar. Não recusa o arquivo."""
        contrato = DatasetSchemaContract(expected_columns=frozenset({"Date"}))
        # O NOME VOLTA COMO VEIO NO ARQUIVO, não normalizado: a comparação
        # ignora caixa, o relatório não — quem lê precisa achar a coluna.
        assert contrato.unexpected(self._observado("Date", "xG")) == ("xG",)

    def test_tipo_desconhecido_nao_conta_como_divergencia(self) -> None:
        """Não-saber não é discordar.

        Tratar `UNKNOWN` como divergência encheria o relatório de achados que
        descrevem o limite do nosso inspetor, não o do arquivo.
        """
        contrato = DatasetSchemaContract(
            expected_columns=frozenset({"FTHG"}),
            declared_types={"FTHG": DetectedType.INTEGER},
        )
        observado = DatasetSchemaObservation(
            file_id="f1",
            row_count=1,
            columns=(ColumnObservation(name="FTHG", detected_type=DetectedType.UNKNOWN),),
        )
        assert contrato.type_mismatches(observado) == ()

    def test_divergencia_real_de_tipo_e_relatada(self) -> None:
        contrato = DatasetSchemaContract(
            expected_columns=frozenset({"FTHG"}),
            declared_types={"FTHG": DetectedType.INTEGER},
        )
        observado = DatasetSchemaObservation(
            file_id="f1",
            row_count=1,
            columns=(ColumnObservation(name="FTHG", detected_type=DetectedType.STRING),),
        )
        assert contrato.type_mismatches(observado) == (
            ("FTHG", DetectedType.INTEGER, DetectedType.STRING),
        )

    def test_contrato_contraditorio_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="se contradiz"):
            DatasetSchemaContract(
                required_columns=frozenset({"A"}), expected_columns=frozenset({"B"})
            )

    def test_coluna_duplicada_e_detectada_sem_caixa(self) -> None:
        """O defeito que mais atravessa despercebido: quase toda biblioteca
        resolve sozinha, e o dado de uma das duas some sem aviso."""
        assert self._observado("Date", "date", "FTHG").duplicated_columns() == ("date",)

    def test_amostras_sao_truncadas(self) -> None:
        """Amostra é conteúdo de dataset num lugar onde ele não pertence."""
        coluna = ColumnObservation(
            name="x",
            detected_type=DetectedType.STRING,
            samples=("a" * 500, "b", "c", "d", "e"),
        )
        assert len(coluna.samples) <= 3
        assert len(coluna.samples[0]) <= 65


class TestManifesto:
    def _manifesto(self, *conteudos: bytes) -> DatasetManifest:
        arquivos = tuple(
            _arquivo(c, f"arquivo{i}.csv").with_inspection(row_count=10, column_count=3)
            for i, c in enumerate(conteudos)
        )
        d = _dataset(arquivos)
        return DatasetManifest.build(
            dataset=d, report=_relatorio(dataset_id=d.id), created_at=AGORA
        )

    def test_impressao_e_estavel_para_o_mesmo_conteudo(self) -> None:
        r = _relatorio(dataset_id=_dataset().id)
        d = _dataset((_arquivo(b"a").with_inspection(row_count=10, column_count=3),))
        primeiro = DatasetManifest.build(dataset=d, report=r, created_at=AGORA)
        segundo = DatasetManifest.build(dataset=d, report=r, created_at=DEPOIS)
        # `created_at` FICA DE FORA DA IMPRESSÃO, e é o ponto: incluí-lo faria
        # dois manifestos do mesmo conjunto terem impressões diferentes, que é
        # o contrário do que uma impressão serve para fazer.
        assert primeiro.fingerprint == segundo.fingerprint

    def test_conteudo_diferente_muda_a_impressao(self) -> None:
        assert self._manifesto(b"a").fingerprint != self._manifesto(b"b").fingerprint

    def test_ordem_dos_arquivos_e_canonica(self) -> None:
        """Sem ordem canônica, o mesmo conjunto lido do banco em outra ordem
        produziria outra impressão."""
        m = self._manifesto(b"z", b"a", b"m")
        hashes = [f.sha256.value for f in m.files]
        assert hashes == sorted(hashes)

    def test_serializacao_e_deterministica(self) -> None:
        m = self._manifesto(b"a", b"b")
        assert m.canonical_bytes() == m.canonical_bytes()
        assert json.loads(m.canonical_bytes())["files"][0]["sha256"]

    def test_manifesto_so_lista_arquivos_com_bytes_confirmados(self) -> None:
        """Um manifesto que listasse promessas afirmaria ter provado o que
        não provou."""
        base = _dataset()
        pendente = DatasetFile.intent(
            dataset_id=base.id,
            version=V1,
            original_filename="pendente.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(b"pendente"),
            size_bytes=8,
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=base.source.to_provenance(ingested_at=AGORA),
        )
        confirmado = _arquivo(b"ok").with_inspection(row_count=1, column_count=1)
        d = _dataset((pendente, confirmado))
        m = DatasetManifest.build(dataset=d, report=_relatorio(dataset_id=d.id), created_at=AGORA)
        assert len(m.files) == 1
        assert m.files[0].sha256 == confirmado.content_hash

    def test_manifesto_de_versao_diferente_e_recusado(self) -> None:
        d = _dataset((_arquivo(b"a"),))
        outra = _relatorio(dataset_id=d.id, dataset_version=DatasetVersion(major=2, minor=0))
        with pytest.raises(ConflictError, match="versão"):
            DatasetManifest.build(dataset=d, report=outra, created_at=AGORA)

    def test_manifesto_sem_arquivo_e_recusado(self) -> None:
        with pytest.raises(ConflictError, match="nenhum arquivo"):
            DatasetManifest.build(
                dataset=_dataset(), report=_relatorio(dataset_id=_dataset().id), created_at=AGORA
            )

    def test_mesma_entrada_e_reconhecida_apesar_de_impressoes_diferentes(self) -> None:
        """Duas validações do mesmo conteúdo têm impressões diferentes — e a
        MESMA entrada. São duas perguntas legítimas e diferentes."""
        d = _dataset((_arquivo(b"a").with_inspection(row_count=1, column_count=1),))
        primeiro = DatasetManifest.build(
            dataset=d, report=_relatorio(dataset_id=d.id), created_at=AGORA
        )
        segundo = DatasetManifest.build(
            dataset=d, report=_relatorio(dataset_id=d.id), created_at=DEPOIS
        )
        assert primeiro.fingerprint != segundo.fingerprint
        assert primeiro.describes_same_input_as(segundo)

    def test_manifesto_nao_carrega_conteudo_do_dataset(self) -> None:
        """Ele é o índice remissivo do arquivo bruto, não uma cópia dele.

        Um manifesto que crescesse com o dataset deixaria de caber onde
        precisa caber: numa coluna, num log, num cabeçalho.
        """
        texto = json.dumps(self._manifesto(b"Date,HomeTeam\n2019-08-09,Liverpool").as_canonical())
        assert "Liverpool" not in texto
