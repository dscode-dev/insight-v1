"""Os erros do motor de features — tipados, e ancorados no catálogo existente.

POR QUE NÃO SÃO `ValidationError` GENÉRICOS. Três das quatro situações abaixo
não são «entrada inválida»: elas são pedidos coerentes que o domínio recusa por
razão própria, e a ação de quem os recebe é diferente em cada caso.

    TemporalLeakageError            o cálculo pediu um fato do futuro
    FeatureDefinitionError          a definição em si é incoerente
    FeatureSpaceCompatibilityError  espaço e corpus não combinam
    TemporalAvailabilityError       a política não sabe classificar o fato

O CATÁLOGO EXISTENTE É REAPROVEITADO, e não substituído: os quatro herdam de
`EngineError` pela categoria certa, então o logger, a resposta de erro e a
trilha continuam funcionando sem saber que features existem.
"""

from __future__ import annotations

from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
    ValidationError,
)


class FeatureDefinitionError(ValidationError):
    """A definição de feature é incoerente com ela mesma.

    Chave malformada, parâmetro não primitivo, dependência de si própria.
    Conserta-se corrigindo a declaração.
    """


class FeatureSpaceCompatibilityError(ConflictError):
    """O espaço e o corpus (ou o modo temporal) não combinam.

    `ConflictError` E NÃO `ValidationError`: não há nada errado com o espaço
    nem com o corpus isoladamente — o que não existe é a combinação. Quem
    recebe escolhe outro corpus ou outro espaço.
    """


class TemporalAvailabilityError(ValidationError):
    """A política temporal não cobre o que lhe perguntaram.

    Uma família de fato sem classificação, um corte sem a régua que o fato
    exige. Conserta-se declarando — nunca assumindo.
    """


class TemporalLeakageError(InvariantViolationError):
    """Um fato do futuro chegou ao cálculo.

    `InvariantViolationError` É DELIBERADO E É A COISA MAIS FORTE DESTE
    MÓDULO. Vazamento temporal não é entrada inválida nem conflito de
    configuração: é uma promessa estrutural quebrada — o motor afirma que
    `Feature_t = f(Facts_≤t)`, e alguém entregou `Facts_>t`. Não se trata com
    retry, não se devolve como «400», e não se contorna: investiga-se.

    ELE NÃO É LEVANTADO NO CAMINHO NORMAL. O caminho normal é o guarda recusar
    o fato e a feature sair indisponível com motivo. Este erro existe para o
    caso em que a recusa foi CONTORNADA — um calculador que recebeu contexto
    montado sem projeção, por exemplo. É a última linha, e ela deve ser
    silenciosa em produção.
    """
