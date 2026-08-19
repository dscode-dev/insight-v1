"""As INVARIANTES executáveis do PR-05.1 — o gate do §160 ao §163.

A DIFERENÇA ENTRE ESTES TESTES E OS DE UNIDADE. Os de unidade provam casos: «o
evento dos 64 é negado num corte de 63». Estes provam PROPRIEDADES sobre
conjuntos inteiros: «acrescentar QUALQUER fato do futuro não muda nada». A
segunda forma é a que pega o vazamento que ninguém pensou em testar.

    Snapshot(F<=t)  =  Snapshot(F<=t mais F>t)                         §160
    KnownAt_t(F)    =  KnownAt_t(F mais Corrections>t)                §161
    Unavailable    ≠  0        e     NotDeclared ≠ MeasuredZero   §162
    mesmos quatro insumos  ⇒  mesma impressão de snapshot         §163

O SENTINELA (§125) é o que transforma «passou» em «passou por bom motivo»: o
futuro do cenário carrega 999 eventos, e qualquer feature causal que os
enxergue salta de uma casa decimal — não de uma unidade que se confunda com
ruído.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import final

import pytest

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CanonicalFeatureContext
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.provenance import (
    FeatureProvenanceClass,
    ProvenanceBuilder,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.features.values import ComputedFeature
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import (
    CORRECAO_C2,
    SENTINELA_QUANTIDADE,
    _id,
    conhecimento_das_correcoes,
    contexto,
    corte,
    definicao_de_teste,
    espaco_de_teste,
    historia,
    historia_ate_o_corte,
    historia_com_sentinela,
    origem,
)

pytestmark = pytest.mark.property


# ------------------------------------------------- calculadores de TESTE --
#
# ELES NÃO SÃO FEATURES DE PRODUÇÃO (§92). São o mínimo necessário para que a
# propriedade tenha o que medir: uma contagem de eventos efetivos e um booleano
# de disponibilidade. Nenhum deles calcula janela, pressão ou força.


@final
@dataclass(frozen=True, slots=True)
class ContagemDeEventos:
    """Conta os eventos da PROJEÇÃO EFETIVA — nunca a história canônica.

    É ELE QUE O SENTINELA TESTA. Um calculador que lesse `historia()` em vez do
    contexto veria os 999 eventos do futuro, e a propriedade do §160 falharia
    com um número impossível de confundir com ruído.
    """

    definition: FeatureDefinition

    def compute(
        self, context: CanonicalFeatureContext, as_of: FeatureAsOf
    ) -> ComputedFeature:
        if not context.publishes(CoverageFamily.EVENT):
            return ComputedFeature.unavailable(
                definition_key=self.definition.key,
                definition_fingerprint=self.definition.fingerprint,
                as_of=as_of,
                availability=FeatureAvailability.NOT_DECLARED,
            )
        procedencia = ProvenanceBuilder()
        for projetado in context.events.events:
            procedencia.add("EVENT", str(projetado.id))
        return ComputedFeature.available(
            definition_key=self.definition.key,
            definition_fingerprint=self.definition.fingerprint,
            as_of=as_of,
            value=context.events.size,
            provenance=procedencia.finish(FeatureProvenanceClass.DERIVED_FROM_CANONICAL),
        )


def _definicao() -> FeatureDefinition:
    return definicao_de_teste(key="test_event_count")


def _espaco() -> FeatureSpaceDefinition:
    return espaco_de_teste(_definicao())


def _snapshot(
    *,
    as_of: FeatureAsOf,
    eventos: tuple[CanonicalMatchEvent, ...],
    policy: TemporalAvailabilityPolicy | None = None,
    knowledge: EventKnowledge | None = None,
    com_resultado: bool = True,
) -> FeatureSnapshot:
    """Calcula o snapshot do espaço de teste sobre aqueles eventos."""
    politica = policy or TemporalAvailabilityPolicy.default()
    ambiente = contexto(
        as_of=as_of,
        eventos=eventos,
        policy=politica,
        com_resultado=com_resultado,
        knowledge=knowledge,
    )
    definicao = _definicao()
    calculador = ContagemDeEventos(definition=definicao)
    return FeatureSnapshot.of(
        as_of=as_of,
        space=_espaco(),
        source=origem(),
        policy=politica,
        features=(calculador.compute(ambiente, as_of),),
    )


class TestOPrimeiroGate:
    """§126, §128, §160. Acrescentar futuro não muda o snapshot causal."""

    def test_acrescentar_o_futuro_nao_muda_o_snapshot(self) -> None:
        so_passado = _snapshot(as_of=corte(63), eventos=historia_ate_o_corte())
        com_futuro = _snapshot(as_of=corte(63), eventos=historia())
        assert so_passado.fingerprint == com_futuro.fingerprint

    def test_o_sentinela_de_novecentos_e_noventa_e_nove_nao_vaza(self) -> None:
        """§125. Se vazasse, a contagem saltaria de 4 para mais de mil."""
        limpo = _snapshot(as_of=corte(63), eventos=historia())
        com_sentinela = _snapshot(as_of=corte(63), eventos=historia_com_sentinela())
        assert limpo.fingerprint == com_sentinela.fingerprint
        assert com_sentinela.value_of("test_event_count").numeric == 4
        assert SENTINELA_QUANTIDADE == 999

    def test_a_propriedade_vale_em_varios_cortes(self) -> None:
        """§123. Ela não pode valer só no corte de referência."""
        cortes = (
            corte(9, periodo=Period.FIRST_HALF),
            corte(10, periodo=Period.FIRST_HALF),
            corte(34, periodo=Period.FIRST_HALF),
            corte(36, periodo=Period.FIRST_HALF),
            corte(63),
            corte(75),
        )
        for momento in cortes:
            passado = tuple(
                e
                for e in historia()
                if (e.clock.period.order, e.clock.minute)
                <= (momento.position.period.order, momento.position.minute)
            )
            assert (
                _snapshot(as_of=momento, eventos=passado).fingerprint
                == _snapshot(as_of=momento, eventos=historia_com_sentinela()).fingerprint
            ), f"o futuro vazou no corte {momento.position}"

    def test_o_valor_cresce_com_o_corte_e_nunca_com_o_futuro(self) -> None:
        """A contagem aos 10 é menor que aos 63 — o estado avança —, e nenhuma
        das duas depende do que vem depois."""
        aos_10 = _snapshot(
            as_of=corte(10, periodo=Period.FIRST_HALF), eventos=historia_com_sentinela()
        )
        aos_63 = _snapshot(as_of=corte(63), eventos=historia_com_sentinela())
        assert aos_10.value_of("test_event_count").numeric == 1
        assert aos_63.value_of("test_event_count").numeric == 4


class TestOSegundoGate:
    """§130, §161. Correção conhecida depois do corte não muda o replay."""

    def test_correcao_posterior_nao_muda_o_estado_anterior(self) -> None:
        sem_correcao = tuple(e for e in historia() if e.id != _id(CORRECAO_C2))
        # SEM A CORREÇÃO, o gol original está `ACTIVE`; com ela, `CORRECTED`.
        # A projeção precisa produzir o mesmo ESTADO EFETIVO nos dois casos, e
        # é por isso que o teste compara a contagem e os ids, não os objetos.
        antes = contexto(as_of=corte(34, periodo=Period.FIRST_HALF), eventos=sem_correcao)
        depois = contexto(as_of=corte(34, periodo=Period.FIRST_HALF), eventos=historia())
        assert antes.events.ids() == depois.events.ids()

    def test_a_correcao_conhecida_depois_do_corte_nao_entra(self) -> None:
        """O carimbo diz 35'; o corte de conhecimento é 33'."""
        projecao = contexto(
            as_of=corte(34, periodo=Period.FIRST_HALF, conhecimento=33),
            knowledge=conhecimento_das_correcoes(),
        ).events
        assert _id(CORRECAO_C2) not in set(projecao.ids())

    def test_a_correcao_conhecida_antes_do_corte_entra(self) -> None:
        """E aqui o estado MUDA — que é o comportamento certo (§77)."""
        projecao = contexto(
            as_of=corte(40, periodo=Period.FIRST_HALF, conhecimento=36),
            knowledge=conhecimento_das_correcoes(),
        ).events
        assert _id(CORRECAO_C2) in set(projecao.ids())


class TestOTerceiroGate:
    """§127, §162. Pós-jogo não vaza, e ausente não é zero."""

    def test_mudar_o_resultado_nao_muda_o_snapshot_intra_jogo(self) -> None:
        """§127. Ele não é consultado, então mudá-lo não pode mover nada."""
        com = _snapshot(as_of=corte(63), eventos=historia(), com_resultado=True)
        sem = _snapshot(as_of=corte(63), eventos=historia(), com_resultado=False)
        assert com.fingerprint == sem.fingerprint

    def test_indisponivel_nao_e_zero(self) -> None:
        """§162. Um corpus que não publica eventos produz INDISPONÍVEL — e não
        uma contagem de zero eventos."""
        definicao = _definicao()
        sem_eventos = replace(
            contexto(as_of=corte(63)),
            source=origem(families=frozenset({CoverageFamily.MATCH})),
        )
        calculada = ContagemDeEventos(definition=definicao).compute(sem_eventos, corte(63))
        assert not calculada.is_available
        assert calculada.numeric is None
        assert calculada.availability is FeatureAvailability.NOT_DECLARED

    def test_zero_medido_e_diferente_de_nao_declarado(self) -> None:
        """Um jogo sem evento nenhum ANTES do corte conta zero — e isso é um
        fato, não uma ausência."""
        definicao = _definicao()
        antes_de_tudo = contexto(as_of=corte(5, periodo=Period.FIRST_HALF))
        medida = ContagemDeEventos(definition=definicao).compute(
            antes_de_tudo, corte(5, periodo=Period.FIRST_HALF)
        )
        assert medida.is_available
        assert medida.numeric == 0

    def test_as_duas_ausencias_produzem_impressoes_diferentes(self) -> None:
        """Zero medido e indisponível não podem colidir na impressão."""
        definicao = _definicao()
        zero = ContagemDeEventos(definition=definicao).compute(
            contexto(as_of=corte(5, periodo=Period.FIRST_HALF)),
            corte(5, periodo=Period.FIRST_HALF),
        )
        ausente = ComputedFeature.unavailable(
            definition_key=definicao.key,
            definition_fingerprint=definicao.fingerprint,
            as_of=corte(5, periodo=Period.FIRST_HALF),
            availability=FeatureAvailability.NOT_DECLARED,
        )
        assert zero.as_canonical() != ausente.as_canonical()


class TestOQuartoGate:
    """§131, §139, §163. Reprodutibilidade."""

    def test_os_mesmos_quatro_insumos_produzem_a_mesma_impressao(self) -> None:
        primeiro = _snapshot(as_of=corte(63), eventos=historia())
        segundo = _snapshot(as_of=corte(63), eventos=historia())
        assert primeiro.fingerprint == segundo.fingerprint

    def test_a_ordem_fisica_das_linhas_nao_muda_a_impressao(self) -> None:
        """§131. Mudar a ordem de leitura sem mudar a cronologia."""
        direta = _snapshot(as_of=corte(63), eventos=historia())
        invertida = _snapshot(as_of=corte(63), eventos=tuple(reversed(historia())))
        assert direta.fingerprint == invertida.fingerprint

    def test_o_corte_muda_a_impressao(self) -> None:
        """§145. E precisa mudar: 62' e 63' são estados diferentes."""
        aos_62 = _snapshot(as_of=corte(62), eventos=historia())
        aos_63 = _snapshot(as_of=corte(63), eventos=historia())
        assert aos_62.fingerprint != aos_63.fingerprint

    def test_a_politica_muda_a_impressao(self) -> None:
        """§144. Outra causalidade, outro estado."""
        padrao = _snapshot(as_of=corte(63), eventos=historia())
        estrita = _snapshot(
            as_of=corte(63, conhecimento=63),
            eventos=historia(),
            policy=TemporalAvailabilityPolicy.strict_observed(),
        )
        assert padrao.fingerprint != estrita.fingerprint

    def test_o_modo_temporal_muda_o_estado(self) -> None:
        """A verdade retrospectiva aplica a correção; a causal, não."""
        causal = contexto(as_of=corte(63)).events.ids()
        retrospectivo = contexto(
            as_of=corte(63, mode=TemporalMode.CANONICAL_FINAL)
        ).events.ids()
        assert set(causal) != set(retrospectivo)


class TestAProcedenciaCausal:
    """§48, §50. A linhagem também não pode citar o futuro."""

    def test_a_procedencia_so_cita_eventos_do_passado(self) -> None:
        snapshot = _snapshot(as_of=corte(63), eventos=historia_com_sentinela())
        procedencia = snapshot.value_of("test_event_count").provenance
        do_futuro = {str(e.id) for e in historia_com_sentinela() if e.clock.minute > 63}
        citados = {c.reference for c in procedencia.sample}
        assert procedencia.count == 4
        assert not (citados & do_futuro)

    def test_a_procedencia_e_a_mesma_com_e_sem_futuro(self) -> None:
        """§50. Mesmo cálculo, mesma identidade semântica de procedência."""
        limpo = _snapshot(as_of=corte(63), eventos=historia())
        com_futuro = _snapshot(as_of=corte(63), eventos=historia_com_sentinela())
        assert (
            limpo.value_of("test_event_count").provenance.contribution_digest
            == com_futuro.value_of("test_event_count").provenance.contribution_digest
        )
