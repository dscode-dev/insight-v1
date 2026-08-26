"""As INVARIANTES do PR-05.2 — o gate do §195 ao §200.

A DIFERENÇA ENTRE ESTES TESTES E OS DE UNIDADE. Os de unidade provam casos: «o
gol dos 70 não entra num corte de 63». Estes provam PROPRIEDADES sobre
conjuntos inteiros de entrada:

    §195  State(F<=t)  =  State(F<=t mais F>t)      para QUALQUER futuro
    §196  reconstruir duas vezes dá a mesma impressão
    §197  degradar um componente não move os outros
    §198  Unavailable ≠ 0, e NotDeclared ≠ ObservedZero
    §199  a ordem da entrada não muda o estado
    §200  o placar vem dos EVENTOS, e nunca do `MatchResult`

A SEGUNDA FORMA É A QUE PEGA O VAZAMENTO QUE NINGUÉM PENSOU EM TESTAR. Um
teste de caso prova que aquele gol não vaza; a propriedade prova que NENHUM
fato posterior vaza — inclusive o que for acrescentado ao cenário no ano que
vem por outra pessoa.

O SENTINELA (§125, herdado do PR-05.1) transforma «passou» em «passou por bom
motivo»: o futuro carrega centenas de eventos, e um estado que os enxergasse
saltaria de uma casa decimal em vez de errar por uma unidade que se confunde
com ruído.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.details import CardType
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.state.builder import (
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.features.state.match_state import HistoricalMatchState
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import CASA, FORA, PARTIDA, corte, cotacao
from tests.support.state_fixtures import (
    CASA_BANCO,
    CASA_TITULARES,
    FORA_BANCO,
    FORA_TITULARES,
    TODAS_AS_FAMILIAS,
    construir,
    entrada,
    escalacoes,
    evento,
    historia,
    passado,
)

pytestmark = pytest.mark.property

#: Quantos fatos absurdos o futuro sintético carrega (§125). Ele é grande de
#: propósito: um estado que enxergasse o futuro não erraria por um gol — ele
#: mudaria de ordem de grandeza, e o diagnóstico seria imediato.
SENTINELAS: int = 200


def futuro_absurdo() -> tuple[CanonicalMatchEvent, ...]:
    """Um futuro que NENHUM estado de 63' pode enxergar.

    Gols dos dois lados, substituições, expulsões e cartões — um de cada
    espécie estrutural, porque a propriedade precisa valer para TODOS os
    caminhos do reducer, e não só para o do gol.
    """
    fatos: list[CanonicalMatchEvent] = []
    for n in range(SENTINELAS):
        fatos.append(
            evento(
                f"futuro-gol-casa-{n}",
                tipo=EventType.GOAL,
                minuto=70,
                periodo=Period.SECOND_HALF,
                sequencia=1000 + n,
                time=CASA,
                jogador_id=CASA_TITULARES[n % 11],
            )
        )
        fatos.append(
            evento(
                f"futuro-gol-fora-{n}",
                tipo=EventType.GOAL,
                minuto=71,
                periodo=Period.SECOND_HALF,
                sequencia=2000 + n,
                time=FORA,
                jogador_id=FORA_TITULARES[n % 11],
            )
        )
        fatos.append(
            evento(
                f"futuro-amarelo-{n}",
                tipo=EventType.CARD,
                minuto=72,
                periodo=Period.SECOND_HALF,
                sequencia=3000 + n,
                time=CASA,
                jogador_id=CASA_TITULARES[n % 11],
                cartao=CardType.YELLOW,
            )
        )
    fatos.append(
        evento(
            "futuro-substituicao",
            tipo=EventType.SUBSTITUTION,
            minuto=75,
            periodo=Period.SECOND_HALF,
            sequencia=4000,
            time=FORA,
            substituicao=(FORA_TITULARES[9], FORA_BANCO[0]),
        )
    )
    fatos.append(
        evento(
            "futuro-vermelho",
            tipo=EventType.CARD,
            minuto=80,
            periodo=Period.SECOND_HALF,
            sequencia=4001,
            time=CASA,
            jogador_id=CASA_TITULARES[0],
            cartao=CardType.RED,
        )
    )
    return tuple(fatos)


def observavel(estado: HistoricalMatchState) -> tuple[object, ...]:
    """O que o estado AFIRMA — sem a procedência e sem a contagem de eventos.

    ELA EXISTE PARA SEPARAR DUAS PERGUNTAS. «O estado observável mudou?» é
    diferente de «a identidade mudou?»: a segunda inclui a procedência, e um
    teste que só olhasse a impressão não diria QUAL componente vazou.
    """
    return (
        estado.score.as_canonical(),
        estado.on_field.as_canonical(),
        estado.discipline.as_canonical(),
        estado.substitutions.as_canonical(),
        estado.odds.as_canonical(),
    )


# ------------------------------------------------------------------ §195 --


class TestFuturoNaoVaza:
    """`State(F<=t) = State(F<=t mais F>t)` — para qualquer `F>t`."""

    def test_o_estado_e_identico_com_e_sem_o_futuro(self) -> None:
        so_passado = construir(entrada(eventos=passado())).state
        com_futuro = construir(entrada(eventos=(*passado(), *futuro_absurdo()))).state
        assert observavel(com_futuro) == observavel(so_passado)
        assert com_futuro.fingerprint == so_passado.fingerprint

    def test_o_futuro_absurdo_nao_move_o_placar(self) -> None:
        """Seiscentos fatos depois do corte, e o placar continua 1-1."""
        estado = construir(entrada(eventos=(*passado(), *futuro_absurdo()))).state
        assert (estado.score.home, estado.score.away) == (1, 1)

    def test_o_futuro_absurdo_nao_move_o_campo(self) -> None:
        estado = construir(entrada(eventos=(*passado(), *futuro_absurdo()))).state
        casa = estado.on_field.team(CASA)
        fora = estado.on_field.team(FORA)
        assert casa is not None
        assert fora is not None
        assert (casa.size, fora.size) == (11, 10)

    def test_o_futuro_absurdo_nao_move_a_disciplina(self) -> None:
        estado = construir(entrada(eventos=(*passado(), *futuro_absurdo()))).state
        casa = estado.discipline.team(CASA)
        assert casa is not None
        assert (casa.yellow_cards, casa.dismissals) == (1, 0)

    @pytest.mark.parametrize(
        ("minuto", "periodo"),
        [
            (0, Period.PRE_MATCH),
            (12, Period.FIRST_HALF),
            (45, Period.FIRST_HALF),
            (58, Period.SECOND_HALF),
            (63, Period.SECOND_HALF),
            (89, Period.SECOND_HALF),
        ],
    )
    def test_a_propriedade_vale_em_todo_corte(self, minuto: int, periodo: Period) -> None:
        """§195 vale para QUALQUER `t`, e não só para o corte de referência."""
        alvo = FeatureAsOf.at(PARTIDA, periodo, minuto)
        so_historia = construir(entrada(eventos=historia()), as_of=alvo).state
        com_ruido = construir(entrada(eventos=(*historia(), *futuro_absurdo())), as_of=alvo).state
        # O ruído só é FUTURO a partir dos 70; nos cortes anteriores a ele, os
        # dois estados precisam coincidir. Nos posteriores, o ruído é passado
        # legítimo — e aí a diferença é esperada, e não vazamento.
        if periodo is Period.SECOND_HALF and minuto >= 70:
            assert observavel(com_ruido) != observavel(so_historia)
        else:
            assert observavel(com_ruido) == observavel(so_historia)

    def test_a_cotacao_do_futuro_nao_entra(self) -> None:
        """§46 — a régua de parede também é causal."""
        base = entrada(odds=(cotacao(-60.0),))
        com_futuro = entrada(odds=(cotacao(-60.0), cotacao(120.0, valor="9.99")))
        alvo = corte(conhecimento=63)
        assert (
            construir(com_futuro, as_of=alvo).state.fingerprint
            == construir(base, as_of=alvo).state.fingerprint
        )

    def test_o_resultado_publicado_nao_muda_o_estado_intra_jogo(self) -> None:
        """§200 — o `MatchResult` é invisível antes do apito final."""
        sem = construir(entrada(result=None)).state
        com = construir(entrada(result=MatchResult(regular_time=Score(home=9, away=0)))).state
        assert com.fingerprint == sem.fingerprint


# ------------------------------------------------------------------ §196 --


class TestReprodutibilidade:
    """Os mesmos quatro insumos produzem o mesmo estado — sempre."""

    def test_dez_reconstrucoes_dao_a_mesma_impressao(self) -> None:
        impressoes = {construir().state.fingerprint for _ in range(10)}
        assert len(impressoes) == 1

    def test_a_impressao_muda_quando_o_corpus_muda(self) -> None:
        """§8 — «parece igual» seria coincidência, e não reprodutibilidade."""
        from tests.support.feature_fixtures import origem

        outro = origem(families=TODAS_AS_FAMILIAS, fingerprint="c" * 64)
        estado = (
            HistoricalMatchStateBuilder(policy=TemporalAvailabilityPolicy.default())
            .build(entrada(), as_of=corte(), source=outro)
            .state
        )
        assert estado.fingerprint != construir().state.fingerprint

    def test_a_impressao_muda_quando_a_politica_muda(self) -> None:
        estrita = construir(policy=TemporalAvailabilityPolicy.strict_observed()).state
        assert estrita.fingerprint != construir().state.fingerprint

    def test_o_estado_observavel_nao_depende_do_objeto_de_entrada(self) -> None:
        """Duas montagens equivalentes da MESMA entrada dão o mesmo estado."""
        a = construir(entrada(eventos=passado())).state
        b = construir(entrada(eventos=tuple(passado()))).state
        assert a.fingerprint == b.fingerprint


# ------------------------------------------------------------------ §197 --


class TestIndependenciaDeComponentes:
    """Degradar um componente não move os outros (§105, §106)."""

    def test_sem_escalacao_o_placar_e_a_disciplina_sobrevivem(self) -> None:
        completo = construir().state
        sem_campo = construir(
            entrada(families=frozenset(TODAS_AS_FAMILIAS) - {CoverageFamily.LINEUP})
        ).state
        assert sem_campo.score.as_canonical() == completo.score.as_canonical()
        assert sem_campo.discipline.as_canonical() == completo.discipline.as_canonical()
        assert not sem_campo.on_field.is_available

    def test_sem_odds_o_resto_do_estado_e_o_mesmo(self) -> None:
        com = construir(entrada(odds=(cotacao(-60.0),)), as_of=corte(conhecimento=63)).state
        sem = construir(entrada(odds=()), as_of=corte(conhecimento=63)).state
        assert com.score.as_canonical() == sem.score.as_canonical()
        assert com.on_field.as_canonical() == sem.on_field.as_canonical()

    def test_um_lado_degradado_nao_derruba_o_outro(self) -> None:
        """O conflito no elenco do mandante não diz nada sobre o visitante."""
        conflito = evento(
            "substituicao-impossivel",
            tipo=EventType.SUBSTITUTION,
            minuto=50,
            periodo=Period.SECOND_HALF,
            sequencia=99,
            time=CASA,
            substituicao=(CASA_BANCO[2], CASA_BANCO[1]),
        )
        estado = construir(entrada(eventos=(*passado(), conflito))).state
        casa = estado.on_field.team(CASA)
        fora = estado.on_field.team(FORA)
        assert casa is not None
        assert not casa.is_available
        assert fora is not None
        assert fora.is_available
        assert fora.size == 10

    def test_o_placar_sobrevive_ao_jogador_nos_dois_times(self) -> None:
        """§106 — o defeito é do elenco, e o placar não depende dele."""
        cruzada = escalacoes(titulares_fora=(CASA_TITULARES[0], *FORA_TITULARES[1:]))
        estado = construir(entrada(lineups=cruzada)).state
        assert estado.score.is_available
        assert (estado.score.home, estado.score.away) == (1, 1)
        assert not estado.on_field.is_available


# ------------------------------------------------------------------ §198 --


class TestAusenciaNaoEZero:
    """`Unavailable ≠ 0` e `NotDeclared ≠ ObservedZero`."""

    def test_placar_nao_declarado_nao_e_zero_a_zero_observado(self) -> None:
        observado = construir(as_of=FeatureAsOf.pre_match(PARTIDA)).state
        nao_declarado = construir(
            entrada(families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})),
            as_of=FeatureAsOf.pre_match(PARTIDA),
        ).state
        assert (observado.score.home, nao_declarado.score.home) == (0, 0)
        assert observado.score.is_available
        assert not nao_declarado.score.is_available
        assert observado.fingerprint != nao_declarado.fingerprint

    def test_zero_cartoes_observado_nao_e_disciplina_ausente(self) -> None:
        observado = construir(entrada(eventos=()), as_of=FeatureAsOf.pre_match(PARTIDA)).state
        ausente = construir(
            entrada(families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP})),
            as_of=FeatureAsOf.pre_match(PARTIDA),
        ).state
        casa_observada = observado.discipline.team(CASA)
        casa_ausente = ausente.discipline.team(CASA)
        assert casa_observada is not None
        assert casa_ausente is not None
        assert casa_observada.yellow_cards == casa_ausente.yellow_cards == 0
        assert casa_observada.is_available
        assert not casa_ausente.is_available

    def test_odds_ausente_e_odds_nao_publicada_sao_estados_diferentes(self) -> None:
        sem_familia = construir(
            entrada(families=frozenset(TODAS_AS_FAMILIAS) - {CoverageFamily.ODDS})
        ).state
        familia_sem_dado = construir(entrada(odds=())).state
        fora_do_corte = construir(entrada(odds=(cotacao(-60.0),))).state
        estados = {
            sem_familia.odds.availability,
            familia_sem_dado.odds.availability,
            fora_do_corte.odds.availability,
        }
        assert estados == {
            FeatureAvailability.NOT_DECLARED,
            FeatureAvailability.SOURCE_UNAVAILABLE,
            FeatureAvailability.TEMPORALLY_UNAVAILABLE,
        }

    def test_nenhum_componente_indisponivel_carrega_valor_utilizavel(self) -> None:
        """Um campo «indisponível» com dez nomes seria usado como dez nomes."""
        estado = construir(entrada(lineups=())).state
        casa = estado.on_field.team(CASA)
        assert casa is not None
        assert casa.players == ()


# ------------------------------------------------------------------ §199 --


class TestOrdemDaEntrada:
    """A ordem em que os fatos chegam não muda o estado."""

    @pytest.mark.parametrize("giro", [1, 2, 3, 4])
    def test_rotacionar_a_entrada_nao_muda_o_estado(self, giro: int) -> None:
        fatos = passado()
        girada = (*fatos[giro:], *fatos[:giro])
        assert (
            construir(entrada(eventos=girada)).state.fingerprint
            == construir(entrada(eventos=fatos)).state.fingerprint
        )

    def test_a_entrada_invertida_produz_o_mesmo_estado(self) -> None:
        invertida = tuple(reversed(passado()))
        assert (
            construir(entrada(eventos=invertida)).state.fingerprint
            == construir(entrada(eventos=passado())).state.fingerprint
        )

    def test_toda_permutacao_de_um_recorte_produz_o_mesmo_estado(self) -> None:
        """Vinte e quatro ordens, um estado — a ordenação é da projeção."""
        recorte = passado()[:4]
        impressoes = {
            construir(entrada(eventos=ordem)).state.fingerprint
            for ordem in itertools.permutations(recorte)
        }
        assert len(impressoes) == 1

    def test_a_ordem_das_escalacoes_nao_importa(self) -> None:
        direta = escalacoes()
        assert (
            construir(entrada(lineups=tuple(reversed(direta)))).state.fingerprint
            == construir(entrada(lineups=direta)).state.fingerprint
        )

    def test_a_ordem_das_cotacoes_nao_importa(self) -> None:
        cotacoes = (cotacao(-60.0, valor="1.70"), cotacao(-30.0, valor="1.80"))
        alvo = corte(conhecimento=63)
        assert (
            construir(entrada(odds=tuple(reversed(cotacoes))), as_of=alvo).state.fingerprint
            == construir(entrada(odds=cotacoes), as_of=alvo).state.fingerprint
        )


# ------------------------------------------------------------------ §200 --


class TestAutoridadeDoPlacar:
    """O placar vem dos EVENTOS efetivos, e de nada mais."""

    def test_qualquer_resultado_publicado_produz_o_mesmo_placar_intra_jogo(self) -> None:
        placares = [
            None,
            MatchResult(regular_time=Score(home=0, away=0)),
            MatchResult(regular_time=Score(home=2, away=1)),
            MatchResult(regular_time=Score(home=9, away=9)),
        ]
        obtidos = {
            construir(entrada(result=r)).state.score.as_canonical()["regular"]["home"]  # type: ignore[index]
            for r in placares
        }
        assert obtidos == {1}

    def test_sem_gol_efetivo_nao_ha_ponto_no_placar(self) -> None:
        sem_gols = tuple(e for e in passado() if e.type is not EventType.GOAL)
        estado = construir(entrada(eventos=sem_gols, result=resultado_impossivel())).state
        assert (estado.score.home, estado.score.away) == (0, 0)
        assert estado.score.is_available

    def test_o_gol_cancelado_nao_conta(self) -> None:
        """§17 — a autoridade sobre o que é efetivo é a projeção do PR-05.1."""
        from sports_intelligence.domain.events.canonical import EventStatus

        cancelado = replace(passado()[0], status=EventStatus.CANCELLED)
        estado = construir(entrada(eventos=(cancelado, *passado()[1:]))).state
        assert (estado.score.home, estado.score.away) == (0, 1)

    def test_no_apito_final_o_placar_continua_sendo_o_dos_eventos(self) -> None:
        """§101 — a conferência é diagnóstico, e nunca correção."""
        estado = construir(
            entrada(result=MatchResult(regular_time=Score(home=7, away=0))),
            as_of=FeatureAsOf.at(PARTIDA, Period.FULL_TIME, 90),
        ).state
        assert (estado.score.home, estado.score.away) == (2, 1)


def resultado_impossivel() -> MatchResult:
    """Um resultado que nenhum conjunto de eventos do cenário produz."""
    return MatchResult(regular_time=Score(home=4, away=4))
