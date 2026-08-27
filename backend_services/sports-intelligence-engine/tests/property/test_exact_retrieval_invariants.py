"""As INVARIANTES do oráculo — o que não pode mudar o top-K.

O QUE ESTE ARQUIVO PROVA, e cada item é um jeito de o oráculo deixar de ser
oráculo sem que nada quebre:

    ordem de iteração    embaralhar os candidatos não muda o ranking
    tamanho de lote      128, 512 ou 2048 produzem o MESMO resultado
    prefixo do K         `top10(K=50) == resultado(K=10)`
    empate               dois candidatos à mesma distância ordenam pela chave
    caso completo        um eixo ausente ⇒ nenhuma distância
    exaustividade        todo comparável foi MEDIDO antes da escolha
    avaliação            mexer noutra partida de avaliação não muda nada
    outra competição     mexer na referência de outra liga não muda nada

O DEFEITO QUE ELES PEGAM É INVISÍVEL EM CORPUS PEQUENO. Um `<` no lugar de um
`<=` dentro do heap produz um top-K correto em conteúdo e errado em ordem
apenas quando há empate exatamente no corte do `K` — e num cenário de cinco
candidatos isso nunca acontece. Por isso os cenários aqui têm empates
DELIBERADOS no corte.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Final

import pytest

from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.exact import ExactHistoricalRetriever
from sports_intelligence.domain.retrieval.query import QueryNotComparableError
from sports_intelligence.domain.retrieval.result import ExactRetrievalResult
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.temporal import Period
from tests.support.retrieval_fixtures import (
    EIXO_A,
    EIXO_B,
    LIGA_B,
    OUTRA_IMPRESSAO,
    candidato,
    consulta,
    distancia,
    pedido,
    perfil,
)

pytestmark = pytest.mark.property

REFERENCIA: Final[str] = "r" * 64


def recuperar(
    candidatos: Sequence[CandidateRow],
    *,
    k: int = 3,
    referencia: str = REFERENCIA,
) -> ExactRetrievalResult:
    """O caminho completo do oráculo sobre uma lista em memória."""
    alvo = perfil()
    retriever = ExactHistoricalRetriever(
        policy=DEFAULT_CANDIDATE_POLICY, profile=alvo, distance=distancia(alvo)
    )
    return retriever.retrieve(
        query=pedido(k=k),
        snapshot=consulta(),
        candidates=candidatos,
        reference_content_fingerprint=referencia,
    )


def em_grade(n: int) -> list[CandidateRow]:
    """`n` candidatos com distâncias crescentes e distintas.

    O CANDIDATO `i` FICA A `2i²` DA QUERY — `q=[0,0]`, `c=[i,i]` —, então o
    ranking esperado é a ordem de `i`. Distâncias distintas isolam a ordenação
    do desempate: quando um teste destes falha, o defeito é do ranking.
    """
    return [
        candidato(match=f"ref-{i:03d}", valores={EIXO_A: float(i), EIXO_B: float(i)})
        for i in range(1, n + 1)
    ]


class TestAOrdemDeIteracaoNaoImporta:
    """§68, §147 — embaralhar a entrada não muda a saída."""

    def test_dez_permutacoes_produzem_a_mesma_impressao(self) -> None:
        base = em_grade(40)
        esperado = recuperar(base, k=10)
        gerador = random.Random(20260826)
        for _ in range(10):
            embaralhado = list(base)
            gerador.shuffle(embaralhado)
            assert recuperar(embaralhado, k=10).fingerprint == esperado.fingerprint

    def test_a_ordem_inversa_tambem(self) -> None:
        base = em_grade(40)
        assert (
            recuperar(list(reversed(base)), k=10).fingerprint == recuperar(base, k=10).fingerprint
        )


class TestOTamanhoDoLoteNaoImporta:
    """§69, §148 — o oráculo não sabe em que pedaços o leitor entregou.

    O LOTE NÃO É UM PARÂMETRO DO RETRIEVER, e é por isso que estes testes
    entregam a lista em pedaços: o efeito de um lote sobre o resultado só
    existiria se o retriever guardasse estado entre chamadas — e ele não
    guarda, porque recebe um iterável e o consome uma vez.
    """

    @pytest.mark.parametrize("lote", [1, 7, 128, 512, 2048])
    def test_lotes_diferentes_produzem_a_mesma_impressao(self, lote: int) -> None:
        base = em_grade(60)

        def em_pedacos() -> list[CandidateRow]:
            saida: list[CandidateRow] = []
            for inicio in range(0, len(base), lote):
                saida.extend(base[inicio : inicio + lote])
            return saida

        assert recuperar(em_pedacos(), k=10).fingerprint == recuperar(base, k=10).fingerprint


class TestOPrefixoDoK:
    """§70, §149 — `top10(K=50)` é exatamente `resultado(K=10)`."""

    def test_o_prefixo_coincide(self) -> None:
        base = em_grade(80)
        dez = recuperar(base, k=10)
        cinquenta = recuperar(base, k=50)
        assert [v.key for v in cinquenta.top(10)] == [v.key for v in dez.neighbors]
        assert [v.squared_distance for v in cinquenta.top(10)] == [
            v.squared_distance for v in dez.neighbors
        ]

    def test_o_prefixo_coincide_COM_EMPATES_NO_CORTE(self) -> None:
        """O caso que um `<` no lugar de um `<=` quebraria.

        SEIS CANDIDATOS À MESMA DISTÂNCIA, e o corte cai no meio deles: com
        `K=3`, três dos seis entram, e QUAIS três é decidido pela chave
        canônica. Um heap que desempatasse pela ordem de chegada devolveria
        três quaisquer — e o prefixo deixaria de coincidir.
        """
        empatados = [
            candidato(match=f"ref-{letra}", valores={EIXO_A: 1.0, EIXO_B: 1.0})
            for letra in "fedcba"
        ]
        tres = recuperar(empatados, k=3)
        seis = recuperar(empatados, k=6)
        assert [v.key.text for v in tres.neighbors] == [
            "ref-a#0030",
            "ref-b#0030",
            "ref-c#0030",
        ]
        assert [v.key for v in seis.top(3)] == [v.key for v in tres.neighbors]

    def test_K_maior_que_o_universo_devolve_todos(self) -> None:
        """§71 — sem preenchimento."""
        resultado = recuperar(em_grade(4), k=50)
        assert resultado.requested_k == 50
        assert resultado.returned_k == 4


class TestOEmpate:
    """§63, §107, §152 — a chave canônica, e nunca a ordem de chegada."""

    def test_a_ordem_e_pela_chave(self) -> None:
        embaralhados = [
            candidato(match=f"ref-{letra}", valores={EIXO_A: 2.0, EIXO_B: 0.0})
            for letra in ("c", "a", "b")
        ]
        resultado = recuperar(embaralhados, k=3)
        assert [v.key.text for v in resultado.neighbors] == [
            "ref-a#0030",
            "ref-b#0030",
            "ref-c#0030",
        ]
        assert len({v.squared_distance for v in resultado.neighbors}) == 1

    def test_o_desempate_sobrevive_a_permutacao(self) -> None:
        empatados = [
            candidato(match=f"ref-{i:03d}", valores={EIXO_A: 1.0, EIXO_B: 0.0}) for i in range(20)
        ]
        gerador = random.Random(7)
        esperado = recuperar(empatados, k=5).fingerprint
        for _ in range(8):
            copia = list(empatados)
            gerador.shuffle(copia)
            assert recuperar(copia, k=5).fingerprint == esperado


class TestOCasoCompleto:
    """§49 ao §53, §103, §151 — um eixo ausente e a distância não existe."""

    def test_um_eixo_ausente_torna_o_candidato_inelegivel(self) -> None:
        """§103 — idêntico em um eixo, sem valor no outro."""
        resultado = recuperar(
            [
                candidato(match="ref-completo", valores={EIXO_A: 5.0, EIXO_B: 5.0}),
                candidato(match="ref-parcial", valores={EIXO_A: 0.0, EIXO_B: None}),
            ],
            k=5,
        )
        assert resultado.universe_count == 2
        assert resultado.comparable_count == 1
        assert resultado.returned_k == 1
        assert resultado.neighbors[0].key.match_key == "ref-completo"
        assert resultado.ineligible == {IneligibilityReason.INCOMPLETE_PROFILE.value: 1}

    def test_o_candidato_incompleto_estaria_em_primeiro_se_fosse_medido(self) -> None:
        """O SENTINELA. O candidato incompleto tem `EIXO_A` IGUAL ao da query.

        SE ALGUÉM IMPUTASSE ZERO no eixo que falta, ele sairia a distância 0 e
        assumiria o primeiro lugar — passando por cima do único candidato de
        fato comparável. O teste acima já provaria a contagem; este prova que a
        contagem não está escondendo uma imputação.
        """
        resultado = recuperar(
            [
                candidato(match="ref-completo", valores={EIXO_A: 5.0, EIXO_B: 5.0}),
                candidato(match="ref-parcial", valores={EIXO_A: 0.0, EIXO_B: None}),
            ],
            k=5,
        )
        assert all(v.key.match_key != "ref-parcial" for v in resultado.neighbors)
        assert resultado.neighbors[0].squared_distance == 50.0

    def test_uma_query_incompleta_e_recusada_com_tipo(self) -> None:
        """§50, §104 — e o perfil NÃO é reduzido para caber nela."""
        alvo = perfil()
        retriever = ExactHistoricalRetriever(
            policy=DEFAULT_CANDIDATE_POLICY, profile=alvo, distance=distancia(alvo)
        )
        with pytest.raises(QueryNotComparableError) as capturada:
            retriever.retrieve(
                query=pedido(),
                snapshot=consulta(valores={EIXO_A: 1.0, EIXO_B: None}),
                candidates=em_grade(5),
                reference_content_fingerprint=REFERENCIA,
            )
        assert capturada.value.reason == "QUERY_NOT_COMPARABLE_UNDER_PROFILE"
        assert capturada.value.missing_axes == (EIXO_B,)
        assert capturada.value.axis_count == 2

    def test_zero_comparaveis_e_um_resultado_valido(self) -> None:
        """§72 — e NÃO uma queda para outra competição."""
        resultado = recuperar([candidato(match="ref-a", valores={EIXO_A: None, EIXO_B: None})], k=5)
        assert resultado.is_empty
        assert resultado.returned_k == 0
        assert resultado.universe_count == 1
        assert resultado.comparable_count == 0


class TestAExaustividade:
    """§37, §39, §155 — todo comparável foi MEDIDO antes da escolha."""

    def test_o_comparavel_conta_os_MEDIDOS_e_nao_os_devolvidos(self) -> None:
        resultado = recuperar(em_grade(500), k=5)
        assert resultado.returned_k == 5
        assert resultado.comparable_count == 500
        assert resultado.universe_count == 500
        assert resultado.exhaustive

    def test_o_ultimo_candidato_da_varredura_pode_vencer(self) -> None:
        """A prova de que não há parada antecipada.

        O MELHOR CANDIDATO É O ÚLTIMO A CHEGAR, e a distância dele é menor que
        a de todos os anteriores. Uma parada antecipada — ou uma poda por
        distância — o perderia, e o top-1 sairia errado com o heap cheio.
        """
        candidatos = [
            *em_grade(200),
            candidato(match="ref-zzz-melhor", valores={EIXO_A: 0.0, EIXO_B: 0.0}),
        ]
        resultado = recuperar(candidatos, k=3)
        assert resultado.neighbors[0].key.match_key == "ref-zzz-melhor"
        assert resultado.neighbors[0].squared_distance == 0.0
        assert resultado.comparable_count == 201


class TestOsInvariantesEstruturais:
    """§10, §11, §23, §100, §101 — o que o retriever RECUSA."""

    def test_um_candidato_de_outra_competicao_para_a_varredura(self) -> None:
        with pytest.raises(Exception, match="escala é ajustada por competição"):
            recuperar([candidato(match="ref-a", competition=LIGA_B)], k=3)

    def test_um_candidato_noutro_instante_para_a_varredura(self) -> None:
        """§100 — o minuto 29 não entra numa query do minuto 30."""
        with pytest.raises(Exception, match="instante é EXATO"):
            recuperar(
                [
                    candidato(
                        match="ref-a",
                        position=GridTimePoint.of(Period.FIRST_HALF, 29),
                    )
                ],
                k=3,
            )

    def test_a_mesma_partida_e_excluida(self) -> None:
        """§23, §101 — fail-closed, ainda que a divisão já o impeça."""
        resultado = recuperar(
            [
                candidato(match="eva-001", valores={EIXO_A: 0.0, EIXO_B: 0.0}),
                candidato(match="ref-a", valores={EIXO_A: 9.0, EIXO_B: 9.0}),
            ],
            k=5,
        )
        assert resultado.universe_count == 2
        assert resultado.ineligible == {IneligibilityReason.SAME_MATCH.value: 1}
        assert [v.key.match_key for v in resultado.neighbors] == ["ref-a"]

    def test_uma_representacao_divergente_e_contada_e_nao_medida(self) -> None:
        """§90 — os números estariam na mesma ordem e em outra grandeza."""
        resultado = recuperar(
            [
                candidato(
                    match="ref-outra",
                    representation_fingerprint=OUTRA_IMPRESSAO,
                    valores={EIXO_A: 0.0, EIXO_B: 0.0},
                ),
                candidato(match="ref-a", valores={EIXO_A: 3.0, EIXO_B: 4.0}),
            ],
            k=5,
        )
        assert resultado.ineligible == {IneligibilityReason.REPRESENTATION_MISMATCH.value: 1}
        assert [v.key.match_key for v in resultado.neighbors] == ["ref-a"]
        assert resultado.neighbors[0].squared_distance == 25.0


class TestAAvaliacaoNaoMudaNada:
    """§95, §96, §145 — a derivada em relação à avaliação é nula.

    O UNIVERSO É DE REFERÊNCIA, e o retriever nem enxerga outras linhas de
    avaliação: elas não chegam como candidatas porque a poda é por metade. O
    que estes testes provam é que a IMPRESSÃO do universo também não depende
    delas — nem por linhagem, nem por contagem.
    """

    def test_a_impressao_do_universo_nao_depende_da_linhagem(self) -> None:
        base = em_grade(10)
        um = recuperar(base, k=5)
        outro = recuperar(base, k=5)
        assert um.candidate_universe_fingerprint == outro.candidate_universe_fingerprint

    def test_mudar_a_referencia_MUDA_a_impressao(self) -> None:
        """§97 — o outro lado. Um teste que só provasse igualdade passaria com
        uma implementação que devolvesse constante."""
        base = em_grade(10)
        assert (
            recuperar(base, k=5, referencia=REFERENCIA).candidate_universe_fingerprint
            != recuperar(base, k=5, referencia="s" * 64).candidate_universe_fingerprint
        )

    def test_um_candidato_a_mais_muda_a_impressao_do_universo(self) -> None:
        dez = recuperar(em_grade(10), k=5)
        onze = recuperar(em_grade(11), k=5)
        assert dez.candidate_universe_fingerprint != onze.candidate_universe_fingerprint
