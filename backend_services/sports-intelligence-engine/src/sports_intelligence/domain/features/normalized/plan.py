"""O plano de normalização — qual transformação cada eixo recebe, e por quê.

A DECISÃO CENTRAL DESTE MÓDULO, e ela é científica e não técnica: **escalar ou
não escalar é uma decisão SEMÂNTICA sobre o que a dimensão mede**, e nunca uma
consequência do tipo dela.

    if dtype == float: normalize()        ← PROIBIDO, e o teste de
                                            arquitetura recusa

`xg_home_5m` e `corners_home_5m` são os dois números. O primeiro é uma
quantidade contínua cuja escala varia entre ligas; o segundo é uma contagem
discreta de eventos raros numa janela curta, e a distribuição dela num minuto é
quase toda zero. Dividir o segundo por um IQR — que ali vale zero — não produz
uma escala: produz uma dimensão inutilizada.

    PASS_THROUGH_V1        a escala já significa alguma coisa; preservá-la
    ROBUST_MEDIAN_IQR_V1   a escala relativa à competição é o que importa

`PASS_THROUGH` NÃO É FALLBACK. Ele é uma decisão declarada, tomada por família,
com motivo escrito. A diferença importa: um fallback acontece quando o ajuste
falha, e esta escolha acontece ANTES de qualquer ajuste existir.

E NÃO HÁ FALLBACK NENHUM EM TEMPO DE EXECUÇÃO. Uma feature declarada
`ROBUST_MEDIAN_IQR_V1` cujo artefato saia `DEGENERATE_SCALE` **não** vira
`PASS_THROUGH`: a célula fica indisponível com motivo tipado. Trocar de
estratégia calada faria duas linhas do mesmo dataset serem produzidas por
regras diferentes, e nada no arquivo diria qual.

A CLASSIFICAÇÃO VEM DOS METADADOS DO CATÁLOGO, e não de casar texto de chave. O
catálogo já sabe que `xg_home_5m` é da família `XG` e que
`market_1x2_home_support` é do tipo `SUPPORT`; perguntar isso ao objeto é
robusto, e `key.startswith("xg_")` quebra no dia em que alguém acrescentar
`xg_pressure_index`.

O PLANO É COMPLETO POR CONSTRUÇÃO. As cento e cinco definições do espaço têm
exatamente uma entrada cada — nem curinga, nem padrão implícito, nem omissão. O
construtor recusa qualquer uma das três.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Self, final

from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.extraction.catalog import (
    RollingFamily,
    RollingFeatureSpec,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ContextFeatureKind,
    ContextFeatureSpec,
    ExtendedFeatureCatalog,
    ExtendedFeatureSpec,
    MarketFeatureKind,
    MarketFeatureSpec,
    extended_feature_catalog,
)
from sports_intelligence.domain.features.normalization import (
    DEFAULT_V1_NORMALIZER,
    NormalizerDefinition,
)
from sports_intelligence.domain.features.normalized.bridge import (
    DEFAULT_INPUT_BRIDGE,
    DEFAULT_OUTPUT_ENCODING,
    DecimalToFloatEncoding,
    FloatToDecimalBridge,
)
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

#: O nome e a versão do plano. Ele é um CONTRATO, e por isso tem identidade
#: própria: dois datasets normalizados sob planos diferentes não são
#: comparáveis, ainda que venham do mesmo dataset cru.
NORMALIZATION_PLAN_NAME: Final[str] = "MATCH_STATE_NORMALIZATION_PLAN_V1"
NORMALIZATION_PLAN_VERSION: Final[str] = "1.0"

#: A metade do split sobre a qual o ajuste acontece. Ela entra na impressão do
#: plano porque um plano ajustado sobre a avaliação seria outro plano — e o
#: número que ele produzisse pareceria igual.
FIT_SPLIT: Final[str] = "REFERENCE"

PLAN_FINGERPRINT_ALGORITHM: Final[str] = "normalization-plan-sha256-v1"


@final
class TransformStrategy(StrEnum):
    """O catálogo FECHADO de transformações da V1.

    DUAS, E A LISTA DO QUE NÃO ESTÁ AQUI É A DECISÃO: sem z-score, sem
    min-max, sem logaritmo, sem winsorização, sem recorte, sem Box-Cox, sem
    transformação por quantis, sem nada aprendido. Cada uma dessas é uma
    decisão estatística com evidência própria, e nenhuma foi tomada.
    """

    #: O valor cru atravessa intacto. Nenhum artefato é necessário.
    PASS_THROUGH = "PASS_THROUGH_V1"
    #: `(x - mediana) / IQR`, com artefato por competição (PR-05.4).
    ROBUST_MEDIAN_IQR = "ROBUST_MEDIAN_IQR_V1"

    @property
    def requires_artifact(self) -> bool:
        return self is TransformStrategy.ROBUST_MEDIAN_IQR


@final
class TransformRationale(StrEnum):
    """POR QUE cada eixo recebe a transformação que recebe. Catálogo fechado.

    ELE EXISTE PARA SER LIDO, e vai para o documento do plano. «Por que os
    escanteios não são escalados?» é uma pergunta que alguém faz seis meses
    depois, e a resposta não pode ser «porque sim» nem exigir arqueologia de
    commit.
    """

    #: Coordenada de relógio: a escala é o próprio minuto do jogo.
    CLOCK_COORDINATE = "CLOCK_COORDINATE"
    #: Estado estrutural da partida — placar, jogadores em campo, cartões,
    #: substituições. A unidade É a contagem, e reescalá-la apaga o significado.
    STRUCTURAL_MATCH_STATE = "STRUCTURAL_MATCH_STATE"
    #: Contagem discreta de eventos numa janela curta. A distribuição é quase
    #: toda zero, o IQR tende a zero, e escalar inutilizaria a dimensão.
    SPARSE_DISCRETE_COUNT = "SPARSE_DISCRETE_COUNT"
    #: Quantas casas de aposta sustentam o consenso. É contagem de suporte, e
    #: não preço: comparar «quatro casas» com «quatro casas» já é comparável.
    BOOKMAKER_SUPPORT_COUNT = "BOOKMAKER_SUPPORT_COUNT"
    #: Quantas partidas o time jogou na janela. Contagem pequena e limitada.
    CALENDAR_MATCH_COUNT = "CALENDAR_MATCH_COUNT"
    #: Quantidade contínua cuja escala típica difere entre competições.
    CONTINUOUS_COMPETITION_SCALED = "CONTINUOUS_COMPETITION_SCALED"
    #: Preço de mercado: o nível absoluto depende da liga e do equilíbrio dela.
    MARKET_PRICE_LEVEL = "MARKET_PRICE_LEVEL"
    #: Dispersão de preço entre casas: mesma razão do nível.
    MARKET_PRICE_DISPERSION = "MARKET_PRICE_DISPERSION"
    #: Intervalo de calendário em horas — contínuo, e a escala varia com o
    #: formato da competição.
    CALENDAR_INTERVAL_HOURS = "CALENDAR_INTERVAL_HOURS"


@final
@dataclass(frozen=True, slots=True)
class FeatureTransform:
    """A entrada do plano para UMA feature.

    ELA CARREGA A IMPRESSÃO DA DEFINIÇÃO, e não só a chave. Duas versões da
    mesma feature têm a mesma chave e escalas diferentes; um plano que
    guardasse só o nome continuaria «válido» depois de a definição mudar.
    """

    feature_key: str
    feature_version: str
    feature_fingerprint: str
    strategy: TransformStrategy
    rationale: TransformRationale

    def as_canonical(self) -> dict[str, object]:
        return {
            "feature_fingerprint": self.feature_fingerprint,
            "feature_key": self.feature_key,
            "feature_version": self.feature_version,
            "rationale": self.rationale.value,
            "strategy": self.strategy.value,
        }

    def __str__(self) -> str:
        return f"{self.feature_key} -> {self.strategy.value}"


def classify(spec: ExtendedFeatureSpec) -> tuple[TransformStrategy, TransformRationale]:
    """A classificação semântica de UM eixo, a partir dos METADADOS do catálogo.

    NADA AQUI OLHA O TIPO DE SAÍDA da feature, e nada casa texto de chave. O
    catálogo já sabe a família da janela móvel, o tipo do contexto e o tipo da
    dimensão de mercado; perguntar ao objeto é o que sobrevive a uma feature
    nova cujo nome comece igual e signifique outra coisa.
    """
    if isinstance(spec, RollingFeatureSpec):
        if spec.family is RollingFamily.XG:
            return (
                TransformStrategy.ROBUST_MEDIAN_IQR,
                TransformRationale.CONTINUOUS_COMPETITION_SCALED,
            )
        # Chutes, chutes no gol, gols e escanteios numa janela de um a dez
        # minutos: a distribuição é quase toda zero.
        return (
            TransformStrategy.PASS_THROUGH,
            TransformRationale.SPARSE_DISCRETE_COUNT,
        )
    if isinstance(spec, ContextFeatureSpec):
        if spec.kind is ContextFeatureKind.PREV_KICKOFF_GAP_HOURS:
            return (
                TransformStrategy.ROBUST_MEDIAN_IQR,
                TransformRationale.CALENDAR_INTERVAL_HOURS,
            )
        return (
            TransformStrategy.PASS_THROUGH,
            TransformRationale.CALENDAR_MATCH_COUNT,
        )
    if isinstance(spec, MarketFeatureSpec):
        if spec.kind is MarketFeatureKind.MEDIAN:
            return (
                TransformStrategy.ROBUST_MEDIAN_IQR,
                TransformRationale.MARKET_PRICE_LEVEL,
            )
        if spec.kind is MarketFeatureKind.IQR:
            return (
                TransformStrategy.ROBUST_MEDIAN_IQR,
                TransformRationale.MARKET_PRICE_DISPERSION,
            )
        return (
            TransformStrategy.PASS_THROUGH,
            TransformRationale.BOOKMAKER_SUPPORT_COUNT,
        )
    # `StateFeatureSpec` — relógio e estado estrutural.
    return (
        TransformStrategy.PASS_THROUGH,
        _estado(spec),
    )


def _estado(spec: ExtendedFeatureSpec) -> TransformRationale:
    """Relógio ou estado estrutural — a distinção que o `kind` já carrega."""
    nome = getattr(getattr(spec, "kind", None), "value", "")
    if str(nome).startswith("CLOCK_"):
        return TransformRationale.CLOCK_COORDINATE
    return TransformRationale.STRUCTURAL_MATCH_STATE


@final
@dataclass(frozen=True, slots=True)
class NormalizationPlan:
    """O contrato completo: uma decisão por eixo, e nenhuma implícita.

    ELE É COMPLETO POR CONSTRUÇÃO. O construtor confere que o conjunto de
    chaves do plano é EXATAMENTE o conjunto de chaves do espaço — não um
    superconjunto, não um subconjunto, e sem repetição. Um plano com uma
    feature a menos normalizaria cento e quatro dimensões e deixaria a última
    passar crua sem que ninguém tivesse decidido isso.
    """

    name: str
    version: str
    space_name: str
    space_version: str
    space_fingerprint: str
    normalizer_key: str
    normalizer_fingerprint: str
    fit_split: str
    input_bridge: FloatToDecimalBridge
    output_encoding: DecimalToFloatEncoding
    transforms: tuple[FeatureTransform, ...]

    def __post_init__(self) -> None:
        chaves = [t.feature_key for t in self.transforms]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(
                f"plano de normalização com feature repetida: {repetidas}. Duas "
                "entradas para o mesmo eixo fariam a segunda decidir em silêncio"
            )
        if self.fit_split != FIT_SPLIT:
            raise ValidationError(
                f"plano declarando ajuste sobre {self.fit_split!r}: o ajuste da V1 é "
                f"somente sobre {FIT_SPLIT}, e qualquer outra metade contaminaria a "
                "escala com o futuro que ela deveria avaliar"
            )
        if not self.transforms:
            raise ValidationError("plano de normalização vazio")

    def assert_covers(self, space: FeatureSpaceDefinition) -> None:
        """As chaves do plano são EXATAMENTE as do espaço (§11).

        AS TRÊS FALHAS SÃO DIFERENTES E TODAS FATAIS: uma feature sem entrada
        atravessaria sem decisão; uma entrada sem feature descreveria um eixo
        que não existe; e uma impressão divergente significaria que a definição
        mudou debaixo do plano.
        """
        do_plano = {t.feature_key for t in self.transforms}
        do_espaco = set(space.keys)
        faltando = sorted(do_espaco - do_plano)
        sobrando = sorted(do_plano - do_espaco)
        if faltando:
            raise ValidationError(
                f"o plano não decide sobre {len(faltando)} feature(s): "
                f"{faltando[:5]}. Elas atravessariam sem que ninguém tivesse escolhido",
                context={"missing": ",".join(faltando[:10])},
            )
        if sobrando:
            raise ValidationError(
                f"o plano decide sobre {len(sobrando)} feature(s) que o espaço não "
                f"tem: {sobrando[:5]}",
                context={"unknown": ",".join(sobrando[:10])},
            )
        impressoes = {d.key: d.fingerprint for d in space.features}
        divergentes = [
            t.feature_key
            for t in self.transforms
            if impressoes[t.feature_key] != t.feature_fingerprint
        ]
        if divergentes:
            raise ValidationError(
                f"{len(divergentes)} feature(s) do plano com impressão diferente da "
                f"do espaço: {divergentes[:5]}. A definição mudou, e a decisão do "
                "plano foi tomada sobre outra coisa",
                context={"drifted": ",".join(divergentes[:10])},
            )

    # ------------------------------------------------------------ leitura --

    @property
    def size(self) -> int:
        return len(self.transforms)

    @property
    def robust_keys(self) -> tuple[str, ...]:
        """Os eixos que EXIGEM artefato, em ordem canônica do plano."""
        return tuple(
            t.feature_key
            for t in self.transforms
            if t.strategy is TransformStrategy.ROBUST_MEDIAN_IQR
        )

    @property
    def pass_through_keys(self) -> tuple[str, ...]:
        return tuple(
            t.feature_key for t in self.transforms if t.strategy is TransformStrategy.PASS_THROUGH
        )

    def strategy_of(self, feature_key: str) -> TransformStrategy:
        for transformacao in self.transforms:
            if transformacao.feature_key == feature_key:
                return transformacao.strategy
        raise ValidationError(f"o plano não decide sobre {feature_key!r} — e não existe padrão")

    def transform_of(self, feature_key: str) -> FeatureTransform:
        for transformacao in self.transforms:
            if transformacao.feature_key == feature_key:
                return transformacao
        raise ValidationError(f"o plano não decide sobre {feature_key!r}")

    def counts(self) -> Mapping[str, int]:
        contagem: dict[str, int] = {}
        for transformacao in self.transforms:
            chave = transformacao.strategy.value
            contagem[chave] = contagem.get(chave, 0) + 1
        return dict(sorted(contagem.items()))

    def rationale_counts(self) -> Mapping[str, int]:
        contagem: dict[str, int] = {}
        for transformacao in self.transforms:
            chave = transformacao.rationale.value
            contagem[chave] = contagem.get(chave, 0) + 1
        return dict(sorted(contagem.items()))

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A forma que a impressão cobre.

        A ORDEM DAS TRANSFORMAÇÕES É A DO ESPAÇO, e ela entra: o plano descreve
        eixos ordenados, e reordená-los produziria o mesmo conjunto de decisões
        sobre um espaço diferente.
        """
        return {
            "algorithm": PLAN_FINGERPRINT_ALGORITHM,
            "fit_split": self.fit_split,
            "input_bridge": self.input_bridge.as_canonical(),
            "name": self.name,
            "normalizer": {
                "fingerprint": self.normalizer_fingerprint,
                "key": self.normalizer_key,
            },
            "output_encoding": self.output_encoding.as_canonical(),
            "space": {
                "fingerprint": self.space_fingerprint,
                "name": self.space_name,
                "version": self.space_version,
            },
            "transforms": [t.as_canonical() for t in self.transforms],
            "version": self.version,
        }

    @classmethod
    def from_canonical(cls, forma: Mapping[str, Any]) -> Self:
        """O plano de volta, EXATAMENTE como foi gravado.

        DO DOCUMENTO, E NÃO DO CATÁLOGO. `normalization_plan_v1()` reconstrói o
        plano de HOJE; um manifesto de seis meses atrás descreve o plano
        DAQUELE dia, e regenerá-lo do catálogo devolveria as decisões atuais
        sob o nome antigo — que é exatamente a confusão que a impressão existe
        para impedir.
        """
        espaco = forma["space"]
        normalizador = forma["normalizer"]
        return cls(
            name=str(forma["name"]),
            version=str(forma["version"]),
            space_name=str(espaco["name"]),
            space_version=str(espaco["version"]),
            space_fingerprint=str(espaco["fingerprint"]),
            normalizer_key=str(normalizador["key"]),
            normalizer_fingerprint=str(normalizador["fingerprint"]),
            fit_split=str(forma["fit_split"]),
            input_bridge=FloatToDecimalBridge(forma["input_bridge"]["policy"]),
            output_encoding=DecimalToFloatEncoding(forma["output_encoding"]["policy"]),
            transforms=tuple(
                FeatureTransform(
                    feature_key=str(t["feature_key"]),
                    feature_version=str(t["feature_version"]),
                    feature_fingerprint=str(t["feature_fingerprint"]),
                    strategy=TransformStrategy(t["strategy"]),
                    rationale=TransformRationale(t["rationale"]),
                )
                for t in forma["transforms"]
            ),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        contagem = self.counts()
        return (
            f"{self.name}@{self.version} · {self.size} eixos · "
            f"{contagem.get(TransformStrategy.ROBUST_MEDIAN_IQR.value, 0)} robustos"
        )


def normalization_plan_v1(
    *,
    space: FeatureSpaceDefinition | None = None,
    catalog: ExtendedFeatureCatalog | None = None,
    normalizer: NormalizerDefinition = DEFAULT_V1_NORMALIZER,
    input_bridge: FloatToDecimalBridge = DEFAULT_INPUT_BRIDGE,
    output_encoding: DecimalToFloatEncoding = DEFAULT_OUTPUT_ENCODING,
) -> NormalizationPlan:
    """O plano de produção da V1, derivado dos metadados do catálogo.

    ELE NÃO É UMA TABELA ESCRITA À MÃO. Uma lista literal de cento e cinco
    linhas envelheceria em silêncio: a feature nova entraria no espaço e
    ficaria de fora do plano, e o construtor só acusaria na hora de usar. Aqui a
    classificação é uma FUNÇÃO dos metadados, e a cobertura é conferida.

    O NORMALIZADOR ENTRA PELA IMPRESSÃO, e o corte dele faz parte dela: o plano
    de um ajuste até junho não é o plano de um ajuste até agosto.
    """
    catalogo = catalog or extended_feature_catalog()
    espaco = space or _espaco_do_catalogo(catalogo)
    transformacoes = tuple(
        _transformacao(spec.definition, *classify(spec)) for spec in catalogo.specs
    )
    plano = NormalizationPlan(
        name=NORMALIZATION_PLAN_NAME,
        version=NORMALIZATION_PLAN_VERSION,
        space_name=espaco.name,
        space_version=str(espaco.version),
        space_fingerprint=espaco.fingerprint,
        normalizer_key=normalizer.key,
        normalizer_fingerprint=normalizer.fingerprint,
        fit_split=FIT_SPLIT,
        input_bridge=input_bridge,
        output_encoding=output_encoding,
        transforms=transformacoes,
    )
    plano.assert_covers(espaco)
    return plano


def _transformacao(
    definition: FeatureDefinition,
    strategy: TransformStrategy,
    rationale: TransformRationale,
) -> FeatureTransform:
    return FeatureTransform(
        feature_key=definition.key,
        feature_version=str(definition.version),
        feature_fingerprint=definition.fingerprint,
        strategy=strategy,
        rationale=rationale,
    )


def _espaco_do_catalogo(catalog: ExtendedFeatureCatalog) -> FeatureSpaceDefinition:
    from sports_intelligence.domain.features.extraction.catalog_v2 import (
        match_state_raw_space_v2,
    )

    espaco = match_state_raw_space_v2()
    if [d.key for d in espaco.features] != [d.key for d in catalog.definitions]:
        raise ValidationError(
            "o catálogo e o espaço da V2 discordam sobre os eixos: o plano seria "
            "montado sobre um e conferido contra o outro"
        )
    return espaco


def plan_summary(plan: NormalizationPlan) -> Sequence[str]:
    """As linhas do resumo legível — para o documento e para o manifesto."""
    linhas = [f"{plan.name}@{plan.version}", f"eixos: {plan.size}"]
    linhas.extend(f"{k}: {v}" for k, v in plan.counts().items())
    linhas.extend(f"  {k}: {v}" for k, v in plan.rationale_counts().items())
    return linhas


def plan_for(
    *,
    reference_end_exclusive_normalizer: NormalizerDefinition,
    space: FeatureSpaceDefinition | None = None,
    catalog: ExtendedFeatureCatalog | None = None,
) -> NormalizationPlan:
    """O plano para um normalizador com corte declarado.

    O CORTE DO AJUSTE É PARTE DA IDENTIDADE DO PLANO (PR-05.1 §89, §90). O
    normalizador de referência da V1 declara `BEFORE_EVALUATED_MATCH`, que é
    uma regra por partida; aqui o corte é o INSTANTE da fronteira do split, e
    quem o constrói é `causal_normalizer_for` — este atalho apenas costura os
    dois sem que o chamador precise repetir a montagem.
    """
    return normalization_plan_v1(
        space=space, catalog=catalog, normalizer=reference_end_exclusive_normalizer
    )
