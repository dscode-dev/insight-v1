"""O port do calculador de feature — puro, determinístico, sem I/O.

A ASSINATURA É O CONTRATO INTEIRO (§91, §95):

    Feature = f(Definition, AsOf, CanonicalContext)

Três entradas e uma saída. Nenhuma conexão de banco, nenhum repositório,
nenhum cliente de object store — e a ausência deles não é economia de
parâmetros: um calculador que pudesse ler o corpus poderia ler o FUTURO dele, e
todas as guardas temporais deste PR passariam a depender de disciplina em vez
de estrutura (§94).

DETERMINÍSTICO SIGNIFICA O QUE PARECE. Duas chamadas com as mesmas três
entradas devolvem o mesmo valor, com a mesma procedência — sem relógio, sem
sorteio, sem estado guardado entre chamadas. É essa propriedade que torna o
snapshot reproduzível (§139) e o teste de vazamento possível: se o resultado
pudesse variar sozinho, nenhuma propriedade sobre ele seria verificável.

NENHUM CALCULADOR DE PRODUÇÃO EXISTE (§92). Este PR entrega o contrato; as
implementações reais — contagem em janela, diferença de placar, pressão —
chegam nas fases seguintes, e as de teste vivem nos testes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.context import CanonicalFeatureContext
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.features.values import ComputedFeature


@runtime_checkable
class FeatureCalculator(Protocol):
    """Calcula UMA feature a partir do contexto de UMA partida.

    ELE DEVOLVE `ComputedFeature`, E NUNCA LEVANTA POR AUSÊNCIA. Um fato que
    falta, um corte que proíbe ou uma cobertura insuficiente produzem valor
    INDISPONÍVEL com motivo — não exceção. A exceção fica para o que é defeito
    nosso: definição incompatível com o contexto, contrato quebrado.

    A DIFERENÇA IMPORTA no lote: uma partida sem escalação não pode derrubar o
    cálculo das outras nove mil, e um `try/except` em volta de cada feature
    transformaria toda ausência legítima em erro engolido.
    """

    @property
    def definition(self) -> FeatureDefinition:
        """A definição que este calculador implementa.

        ELE CARREGA A DEFINIÇÃO, e não recebe qualquer uma: é isso que permite
        ao registro conferir que o calculador de `shots_home_5m` implementa a
        versão de `shots_home_5m` que o espaço declara — e não outra com o
        mesmo nome.
        """
        ...

    def compute(self, context: CanonicalFeatureContext, as_of: FeatureAsOf) -> ComputedFeature:
        """O valor da feature naquele corte.

        `as_of` VEM SEPARADO DO CONTEXTO de propósito, mesmo o contexto já o
        carregando: a assinatura declara que o corte é entrada do cálculo, e
        não um detalhe de como o contexto foi montado. Um calculador que
        ignorasse o corte e olhasse só o contexto continuaria correto — e a
        assinatura deixaria de dizer a verdade sobre o que ele depende.
        """
        ...
