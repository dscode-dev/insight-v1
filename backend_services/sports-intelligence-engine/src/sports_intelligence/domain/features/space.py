"""O conjunto ORDENADO de features que forma um espaço — e sua identidade.

POR QUE A ORDEM É PARTE DA IDENTIDADE (§52, §55). Um `FeatureSpace` vira, mais
adiante, um vetor. `[f1, f2, f3]` e `[f3, f1, f2]` carregam os mesmos números
em eixos diferentes, e a distância entre um vetor de um e um vetor do outro é
aritmética sobre dimensões trocadas — que não falha, só mente. Guardar a ordem
na identidade é o que impede dois espaços de mesmo nome produzirem vetores
incomparáveis.

    FeatureSpaceIdentity = nome + versão + impressão(ordem + conteúdo)

`live_comparable` É UMA PROMESSA, E ELA É ESTRUTURALMENTE PROTEGIDA (§29, §80).
Um espaço declarado comparável com partida ao vivo não pode ser calculado sob
verdade retrospectiva — o objeto com essa combinação simplesmente não é
construível. Deixar isso para a revisão de código seria confiar que ninguém vai
escrever a linha errada às onze da noite.

O QUE ESTE MÓDULO NÃO FAZ: não calcula, não ordena por conta própria, não
escolhe features. Ele recebe uma tupla ordenada e a torna uma identidade.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import FeatureSpaceVersion

#: O algoritmo da impressão do espaço, nomeado como o do corpus. Duas
#: impressões produzidas por construções diferentes são dois hex de 64
#: caracteres indistinguíveis — e compará-los diria «espaço diferente» sem
#: explicação nenhuma.
FEATURE_SPACE_FINGERPRINT_ALGORITHM: Final[str] = "feature-space-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class CorpusRequirement:
    """O que o espaço EXIGE do corpus que o alimenta (§57, §58).

    `requires EVENT` SIGNIFICA «o corpus precisa DECLARAR a capacidade», e não
    «toda partida tem evento». A diferença é o §58 inteiro: a exigência é sobre
    a VERSÃO do corpus — se ela não publica eventos, nenhuma feature de evento
    pode existir ali, e descobrir isso antes de compor é barato. A
    disponibilidade por partida continua sendo decidida partida a partida.
    """

    families: tuple[CoverageFamily, ...] = ()
    #: As famílias que o espaço USA quando existem e que NÃO o inviabilizam
    #: (PR-05.4 §80, §82). O mercado é o caso: um corpus sem `ODDS` continua
    #: produzindo snapshot — com as dimensões de mercado indisponíveis na
    #: máscara. Torná-las obrigatórias faria o corpus inteiro ser recusado por
    #: causa de uma família acessória, e a ausência é da MÁSCARA, não do espaço.
    optional_families: tuple[CoverageFamily, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.families)) != len(self.families):
            raise ValidationError("requisito de corpus com família repetida")
        if len(set(self.optional_families)) != len(self.optional_families):
            raise ValidationError("requisito de corpus com família opcional repetida")
        ambas = set(self.families) & set(self.optional_families)
        if ambas:
            nomes = sorted(f.value for f in ambas)
            raise ValidationError(
                f"família declarada como obrigatória E opcional: {nomes}. As duas "
                "afirmações não podem valer ao mesmo tempo"
            )

    @classmethod
    def of(
        cls,
        *families: CoverageFamily,
        optional: tuple[CoverageFamily, ...] = (),
    ) -> Self:
        return cls(
            families=tuple(sorted(set(families), key=lambda f: f.value)),
            optional_families=tuple(sorted(set(optional), key=lambda f: f.value)),
        )

    @property
    def declared(self) -> frozenset[CoverageFamily]:
        """Tudo que o espaço declara conhecer — obrigatório ou não."""
        return frozenset(self.families) | frozenset(self.optional_families)

    def missing_from(self, published: frozenset[CoverageFamily]) -> tuple[CoverageFamily, ...]:
        """As famílias exigidas que aquele corpus NÃO publica."""
        return tuple(f for f in self.families if f not in published)

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica.

        `optional_families` SÓ APARECE QUANDO EXISTE. Um espaço sem famílias
        opcionais produz exatamente o documento que produzia antes deste campo
        existir — e é isso que mantém a impressão dourada da V1 intacta
        (PR-05.4 §3, §90). Emitir `[]` mudaria o hash de todo espaço já
        publicado por causa de um campo que ninguém usou.
        """
        documento: dict[str, object] = {"families": sorted(f.value for f in self.families)}
        if self.optional_families:
            documento["optional_families"] = sorted(f.value for f in self.optional_families)
        return documento


@final
@dataclass(frozen=True, slots=True)
class FeatureSpaceDefinition:
    """Um conjunto ordenado e versionado de features compatíveis (§51).

    AS RECUSAS DO CONSTRUTOR SÃO O CONTRATO:

        chave repetida            duas features com o mesmo nome no mesmo
                                  espaço — uma delas seria ignorada em silêncio
        modo incompatível         `live_comparable` com verdade retrospectiva
        classe incompatível       feature `POST_MATCH` num espaço comparável
                                  ao vivo: ela nunca existiria ao vivo
        dependência ausente       feature que depende de outra que não está
                                  aqui
        ciclo                     `A → B → A`
        exigência incoerente      feature que exige família que o espaço não
                                  declara exigir
    """

    name: str
    version: FeatureSpaceVersion
    #: A ORDEM É CONTEÚDO. Ela é a ordem dos eixos do vetor futuro.
    features: tuple[FeatureDefinition, ...]
    temporal_mode: TemporalMode = TemporalMode.AS_KNOWN
    #: Se este espaço promete ser comparável com partida ao vivo (§29).
    live_comparable: bool = True
    requirement: CorpusRequirement = CorpusRequirement()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("espaço de features sem nome")
        if not self.features:
            raise ValidationError(
                f"espaço {self.name} sem feature nenhuma — um espaço vazio produz "
                "vetor de dimensão zero, e comparar dois deles daria sempre igual"
            )
        chaves = [f.key for f in self.features]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(
                f"espaço {self.name} com chave repetida: {repetidas}. Uma das duas "
                "seria ignorada, e ninguém saberia qual (§56)",
                context={"duplicated": ", ".join(repetidas)},
            )
        # A GUARDA ESTRUTURAL DO §80. A combinação inválida não é recusada na
        # revisão de código nem no cálculo: ela não constrói.
        if self.live_comparable and self.temporal_mode is TemporalMode.CANONICAL_FINAL:
            raise ValidationError(
                f"o espaço {self.name} se declara comparável com partida ao vivo e "
                "pede verdade retrospectiva (CANONICAL_FINAL). Ao vivo não existe "
                "retrospectiva: o estado histórico teria um privilégio que o "
                "presente nunca tem (PR-05.1 §29, §80)",
                context={"space": self.name, "mode": self.temporal_mode.value},
            )
        if self.live_comparable:
            pos_jogo = [
                f.key for f in self.features if f.temporal_class is FeatureTemporalClass.POST_MATCH
            ]
            if pos_jogo:
                raise ValidationError(
                    f"o espaço {self.name} é comparável ao vivo e contém feature(s) "
                    f"pós-jogo: {sorted(pos_jogo)}. Elas não existem enquanto a "
                    "partida acontece",
                    context={"features": ", ".join(sorted(pos_jogo))},
                )
        conhecidas = set(chaves)
        for definicao in self.features:
            faltando = [d for d in definicao.depends_on_features if d not in conhecidas]
            if faltando:
                raise ValidationError(
                    f"a feature {definicao.key} depende de {sorted(faltando)}, que não "
                    f"está no espaço {self.name}"
                )
        ciclo = _ciclo_em(self.features)
        if ciclo:
            raise ValidationError(
                f"dependência cíclica entre features: {' → '.join(ciclo)} (§105)",
                context={"cycle": " → ".join(ciclo)},
            )
        exigidas = {f for d in self.features for f in d.required_families}
        nao_declaradas = exigidas - self.requirement.declared
        if nao_declaradas:
            nomes = sorted(f.value for f in nao_declaradas)
            raise ValidationError(
                f"o espaço {self.name} contém feature(s) que exigem {nomes} e não "
                "declara a exigência. Sem a declaração, a incompatibilidade com o "
                "corpus só apareceria no meio do cálculo (§57)",
                context={"families": ", ".join(nomes)},
            )

    @property
    def keys(self) -> tuple[str, ...]:
        """As chaves, NA ORDEM. É ela que vira a ordem dos eixos."""
        return tuple(f.key for f in self.features)

    @property
    def size(self) -> int:
        return len(self.features)

    def definition_of(self, key: str) -> FeatureDefinition:
        for definicao in self.features:
            if definicao.key == key:
                return definicao
        raise ValidationError(f"o espaço {self.name} não contém a feature {key!r}")

    def assert_compatible_with(self, published: frozenset[CoverageFamily]) -> None:
        """Recusa um corpus que não declara o que o espaço exige (§57).

        ANTES DE CALCULAR, e não durante: descobrir na décima milésima partida
        que o corpus não publica eventos custa a composição inteira.
        """
        faltando = self.requirement.missing_from(published)
        if faltando:
            nomes = sorted(f.value for f in faltando)
            raise ValidationError(
                f"o espaço {self.name} exige {nomes} e o corpus não publica essa(s) família(s)",
                context={"space": self.name, "missing": ", ".join(nomes)},
            )

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica do espaço — COM a ordem (§54).

        AS FEATURES ENTRAM NA ORDEM DECLARADA, e não ordenadas: ordená-las aqui
        faria dois espaços com ordens diferentes terem a mesma impressão, que é
        exatamente o que o §55 proíbe.
        """
        return {
            "algorithm": FEATURE_SPACE_FINGERPRINT_ALGORITHM,
            "features": [
                {"fingerprint": f.fingerprint, "key": f.key, "position": i}
                for i, f in enumerate(self.features)
            ],
            "live_comparable": self.live_comparable,
            "name": self.name,
            "requirement": self.requirement.as_canonical(),
            "temporal_mode": self.temporal_mode.value,
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}#{self.fingerprint[:16]}"

    def __str__(self) -> str:
        return f"{self.identity} · {self.size} feature(s)"


def _ciclo_em(features: tuple[FeatureDefinition, ...]) -> list[str]:
    """O primeiro ciclo de dependência, ou lista vazia (§105).

    BUSCA EM PROFUNDIDADE COM TRÊS CORES. Ela devolve o CAMINHO, e não um
    booleano: «há um ciclo» manda alguém procurar; «a → b → a» já é a
    resposta.
    """
    dependencias = {f.key: f.depends_on_features for f in features}
    visitando: list[str] = []
    concluidos: set[str] = set()

    def visitar(chave: str) -> list[str]:
        if chave in concluidos:
            return []
        if chave in visitando:
            inicio = visitando.index(chave)
            return [*visitando[inicio:], chave]
        visitando.append(chave)
        for seguinte in dependencias.get(chave, ()):
            encontrado = visitar(seguinte)
            if encontrado:
                return encontrado
        visitando.pop()
        concluidos.add(chave)
        return []

    for definicao in features:
        ciclo = visitar(definicao.key)
        if ciclo:
            return ciclo
    return []
