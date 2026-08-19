"""O domínio do corpus: ciclo de vida, pertinência, manifesto, impressão.

O QUE ESTES TESTES DE FATO PROTEGEM, e não é «cobertura»:

    a aresta que NÃO existe        `DRAFT → READY` — o gate do §12
    a imutabilidade                uma versão publicada não muda de conteúdo
    o que ENTRA na impressão       conteúdo, e nada de carimbo de execução
    o que NÃO entra                `created_at`, ids de run — o §31
    a comutatividade               o lote não muda a impressão — o §88
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sports_intelligence.domain.corpus.composition import ComposedMatchCorpusFacts
from sports_intelligence.domain.corpus.facts import (
    MATERIALIZABLE_FAMILIES,
    MatchCorpusFacts,
)
from sports_intelligence.domain.corpus.fingerprint import (
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_SCHEMA_VERSION,
    CorpusFingerprintBuilder,
    canonical_json,
    fingerprint_of,
    frame,
    member_payload,
)
from sports_intelligence.domain.corpus.manifest import (
    MANIFEST_SCHEMA_VERSION,
    MAX_ISSUE_EXAMPLES,
    FamilyCoverageSummary,
    HistoricalCanonicalManifest,
    IssueSummary,
    LicenseSummary,
    QualitySummary,
)
from sports_intelligence.domain.corpus.membership import MembershipCounts
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDatasetVersion,
    assert_not_vector_active,
    can_transition,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
    ValidationError,
)
from tests.support.build_fixtures import AGORA
from tests.support.corpus_fixtures import (
    DATASET_ID,
    dataset,
    entradas,
    escopo,
    fatos,
    membros,
    versao_rascunho,
)


class TestOCicloDeVidaDaVersao:
    def test_draft_nao_vai_direto_para_ready(self) -> None:
        """§12. A ARESTA QUE NÃO EXISTE É O GATE.

        Uma versão que nunca materializou nem conferiu não pode se declarar
        publicada — e o lugar onde essa recusa mora é o grafo, e não um `if`
        espalhado por quem publica.
        """
        assert not can_transition(DatasetVersionStatus.DRAFT, DatasetVersionStatus.READY)
        rascunho = versao_rascunho()
        with pytest.raises(ConflictError, match="não existe no ciclo de vida"):
            rascunho.publish(manifest_id="qualquer", at=AGORA)

    def test_o_caminho_completo_chega_a_ready(self) -> None:
        pronta = (
            versao_rascunho()
            .start_building()
            .start_validating(match_count=3, corpus_fingerprint=ContentHash("b" * 64))
            .publish(manifest_id="m-1", at=AGORA)
        )
        assert pronta.status is DatasetVersionStatus.READY
        assert pronta.is_frozen
        assert pronta.status.is_readable_corpus

    def test_ready_sem_impressao_e_recusado_pelo_construtor(self) -> None:
        """Uma versão publicada sem impressão afirmaria estar publicada sem
        nada que prove o que publicou."""
        with pytest.raises(ValidationError, match="sem impressão"):
            HistoricalCanonicalDatasetVersion(
                id="v-1",
                dataset_id=DATASET_ID,
                version=versao_rascunho().version,
                scope=escopo(),
                inputs=entradas(),
                status=DatasetVersionStatus.READY,
                created_at=AGORA,
                created_by=versao_rascunho().created_by,
                completed_at=AGORA,
            )

    def test_superseded_continua_legivel(self) -> None:
        """§79. Um resultado calculado sobre a 1.0 continua explicável por ela,
        e seria irreproduzível se ela sumisse."""
        publicada = (
            versao_rascunho()
            .start_building()
            .start_validating(match_count=1, corpus_fingerprint=ContentHash("c" * 64))
            .publish(manifest_id="m-1", at=AGORA)
        )
        superada = publicada.supersede(by_version_id="v-2", at=AGORA)
        assert superada.status.is_readable_corpus
        assert superada.is_frozen
        assert superada.superseded_by == "v-2"

    def test_uma_versao_nao_substitui_a_si_mesma(self) -> None:
        publicada = (
            versao_rascunho()
            .start_building()
            .start_validating(match_count=1, corpus_fingerprint=ContentHash("c" * 64))
            .publish(manifest_id="m-1", at=AGORA)
        )
        with pytest.raises(ValidationError, match="a si mesma"):
            publicada.supersede(by_version_id=publicada.id, at=AGORA)

    def test_versao_congelada_recusa_alteracao_de_composicao(self) -> None:
        """§115. Acrescentar um fato a um corpus publicado o faria mudar de
        conteúdo sem mudar de nome."""
        publicada = (
            versao_rascunho()
            .start_building()
            .start_validating(match_count=1, corpus_fingerprint=ContentHash("d" * 64))
            .publish(manifest_id="m-1", at=AGORA)
        )
        with pytest.raises(ConflictError, match="imutável"):
            publicada.assert_mutable()

    def test_o_limite_do_pr_05_recusa_sempre(self) -> None:
        """§4. HISTORICAL_CANONICAL_READY ≠ HISTORICAL_VECTOR_ACTIVE."""
        publicada = (
            versao_rascunho()
            .start_building()
            .start_validating(match_count=1, corpus_fingerprint=ContentHash("e" * 64))
            .publish(manifest_id="m-1", at=AGORA)
        )
        with pytest.raises(InvariantViolationError, match="espaço vetorial"):
            assert_not_vector_active(publicada)


class TestAPertinencia:
    def test_o_membro_carrega_familias_em_ordem_canonica(self) -> None:
        membro = ComposedMatchCorpusFacts.of(
            fatos(families=(CoverageFamily.ODDS, CoverageFamily.MATCH))
        ).as_member()
        assert membro.included_families == (CoverageFamily.MATCH, CoverageFamily.ODDS)

    def test_a_forma_canonica_do_membro_nao_carrega_id_de_execucao(self) -> None:
        """§31. Duas publicações independentes dos MESMOS fatos têm ids
        diferentes e são o mesmo corpus."""
        a = ComposedMatchCorpusFacts.of(
            fatos(build_run_id="11111111-1111-4111-8111-111111111111")
        ).as_member()
        b = ComposedMatchCorpusFacts.of(
            fatos(build_run_id="99999999-9999-4999-8999-999999999999")
        ).as_member()
        assert a.as_canonical() == b.as_canonical()
        assert a.build_run_ids != b.build_run_ids

    def test_um_membro_sem_familia_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="sem família"):
            MatchCorpusFacts(
                match=fatos().match,
                competition=fatos().competition,
                season_label=fatos().season_label,
                included_families=(),
                build_run_id="x",
                quality_assessment_id="y",
            )

    def test_familia_que_o_motor_nao_materializa_e_recusada(self) -> None:
        """Publicar uma família sem saber escrevê-la faria o manifesto
        prometer conteúdo que não existe no corpus.

        `EVENT` SAIU DESTA LISTA NO PR-04.4.2, e `TRACKING` continua nela: a
        primeira ganhou pipeline, tabela e arquivo; a segunda não existe na V1.
        """
        assert CoverageFamily.TRACKING not in MATERIALIZABLE_FAMILIES
        with pytest.raises(ValidationError, match="não materializa"):
            MatchCorpusFacts(
                match=fatos().match,
                competition=fatos().competition,
                season_label=fatos().season_label,
                included_families=(CoverageFamily.TRACKING,),
                build_run_id="x",
                quality_assessment_id="y",
            )

    def test_familia_de_evento_declarada_sem_evento_e_recusada(self) -> None:
        """PR-04.4.2 §52. A família é a PROMESSA de conteúdo; declarada sem
        evento nenhum, ela ficaria vazia no arquivo e zerada no manifesto —
        e a cobertura afirmaria uma presença que não existe."""
        with pytest.raises(ValidationError, match="não traz evento nenhum"):
            MatchCorpusFacts(
                match=fatos().match,
                competition=fatos().competition,
                season_label=fatos().season_label,
                included_families=(CoverageFamily.MATCH, CoverageFamily.EVENT),
                build_run_id="x",
                quality_assessment_id="y",
            )

    def test_as_contagens_somam_por_familia_e_por_particao(self) -> None:
        contagens = MembershipCounts.of(
            membros(3, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        )
        assert contagens.matches == 3
        assert contagens.by_family["MATCH"] == 3
        assert contagens.by_family["ODDS"] == 3
        assert contagens.by_partition["PREMIER_LEAGUE/2025/26"] == 3


class TestAImpressaoDoConteudo:
    def test_placar_diferente_muda_a_impressao(self) -> None:
        """§32. Dois corpus com as mesmas partidas e placares DIFERENTES não
        são o mesmo corpus — e uma impressão que dissesse que sim não
        responderia a única pergunta que ela existe para responder."""
        assert fatos(home=2).content_fingerprint() != fatos(home=3).content_fingerprint()

    def test_a_impressao_do_conteudo_ignora_id_de_execucao(self) -> None:
        a = fatos(build_run_id="11111111-1111-4111-8111-111111111111")
        b = fatos(build_run_id="99999999-9999-4999-8999-999999999999")
        assert a.content_fingerprint() == b.content_fingerprint()

    def test_familias_diferentes_produzem_impressoes_diferentes(self) -> None:
        """Pesquisa e comércio publicam conteúdos diferentes da MESMA partida,
        e a impressão precisa dizer isso."""
        pesquisa = fatos(families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        comercial = fatos(families=(CoverageFamily.MATCH,))
        assert pesquisa.content_fingerprint() != comercial.content_fingerprint()

    def test_ausencia_de_resultado_e_distinta_de_zero_a_zero(self) -> None:
        """§46. Zero é um placar; ausente é a falta de um."""
        sem_placar = MatchCorpusFacts(
            match=fatos().match,
            competition=fatos().competition,
            season_label=fatos().season_label,
            included_families=(CoverageFamily.MATCH,),
            build_run_id="x",
            quality_assessment_id="y",
            result=None,
        )
        assert sem_placar.content_fingerprint() != fatos(home=0, away=0).content_fingerprint()
        linha = sem_placar.rows_for(CoverageFamily.MATCH)[0]
        assert linha["home_goals"] is None
        assert linha["away_goals"] is None

    def test_a_linha_de_odds_leva_decimal_e_nao_float(self) -> None:
        """§47. `float(Decimal("2.05"))` não é 2.05, e o erro aparece
        exatamente onde dói: duas casas cotando o mesmo preço."""
        from decimal import Decimal

        linha = fatos(families=(CoverageFamily.MATCH, CoverageFamily.ODDS)).rows_for(
            CoverageFamily.ODDS
        )[0]
        assert isinstance(linha["decimal_odds"], Decimal)
        assert linha["observed_at"] is None

    def test_familia_ausente_nao_produz_linha(self) -> None:
        assert fatos(families=(CoverageFamily.MATCH,)).rows_for(CoverageFamily.ODDS) == []


class TestAImpressaoDoCorpus:
    """A impressão SEMÂNTICA — SHA-256 sobre serialização ordenada.

    O QUE MUDOU NO PR-04.3.1 e por que estes testes existem: o XOR-fold do
    PR-04.3 tinha `H(A) ⊕ H(A) = 0`, então um item repetido se CANCELAVA. A
    construção nova é sequencial sobre ordem imposta, e a duplicata vira ERRO
    em vez de virar silêncio.
    """

    @staticmethod
    def _em_lotes(quantos: int, *, lote: int) -> ContentHash:
        """Acumula em lotes, como a composição de verdade faz."""
        construtor = CorpusFingerprintBuilder(scope=escopo())
        todos = membros(quantos)
        contagens = MembershipCounts()
        for inicio in range(0, quantos, lote):
            bloco = todos[inicio : inicio + lote]
            for membro in bloco:
                construtor.add(membro)
            contagens = contagens.merged_with(MembershipCounts.of(bloco))
        return construtor.finish(contagens)

    # ------------------------------------------------- determinismo (§13) --

    def test_o_tamanho_do_lote_nao_muda_a_impressao(self) -> None:
        """§13. O lote é detalhe de execução, não de conteúdo."""
        de_um = self._em_lotes(12, lote=1)
        de_cinco = self._em_lotes(12, lote=5)
        de_doze = self._em_lotes(12, lote=12)
        assert de_um == de_cinco == de_doze

    def test_a_ordem_de_processamento_da_origem_nao_muda_a_impressao(self) -> None:
        """§14. A origem pode chegar em qualquer ordem; a SERIALIZAÇÃO é que
        é ordenada, e `fingerprint_of` ordena antes de acumular."""
        conjunto = membros(8)
        embaralhados = tuple(reversed(conjunto))
        assert fingerprint_of(conjunto, scope=escopo()) == fingerprint_of(
            embaralhados, scope=escopo()
        )

    # ---------------------------------------------------- mutacao (do §15 ao §18) --

    def test_fato_alterado_muda_a_impressao(self) -> None:
        """§15. Mesma partida, kickoff diferente — corpus diferente."""
        from datetime import timedelta

        from sports_intelligence.domain.shared.temporal import instant

        original = ComposedMatchCorpusFacts.of(fatos(0))
        deslocada = replace(
            original.facts.match,
            scheduled_kickoff=instant(
                original.facts.match.scheduled_kickoff + timedelta(minutes=1)
            ),
        )
        alterada = ComposedMatchCorpusFacts.of(replace(original.facts, match=deslocada))
        assert fingerprint_of((original.as_member(),), scope=escopo()) != fingerprint_of(
            (alterada.as_member(),), scope=escopo()
        )

    def test_membro_acrescentado_muda_a_impressao(self) -> None:
        """§16."""
        assert fingerprint_of(membros(5), scope=escopo()) != fingerprint_of(
            membros(6), scope=escopo()
        )

    def test_membro_removido_muda_a_impressao(self) -> None:
        """§17."""
        cinco = membros(5)
        assert fingerprint_of(cinco, scope=escopo()) != fingerprint_of(cinco[:-1], scope=escopo())

    def test_familia_diferente_muda_a_impressao(self) -> None:
        """§18, §88. Um corpus com Match+Odds não é o mesmo do Match-only."""
        so_match = membros(4, families=(CoverageFamily.MATCH,))
        com_odds = membros(4, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        assert fingerprint_of(so_match, scope=escopo()) != fingerprint_of(com_odds, scope=escopo())

    # --------------------------------------------- segurança do XOR (§19) --

    def test_membro_repetido_e_recusado_em_vez_de_cancelado(self) -> None:
        """§19. É AQUI QUE O XOR FALHAVA.

        Com XOR, `[A, A, B]` produzia a impressão de `[B]`: o par se cancelava
        e o corpus dizia não conter A. A construção sequencial não tem essa
        álgebra, e além disso RECUSA — a duplicata vira erro no lugar em que
        acontece, e não uma impressão errada meses depois.
        """
        construtor = CorpusFingerprintBuilder(scope=escopo())
        primeiro = membros(2)[0]
        construtor.add(primeiro)
        with pytest.raises(ValidationError, match="estritamente crescente"):
            construtor.add(primeiro)

    def test_a_sequencia_com_repetido_nao_colide_com_a_sem(self) -> None:
        """§19, no nível da PRIMITIVA. Mesmo sem a guarda de ordem, a
        serialização de `[A, A, B]` e a de `[A, B]` são cadeias diferentes —
        que é exatamente o que o XOR não garantia."""
        import hashlib

        a, b = membros(2)
        sem = hashlib.sha256(
            frame(b"member", member_payload(a)) + frame(b"member", member_payload(b))
        ).hexdigest()
        com = hashlib.sha256(
            frame(b"member", member_payload(a))
            + frame(b"member", member_payload(a))
            + frame(b"member", member_payload(b))
        ).hexdigest()
        assert sem != com

    def test_ordem_fora_de_sequencia_e_recusada(self) -> None:
        """A leitura desordenada FALHA em vez de mudar a impressão em silêncio."""
        construtor = CorpusFingerprintBuilder(scope=escopo())
        conjunto = membros(3)
        construtor.add(conjunto[2])
        with pytest.raises(ValidationError, match="estritamente crescente"):
            construtor.add(conjunto[0])

    # --------------------------------------------------------- framing --

    def test_o_enquadramento_impede_colisao_por_concatenacao(self) -> None:
        """§7. Sem prefixo de tamanho, `"AB"+"C"` e `"A"+"BC"` colidem."""
        assert frame(b"m", b"AB") + frame(b"m", b"C") != frame(b"m", b"A") + frame(b"m", b"BC")

    def test_o_separador_de_dominio_esta_no_inicio(self) -> None:
        """§8. A construção não é reaproveitável por acidente para outro
        domínio — o prefixo entra antes de qualquer conteúdo."""
        import hashlib

        vazio_com_dominio = CorpusFingerprintBuilder(scope=escopo()).finish(MembershipCounts())
        sem_dominio = hashlib.sha256()
        sem_dominio.update(
            frame(
                b"header",
                canonical_json(
                    {
                        "algorithm": FINGERPRINT_ALGORITHM,
                        "schema_version": FINGERPRINT_SCHEMA_VERSION,
                        "scope": escopo().as_canonical(),
                    }
                ),
            )
        )
        sem_dominio.update(
            frame(b"trailer", canonical_json({"counts": MembershipCounts().as_canonical()}))
        )
        assert vazio_com_dominio.value != sem_dominio.hexdigest()

    # ------------------------------------------------------- semântica --

    def test_escopo_de_uso_diferente_muda_a_impressao(self) -> None:
        """Pesquisa e comércio publicam conteúdos diferentes; o escopo de uso
        entra no cabeçalho para que isso apareça mesmo com membros iguais."""
        conjunto = membros(3)
        assert fingerprint_of(conjunto, scope=escopo(UsageScope.RESEARCH)) != fingerprint_of(
            conjunto, scope=escopo(UsageScope.COMMERCIAL)
        )

    def test_a_contagem_precisa_bater_com_o_que_foi_absorvido(self) -> None:
        """Um rodapé que discorde do corpo é defeito, e ele aparece aqui em
        vez de aparecer meses depois numa consulta."""
        construtor = CorpusFingerprintBuilder(scope=escopo())
        for membro in membros(3):
            construtor.add(membro)
        with pytest.raises(ValidationError, match="declaram"):
            construtor.finish(MembershipCounts(matches=2))

    def test_o_algoritmo_e_a_versao_do_contrato_sao_nomeados(self) -> None:
        """§20. Uma impressão do XOR e uma desta construção são dois hex de 64
        caracteres; sem o nome, compará-las diria «corpus diferente» sem
        explicação."""
        assert FINGERPRINT_ALGORITHM == "canonical-sha256-v1"
        assert FINGERPRINT_SCHEMA_VERSION == "1.0"

    def test_a_impressao_e_estavel_entre_execucoes(self) -> None:
        """§82, §90. O mesmo conteúdo, calculado duas vezes, dá o mesmo valor —
        e é isto que um valor dourado protegeria contra mudança acidental da
        serialização sem subir a versão do contrato."""
        assert fingerprint_of(membros(4), scope=escopo()) == fingerprint_of(
            membros(4), scope=escopo()
        )


class TestOManifesto:
    @staticmethod
    def _manifesto(**ajustes: object) -> HistoricalCanonicalManifest:
        base: dict[str, object] = {
            "id": "man-1",
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset_id": DATASET_ID,
            "dataset_name": dataset().name,
            "dataset_version": versao_rascunho().version,
            "dataset_version_id": "v-1",
            "scope": escopo(),
            "inputs": entradas(),
            "counts": MembershipCounts(matches=2, by_family={"MATCH": 2}),
            "coverage": (
                FamilyCoverageSummary(
                    family="MATCH",
                    state=CoverageState.MEASURED.value,
                    matches_with_data=2,
                    matches_total=2,
                    available_total=2,
                    expected_total=2,
                ),
            ),
            "quality": QualitySummary(worst_integrity=0.97, eligible=2),
            "license": LicenseSummary(
                usage_scope=UsageScope.RESEARCH.value,
                licenses_present=("PUBLIC_DOMAIN",),
            ),
            "issues": IssueSummary(),
            "corpus_fingerprint": ContentHash("f" * 64),
            "created_at": AGORA,
        }
        base.update(ajustes)
        return HistoricalCanonicalManifest(**base)  # type: ignore[arg-type]

    def test_a_serializacao_e_deterministica(self) -> None:
        assert self._manifesto().to_json() == self._manifesto().to_json()

    def test_as_duas_impressoes_sao_coisas_diferentes(self) -> None:
        """§57. `manifest_sha256` é o hash dos BYTES; `corpus_fingerprint`, do
        CONTEÚDO. Confundi-las é caro: a primeira muda com o carimbo de tempo
        e a segunda não pode mudar."""
        manifesto = self._manifesto()
        assert manifesto.manifest_sha256 != manifesto.corpus_fingerprint

    def test_um_schema_desconhecido_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="schema"):
            self._manifesto(schema_version="0.9")

    def test_a_cobertura_nao_declarada_nao_vira_zero_por_cento(self) -> None:
        """§24. «As fontes não trabalham com eventos» e «prometeram e não veio
        nada» exigem ações opostas."""
        nao_declarada = FamilyCoverageSummary(
            family="EVENT", state=CoverageState.NOT_DECLARED.value, matches_total=10
        )
        assert nao_declarada.ratio is None
        medida = FamilyCoverageSummary(
            family="EVENT",
            state=CoverageState.MEASURED.value,
            matches_with_data=0,
            matches_total=10,
            expected_total=10,
        )
        assert medida.ratio == 0.0

    def test_o_manifesto_nao_vira_o_corpus(self) -> None:
        """§27. Despejar um milhão de problemas no manifesto o transformaria
        no corpus que ele descreve."""
        with pytest.raises(ValidationError, match="exemplos"):
            IssueSummary(examples=tuple(f"P{i}" for i in range(MAX_ISSUE_EXAMPLES + 1)))

    def test_a_cobertura_recusa_subconjunto_maior_que_o_conjunto(self) -> None:
        with pytest.raises(ValidationError, match="maior que o conjunto"):
            FamilyCoverageSummary(
                family="MATCH",
                state=CoverageState.MEASURED.value,
                matches_with_data=11,
                matches_total=10,
                expected_total=10,
            )
