"""O domínio de dataset: lifecycle, identidade, formatos e chaves.

O QUE ESTES TESTES PROTEGEM. Quase todo invariante deste PR é protegido por
uma AUSÊNCIA — uma aresta que não existe no grafo, um método que não foi
escrito. Ausência não falha sozinha: ela some no dia em que alguém acrescenta
o que faltava por conveniência. Estes testes são o que faz a ausência ter voz.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import (
    ContentHash,
    build_object_key,
    dataset_key_prefix,
)
from sports_intelligence.domain.datasets.files import (
    DatasetFile,
    DatasetFileId,
    FileStagingState,
    assert_no_duplicate_content,
)
from sports_intelligence.domain.datasets.formats import (
    DatasetFormat,
    detect_compression,
    resolve_declared_format,
    sanitize_filename,
)
from sports_intelligence.domain.datasets.lifecycle import (
    DatasetLifecycle,
    assert_can_stage,
    assert_not_intelligence_ready,
    can_transition,
    transition_to,
)
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)


def fonte(**mudancas: object) -> DatasetSource:
    padrao: dict[str, object] = {
        "source_name": "football-data.co.uk",
        "source_type": SourceType.OPEN_DATA,
        "license_class": LicenseClass.ATTRIBUTION_REQUIRED,
        "retrieved_at": instant(datetime(2026, 8, 1, tzinfo=UTC)),
        "provider_id": ProviderId("football_data"),
    }
    padrao.update(mudancas)
    return DatasetSource(**padrao)  # type: ignore[arg-type]


def dataset(**mudancas: object) -> Dataset:
    padrao: dict[str, object] = {
        "name": "premier-league-2019-2024",
        "version": V1,
        "source": fonte(),
        "declared_competitions": frozenset({CompetitionCode.PREMIER_LEAGUE}),
        "declared_seasons": ("2019-2020", "2020-2021"),
        "created_at": AGORA,
        "created_by": "darlan",
    }
    padrao.update(mudancas)
    return Dataset.register(**padrao)  # type: ignore[arg-type]


class TestLifecycle:
    def test_registered_nao_vai_direto_para_staged(self) -> None:
        """A regra central deste PR, e ela é uma ARESTA AUSENTE.

        Não é uma conferência especial dentro de `transition_to`: é o grafo
        não ter esse caminho. A diferença importa porque uma conferência
        especial sobrevive a alguém acrescentar um estado no meio, e a
        ausência da aresta não — ela obriga a decisão a ser tomada de novo.
        """
        assert not can_transition(DatasetLifecycle.REGISTERED, DatasetLifecycle.STAGED)
        with pytest.raises(ConflictError, match="transição inválida"):
            transition_to(
                DatasetLifecycle.REGISTERED,
                DatasetLifecycle.STAGED,
                at=AGORA,
                reason="atalho",
            )

    def test_nenhum_caminho_chega_a_staged_sem_passar_por_validated(self) -> None:
        """Prova exaustiva, e não por amostragem.

        Testar "REGISTERED não vai para STAGED" cobre um caso. Este varre os
        nove estados e afirma que `VALIDATED` é o ÚNICO predecessor possível —
        o que continua valendo quando um estado novo for acrescentado.
        """
        predecessores = [
            e for e in DatasetLifecycle if can_transition(e, DatasetLifecycle.STAGED)
        ]
        assert predecessores == [DatasetLifecycle.VALIDATED]

    def test_staged_e_rejected_sao_terminais(self) -> None:
        for estado in (DatasetLifecycle.STAGED, DatasetLifecycle.REJECTED):
            assert estado.is_terminal
            assert not any(can_transition(estado, outro) for outro in DatasetLifecycle)

    def test_invalid_so_sai_revalidando_ou_sendo_rejeitado(self) -> None:
        """Não há aresta `INVALID → VALIDATED`.

        Quem conserta manda o arquivo de novo e a validação decide. Um
        caminho direto permitiria marcar como válido o que continua inválido.
        """
        assert not can_transition(DatasetLifecycle.INVALID, DatasetLifecycle.VALIDATED)
        assert can_transition(DatasetLifecycle.INVALID, DatasetLifecycle.VALIDATING)

    def test_transicao_para_o_mesmo_estado_e_recusada(self) -> None:
        with pytest.raises(ConflictError, match="já está em"):
            transition_to(
                DatasetLifecycle.UPLOADED,
                DatasetLifecycle.UPLOADED,
                at=AGORA,
                reason="x",
            )

    def test_transicao_sem_motivo_e_recusada(self) -> None:
        with pytest.raises(ValueError, match="sem motivo"):
            transition_to(
                DatasetLifecycle.REGISTERED,
                DatasetLifecycle.UPLOADING,
                at=AGORA,
                reason="   ",
            )

    @pytest.mark.parametrize(
        ("estado", "aceita"),
        [
            (DatasetLifecycle.REGISTERED, True),
            (DatasetLifecycle.UPLOADING, True),
            (DatasetLifecycle.UPLOADED, True),
            (DatasetLifecycle.VALIDATING, False),
            (DatasetLifecycle.VALIDATED, False),
            (DatasetLifecycle.STAGED, False),
        ],
    )
    def test_conjunto_sela_quando_a_validacao_comeca(
        self, estado: DatasetLifecycle, aceita: bool
    ) -> None:
        """SELA EM `VALIDATING` — não no fim do upload, nem no staging.

        Antes disso, acrescentar arquivo é o caso normal: o operador percebeu
        que faltava uma temporada. Depois, não — o relatório descreve um
        conjunto, e um arquivo que entrasse em seguida ficaria coberto por um
        relatório que não o examinou.
        """
        assert estado.accepts_files is aceita


class TestStagingBoundary:
    def test_staged_exige_validated_e_relatorio_limpo(self) -> None:
        assert_can_stage(DatasetLifecycle.VALIDATED, has_blocking_issues=False)

    def test_staged_recusa_com_impeditivo_mesmo_estando_validated(self) -> None:
        """AS DUAS GUARDAS SÃO NECESSÁRIAS, e nenhuma basta."""
        with pytest.raises(ConflictError, match="impeditivos"):
            assert_can_stage(DatasetLifecycle.VALIDATED, has_blocking_issues=True)

    def test_staged_recusa_de_qualquer_outro_estado(self) -> None:
        for estado in DatasetLifecycle:
            if estado is DatasetLifecycle.VALIDATED:
                continue
            with pytest.raises(ConflictError):
                assert_can_stage(estado, has_blocking_issues=False)

    def test_nenhum_estado_autoriza_alimentar_inteligencia(self) -> None:
        """`STAGED != HISTORICAL_ACTIVE`, dito como guarda executável.

        A função recusa SEMPRE, inclusive para `STAGED`. Ela existe para ser
        chamada por qualquer caminho futuro que pretenda alimentar o índice
        histórico a partir de um dataset de intake.
        """
        for estado in DatasetLifecycle:
            with pytest.raises(InvariantViolationError, match="não alimenta inteligência"):
                assert_not_intelligence_ready(estado)


class TestIdentidadeDoDataset:
    def test_id_e_derivado_de_nome_e_versao(self) -> None:
        """Registrar duas vezes o mesmo par produz o mesmo id.

        É o que torna o retry idempotente de graça: sem isso, um cliente que
        reenvia por timeout cria dois datasets idênticos com ids diferentes, e
        nenhum dos dois está errado o bastante para ser detectável depois.
        """
        assert dataset().id == dataset().id

    def test_versao_diferente_e_dataset_diferente(self) -> None:
        outra = dataset(version=DatasetVersion(major=1, minor=1))
        assert outra.id != dataset().id

    def test_nome_e_normalizado_antes_de_derivar(self) -> None:
        assert dataset(name="  Premier-League-2019-2024  ").id == dataset(
            name="premier-league-2019-2024"
        ).id

    def test_nome_invalido_e_recusado(self) -> None:
        for ruim in ("ab", "Com Espaço", "-comeca-com-hifen", "a" * 80):
            with pytest.raises(ValidationError, match="nome de dataset"):
                dataset(name=ruim)

    def test_sem_competicao_declarada_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="sem competição declarada"):
            dataset(declared_competitions=frozenset())

    def test_temporada_declarada_em_duplicidade_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="duplicidade"):
            dataset(declared_seasons=("2019-2020", "2019-2020"))

    def test_dataset_nao_expoe_resultado_de_futebol(self) -> None:
        """A fronteira do PR: um dataset é evidência, não conhecimento.

        Ele não sabe o que é um `TeamId`. Se algum destes atributos aparecer,
        a resolução de identidade terá vazado para a camada de intake.
        """
        d = dataset()
        for proibido in ("team_id", "teams", "matches", "resolve", "competition_id"):
            assert not hasattr(d, proibido), f"{proibido} vazou para o dataset"


class TestDeclaracaoMultiTemporada:
    def test_um_dataset_pode_declarar_varias_temporadas(self) -> None:
        d = dataset(declared_seasons=("2019-2020", "2020-2021", "2021-2022"))
        assert len(d.declared_seasons) == 3

    def test_um_dataset_pode_declarar_varias_competicoes(self) -> None:
        d = dataset(
            declared_competitions=frozenset(
                {CompetitionCode.PREMIER_LEAGUE, CompetitionCode.LA_LIGA}
            )
        )
        assert len(d.declared_competitions) == 2

    def test_temporadas_sao_rotulos_e_nao_entidades(self) -> None:
        """RÓTULO E NÃO `SeasonId`, e é deliberado.

        Um `SeasonId` exigiria que a temporada já existisse como entidade — e
        no momento do upload ela pode não existir, porque a fonte é
        justamente o que vai povoá-la. Criá-la a partir do rótulo aqui seria
        resolução de identidade na camada errada.
        """
        d = dataset(declared_seasons=("2019/20",))
        assert d.declared_seasons == ("2019/20",)
        assert isinstance(d.declared_seasons[0], str)


class TestSanitizacaoDeNome:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("../../etc/passwd", "passwd"),
            ("C:\\Windows\\system32\\x.csv", "x.csv"),
            ("/absoluto/arquivo.csv", "arquivo.csv"),
            ("normal_file.csv", "normal_file.csv"),
            ("....//....//x.csv", "x.csv"),
        ],
    )
    def test_travessia_de_caminho_nao_sobrevive(self, entrada: str, esperado: str) -> None:
        limpo = sanitize_filename(entrada)
        assert limpo == esperado
        assert "/" not in limpo
        assert "\\" not in limpo
        assert ".." not in limpo

    def test_nome_reservado_do_windows_e_prefixado(self) -> None:
        assert sanitize_filename("CON.csv").startswith("arquivo_")

    def test_byte_nulo_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="byte nulo"):
            sanitize_filename("bom\x00ruim.csv")

    def test_nome_gigante_e_truncado_preservando_extensao(self) -> None:
        limpo = sanitize_filename("a" * 500 + ".csv")
        assert len(limpo) <= 120
        assert limpo.endswith(".csv")

    def test_nome_que_some_inteiro_e_recusado(self) -> None:
        with pytest.raises(ValidationError):
            sanitize_filename("///")


class TestFormatos:
    def test_xlsx_e_recusado_com_o_motivo(self) -> None:
        with pytest.raises(ValidationError, match="XLSX"):
            resolve_declared_format("xlsx")

    def test_apelidos_de_jsonl(self) -> None:
        assert resolve_declared_format("ndjson") is DatasetFormat.JSONL
        assert resolve_declared_format(".JSONL") is DatasetFormat.JSONL

    @pytest.mark.parametrize(
        ("cabeca", "esperado"),
        [
            (b"PK\x03\x04qualquer", "ZIP"),
            (b"\x1f\x8b\x08\x00", "GZIP"),
            (b"BZh9", "BZIP2"),
            (b"\x28\xb5\x2f\xfd", "ZSTD"),
            (b"Date,HomeTeam", None),
            (b"PAR1", None),
        ],
    )
    def test_compactacao_e_detectada_nos_primeiros_bytes(
        self, cabeca: bytes, esperado: str | None
    ) -> None:
        """Um `.csv.gz` renomeado para `.csv` é pego ANTES do parser.

        Sem isso ele viraria um CSV de uma coluna com bytes ilegíveis, e
        atravessaria a validação como "dado ruim" em vez de "arquivo errado".
        """
        assert detect_compression(cabeca) == esperado


class TestChaveDeObjeto:
    def test_chave_e_deterministica(self) -> None:
        h = ContentHash.of(b"conteudo")
        d = DatasetId.derive("x", "v1.0")
        primeira = build_object_key(
            dataset_id=d, version=V1, content_hash=h, safe_filename="e0.csv"
        )
        segunda = build_object_key(
            dataset_id=d, version=V1, content_hash=h, safe_filename="e0.csv"
        )
        assert primeira == segunda

    def test_chave_contem_o_hash_e_nao_depende_do_nome_para_ser_unica(self) -> None:
        """É o que torna o retry idempotente no object store.

        Dois nomes diferentes com os MESMOS bytes produzem chaves que só
        diferem na folha, e o conteúdo endereçado é o mesmo. Dois conteúdos
        diferentes nunca disputam a mesma chave.
        """
        d = DatasetId.derive("x", "v1.0")
        h1, h2 = ContentHash.of(b"a"), ContentHash.of(b"b")
        k1 = build_object_key(dataset_id=d, version=V1, content_hash=h1, safe_filename="x.csv")
        k2 = build_object_key(dataset_id=d, version=V1, content_hash=h2, safe_filename="x.csv")
        assert k1 != k2
        assert h1.value in k1

    def test_chave_recusa_nome_com_separador(self) -> None:
        """A função não confia em ter sido chamada depois da sanitização."""
        with pytest.raises(ValidationError, match="separador de caminho"):
            build_object_key(
                dataset_id=DatasetId.derive("x", "v1.0"),
                version=V1,
                content_hash=ContentHash.of(b"a"),
                safe_filename="../fora.csv",
            )

    def test_prefixo_do_dataset_cobre_as_chaves_dele(self) -> None:
        d = DatasetId.derive("x", "v1.0")
        chave = build_object_key(
            dataset_id=d, version=V1, content_hash=ContentHash.of(b"a"), safe_filename="x.csv"
        )
        assert chave.startswith(dataset_key_prefix(d))
        assert chave.startswith(dataset_key_prefix(d, V1))


class TestContentHash:
    def test_hash_do_mesmo_conteudo_e_igual(self) -> None:
        assert ContentHash.of(b"abc") == ContentHash.of(b"abc")

    def test_crlf_e_lf_sao_conteudos_diferentes(self) -> None:
        """DOS BYTES RECEBIDOS, e não do conteúdo lógico.

        Normalizar antes de hashear seria afirmar que recebemos algo que não
        recebemos — e a função desta camada é justamente provar o que chegou.
        """
        assert ContentHash.of(b"a,b\r\n1,2") != ContentHash.of(b"a,b\n1,2")

    def test_hash_invalido_e_recusado(self) -> None:
        for ruim in ("", "abc", "z" * 64, "A" * 63):
            with pytest.raises(ValidationError, match="SHA-256"):
                ContentHash(ruim)

    def test_hash_e_normalizado_para_minusculas(self) -> None:
        maiusculo = ContentHash.of(b"x").value.upper()
        assert ContentHash(maiusculo).value == ContentHash.of(b"x").value


class TestArquivosDoDataset:
    def _arquivo(self, conteudo: bytes, nome: str = "e0.csv") -> DatasetFile:
        d = dataset()
        return DatasetFile.intent(
            dataset_id=d.id,
            version=d.version,
            original_filename=nome,
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(conteudo),
            size_bytes=len(conteudo),
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=d.source.to_provenance(ingested_at=AGORA),
        )

    def test_intencao_nasce_pendente(self) -> None:
        """PENDING é a janela do ADR-0017, e ela precisa ser visível."""
        assert self._arquivo(b"x").staging_state is FileStagingState.PENDING

    def test_id_do_arquivo_e_derivado_do_conteudo(self) -> None:
        assert self._arquivo(b"x", "a.csv").id == self._arquivo(b"x", "b.csv").id

    def test_conteudo_diferente_gera_id_diferente(self) -> None:
        assert self._arquivo(b"x").id != self._arquivo(b"y").id

    def test_confirmar_duas_vezes_nao_e_erro(self) -> None:
        """O retry chegando depois de a gravação ter dado certo.

        Tratar isso como conflito transformaria a convergência normal em
        alarme — e o alarme apareceria justamente quando tudo deu certo.
        """
        confirmado = self._arquivo(b"x").confirm_stored()
        assert confirmado.confirm_stored() is confirmado

    def test_inspecao_exige_bytes_confirmados(self) -> None:
        with pytest.raises(ConflictError, match="não há bytes confirmados"):
            self._arquivo(b"x").with_inspection(row_count=10, column_count=3)

    def test_pendente_nao_conta_como_presente(self) -> None:
        pendente = self._arquivo(b"x")
        d = dataset().with_files((pendente,))
        assert d.stored_files == ()
        assert d.has_pending_uploads
        assert d.total_bytes == 0

    def test_validacao_recusa_com_upload_em_aberto(self) -> None:
        """A guarda que impede um relatório sobre conjunto incompleto.

        Sem ela, o relatório sairia limpo e PARECERIA completo — a forma
        exata do `STAGED` falso que este PR existe para impedir.
        """
        d = dataset().with_files((self._arquivo(b"x"), self._arquivo(b"y").confirm_stored()))
        with pytest.raises(ConflictError, match="upload em aberto"):
            d.assert_ready_for_validation()

    def test_validacao_recusa_sem_nenhum_arquivo_confirmado(self) -> None:
        with pytest.raises(ConflictError, match="não há arquivo"):
            dataset().assert_ready_for_validation()

    def test_conteudo_duplicado_no_conjunto_e_recusado(self) -> None:
        """O mesmo arquivo com dois nomes: comum na operação manual.

        Sem esta guarda, cada linha entraria duas vezes no que vier depois — e
        nada falharia, o histórico só ficaria com o dobro dos jogos.
        """
        a = self._arquivo(b"mesmo", "e0.csv").confirm_stored()
        b = self._arquivo(b"mesmo", "premier_2019.csv").confirm_stored()
        with pytest.raises(ConflictError, match="conteúdo duplicado"):
            assert_no_duplicate_content((a, b))

    def test_arquivo_e_recusado_apos_selar(self) -> None:
        selado = (
            dataset()
            .with_lifecycle(DatasetLifecycle.UPLOADING, at=AGORA, reason="x")
            .with_lifecycle(DatasetLifecycle.UPLOADED, at=AGORA, reason="y")
            .with_lifecycle(DatasetLifecycle.VALIDATING, at=AGORA, reason="z")
        )
        with pytest.raises(ConflictError, match="não aceita mais arquivos"):
            selado.assert_accepts_files()

    def test_file_id_nao_colide_com_outros_tipos_de_id(self) -> None:
        assert DatasetFileId.NAMESPACE != DatasetId.NAMESPACE


class TestFonte:
    def test_origem_nativa_e_recusada_no_intake(self) -> None:
        """`INSIGHT_NATIVE` não chega por upload, e a exclusão é estrutural.

        Se chegasse, seria dado nosso voltando pela porta da frente como se
        fosse externo — e a precedência do ADR-0009 passaria a favorecê-lo
        sobre a fonte que de fato o originou.
        """
        with pytest.raises(ValidationError, match="não é uma origem de intake"):
            fonte(source_type=SourceType.INSIGHT_NATIVE, provider_id=None)

    def test_origem_externa_exige_provedor(self) -> None:
        with pytest.raises(ValidationError, match="exige provider_id"):
            fonte(source_type=SourceType.OPEN_DATA, provider_id=None)

    def test_origem_manual_recusa_provedor(self) -> None:
        with pytest.raises(ValidationError, match="MANUAL não tem provedor"):
            fonte(source_type=SourceType.MANUAL, provider_id=ProviderId("x"))

    def test_url_local_e_recusada(self) -> None:
        """Um caminho local numa ficha de origem é irreproduzível.

        A ficha existe justamente para que outra pessoa reencontre o dado.
        """
        with pytest.raises(ValidationError, match="esquema"):
            fonte(source_url="file:///home/ninja/e0.csv")

    def test_licenca_desconhecida_marca_revisao_sem_bloquear(self) -> None:
        """Armazenar e validar é legítimo; promover a uso comercial não.

        A marca garante que a pergunta seja feita — ela não impede o staging.
        """
        d = dataset(source=fonte(license_class=LicenseClass.UNKNOWN))
        assert d.needs_license_review
        assert not d.source.allows_commercial_use

    def test_research_only_tambem_pede_revisao(self) -> None:
        assert dataset(source=fonte(license_class=LicenseClass.RESEARCH_ONLY)).needs_license_review

    def test_licenca_comercial_nao_pede_revisao(self) -> None:
        assert not dataset(
            source=fonte(license_class=LicenseClass.COMMERCIAL_ALLOWED)
        ).needs_license_review

    def test_coleta_no_futuro_e_recusada(self) -> None:
        """A assinatura de um fuso lido errado, pega na única hora possível."""
        futura = fonte(retrieved_at=instant(AGORA + timedelta(days=2)))
        with pytest.raises(ValidationError, match="futuro"):
            futura.to_provenance(ingested_at=AGORA)

    def test_procedencia_herda_licenca_e_carimbos(self) -> None:
        p = fonte().to_provenance(ingested_at=AGORA)
        assert p.license_class is LicenseClass.ATTRIBUTION_REQUIRED
        assert p.times.ingested_at == AGORA
        assert p.times.occurred_at < p.times.ingested_at
