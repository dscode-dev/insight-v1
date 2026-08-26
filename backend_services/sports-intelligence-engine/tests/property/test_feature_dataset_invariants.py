"""As INVARIANTES do PR-05.5.1 — os cinco portões do §164 ao §168.

    §164  a grade é DETERMINÍSTICA e a mesma para toda partida comparável
    §165  a divisão é ATÔMICA por partida e MONOTÔNICA no apito
    §166  a linha do minuto `m` NÃO depende de fato nenhum posterior a `m`
    §167  qualquer mudança na linha muda o digesto dela
    §168  qualquer permutação das linhas muda — ou recusa — a impressão

A DIFERENÇA ENTRE ESTES E OS DE UNIDADE. Os de unidade conferem números contra
uma tabela; estes provam propriedades sobre CONJUNTOS de entrada: «truncar o
corpus em `m` não muda a linha de `m`», «trocar QUALQUER coisa muda o digesto».
A segunda forma é a que pega o vazamento que ninguém pensou em testar.

O §166 É O MAIS IMPORTANTE, e a forma dele é a que dá a garantia: em vez de
conferir que o valor «parece causal», ele RECONSTRÓI a linha a partir de um
corpus do qual os fatos posteriores foram removidos, e exige o MESMO digesto.
Se qualquer fato do futuro tivesse entrado no cálculo, os dois divergiriam.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import timedelta

import pytest

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    ExtraTimeEvidence,
    canonical_kickoff,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
    OrderedRowFingerprint,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.extraction.extractor_v2 import (
    ExtendedFeatureExtractionContext,
    ExtendedMatchStateFeatureExtractor,
)
from sports_intelligence.domain.features.market.consensus import MarketConsensusPolicy
from sports_intelligence.domain.features.prematch.policy import DEFAULT_CONTEXT_POLICY
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.state.builder import (
    CanonicalMatchStateInput,
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period, instant
from tests.support.dataset_fixtures import (
    apito_de,
    corpus_do_cenario,
    divisao,
    id_de_partida,
    origem_do_cenario,
)

pytestmark = pytest.mark.property

CORPUS = corpus_do_cenario()
ORIGEM = origem_do_cenario()
POLITICA = TemporalAvailabilityPolicy.default()
CATALOGO = extended_feature_catalog()


def _snapshot(entrada: CanonicalMatchStateInput, ponto: object) -> FeatureSnapshot:
    build = HistoricalMatchStateBuilder(policy=POLITICA).build(
        entrada,
        as_of=ponto.as_of,  # type: ignore[attr-defined]
        source=ORIGEM,
    )
    return ExtendedMatchStateFeatureExtractor().extract(
        ExtendedFeatureExtractionContext.of(
            build,
            space=match_state_raw_space_v2(),
            catalog=CATALOGO,
            source=ORIGEM,
            policy=POLITICA,
            v1_space=match_state_raw_space_v1(),
            context_policy=DEFAULT_CONTEXT_POLICY,
            market_policy=MarketConsensusPolicy(),
            context=None,
        )
    )


def _linha(entrada: CanonicalMatchStateInput, ponto: object) -> MaterializedFeatureRow:
    return MaterializedFeatureRow(
        key=HistoricalFeatureSnapshotKey.of(
            entrada.match.id,
            grid_index=ponto.index,  # type: ignore[attr-defined]
        ),
        snapshot=_snapshot(entrada, ponto),
        split=divisao().assign(kickoff=canonical_kickoff(entrada.match)),
        competition_code=entrada.competition_code,
        season_label=entrada.season_label,
        kickoff=canonical_kickoff(entrada.match),
        grid_label=ponto.label,  # type: ignore[attr-defined]
    )


class TestOPortao164AGradeEDeterministica:
    """§164. A grade é a MESMA para toda partida comparável."""

    def test_todas_as_partidas_do_cenario_produzem_a_mesma_forma(self) -> None:
        formas = {
            tuple(
                (p.period.value, p.minute)
                for p in DEFAULT_SNAPSHOT_GRID.points_for(
                    identificador, kickoff=canonical_kickoff(entrada.match)
                )
            )
            for identificador, entrada in CORPUS.items()
        }
        assert len(formas) == 1, "a grade tem de ser a mesma entre partidas"

    def test_duas_chamadas_produzem_a_mesma_grade(self) -> None:
        partida = id_de_partida(0)
        primeira = DEFAULT_SNAPSHOT_GRID.points_for(partida, kickoff=apito_de(0))
        segunda = DEFAULT_SNAPSHOT_GRID.points_for(partida, kickoff=apito_de(0))
        assert primeira == segunda

    def test_o_indice_e_estritamente_crescente(self) -> None:
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(id_de_partida(0), kickoff=apito_de(0))
        assert all(b.index == a.index + 1 for a, b in itertools.pairwise(pontos))

    def test_nenhum_ponto_esta_numa_fase_proibida(self) -> None:
        proibidas = {
            Period.HALF_TIME,
            Period.FULL_TIME,
            Period.PENALTY_SHOOTOUT,
            Period.EXTRA_TIME_BREAK,
        }
        for identificador, entrada in CORPUS.items():
            pontos = DEFAULT_SNAPSHOT_GRID.points_for(
                identificador, kickoff=canonical_kickoff(entrada.match)
            )
            assert not [p for p in pontos if p.period in proibidas]

    def test_o_apito_nao_muda_a_forma_da_grade(self) -> None:
        """A grade é uma propriedade do RELÓGIO DO JOGO, e não do calendário."""
        partida = id_de_partida(0)
        a = DEFAULT_SNAPSHOT_GRID.points_for(partida, kickoff=apito_de(0))
        b = DEFAULT_SNAPSHOT_GRID.points_for(partida, kickoff=apito_de(5))
        assert [(p.period, p.minute, p.index) for p in a] == [
            (p.period, p.minute, p.index) for p in b
        ]


class TestOPortao165ADivisaoEAtomica:
    """§165. Atômica por partida, e monotônica no apito."""

    def test_todos_os_cortes_de_uma_partida_caem_na_mesma_metade(self) -> None:
        politica = divisao()
        for entrada in CORPUS.values():
            apito = canonical_kickoff(entrada.match)
            metades = {
                politica.assign(kickoff=apito)
                for _ in DEFAULT_SNAPSHOT_GRID.points_for(entrada.match.id, kickoff=apito)
            }
            assert len(metades) == 1

    def test_um_apito_mais_cedo_nunca_cai_depois_na_ordem_das_metades(self) -> None:
        """`REFERENCE` antes de `EVALUATION`: se o mais cedo caísse na
        avaliação e o mais tarde na referência, a divisão não seria temporal."""
        politica = divisao()
        ordem = {DatasetSplit.REFERENCE: 0, DatasetSplit.EVALUATION: 1}
        apitos = sorted(canonical_kickoff(e.match) for e in CORPUS.values())
        posicoes = [ordem[politica.assign(kickoff=a)] for a in apitos]
        assert posicoes == sorted(posicoes)

    def test_deslocar_a_fronteira_move_partidas_num_sentido_so(self) -> None:
        """Adiantar a fronteira só pode TIRAR partidas da referência."""
        cedo = divisao(fronteira=instant(apito_de(0) + timedelta(days=1)))
        tarde = divisao(fronteira=instant(apito_de(5) + timedelta(days=1)))
        for entrada in CORPUS.values():
            apito = canonical_kickoff(entrada.match)
            if cedo.assign(kickoff=apito) is DatasetSplit.REFERENCE:
                assert tarde.assign(kickoff=apito) is DatasetSplit.REFERENCE


class TestOPortao166ALinhaNaoConheceOFuturo:
    """§166. A linha do minuto `m` não depende de fato nenhum posterior."""

    @pytest.mark.parametrize(
        ("fase", "minuto"),
        [
            (Period.FIRST_HALF, 10),
            (Period.FIRST_HALF, 30),
            (Period.SECOND_HALF, 50),
            (Period.SECOND_HALF, 63),
            (Period.SECOND_HALF, 80),
        ],
    )
    def test_truncar_o_corpus_no_corte_nao_muda_o_digesto(self, fase: Period, minuto: int) -> None:
        """A PROVA É POR RECONSTRUÇÃO. Se qualquer fato do futuro tivesse
        entrado no cálculo, a linha sobre o corpus truncado seria diferente.
        """
        entrada = CORPUS[id_de_partida(0)]
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=canonical_kickoff(entrada.match)
        )
        ponto = next(p for p in pontos if p.period is fase and p.minute == minuto)
        completa = _linha(entrada, ponto)

        truncado = replace(
            entrada,
            candidate_events=tuple(
                e
                for e in entrada.candidate_events
                if (e.clock.period.order, e.clock.minute) <= (fase.order, minuto)
            ),
        )
        assert _linha(truncado, ponto).digest == completa.digest

    def test_a_linha_do_pre_jogo_nao_muda_com_evento_nenhum(self) -> None:
        entrada = CORPUS[id_de_partida(0)]
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=canonical_kickoff(entrada.match)
        )
        sem_eventos = replace(entrada, candidate_events=())
        assert _linha(sem_eventos, pontos[0]).digest == _linha(entrada, pontos[0]).digest

    def test_o_resultado_final_nao_alcanca_linha_nenhuma(self) -> None:
        """`MatchResult` serve à conferência pós-jogo, e nunca ao estado."""
        from sports_intelligence.domain.matches.result import MatchResult, Score

        entrada = CORPUS[id_de_partida(0)]
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=canonical_kickoff(entrada.match)
        )
        com_resultado = replace(entrada, result=MatchResult(regular_time=Score(home=7, away=0)))
        for ponto in (pontos[0], pontos[45], pontos[-1]):
            assert _linha(com_resultado, ponto).digest == _linha(entrada, ponto).digest


class TestOPortao167ODigestoESensivel:
    """§167. Qualquer mudança na linha muda o digesto dela."""

    def _base(self) -> MaterializedFeatureRow:
        entrada = CORPUS[id_de_partida(0)]
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=canonical_kickoff(entrada.match)
        )
        return _linha(entrada, pontos[63])

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("split", DatasetSplit.EVALUATION),
            ("competition_code", "LA_LIGA"),
            ("season_label", "2024/25"),
            ("grid_label", "OUTRO"),
            ("state_issue_count", 3),
        ],
    )
    def test_trocar_qualquer_coordenada_muda_o_digesto(self, campo: str, valor: object) -> None:
        base = self._base()
        assert replace(base, **{campo: valor}).digest != base.digest  # type: ignore[arg-type]

    def test_trocar_o_apito_muda_o_digesto(self) -> None:
        base = self._base()
        assert replace(base, kickoff=apito_de(3)).digest != base.digest

    def test_dois_cortes_diferentes_nunca_colidem(self) -> None:
        entrada = CORPUS[id_de_partida(0)]
        pontos = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=canonical_kickoff(entrada.match)
        )
        digestos = [_linha(entrada, p).digest for p in pontos[:20]]
        assert len(set(digestos)) == len(digestos)

    def test_duas_partidas_com_a_mesma_historia_tem_digestos_diferentes(self) -> None:
        """A identidade da partida é conteúdo da linha, e não etiqueta."""
        primeira = CORPUS[id_de_partida(0)]
        segunda = CORPUS[id_de_partida(1)]
        pontos_a = DEFAULT_SNAPSHOT_GRID.points_for(
            primeira.match.id, kickoff=canonical_kickoff(primeira.match)
        )
        pontos_b = DEFAULT_SNAPSHOT_GRID.points_for(
            segunda.match.id, kickoff=canonical_kickoff(segunda.match)
        )
        assert _linha(primeira, pontos_a[63]).digest != _linha(segunda, pontos_b[63]).digest


def _alimentar(
    acumulador: OrderedRowFingerprint,
    chaves: list[HistoricalFeatureSnapshotKey],
) -> None:
    for chave in chaves:
        acumulador.update(chave, "d")


class TestOPortao168APermutacaoENotada:
    """§168. Permutar as linhas muda — ou recusa — a impressão."""

    def _acumulador(self) -> OrderedRowFingerprint:
        return OrderedRowFingerprint(
            space_name="MATCH_STATE_RAW_V2",
            space_version="2.0",
            grid_fingerprint=DEFAULT_SNAPSHOT_GRID.fingerprint,
            split_fingerprint=divisao().fingerprint,
        )

    def test_a_ordem_certa_e_aceita(self) -> None:
        acumulador = self._acumulador()
        for i in range(10):
            acumulador.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        assert acumulador.rows == 10

    @pytest.mark.parametrize("troca", [(0, 1), (3, 7), (8, 9)])
    def test_qualquer_inversao_e_RECUSADA(self, troca: tuple[int, int]) -> None:
        """Uma impressão comutativa aceitaria a permutação e diria «igual»."""
        chaves = [HistoricalFeatureSnapshotKey("a", i) for i in range(10)]
        i, j = troca
        chaves[i], chaves[j] = chaves[j], chaves[i]
        acumulador = self._acumulador()
        with pytest.raises(ValidationError, match="ordenada"):
            _alimentar(acumulador, chaves)

    def test_partidas_em_ordem_invertida_sao_recusadas(self) -> None:
        acumulador = self._acumulador()
        acumulador.update(HistoricalFeatureSnapshotKey("bbb", 0), "d")
        with pytest.raises(ValidationError, match="ordenada"):
            acumulador.update(HistoricalFeatureSnapshotKey("aaa", 0), "d")

    def test_um_conjunto_a_menos_produz_impressao_diferente(self) -> None:
        completa, parcial = self._acumulador(), self._acumulador()
        for i in range(10):
            completa.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        for i in range(10):
            if i != 4:
                parcial.update(HistoricalFeatureSnapshotKey("a", i), f"d{i}")
        assert completa.finalize() != parcial.finalize()


class TestAProrrogacaoNaoInventaEstado:
    """A grade nunca cresce sem prova — o corolário do §33."""

    def test_nenhuma_partida_do_cenario_ganha_prorrogacao(self) -> None:
        from sports_intelligence.domain.features.dataset.grid import extra_time_evidence

        for entrada in CORPUS.values():
            prova = extra_time_evidence(events=entrada.candidate_events, result=entrada.result)
            assert not prova.proven
            pontos = DEFAULT_SNAPSHOT_GRID.points_for(
                entrada.match.id,
                kickoff=canonical_kickoff(entrada.match),
                extra_time=prova,
            )
            assert len(pontos) == 91

    def test_a_prova_e_a_unica_coisa_que_muda_o_tamanho(self) -> None:
        entrada = CORPUS[id_de_partida(0)]
        apito = canonical_kickoff(entrada.match)
        sem = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=apito, extra_time=ExtraTimeEvidence.none()
        )
        com = DEFAULT_SNAPSHOT_GRID.points_for(
            entrada.match.id, kickoff=apito, extra_time=ExtraTimeEvidence(proven=True)
        )
        assert len(sem) == 91
        assert len(com) == 121
        assert [p.index for p in com[:91]] == [p.index for p in sem]
