"""A ponte entre `atlas.match_vector` e o contrato que o detector lê.

Dois assuntos: que a conversão preserva o que a vizinhança diz, e que o
portão de acordo do detector — que hoje rejeita tudo — rejeita por uma razão
aritmética, não por causa da ponte.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.similarity.scoring import confidence_for_matches
from atlas.vector.bridge import MINIMO_VIZINHOS, _unidade, para_contexto
from atlas.vector.query import Consulta, Vizinho
from atlas.vector.space import VERSAO


def _consulta(**features) -> Consulta:
    return Consulta(
        categoria="resultado",
        competition="premier_league",
        season="2024-2025",
        home_club_id="arsenal",
        away_club_id="chelsea",
        as_of=datetime(2025, 3, 1, tzinfo=timezone.utc),
        features=features,
    )


def _vizinhos(
    similaridades: list[float], desfechos: list[str] | None = None
) -> list[Vizinho]:
    return [
        Vizinho(
            uid=f"00000000-0000-5000-8000-{i:012d}",
            competition="premier_league",
            season="2024-2025",
            kickoff=datetime(2024, 5, 1, tzinfo=timezone.utc),
            home="liverpool",
            away="everton",
            label=(desfechos[i] if desfechos else "HOME_WIN"),
            similaridade=s,
            features={},
        )
        for i, s in enumerate(similaridades)
    ]


class TestEscala:
    def test_cosseno_negativo_nao_e_cortado_em_zero(self):
        """O espaço é centrado, então o cosseno vai de -1 a 1. Cortar em zero
        empilharia todo vizinho ruim no mesmo ponto e faria a amplitude das
        distâncias — que é o que mede acordo — descrever um empate que não
        existe."""
        assert _unidade(-1.0) == 0.0
        assert _unidade(0.0) == 0.5
        assert _unidade(1.0) == 1.0
        # A ordem é preservada em toda a faixa, inclusive na parte negativa.
        assert _unidade(-0.8) < _unidade(-0.2) < _unidade(0.2)

    def test_distancia_e_o_complemento_exato_da_similaridade(self):
        """`confidence_for_matches` calcula acordo a partir das distâncias. Se
        elas não forem o complemento exato da similaridade convertida, o acordo
        descreve outra coisa que não a vizinhança."""
        contexto = para_contexto(_consulta(), _vizinhos([0.9, 0.8, 0.7, 0.6, 0.5]))
        assert contexto is not None
        for m in contexto.matches:
            assert m.distance == pytest.approx(1.0 - m.similarity)


class TestContexto:
    def test_vizinhanca_rasa_nao_vira_contexto(self):
        assert para_contexto(_consulta(), _vizinhos([0.9] * (MINIMO_VIZINHOS - 1))) is None

    def test_carrega_a_versao_do_espaco_novo(self):
        """O detector filtra por `embedding_version`: um contexto que declare
        a versão errada tem todos os vizinhos descartados pelo portão de
        compatibilidade, em silêncio."""
        contexto = para_contexto(_consulta(), _vizinhos([0.9] * 10))
        assert contexto is not None
        assert contexto.embedding_version == VERSAO
        assert contexto.filters.embedding_version == VERSAO
        assert all(m.embedding_version == VERSAO for m in contexto.matches)

    def test_respeita_o_limite_de_vizinhos(self):
        contexto = para_contexto(_consulta(), _vizinhos([0.9] * 60), limite=25)
        assert contexto is not None
        assert len(contexto.matches) == 25
        assert contexto.distribution.count == 25

    def test_distingue_pergunta_pela_metade_de_vizinhanca_fraca(self):
        """Sem isto, as duas viram o mesmo número baixo e o operador não sabe
        se o problema é o corpus ou a consulta."""
        cheia = para_contexto(_consulta(implied_home=0.5, elo_delta=0.3), _vizinhos([0.9] * 10))
        vazia = para_contexto(_consulta(), _vizinhos([0.9] * 10))
        assert cheia is not None and vazia is not None
        assert cheia.metadata["dimensoes_informadas"] == 2
        assert vazia.metadata["dimensoes_informadas"] == 0


class TestPortaoDeAcordo:
    """O portão media a coisa errada, e estes testes são a prova dos dois
    estados: o que ele fazia, e o que faz agora.

    ELE EXIGIA `neighbor_agreement >= 0,40`, e aquele número era
    1 - amplitude/média das DISTÂNCIAS — um coeficiente de variação. Num
    top-K ordenado as distâncias cobrem toda a faixa entre o melhor e o pior
    vizinho, então a razão é grande e o "acordo" baixo, sempre. Medido sobre
    o corpus de 15.627 partidas, o portão deixava passar 0,0% das
    vizinhanças na lente `gols` do Brasileirão e da Argentina, e 9,7% em
    `resultado` na Premier League — que é a lente mais forte que existe.

    AGORA ELE MEDE CONCORDÂNCIA DE DESFECHO contra a taxa base da
    competição, e o desfecho atravessa a ponte para que isso seja possível.
    """

    def test_a_uniformidade_de_distancia_continua_baixa_num_top_k_real(self):
        """O número antigo não sumiu nem estava errado como medida — ele
        descreve a forma da vizinhança. Só não é concordância, e o nome agora
        diz isso."""
        contexto = para_contexto(
            _consulta(), _vizinhos([0.926 - 0.112 * i / 24 for i in range(25)])
        )
        assert contexto is not None
        assert contexto.confidence.distance_uniformity < 0.40

    def test_e_a_concordancia_de_desfecho_e_alta_na_mesma_vizinhanca(self):
        """A MESMA vizinhança que o portão antigo reprovava. Os 25 vizinhos
        terminaram todos do mesmo jeito — o que é exatamente a informação que
        o detector precisava e não recebia."""
        contexto = para_contexto(
            _consulta(), _vizinhos([0.926 - 0.112 * i / 24 for i in range(25)])
        )
        assert contexto is not None
        assert contexto.confidence.outcome_agreement == 1.0
        assert contexto.confidence.modal_outcome == "HOME_WIN"
        assert contexto.agreement == 1.0

    def test_vizinhos_que_terminaram_diferente_dao_concordancia_baixa(self):
        desfechos = ["HOME_WIN", "AWAY_WIN", "DRAW", "AWAY_WIN", "HOME_WIN"]
        contexto = para_contexto(
            _consulta(), _vizinhos([0.9, 0.88, 0.86, 0.84, 0.82], desfechos)
        )
        assert contexto is not None
        assert contexto.confidence.outcome_agreement == 0.4

    def test_a_taxa_base_viaja_no_contexto(self):
        """O detector é uma função pura de portões e não abre conexão. Sem
        este campo ele julgaria concordância contra um número fixo, e 50% de
        vitórias do mandante quer dizer coisas opostas na Premier League
        (43,3%) e no Brasileirão (48,4%)."""
        contexto = para_contexto(
            _consulta(),
            _vizinhos([0.9] * 10),
            taxa_base=0.433,
        )
        assert contexto is not None
        assert contexto.metadata["taxa_base"] == 0.433

    def test_a_confianca_em_si_e_alta(self):
        """A vizinhança é boa por toda outra medida — o portão é que mede a
        coisa errada. `confidence` combina melhor similaridade, média e
        cobertura, e chega a 0,77 no mesmo conjunto que o acordo reprova."""
        vizinhos = _vizinhos([0.926 - 0.112 * i / 24 for i in range(25)])
        contexto = para_contexto(_consulta(), vizinhos)
        assert contexto is not None
        assert contexto.confidence.confidence > 0.7
        assert contexto.distribution.best_similarity > 0.9

    def test_a_funcao_de_pontuacao_e_a_mesma_do_detector(self):
        """A ponte não recalcula confiança por conta própria: usa
        `confidence_for_matches`, a mesma função pura que o detector aplica
        depois de filtrar. Duas contas de confiança divergiriam em silêncio."""
        contexto = para_contexto(_consulta(), _vizinhos([0.9, 0.85, 0.8, 0.75, 0.7]))
        assert contexto is not None
        recalculada = confidence_for_matches(
            list(contexto.matches), minimum_neighbors=MINIMO_VIZINHOS
        )
        assert recalculada.confidence == contexto.confidence.confidence
