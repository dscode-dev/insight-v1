"""O que é uma feature — antes de existir qualquer feature.

UMA `FeatureDefinition` É UM CONTRATO SEMÂNTICO, e não um nome com um cálculo
pendurado. Ela declara o que a feature significa, que tipo de valor produz, de
que fatos depende, sob que causalidade pode ser calculada e o que acontece
quando o dado falta. É esse contrato que permite dizer, meses depois, se dois
números chamados `shots_home_5m` são a mesma coisa.

    FeatureIdentity = Key + Version + ContentFingerprint

A IMPRESSÃO É O QUE FECHA A IDENTIDADE (§35, §37). Chave e versão são
declaração humana e podem mentir: alguém muda a janela de 5 para 10 minutos e
esquece de subir a versão. A impressão não deixa — o conteúdo mudou, a
identidade muda, e a comparação entre o antes e o depois passa a ser
explicitamente entre coisas diferentes.

NENHUMA FEATURE DE PRODUÇÃO É DEFINIDA AQUI (§32, §115 ao §119). Não há
`shots_home_5m`, não há pressão, não há força de time. O que existe é o
contrato que elas vão precisar cumprir — e definições de teste, que vivem nos
testes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, final

from sports_intelligence.domain.features.availability import FactKind
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import Version

#: A forma de uma chave de feature. Minúsculas, dígitos e sublinhado — nada de
#: espaço, acento ou maiúscula. Ela vira nome de coluna, chave de dicionário e
#: eixo de vetor; uma chave com espaço quebra o primeiro dos três.
_FORMA_DA_CHAVE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


@final
class FeatureOutputType(StrEnum):
    """O tipo do valor que a feature produz. Catálogo FECHADO (§38).

    NÃO EXISTE `VECTOR` AQUI, e a ausência é a decisão: o vetor é a
    representação do ESPAÇO, montada a partir de features escalares ordenadas —
    e não o tipo de saída de uma feature. Introduzi-lo agora seria antecipar o
    `MatchStateVector`, que é o PR-05.2/05.3.
    """

    FLOAT = "FLOAT"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    CATEGORY = "CATEGORY"

    @property
    def is_numeric(self) -> bool:
        return self in (FeatureOutputType.FLOAT, FeatureOutputType.INTEGER)


@final
class FeatureScope(StrEnum):
    """A quem a feature se refere (§39).

    `HOME_TEAM` e `AWAY_TEAM` SÃO SEPARADOS DE `TEAM` de propósito: os dois
    primeiros são posições da partida — quem joga em casa —, e o terceiro é uma
    feature calculada para um time identificado. `score_diff` é `MATCH`;
    `shots_home_5m` é `HOME_TEAM`; uma força de time seria `TEAM`.

    `PLAYER` existe no catálogo e NÃO tem motor (§39): declará-lo não implementa
    nada, e omiti-lo obrigaria a mudar o enum quando o PR de jogador chegar.
    """

    MATCH = "MATCH"
    HOME_TEAM = "HOME_TEAM"
    AWAY_TEAM = "AWAY_TEAM"
    TEAM = "TEAM"
    PLAYER = "PLAYER"


@final
class FeatureTemporalClass(StrEnum):
    """Sob qual causalidade a feature pode ser calculada.

    ELA NÃO É A CLASSE DO FATO (`TemporalAvailability`), e a diferença é o
    sentido: aquela descreve QUANDO um fato pode ser conhecido; esta declara o
    que a FEATURE exige de quem a alimenta.
    """

    #: Só informação pré-jogo. Escalação divulgada, mando, competição.
    PRE_MATCH = "PRE_MATCH"
    #: Estado dentro do jogo, com causalidade estrita: só fatos que poderiam
    #: ser conhecidos no corte.
    INTRA_MATCH_CAUSAL = "INTRA_MATCH_CAUSAL"
    #: Só faz sentido depois do apito — placar final, resultado.
    POST_MATCH = "POST_MATCH"

    @property
    def requires_causal_knowledge(self) -> bool:
        """Se a feature exige prova de conhecimento, e não só de ocorrência."""
        return self is FeatureTemporalClass.INTRA_MATCH_CAUSAL


@final
@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """O contrato de UMA feature (§31).

    O QUE CADA CAMPO EXISTE PARA IMPEDIR:

        key/version          duas features com o mesmo nome significando coisas
                             diferentes em corpus diferentes
        output_type          um booleano virando `0.0` num vetor de floats sem
                             ninguém decidir isso
        unit                 comparar «minutos» com «segundos» achando que é a
                             mesma escala
        scope                somar uma feature de mandante com uma de visitante
        temporal_class       calcular estado intra-jogo com placar final
        required_families    descobrir na décima milésima partida que o corpus
                             não publica eventos
        required_fact_kinds  a mesma coisa, na régua temporal
        parameters           «a janela mudou de 5 para 10 e a identidade não»
        missing_policy       o zero silencioso
        normalizer_key       normalizar sem declarar com o quê
    """

    key: str
    version: Version
    description: str
    output_type: FeatureOutputType
    scope: FeatureScope
    temporal_class: FeatureTemporalClass
    #: As famílias do corpus sem as quais esta feature não pode existir (§57).
    required_families: tuple[CoverageFamily, ...] = ()
    #: As famílias TEMPORAIS de fato que ela consome. É o que o guarda usa.
    required_fact_kinds: tuple[FactKind, ...] = ()
    #: Os parâmetros que mudam o SIGNIFICADO — janela, limiar, unidade de
    #: agregação. Valores primitivos apenas: eles entram na impressão, e um
    #: objeto arbitrário ali não teria serialização determinística (§36).
    parameters: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    #: A unidade semântica, quando existe: `goals`, `minutes`, `probability`.
    unit: str | None = None
    #: Quando `True`, a feature NÃO pode ser calculada sem prova de que todo
    #: fato usado era conhecível — o fail-closed do §27 declarado por feature.
    fail_closed: bool = True
    #: A chave do normalizador, quando a feature exige normalização (§83).
    normalizer_key: str | None = None
    #: Features das quais esta depende (§104). Vazio na V1 — o motor de
    #: composição não existe, e o registro recusa ciclo mesmo assim (§105).
    depends_on_features: tuple[str, ...] = ()
    #: A impressão, MEMORIZADA. Ela é `init=False` de propósito: `replace()`
    #: não a copia, então uma definição derivada de outra recalcula a sua em
    #: vez de herdar a do original — que seria o pior defeito possível aqui.
    #:
    #: POR QUE MEMORIZAR (PR-05.3 §108). A impressão é invariante de um objeto
    #: congelado, e o extrator a consulta cento e cinquenta vezes por snapshot:
    #: setenta e cinco ao construir os valores e setenta e cinco quando o
    #: snapshot confere cada um contra o espaço. Num lote de dez mil, são um
    #: milhão e meio de SHA-256 sobre setenta e cinco objetos que não mudam —
    #: metade do tempo de extração, medida em profile.
    _fingerprint: str = field(default="", compare=False, repr=False, init=False)

    def __post_init__(self) -> None:
        if not _FORMA_DA_CHAVE.match(self.key):
            raise ValidationError(
                f"chave de feature inválida: {self.key!r}. Ela vira nome de coluna, "
                "chave de dicionário e eixo de vetor — minúsculas, dígitos e "
                "sublinhado, começando por letra",
                context={"key": self.key},
            )
        if not self.description.strip():
            raise ValidationError(
                f"feature {self.key} sem descrição: seis meses depois, «o que este "
                "número significa» não teria resposta"
            )
        if self.key in self.depends_on_features:
            raise ValidationError(f"feature {self.key} depende de si mesma")
        if len(set(self.depends_on_features)) != len(self.depends_on_features):
            raise ValidationError(f"feature {self.key} com dependência repetida")
        for nome, valor in self.parameters.items():
            if not isinstance(valor, str | int | float | bool | type(None)):
                raise ValidationError(
                    f"parâmetro {nome!r} de {self.key} não é primitivo: ele entra na "
                    "impressão, e um objeto arbitrário ali não tem serialização "
                    "determinística"
                )
        if self.temporal_class is FeatureTemporalClass.PRE_MATCH and (
            FactKind.EVENT_ORIGINAL in self.required_fact_kinds
            or FactKind.EVENT_REVISION in self.required_fact_kinds
        ):
            raise ValidationError(
                f"feature {self.key} é PRE_MATCH e declara depender de evento — "
                "eventos acontecem depois do apito inicial, e a declaração seria "
                "recusada em todo cálculo"
            )

    @property
    def identity(self) -> str:
        """`chave@versão#impressão` — a identidade completa (§35)."""
        return f"{self.key}@{self.version}#{self.fingerprint[:16]}"

    def as_canonical(self) -> dict[str, Any]:
        """O conteúdo que define a feature (§36).

        O QUE NÃO ENTRA: `description`, carimbo de criação, endereço de
        memória, `repr` de objeto. A descrição é para quem lê — reescrevê-la
        não muda o que a feature calcula, e fazê-la mudar a identidade
        transformaria revisão de texto em quebra de compatibilidade.
        """
        return {
            "depends_on_features": sorted(self.depends_on_features),
            "fail_closed": self.fail_closed,
            "key": self.key,
            "normalizer_key": self.normalizer_key,
            "output_type": self.output_type.value,
            "parameters": {k: self.parameters[k] for k in sorted(self.parameters)},
            "required_families": sorted(f.value for f in self.required_families),
            "required_fact_kinds": sorted(k.value for k in self.required_fact_kinds),
            "scope": self.scope.value,
            "temporal_class": self.temporal_class.value,
            "unit": self.unit,
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 da forma canônica — 64 hex (§34).

        CALCULADA UMA VEZ POR OBJETO. O `dataclass` é congelado: a forma
        canônica não muda, e portanto a impressão também não. `object.__setattr__`
        é o caminho normal para preencher um campo de um congelado, e o campo é
        `compare=False` — dois objetos continuam iguais pelo CONTEÚDO, e não
        por terem sido impressos.
        """
        if not self._fingerprint:
            object.__setattr__(
                self,
                "_fingerprint",
                hashlib.sha256(canonical_json(self.as_canonical())).hexdigest(),
            )
        return self._fingerprint

    def requires(self, family: CoverageFamily) -> bool:
        return family in self.required_families

    def __str__(self) -> str:
        return self.identity
