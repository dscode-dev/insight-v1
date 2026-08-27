"""As invariantes da recuperação ciente de disponibilidade.

CADA TESTE AQUI PROVA UMA AFIRMAÇÃO SOBRE UM CONJUNTO DE ENTRADAS, e não um
caso. A diferença importa: «esta query devolve estes cinco vizinhos» é um
golden, e «nenhuma ordem de leitura muda o resultado» é uma propriedade — a
segunda pega os defeitos que o cenário do golden não tem.

    §132  fronteiras do piso · ausência ≠ zero · penalidade exata ·
          denominador fixo · equivalência de caso completo · simetria ·
          determinismo de ordem, de lote e de prefixo · isolamento entre
          competições · independência da avaliação

O CONTRA-EXEMPLO É CONSTRUÍDO, E NÃO SORTEADO. Um gerador aleatório encontraria
os mesmos defeitos com menos garantia e mais tempo de execução; aqui cada
cenário existe porque um defeito específico o produziria.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence

import pytest

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability_exact import (
    AvailabilityAwareHistoricalRetriever,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.coverage import DEFAULT_COVERAGE_POLICY
from sports_intelligence.domain.retrieval.distance import DistanceDefinition
from sports_intelligence.domain.retrieval.exact import ExactHistoricalRetriever
from sports_intelligence.domain.retrieval.query import QuerySnapshot
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from tests.support.availability_fixtures import (
    CINCO_EIXOS,
    DEZ_EIXOS,
    candidato_ciente,
    consulta_ciente,
    distancia_ciente,
    pedido_ciente,
    perfil_ciente,
    primeiros,
    recuperador,
)
from tests.support.retrieval_fixtures import (
    LIGA_A,
    LIGA_B,
    OUTRA_IMPRESSAO,
    perfil,
)

pytestmark = pytest.mark.property

REFERENCIA = "r" * 64
OUTRA_REFERENCIA = "s" * 64


def _executar(
    candidatos: Sequence[CandidateRow],
    *,
    k: int = 5,
    snapshot: QuerySnapshot | None = None,
    reference: str = REFERENCIA,
    retriever: AvailabilityAwareHistoricalRetriever | None = None,
) -> AvailabilityAwareRetrievalResult:
    alvo = retriever or recuperador()
    return alvo.retrieve(
        query=pedido_ciente(k=k),
        snapshot=snapshot or consulta_ciente(),
        candidates=list(candidatos),
        reference_content_fingerprint=reference,
    )


def _populacao(n: int = 24) -> list[CandidateRow]:
    """Candidatos variados: completos, parciais e abaixo do piso.

    O SORTEIO É SEMEADO E FIXO, e por isso a população é a mesma em toda
    execução — o que varia nos testes é a ORDEM em que ela é percorrida, e é
    isso que as propriedades medem.
    """
    sorteio = random.Random(20260826)
    linhas: list[CandidateRow] = []
    for i in range(n):
        compartilhados = (5, 5, 4, 3, 2)[i % 5]
        valores = {
            chave: round(sorteio.uniform(-2.0, 2.0), 3) for chave in CINCO_EIXOS[:compartilhados]
        }
        linhas.append(candidato_ciente(match=f"ref-{i:03d}", valores=valores))
    return linhas


# ================================================= determinismo ==


class TestONumeroNaoDependeDaOrdemDeLeitura:
    """§136 — o resultado é do CONJUNTO, e não da sequência."""

    def test_dez_permutacoes_produzem_a_mesma_impressao(self) -> None:
        populacao = _populacao()
        base = _executar(populacao)
        sorteio = random.Random(7)
        for _ in range(10):
            embaralhado = populacao[:]
            sorteio.shuffle(embaralhado)
            assert _executar(embaralhado).fingerprint == base.fingerprint

    def test_a_ordem_inversa_produz_a_mesma_impressao(self) -> None:
        populacao = _populacao()
        assert _executar(list(reversed(populacao))).fingerprint == _executar(populacao).fingerprint

    def test_e_as_contagens_de_atricao_tambem(self) -> None:
        populacao = _populacao()
        base = _executar(populacao)
        invertido = _executar(list(reversed(populacao)))
        assert invertido.coverage_eligible_count == base.coverage_eligible_count
        assert invertido.coverage_ineligible_count == base.coverage_ineligible_count
        assert invertido.universe_count == base.universe_count


class TestOTamanhoDoLoteNaoImporta:
    """§135 — a leitura é em fluxo, e o fluxo não pode decidir o ranking."""

    @pytest.mark.parametrize("lote", [1, 7, 128, 512, 2048, 4096])
    def test_todos_os_lotes_dao_o_mesmo_resultado(self, lote: int) -> None:
        populacao = _populacao(40)

        def _em_lotes() -> Iterator[CandidateRow]:
            for inicio in range(0, len(populacao), lote):
                yield from populacao[inicio : inicio + lote]

        esperado = _executar(populacao)
        alvo = recuperador()
        obtido = alvo.retrieve(
            query=pedido_ciente(k=5),
            snapshot=consulta_ciente(),
            candidates=_em_lotes(),
            reference_content_fingerprint=REFERENCIA,
        )
        assert obtido.fingerprint == esperado.fingerprint


class TestOPrefixoDoK:
    """§133 — `top10(K=50)` é o resultado de `K=10`, empates inclusive."""

    def test_o_prefixo_vale_na_populacao_geral(self) -> None:
        populacao = _populacao(40)
        grande = _executar(populacao, k=20)
        for k in (1, 3, 7, 10):
            pequeno = _executar(populacao, k=k)
            assert [v.key.text for v in grande.top(k)] == [v.key.text for v in pequeno.neighbors]
            assert [v.dissimilarity for v in grande.top(k)] == [
                v.dissimilarity for v in pequeno.neighbors
            ]

    def test_o_prefixo_vale_COM_EMPATE_EXATAMENTE_NO_CORTE(self) -> None:
        """O caso que um `<` no lugar de um `<=` quebraria.

        SEIS CANDIDATOS COM O MESMO `D` E A MESMA COBERTURA. Com `K = 3`, o
        terceiro e o quarto empatam nos dois primeiros critérios, e só a chave
        canônica os separa. Um heap que invertesse a chave errado devolveria
        os três candidatos certos em ordem trocada — ou três candidatos
        errados.
        """
        iguais = [candidato_ciente(match=f"ref-{letra}") for letra in "abcdef"]
        grande = _executar(iguais, k=6)
        assert len({v.dissimilarity for v in grande.neighbors}) == 1
        for k in (1, 2, 3, 4, 5):
            pequeno = _executar(iguais, k=k)
            assert [v.key.text for v in grande.top(k)] == [v.key.text for v in pequeno.neighbors]

    def test_o_prefixo_vale_com_empate_de_D_e_coberturas_diferentes(self) -> None:
        """O empate que a COBERTURA desempata, no corte do `K`.

        Todos com `D = 1/5`: três com cinco eixos e `δ² = 1` num deles, três
        com quatro eixos exatos. Com `K = 3`, o corte cai exatamente entre os
        dois grupos.
        """
        com_cinco = [
            candidato_ciente(
                match=f"ref-cheio-{i}",
                valores={**dict.fromkeys(CINCO_EIXOS, 0.0), CINCO_EIXOS[4]: 1.0},
            )
            for i in range(3)
        ]
        com_quatro = [
            candidato_ciente(match=f"ref-parcial-{i}", valores=primeiros(4)) for i in range(3)
        ]
        populacao = [*com_quatro, *com_cinco]
        grande = _executar(populacao, k=6)
        assert {v.dissimilarity for v in grande.neighbors} == {0.2}
        assert [v.shared_count for v in grande.neighbors] == [5, 5, 5, 4, 4, 4]
        for k in (1, 2, 3, 4, 5):
            pequeno = _executar(populacao, k=k)
            assert [v.key.text for v in grande.top(k)] == [v.key.text for v in pequeno.neighbors]


# ================================================= exaustividade ==


class TestAVarreduraEhExaustiva:
    """§64, §65 — todo candidato é classificado, e nenhum é pulado."""

    def test_a_soma_das_tres_contagens_e_o_universo(self) -> None:
        populacao = _populacao(40)
        resultado = _executar(populacao, k=3)
        assert (
            resultado.coverage_eligible_count
            + resultado.coverage_ineligible_count
            + resultado.structural_ineligible_count
        ) == resultado.universe_count
        assert resultado.universe_count == len(populacao)

    def test_os_elegiveis_sao_MEDIDOS_e_nao_devolvidos(self) -> None:
        """`K = 1` sobre quarenta candidatos: um devolvido, muitos medidos."""
        populacao = _populacao(40)
        resultado = _executar(populacao, k=1)
        assert resultado.returned_k == 1
        assert resultado.coverage_eligible_count > 10
        assert resultado.exhaustive

    def test_o_melhor_candidato_pode_ser_o_ULTIMO_da_varredura(self) -> None:
        """Uma parada antecipada o perderia."""
        ruins = [
            candidato_ciente(match=f"ref-{i:03d}", valores=dict.fromkeys(CINCO_EIXOS, 5.0))
            for i in range(30)
        ]
        melhor = candidato_ciente(match="ref-zzz", valores=dict.fromkeys(CINCO_EIXOS, 0.0))
        resultado = _executar([*ruins, melhor], k=1)
        assert resultado.neighbors[0].key.match_key == "ref-zzz"
        assert resultado.neighbors[0].dissimilarity == 0.0

    def test_o_candidato_abaixo_do_piso_e_CONTADO_e_nao_pulado(self) -> None:
        """§65 — a atrição por cobertura tem de ser exata."""
        populacao = [
            *[candidato_ciente(match=f"ref-o-{i}", valores=primeiros(2)) for i in range(7)],
            *[candidato_ciente(match=f"ref-c-{i}") for i in range(3)],
        ]
        resultado = _executar(populacao)
        assert resultado.universe_count == 10
        assert resultado.coverage_eligible_count == 3
        assert resultado.coverage_ineligible_count == 7
        assert resultado.ineligible[IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE.value] == 7


# ================================================= a equivalência ==


class TestEquivalenciaComOCasoCompleto:
    """§41, §42, §90 — no caso completo, o ranking é o mesmo do PR-06.1."""

    def _oraculo(self) -> ExactHistoricalRetriever:
        base = perfil(eixos=CINCO_EIXOS)
        return ExactHistoricalRetriever(
            policy=DEFAULT_CANDIDATE_POLICY,
            profile=base,
            distance=DistanceDefinition(profile=base),
        )

    def test_a_ordem_dos_completos_e_a_mesma_nos_dois(self) -> None:
        """A propriedade central deste PR.

        A POPULAÇÃO TEM DE TUDO — completos, parciais e abaixo do piso —, e a
        afirmação é sobre o SUBCONJUNTO completo: a ordem relativa dele no
        resultado ciente de disponibilidade é a mesma que o oráculo produz.
        """
        from tests.support.retrieval_fixtures import consulta, pedido

        sorteio = random.Random(31337)
        completos = [
            candidato_ciente(
                match=f"ref-cc-{i:03d}",
                valores={chave: round(sorteio.uniform(-2.0, 2.0), 4) for chave in CINCO_EIXOS},
            )
            for i in range(30)
        ]
        parciais = [
            candidato_ciente(match=f"ref-pp-{i:03d}", valores=primeiros(4, 0.3)) for i in range(10)
        ]
        ciente = _executar([*parciais, *completos], k=40)
        exato = self._oraculo().retrieve(
            query=pedido(k=40),
            snapshot=consulta(valores=dict.fromkeys(CINCO_EIXOS, 0.0)),
            candidates=completos,
            reference_content_fingerprint=REFERENCIA,
        )
        assert [v.key.text for v in ciente.complete_case_neighbors] == [
            v.key.text for v in exato.neighbors
        ]

    def test_e_o_numero_e_exatamente_d2_sobre_m(self) -> None:
        """§41 — `D_AA = d²/m` quando `s = m`."""
        from tests.support.retrieval_fixtures import consulta, pedido

        sorteio = random.Random(4242)
        completos = [
            candidato_ciente(
                match=f"ref-{i:03d}",
                valores={chave: round(sorteio.uniform(-2.0, 2.0), 4) for chave in CINCO_EIXOS},
            )
            for i in range(20)
        ]
        ciente = _executar(completos, k=20)
        exato = self._oraculo().retrieve(
            query=pedido(k=20),
            snapshot=consulta(valores=dict.fromkeys(CINCO_EIXOS, 0.0)),
            candidates=completos,
            reference_content_fingerprint=REFERENCIA,
        )
        por_chave = {v.key.text: v.squared_distance for v in exato.neighbors}
        for vizinho in ciente.neighbors:
            assert vizinho.dissimilarity == por_chave[vizinho.key.text] / 5

    def test_o_universo_e_o_MESMO_nos_dois(self) -> None:
        """§5, §6, §43, §101 — a política é a mesma, logo o universo é o mesmo."""
        from tests.support.retrieval_fixtures import consulta, pedido

        populacao = _populacao(24)
        ciente = _executar(populacao, k=5)
        exato = self._oraculo().retrieve(
            query=pedido(k=5),
            snapshot=consulta(valores=dict.fromkeys(CINCO_EIXOS, 0.0)),
            candidates=populacao,
            reference_content_fingerprint=REFERENCIA,
        )
        assert ciente.candidate_universe_fingerprint == exato.candidate_universe_fingerprint
        assert ciente.universe_count == exato.universe_count
        assert ciente.candidate_policy_fingerprint == exato.candidate_policy_fingerprint

    def test_a_recuperacao_de_candidatos_e_positiva_e_medida(self) -> None:
        """§76, §77 — mais candidatos, e o nome disso é RECUPERAÇÃO.

        NÃO É «MELHORIA DE QUALIDADE». Este teste afirma uma contagem, e não
        que os vizinhos recuperados sejam melhores — não há rótulo com que
        afirmar isso, e não haverá antes do PR-06.5.
        """
        from tests.support.retrieval_fixtures import consulta, pedido

        populacao = _populacao(40)
        ciente = _executar(populacao, k=5)
        exato = self._oraculo().retrieve(
            query=pedido(k=5),
            snapshot=consulta(valores=dict.fromkeys(CINCO_EIXOS, 0.0)),
            candidates=populacao,
            reference_content_fingerprint=REFERENCIA,
        )
        recuperados = ciente.coverage_eligible_count - exato.comparable_count
        assert recuperados > 0
        assert ciente.coverage_eligible_count > exato.comparable_count


# ================================================= a semântica ==


class TestOInvarianteDaAusencia:
    """§43 ao §46, §180 — provados sobre populações, e não sobre um caso."""

    @pytest.mark.parametrize("compartilhados", [4, 5])
    def test_um_eixo_a_menos_SEMPRE_piora_quando_o_resto_e_igual(self, compartilhados: int) -> None:
        sorteio = random.Random(99)
        for _ in range(30):
            valores = {
                chave: round(sorteio.uniform(-1.0, 1.0), 4)
                for chave in CINCO_EIXOS[:compartilhados]
            }
            com_tudo = _executar([candidato_ciente(match="ref-a", valores=valores)])
            sem_um = _executar(
                [
                    candidato_ciente(
                        match="ref-a",
                        valores={k: v for k, v in valores.items() if k != CINCO_EIXOS[0]},
                    )
                ]
            )
            if not sem_um.neighbors:
                continue
            perdido = valores[CINCO_EIXOS[0]]
            observado = perdido * perdido
            esperado = com_tudo.neighbors[0].dissimilarity - observado / 5 + 1 / 5
            assert sem_um.neighbors[0].dissimilarity == pytest.approx(esperado)

    def test_a_penalidade_e_EXATAMENTE_um_por_eixo_ausente(self) -> None:
        """§35, §38, §194 — `MissingPenaltySum = m - s`, sempre."""
        for compartilhados in (4, 5):
            resultado = _executar(
                [candidato_ciente(match="ref-a", valores=primeiros(compartilhados))]
            )
            vizinho = resultado.neighbors[0]
            assert vizinho.evidence.missing_penalty_sum == float(5 - compartilhados)
            assert vizinho.evidence.coverage.unshared_count == 5 - compartilhados

    def test_o_denominador_e_SEMPRE_o_perfil(self) -> None:
        """§40, §19 — sobre toda a população, e não num caso."""
        for vizinho in _executar(_populacao(40), k=20).neighbors:
            conta = vizinho.evidence.breakdown
            assert conta.profile_axis_count == 5
            assert conta.value == (conta.observed_squared_sum + conta.missing_penalty_sum) / 5

    def test_zero_nunca_entra_no_lugar_de_um_ausente(self) -> None:
        """§94 — a propriedade, e não o sentinela.

        PARA CADA CANDIDATO PARCIAL, o `D` calculado é estritamente MAIOR que
        o que a imputação por zero produziria — porque a query é toda zero, e
        imputar zero daria `δ = 0` naquele eixo.
        """
        sorteio = random.Random(555)
        for _ in range(40):
            valores = {chave: round(sorteio.uniform(-1.5, 1.5), 4) for chave in CINCO_EIXOS[:4]}
            resultado = _executar([candidato_ciente(match="ref-a", valores=valores)])
            vizinho = resultado.neighbors[0]
            com_zero = vizinho.evidence.observed_squared_sum / 5
            # `(obs + 1)/5` E `obs/5 + 1/5` SAO A MESMA CONTA EM ARITMETICA
            # REAL e nem sempre o mesmo `float64` — a comparacao que importa
            # e a ESTRITA, e ela e exata.
            assert vizinho.dissimilarity == pytest.approx(com_zero + 1 / 5)
            assert vizinho.dissimilarity > com_zero

    def test_o_valor_cru_nunca_e_consultado(self) -> None:
        """§16, §95 — a linha CARREGA um valor cru e ele é ignorado.

        O CENÁRIO É O DO §95: a máscara diz indisponível, e a coluna do valor
        normalizado não tem número. Um leitor que caísse para o valor de origem
        acharia algo — e este teste prova que o candidato continua sem aquele
        eixo. A contradição «indisponível COM valor» tem teste próprio, e para
        a varredura.
        """
        resultado = _executar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        vizinho = resultado.neighbors[0]
        assert vizinho.evidence.candidate_mask == "11110"
        assert CINCO_EIXOS[4] in vizinho.evidence.unshared_features


class TestASimetria:
    """§96 — a fórmula é simétrica; a elegibilidade tem papéis."""

    def test_D_de_q_para_c_e_D_de_c_para_q(self) -> None:
        distancia = distancia_ciente()
        sorteio = random.Random(2024)
        for _ in range(200):
            a = tuple(round(sorteio.uniform(-3, 3), 5) for _ in range(5))
            b = tuple(round(sorteio.uniform(-3, 3), 5) for _ in range(5))
            mascara = tuple(sorteio.random() > 0.3 for _ in range(5))
            assert (
                distancia.evaluate(a, b, mascara).value == distancia.evaluate(b, a, mascara).value
            )


# ================================================= o isolamento ==


class TestOIsolamentoCausal:
    """§102, §103, §104 — o que não pode mexer no resultado."""

    def test_mudar_a_avaliacao_nao_muda_o_universo(self) -> None:
        """§102 — a impressão do universo usa a REFERÊNCIA."""
        populacao = _populacao(12)
        base = _executar(populacao)
        # A MESMA REFERÊNCIA, e outra query da mesma competição e instante.
        outra_chave = HistoricalFeatureSnapshotKey(match_key="eva-999", grid_index=30)
        outra = recuperador().retrieve(
            query=pedido_ciente(k=5, key=outra_chave),
            snapshot=consulta_ciente(match="eva-999", grid_index=30),
            candidates=list(populacao),
            reference_content_fingerprint=REFERENCIA,
        )
        assert outra.candidate_universe_fingerprint != base.candidate_universe_fingerprint
        # A CHAVE DA QUERY ENTRA NA IMPRESSÃO — o CONJUNTO é o mesmo.
        assert outra.universe_count == base.universe_count
        assert outra.coverage_eligible_count == base.coverage_eligible_count
        assert [v.key.text for v in outra.neighbors] == [v.key.text for v in base.neighbors]

    def test_mudar_a_referencia_MUDA_a_impressao_do_universo(self) -> None:
        """O espelho do teste anterior: se nada mudasse, ele não provaria nada."""
        populacao = _populacao(12)
        assert (
            _executar(populacao, reference=OUTRA_REFERENCIA).candidate_universe_fingerprint
            != _executar(populacao).candidate_universe_fingerprint
        )

    def test_um_candidato_de_outra_competicao_PARA_a_varredura(self) -> None:
        """§103 — e não é filtrado em silêncio."""
        with pytest.raises(ValidationError, match="medianas diferentes"):
            _executar(
                [
                    candidato_ciente(match="ref-a"),
                    candidato_ciente(match="ref-b", competition=LIGA_B),
                ]
            )

    def test_um_candidato_em_outro_instante_PARA_a_varredura(self) -> None:
        """§106 — o alinhamento continua EXATO."""
        with pytest.raises(ValidationError, match="EXATO"):
            _executar(
                [candidato_ciente(match="ref-a", position=GridTimePoint.of(Period.FIRST_HALF, 31))]
            )

    def test_a_propria_partida_e_excluida_e_contada_como_ESTRUTURAL(self) -> None:
        """§105 — e ela não infla a atrição por cobertura."""
        resultado = _executar(
            [
                candidato_ciente(match="eva-001"),
                candidato_ciente(match="ref-a"),
            ]
        )
        assert resultado.structural_ineligible_count == 1
        assert resultado.coverage_ineligible_count == 0
        assert resultado.ineligible[IneligibilityReason.SAME_MATCH.value] == 1
        assert resultado.returned_k == 1

    def test_representacao_divergente_e_ESTRUTURAL_e_nao_recebe_distancia(self) -> None:
        resultado = _executar(
            [
                candidato_ciente(match="ref-a", representation_fingerprint=OUTRA_IMPRESSAO),
                candidato_ciente(match="ref-b"),
            ]
        )
        assert resultado.structural_ineligible_count == 1
        assert resultado.ineligible[IneligibilityReason.REPRESENTATION_MISMATCH.value] == 1
        assert resultado.coverage_eligible_count == 1

    def test_a_ordem_das_recusas_separa_o_defeito_da_ausencia(self) -> None:
        """Um candidato da mesma partida E abaixo do piso conta como ESTRUTURAL.

        A ORDEM DAS PERGUNTAS É O CONTRATO. Se a cobertura fosse perguntada
        primeiro, um defeito estrutural entraria na contagem que o PR-06.2
        existe para medir.
        """
        resultado = _executar([candidato_ciente(match="eva-001", valores=primeiros(1))])
        assert resultado.structural_ineligible_count == 1
        assert resultado.coverage_ineligible_count == 0


# ================================================= o perfil ==


class TestOPerfilNaoEncolheNemMuda:
    """§7, §10, §29, §30, §130 — o espaço é fixo."""

    def test_os_dois_perfis_resolvem_os_mesmos_eixos_em_toda_competicao(self) -> None:
        for competicao in (LIGA_A, LIGA_B, "SERIE_A"):
            assert (
                perfil(competition=competicao, eixos=CINCO_EIXOS).feature_keys
                == perfil_ciente(competition=competicao).feature_keys
            )

    def test_duas_queries_da_mesma_liga_usam_o_MESMO_perfil(self) -> None:
        """§30 — as disponibilidades podem diferir; o espaço não."""
        completa = _executar([candidato_ciente(match="ref-a")])
        parcial = _executar(
            [candidato_ciente(match="ref-a")], snapshot=consulta_ciente(valores=primeiros(4))
        )
        assert completa.resolved_profile_fingerprint == parcial.resolved_profile_fingerprint
        assert completa.axis_count == parcial.axis_count == 5

    def test_o_denominador_nao_muda_com_a_cobertura_da_query(self) -> None:
        parcial = _executar(
            [candidato_ciente(match="ref-a")], snapshot=consulta_ciente(valores=primeiros(4))
        )
        assert parcial.neighbors[0].evidence.breakdown.profile_axis_count == 5

    def test_o_perfil_de_dez_eixos_muda_a_grandeza_e_a_impressao(self) -> None:
        """Perfis diferentes produzem números que NÃO se comparam."""
        assert perfil_ciente(eixos=DEZ_EIXOS).fingerprint != perfil_ciente().fingerprint
        assert (
            distancia_ciente(perfil_ciente(eixos=DEZ_EIXOS)).fingerprint
            != distancia_ciente().fingerprint
        )


# ================================================= a evidência ==


class TestTodoVizinhoEhReconstrutivel:
    """§182, §195 — sobre toda a população, e não num caso."""

    def test_toda_evidencia_reconstroi_o_seu_numero(self) -> None:
        for vizinho in _executar(_populacao(40), k=20).neighbors:
            prova = vizinho.evidence
            assert prova.is_reconstructible
            assert (
                prova.observed_squared_sum + prova.missing_penalty_sum
            ) / prova.coverage.profile_axis_count == vizinho.dissimilarity
            assert prova.candidate_key == vizinho.key
            assert len(prova.shared_features) == prova.coverage.shared_count
            assert len(prova.unshared_features) == prova.coverage.unshared_count

    def test_as_mascaras_sao_consistentes_entre_si(self) -> None:
        for vizinho in _executar(_populacao(40), k=20).neighbors:
            prova = vizinho.evidence
            for q, c, s in zip(
                prova.query_mask, prova.candidate_mask, prova.shared_mask, strict=True
            ):
                assert (s == "1") == (q == "1" and c == "1")

    def test_a_impressao_da_evidencia_e_estavel_sob_permutacao(self) -> None:
        populacao = _populacao(24)
        base = {v.key.text: v.evidence.fingerprint for v in _executar(populacao, k=10).neighbors}
        sorteio = random.Random(11)
        for _ in range(5):
            embaralhado = populacao[:]
            sorteio.shuffle(embaralhado)
            atual = {
                v.key.text: v.evidence.fingerprint for v in _executar(embaralhado, k=10).neighbors
            }
            assert atual == base


# ================================================= o piso ==


class TestOPisoEhUmaFuncaoDoParEDoPerfil:
    """§26, §87, §88 — a decisão não depende de mais nada."""

    def test_toda_combinacao_de_s_e_m_ate_sessenta(self) -> None:
        """A definição, verificada exaustivamente contra a fórmula."""
        politica = DEFAULT_COVERAGE_POLICY
        for m in range(1, 61):
            for compartilhados in range(m + 1):
                esperado = compartilhados >= 4 and 5 * compartilhados >= 3 * m
                assert politica.admits_pair(shared=compartilhados, profile_axes=m) is esperado

    def test_o_piso_nao_depende_de_quantos_candidatos_existem(self) -> None:
        """Um universo grande não afrouxa o piso, e um pequeno não o aperta."""
        um = _executar([candidato_ciente(match="ref-a", valores=primeiros(3))])
        muitos = _executar(
            [candidato_ciente(match=f"ref-{i:03d}", valores=primeiros(3)) for i in range(50)]
        )
        assert um.coverage_eligible_count == 0
        assert muitos.coverage_eligible_count == 0
        assert muitos.coverage_ineligible_count == 50
