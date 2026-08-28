"""O E2E do PR-06.3 — janela, movimento e evidência sobre dados reais.

PostgreSQL 17 e object store de verdade, dataset normalizado `READY`, corpus
construído pelo caminho INTEIRO.

O CENÁRIO TEM HISTÓRIA TEMPORAL DE PROPÓSITO (§178 ao §183), e a medição está
no cabeçalho de `trajectory_scenario`:

    perfil     15 eixos (12 de xG em janela móvel + 3 de contexto)
    espaço     `n = 3 x 15 = 45` células
    piso       `5s >= 135`  ->  `s >= 27`, e `>= 2` horizontes evidenciais

    minuto 47   UM horizonte     ->  a query é RECUSADA
    minuto 49   DOIS horizontes  ->  admitida, com 30 células
    minuto 51+  TRÊS horizontes  ->  admitida, com 45 células

E ELE TEM MOVIMENTO. As curvas de xG sobem numa partida, descem noutra e ficam
em patamar na terceira — é isso que faz a discriminação de direção existir
sobre dados reais, e não só sobre valores escritos à mão.
"""

from __future__ import annotations

from typing import Any

import pytest

from sports_intelligence.domain.retrieval.candidate_policy import IneligibilityReason
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    QueryInsufficientTrajectoryEvidenceError,
    TrajectoryCoveragePolicy,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    SlotStatus,
    TrajectoryNotApplicableError,
)
from sports_intelligence.domain.shared.temporal import Period

pytestmark = pytest.mark.integration

K = 5

#: Os minutos do segundo tempo que o E2E ancora. Ver o cabeçalho.
MINUTOS = (47, 49, 51, 60, 75)


@pytest.fixture
async def trajetorias(database: Any, object_store: Any) -> dict[str, Any]:
    """Corpus com movimento → dataset normalizado `READY` → contêiner."""
    from tests.support.trajectory_e2e import ancoras_por_minuto, dataset_com_movimento

    dados = await dataset_com_movimento(database, object_store)
    dados["ancoras"] = await ancoras_por_minuto(
        dados["conteiner"].source,
        dataset_name="match-state-normalized",
        version=str(dados["versao_n"].version),
        minutos=MINUTOS,
    )
    return dados


def _chave(trajetorias: dict[str, Any], minuto: int) -> Any:
    ancoras = trajetorias["ancoras"]
    assert minuto in ancoras, f"o cenário precisa de uma âncora no minuto {minuto}"
    return ancoras[minuto]


# ================================================= a pré-condição ==


class TestOCenarioTemHistoriaEMovimento:
    """§178, §179 — sem isto, os outros testes não provam nada."""

    async def test_a_escada_de_horizontes_existe(self, trajetorias: dict[str, Any]) -> None:
        """§181, §182, §183 — três, dois e um horizonte, no mesmo dataset."""
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        estruturais: dict[int, int] = {}
        for minuto in MINUTOS:
            contexto = await conteiner.retrieve_trajectory.resolve(
                version_id=versao.id, key=_chave(trajetorias, minuto)
            )
            estruturais[minuto] = len(contexto.targets)
        assert estruturais[47] == 1
        assert estruturais[49] == 2
        assert estruturais[51] == 3
        assert estruturais[75] == 3

    async def test_as_curvas_se_MOVEM(self, trajetorias: dict[str, Any]) -> None:
        """§179 — se todo `Δ` fosse zero, o PR não teria o que medir."""
        conteiner = trajetorias["conteiner"]
        contexto = await conteiner.retrieve_trajectory.resolve(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75)
        )
        deslocamentos = [d for d in contexto.representation.displacements if d is not None]
        assert deslocamentos
        movendo = [d for d in deslocamentos if d != 0.0]
        assert len(movendo) >= len(deslocamentos) // 2, (
            "quase toda célula tem deslocamento zero: as curvas do cenário não se "
            f"movem entre os instantes da janela — {deslocamentos}"
        )

    async def test_ha_movimento_em_DIRECOES_opostas_no_universo(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """A matéria-prima do golden de discriminação, sobre dados reais."""
        conteiner = trajetorias["conteiner"]
        contexto = await conteiner.retrieve_trajectory.resolve(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75)
        )
        candidatos = await conteiner.retrieve_trajectory._candidatos(contexto, None)
        sinais: set[int] = set()
        for candidato in candidatos:
            for valor in candidato.representation.displacements:
                if valor is not None and valor != 0.0:
                    sinais.add(1 if valor > 0 else -1)
        assert sinais == {1, -1}, (
            "o universo só tem movimento numa direção: a discriminação de direção "
            "não teria o que separar"
        )

    async def test_ha_celulas_parcialmente_indisponiveis(self, trajetorias: dict[str, Any]) -> None:
        """§179 — «parcialmente unavailable» também é uma das curvas pedidas."""
        conteiner = trajetorias["conteiner"]
        contexto = await conteiner.retrieve_trajectory.resolve(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75)
        )
        candidatos = await conteiner.retrieve_trajectory._candidatos(contexto, None)
        coberturas = {c.representation.usable_count for c in candidatos}
        assert len(coberturas) > 1, f"toda trajetória tem a mesma cobertura — {coberturas}"


# ================================================= a janela ==


class TestAJanelaSobreDadosReais:
    """§16, §17, §153 — o intervalo, medido no dataset."""

    async def test_no_minuto_49_o_horizonte_de_cinco_fica_fora(
        self, trajetorias: dict[str, Any]
    ) -> None:
        contexto = await trajetorias["conteiner"].retrieve_trajectory.resolve(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 49)
        )
        por_horizonte = {s.horizon_minutes: s for s in contexto.slots}
        assert por_horizonte[1].status is SlotStatus.AVAILABLE
        assert por_horizonte[3].status is SlotStatus.AVAILABLE
        assert por_horizonte[5].status is SlotStatus.OUTSIDE_PERIOD_LOOKBACK
        # E NENHUM ALVO CAI NO PRIMEIRO TEMPO.
        assert all(alvo.period is Period.SECOND_HALF for alvo in contexto.targets)
        assert all(alvo.minute >= 46 for alvo in contexto.targets)

    async def test_no_minuto_47_a_query_e_RECUSADA(self, trajetorias: dict[str, Any]) -> None:
        """§83, §154 — um horizonte não descreve movimento, e não há fallback."""
        with pytest.raises(QueryInsufficientTrajectoryEvidenceError) as erro:
            await trajetorias["conteiner"].retrieve_trajectory.execute(
                version_id=trajetorias["versao_n"].id,
                key=_chave(trajetorias, 47),
                k=K,
            )
        assert erro.value.reason == "QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE"
        assert erro.value.assessment.query_usable_horizons == 1

    async def test_a_recusa_da_query_NAO_le_o_universo(self, trajetorias: dict[str, Any]) -> None:
        """§82 — a lição do PR-06.2, aplicada antes de o defeito existir."""
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]

        conteiner.trajectory_source.reset_counters()
        await conteiner.retrieve_trajectory.resolve(
            version_id=versao.id, key=_chave(trajetorias, 47)
        )
        so_a_query = conteiner.trajectory_source.objects_read

        conteiner.trajectory_source.reset_counters()
        with pytest.raises(QueryInsufficientTrajectoryEvidenceError):
            await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=_chave(trajetorias, 47), k=K
            )
        assert conteiner.trajectory_source.objects_read == so_a_query

    async def test_o_PRE_MATCH_nao_tem_trajetoria(self, trajetorias: dict[str, Any]) -> None:
        """§24, §155 — e o tipo do erro diz que tentar de novo não adianta."""
        from tests.support.retrieval_e2e import queries_disponiveis

        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        queries = await queries_disponiveis(
            conteiner.source,
            dataset_name="match-state-normalized",
            version=str(versao.version),
            limite=200,
        )
        pre_jogo = [chave for chave, instante in queries if instante.period is Period.PRE_MATCH]
        assert pre_jogo, "o cenário precisa ter cortes de pré-jogo"
        with pytest.raises(TrajectoryNotApplicableError) as erro:
            await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=pre_jogo[0], k=K)
        assert erro.value.reason == "TRAJECTORY_NOT_APPLICABLE"


# ================================================= o universo ==


class TestOUniversoEhOMesmoDoPR062:
    """§6, §7, §236 — a trajetória muda COMO, e não QUEM."""

    async def test_a_impressao_do_universo_e_identica(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)

        do_estado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        da_trajetoria = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=chave, k=K
        )
        assert (
            da_trajetoria.candidate_universe_fingerprint == do_estado.candidate_universe_fingerprint
        )
        assert da_trajetoria.universe_count == do_estado.universe_count
        assert da_trajetoria.candidate_policy_fingerprint == do_estado.candidate_policy_fingerprint

    async def test_os_eixos_base_sao_os_mesmos(self, trajetorias: dict[str, Any]) -> None:
        """§34, §35 — a condição para a comparação significar alguma coisa."""
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)

        do_estado = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        da_trajetoria = await conteiner.retrieve_trajectory.resolve(version_id=versao.id, key=chave)
        assert da_trajetoria.profile.feature_keys == do_estado.resolution.profile.feature_keys
        assert da_trajetoria.profile.cell_count == 3 * do_estado.resolution.profile.axis_count


# ================================================= a atrição ==


class TestAAtricaoTemporal:
    """§117, §189 — cada candidato cai numa das três contagens."""

    async def test_a_soma_fecha_com_o_universo(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        for minuto in (49, 51, 60, 75):
            resultado = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=_chave(trajetorias, minuto), k=K
            )
            assert (
                resultado.trajectory_eligible_count
                + resultado.trajectory_ineligible_count
                + resultado.structural_ineligible_count
            ) == resultado.universe_count
            assert resultado.exhaustive

    async def test_o_minuto_49_recusa_mais_que_o_51(self, trajetorias: dict[str, Any]) -> None:
        """§36, §193 — a atrição de começo de período, sobre dados reais.

        Com dois horizontes em vez de três, o par tem no máximo `2m` células de
        `3m`, e os candidatos com contexto ausente caem abaixo do piso.
        """
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        cedo = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 49), k=50
        )
        tarde = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 51), k=50
        )
        assert cedo.universe_count == tarde.universe_count
        assert cedo.trajectory_eligible_count < tarde.trajectory_eligible_count
        assert cedo.trajectory_ineligible_count > 0

        # OS TRÊS MOTIVOS DE TRAJETÓRIA SÃO EXCLUSIVOS E EXAUSTIVOS. Cada
        # candidato recusado recebe UM deles — `refusal_reason` devolve o
        # primeiro piso que falhou, na ordem relógio -> feature —, logo a soma
        # fecha com a contagem sem sobreposição.
        DE_TRAJETORIA = (
            IneligibilityReason.INSUFFICIENT_SHARED_TRAJECTORY_CELLS,
            IneligibilityReason.INSUFFICIENT_SHARED_HORIZONS,
            IneligibilityReason.INSUFFICIENT_PER_HORIZON_COVERAGE,
        )
        somados = sum(cedo.ineligible.get(motivo.value, 0) for motivo in DE_TRAJETORIA)
        assert somados == cedo.trajectory_ineligible_count

        # E O MOTIVO DE ESTADO NÃO APARECE MAIS AQUI. Antes do adendo os três
        # fenômenos vinham sob `INSUFFICIENT_SHARED_COVERAGE`, e a causa da
        # recusa era ilegível: «poucas células» e «só um horizonte» somavam no
        # mesmo balde. Esta asserção é o que impede o balde de voltar.
        assert IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE.value not in cedo.ineligible

    async def test_nenhum_vizinho_devolvido_esta_abaixo_do_piso(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """§86, §247 — e o piso é EFETIVO, não o mínimo absoluto.

        O NÚMERO É VINTE E SETE, e não oito. No perfil real da competição
        (`m = 15`, `n = 45`) o piso racional `ceil(135/5)` supera o mínimo
        absoluto em dezenove células, e é ele que decide todo par. Afirmar só
        `meets_shared_floor` esconderia qual dos dois pisos está agindo — e é
        exatamente essa distinção que o adendo existe para tornar explícita.
        """
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        for minuto in (49, 51, 75):
            resultado = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=_chave(trajetorias, minuto), k=50
            )
            for vizinho in resultado.neighbors:
                cobertura = vizinho.evidence.coverage
                assert cobertura.meets_shared_floor
                assert cobertura.refusal_reason is None
                assert vizinho.shared_horizons >= 2
                # O PISO EFETIVO, POR NÚMERO — e o vizinho o satisfaz.
                piso = vizinho.evidence.effective_shared_cell_floor
                assert piso == max(8, -((-3 * cobertura.cell_count) // 5))
                assert vizinho.evidence.shared_cell_count >= piso
                assert vizinho.evidence.margin_over_shared_cell_floor >= 0

    async def test_o_piso_efetivo_do_corpus_e_o_RACIONAL_e_vale_27(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """§25 do adendo — a tabela da competição, sobre o corpus real.

        ESTE É O TESTE QUE IMPEDE A FRASE «oito células bastam» DE VOLTAR. Ele
        lê `m` do perfil resolvido do corpus, e não de uma constante de teste:
        se o perfil mudar, o piso muda junto, e a afirmação continua sendo
        sobre o que o motor realmente aplica.
        """
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 75), k=50
        )
        assert resultado.neighbors
        cobertura = resultado.neighbors[0].evidence.coverage
        assert cobertura.axis_count == 15
        assert cobertura.total_trajectory_cells == 45

        pisos = DEFAULT_TRAJECTORY_COVERAGE.floors(cobertura.axis_count)
        assert pisos.absolute_shared_cell_floor == 8
        assert pisos.ratio_shared_cell_floor == 27
        assert pisos.effective_shared_cell_floor == 27
        assert pisos.effective_horizon_axis_floor == 9
        assert pisos.shared_floor_is_rational

        # E A DIFERENÇA É DE DEZENOVE CÉLULAS: um par com dez compartilhadas
        # passaria pelo mínimo absoluto e é recusado pelo piso que decide.
        assert not DEFAULT_TRAJECTORY_COVERAGE.admits_pair(
            shared_cells=10, cell_count=45, shared_horizons=2
        )


# ================================================= o determinismo ==


class TestODeterminismoSobreOParquetReal:
    """§168 ao §172."""

    async def test_duas_execucoes_dao_a_mesma_impressao(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)
        primeira = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=K)
        segunda = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=K)
        assert primeira.fingerprint == segunda.fingerprint
        assert primeira.query_trajectory_fingerprint == segunda.query_trajectory_fingerprint
        assert [v.evidence.fingerprint for v in primeira.neighbors] == [
            v.evidence.fingerprint for v in segunda.neighbors
        ]

    @pytest.mark.parametrize("lote", [1, 3, 4096])
    async def test_o_lote_nao_muda_o_resultado(
        self, trajetorias: dict[str, Any], lote: int
    ) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)
        esperado = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=K)
        obtido = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=chave, k=K, batch_rows=lote
        )
        assert obtido.fingerprint == esperado.fingerprint

    async def test_o_prefixo_do_K_vale(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)
        grande = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=50)
        for k in (1, 2, 3):
            if k > grande.returned_k:
                break
            pequeno = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=chave, k=k
            )
            assert [v.anchor_key.text for v in grande.top(k)] == [
                v.anchor_key.text for v in pequeno.neighbors
            ]


# ================================================= a leitura ==


class TestNaoHaLeituraNMaisUm:
    """§129, §210, §245 — a prova de NÚMERO, e não só de forma."""

    async def test_os_objetos_lidos_NAO_crescem_com_os_candidatos(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """A razão que denuncia o N+1.

        Com uma varredura por partição, `objetos` é constante e `linhas`
        cresce com os candidatos. Com `candidato x horizonte`, os dois
        cresceriam juntos — e a razão entre eles ficaria fixa.
        """
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]

        conteiner.trajectory_source.reset_counters()
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 75), k=K
        )
        objetos = conteiner.trajectory_source.objects_read
        linhas = conteiner.trajectory_source.source_rows_read

        assert resultado.universe_count > 0
        assert linhas >= resultado.universe_count, (
            "menos linhas que candidatos: a âncora de alguém não foi lida"
        )
        # O NÚMERO QUE IMPORTA: muito menos objetos que `candidatos x horizontes`.
        assert objetos < resultado.universe_count, (
            f"{objetos} objetos para {resultado.universe_count} candidatos: o padrão "
            "N+1 leria pelo menos um por candidato"
        )

    async def test_as_linhas_lidas_sao_ancora_mais_lookback(
        self, trajetorias: dict[str, Any]
    ) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        contexto = await conteiner.retrieve_trajectory.resolve(
            version_id=versao.id, key=_chave(trajetorias, 75)
        )
        conteiner.trajectory_source.reset_counters()
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 75), k=K
        )
        linhas = conteiner.trajectory_source.source_rows_read
        # `candidatos x (1 + horizontes estruturais)`, mais as da query.
        por_candidato = 1 + len(contexto.targets)
        assert linhas <= resultado.universe_count * por_candidato + por_candidato


# ================================================= a evidência ==


class TestAEvidenciaSobreDadosReais:
    """§110, §111, §242."""

    async def test_toda_evidencia_reconstroi_a_conta(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        vistos = 0
        for minuto in (51, 60, 75):
            resultado = await conteiner.retrieve_trajectory.execute(
                version_id=versao.id, key=_chave(trajetorias, minuto), k=K
            )
            for vizinho in resultado.neighbors:
                vistos += 1
                prova = vizinho.evidence
                assert prova.is_reconstructible
                assert (
                    prova.observed_sum + prova.missing_penalty_sum
                ) / resultado.cell_count == vizinho.trajectory_dissimilarity
                assert prova.missing_penalty_sum == float(
                    resultado.cell_count - vizinho.shared_cells
                )
        assert vistos > 0

    async def test_a_abertura_por_horizonte_existe_e_soma(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """§111 — e ela é o insumo do estudo de ponderação temporal."""
        conteiner = trajetorias["conteiner"]
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75), k=K
        )
        for vizinho in resultado.neighbors:
            conta = vizinho.evidence.breakdown
            assert [c.horizon_minutes for c in conta.horizons] == [1, 3, 5]
            assert sum(c.observed for c in conta.horizons) == pytest.approx(conta.observed_sum)

    async def test_ha_REVERSAO_no_top_K(self, trajetorias: dict[str, Any]) -> None:
        """O fenômeno que o PR existe para separar, contado sobre dados reais."""
        conteiner = trajetorias["conteiner"]
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75), k=50
        )
        reversoes = sum(v.evidence.reversals for v in resultado.neighbors)
        assert reversoes > 0, (
            "nenhuma célula do top-K tem movimento em direções opostas: o cenário "
            "perdeu a variedade de direção"
        )


# ================================================= estado x trajetória ==


class TestEstadoETrajetoriaSaoSinaisDIFERENTES:
    """§148, §195, §239 — e os dois números nunca são somados."""

    async def test_os_dois_rankings_podem_diferir(self, trajetorias: dict[str, Any]) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        diferiram = 0
        for minuto in (51, 60, 75):
            lado_a_lado = await conteiner.compare_state_trajectory.execute(
                version_id=versao.id, key=_chave(trajetorias, minuto), k=K
            )
            assert lado_a_lado.state is not None
            assert lado_a_lado.trajectory is not None
            do_estado = [v.key.text for v in lado_a_lado.state.neighbors]
            da_trajetoria = [v.anchor_key.text for v in lado_a_lado.trajectory.neighbors]
            if do_estado != da_trajetoria:
                diferiram += 1
            assert lado_a_lado.top_k_overlap is not None
        assert diferiram > 0, (
            "os dois rankings coincidiram em toda query: ou o cenário não tem "
            "movimento, ou a trajetória está medindo nível"
        )

    async def test_o_comparador_NAO_devolve_score_combinado(
        self, trajetorias: dict[str, Any]
    ) -> None:
        """§4, §147, §258."""
        lado_a_lado = await trajetorias["conteiner"].compare_state_trajectory.execute(
            version_id=trajetorias["versao_n"].id, key=_chave(trajetorias, 75), k=K
        )
        campos = set(lado_a_lado.summary())
        assert not campos & {"combined", "total_score", "d_total", "score"}


# ================================================= o piso ==


class TestOPisoTemporalDecideSobreDadosReais:
    """§202 — a sensibilidade, executável."""

    async def test_exigir_TRES_horizontes_recusa_o_minuto_49(
        self, trajetorias: dict[str, Any]
    ) -> None:
        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        # OS DOIS PISOS PRECISAM SER COERENTES, e o construtor obriga: com
        # três horizontes exigidos e quatro eixos por horizonte, o mínimo de
        # células não pode ser oito. Deixá-lo em oito faria o piso de células
        # nunca ter efeito, e o validador recusa a política — corretamente.
        estrito = TrajectoryCoveragePolicy(
            name="TRES_HORIZONTES",
            minimum_usable_horizons=3,
            minimum_shared_horizons=3,
            minimum_query_trajectory_cells=12,
            minimum_shared_trajectory_cells=12,
        )
        with pytest.raises(QueryInsufficientTrajectoryEvidenceError):
            await conteiner.retrieve_trajectory.execute(
                version_id=versao.id,
                key=_chave(trajetorias, 49),
                k=K,
                coverage_policy=estrito,
            )
        # E O MINUTO 51 CONTINUA PASSANDO — o piso separa os dois.
        resultado = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id, key=_chave(trajetorias, 51), k=K, coverage_policy=estrito
        )
        assert resultado.returned_k > 0

    async def test_um_piso_de_celulas_mais_alto_recusa_mais(
        self, trajetorias: dict[str, Any]
    ) -> None:
        from sports_intelligence.domain.retrieval.coverage import RationalFloor

        conteiner = trajetorias["conteiner"]
        versao = trajetorias["versao_n"]
        chave = _chave(trajetorias, 75)
        padrao = await conteiner.retrieve_trajectory.execute(version_id=versao.id, key=chave, k=50)
        estrito = await conteiner.retrieve_trajectory.execute(
            version_id=versao.id,
            key=chave,
            k=50,
            coverage_policy=TrajectoryCoveragePolicy(
                name="TUDO_OU_NADA",
                shared_trajectory_coverage_floor=RationalFloor(1, 1),
            ),
        )
        assert estrito.trajectory_eligible_count < padrao.trajectory_eligible_count
        assert all(v.is_complete for v in estrito.neighbors)
        # E O PISO ENTRA NA IMPRESSÃO.
        assert estrito.coverage_policy_fingerprint != padrao.coverage_policy_fingerprint
        assert estrito.distance_definition_fingerprint != padrao.distance_definition_fingerprint


# ================================================= a causalidade ==


class TestNenhumFatoCanonicoEhLido:
    """§32, §176 — medido por instrumentação."""

    async def test_nenhuma_tabela_de_fato_e_tocada(
        self, database: Any, trajetorias: dict[str, Any]
    ) -> None:
        proibidas = (
            "canonical_match_events",
            "canonical_odds_observations",
            "lineups",
            "lineup_entries",
            "match_results",
            "historical_canonical_members",
            "historical_canonical_event_members",
        )
        consultas: list[str] = []
        original = database.acquire

        class _Espiao:
            def __init__(self, conexao: Any) -> None:
                self._c = conexao

            def __getattr__(self, nome: str) -> Any:
                alvo = getattr(self._c, nome)
                if nome not in {"fetch", "fetchrow", "fetchval", "execute", "executemany"}:
                    return alvo

                async def _registrar(sql: str, *args: Any, **kwargs: Any) -> Any:
                    consultas.append(sql)
                    return await alvo(sql, *args, **kwargs)

                return _registrar

        class _Contexto:
            def __init__(self, interno: Any) -> None:
                self._i = interno

            async def __aenter__(self) -> Any:
                return _Espiao(await self._i.__aenter__())

            async def __aexit__(self, *args: Any) -> Any:
                return await self._i.__aexit__(*args)

        database.acquire = lambda: _Contexto(original())
        try:
            await trajetorias["conteiner"].retrieve_trajectory.execute(
                version_id=trajetorias["versao_n"].id,
                key=_chave(trajetorias, 75),
                k=K,
            )
        finally:
            database.acquire = original

        assert consultas, "a instrumentação não capturou consulta nenhuma"
        for sql in consultas:
            for tabela in proibidas:
                assert tabela not in sql.lower(), f"leu {tabela}: {sql[:120]}"
