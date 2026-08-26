"""A população de ajuste — quem entrou, e a prova de que foi essa mesma.

O QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§104, §105, §106, §107). Um artefato de
normalizador é uma mediana e um IQR: dois números que não dizem de onde vieram.
Dois ajustes sobre populações DIFERENTES podem produzir a mesma mediana por
coincidência — e a partir daí todo valor normalizado por um seria comparado com
os do outro como se fossem a mesma escala.

    a identidade do ajuste DEPENDE da população real usada.

`population_digest` é o SHA-256 da população canonizada e ORDENADA. Dois
conjuntos com os mesmos membros em ordens diferentes dão o mesmo digest (§106);
um membro a mais, um valor diferente ou um corpus diferente dão outro.

O MEMBRO REPETIDO É RECUSADO (§107). A mesma observação — mesma partida, mesmo
corte, mesma feature — entrando duas vezes deslocaria a mediana em direção a
ela sem que nada denunciasse. Ela não é filtrada em silêncio: é erro.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Self, final, runtime_checkable

from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.canonical import canonical_json, decimal_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId


@runtime_checkable
class FitPopulation(Protocol):
    """O que o ajustador PRECISA de uma população — e nada além disso.

    ELE EXISTE PORQUE HÁ DUAS ESCALAS DE POPULAÇÃO, e as duas são legítimas:

        FeaturePopulation           dezenas a milhares de observações, cada uma
                                    um objeto com identidade própria
        DatasetFeaturePopulation    centenas de milhares, acumuladas em fluxo
                                    (PR-05.5.2)

    A SEGUNDA NÃO PODE GUARDAR OBJETOS. Vinte e nove eixos por competição por
    noventa e uma mil linhas são dois milhões e meio de observações, e
    materializá-las como `FeatureObservation` custaria centenas de megabytes
    para responder às mesmas cinco perguntas que estão aqui.

    O AJUSTADOR NÃO PRECISA SABER QUAL DAS DUAS RECEBEU. Ele lê o tamanho, o
    tamanho disponível, a impressão e os valores; a forma de guardá-los é
    decisão de quem acumula.
    """

    @property
    def competition_id(self) -> CompetitionId: ...

    @property
    def feature_key(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def available_size(self) -> int: ...

    @property
    def digest(self) -> str: ...

    def values(self) -> list[Decimal]: ...


@final
@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """UM valor de feature na população de ajuste (§105).

    A IDENTIDADE É `(partida, corte)`, e o valor é o conteúdo. `value = None`
    representa uma observação INDISPONÍVEL: ela entra na população — porque a
    contagem total é auditável (§120) — e NÃO entra na distribuição (§119).

    `corpus_fingerprint` ENTRA NA IDENTIDADE porque o mesmo jogo no mesmo corte
    pode ter valores diferentes em corpus diferentes: uma republicação corrige
    um evento, e a feature muda. Dois ajustes sobre corpus diferentes não são o
    mesmo ajuste.
    """

    match_id: MatchId
    as_of: FeatureAsOf
    value: Decimal | None = None
    corpus_fingerprint: str = ""

    @property
    def is_available(self) -> bool:
        return self.value is not None

    @property
    def key(self) -> tuple[str, str]:
        """A identidade da observação — o que não pode repetir (§107).

        ELA É TAMBÉM A CHAVE DE ORDENAÇÃO. `MatchId` e `FeatureAsOf` não têm
        ordem total — e nem deveriam ter: «uma partida menor que outra» não
        significa nada. O que existe é uma ordem CANÔNICA, derivada do texto,
        e ela serve para tornar o digest independente da ordem de leitura.
        """
        return (str(self.match_id), canonical_json(self.as_of.as_canonical()).decode())

    def as_canonical(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.as_canonical(),
            "corpus_fingerprint": self.corpus_fingerprint,
            "match_id": str(self.match_id),
            "value": None if self.value is None else decimal_text(self.value),
        }


@final
@dataclass(frozen=True, slots=True)
class FeaturePopulation:
    """As observações de UMA feature em UMA competição (§108, §110).

    A COMPETIÇÃO É DO CONJUNTO, e não de cada membro. Isso torna a regra do
    §110 estrutural: uma população é de uma competição só, e misturar duas
    exigiria construir duas populações e uni-las — o que o ajustador recusa.
    """

    competition_id: CompetitionId
    feature_key: str
    observations: tuple[FeatureObservation, ...] = ()

    def __post_init__(self) -> None:
        chaves = [o.key for o in self.observations]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(
                f"população de {self.feature_key} com observação repetida: "
                f"{repetidas[:3]}. A mesma partida no mesmo corte entrando duas vezes "
                "deslocaria a mediana em direção a ela (PR-05.4 §107)",
                context={"feature": self.feature_key, "duplicated": str(len(repetidas))},
            )
        if list(self.observations) != sorted(self.observations, key=lambda o: o.key):
            raise ValidationError(
                f"população de {self.feature_key} fora de ordem — use `of()`, que "
                "ordena: a ordem entra no digest, e a do banco não pode decidi-lo"
            )

    @classmethod
    def of(
        cls,
        competition_id: CompetitionId,
        feature_key: str,
        observations: Iterable[FeatureObservation],
    ) -> Self:
        """A porta normal — ela ORDENA (§106).

        Duas leituras que trouxeram os mesmos valores em ordens diferentes
        precisam produzir o mesmo digest, senão o artefato mudaria de
        identidade sem a população mudar.
        """
        return cls(
            competition_id=competition_id,
            feature_key=feature_key,
            observations=tuple(sorted(observations, key=lambda o: o.key)),
        )

    @property
    def size(self) -> int:
        """O total, INCLUINDO as indisponíveis (§120)."""
        return len(self.observations)

    @property
    def available(self) -> tuple[FeatureObservation, ...]:
        return tuple(o for o in self.observations if o.is_available)

    @property
    def available_size(self) -> int:
        return len(self.available)

    def values(self) -> list[Decimal]:
        """Só os valores DISPONÍVEIS (§119).

        UM INDISPONÍVEL NÃO VIRA ZERO. Ele simplesmente não participa da
        distribuição — e a contagem separada é o que permite auditar quantos
        ficaram de fora.
        """
        return [o.value for o in self.available if o.value is not None]

    @property
    def digest(self) -> str:
        """A impressão do CONJUNTO — ordem-independente por construção (§106)."""
        if not self.observations:
            return ""
        return hashlib.sha256(
            canonical_json(
                {
                    "competition_id": str(self.competition_id),
                    "feature_key": self.feature_key,
                    "observations": [o.as_canonical() for o in self.observations],
                }
            )
        ).hexdigest()

    def __iter__(self) -> Iterator[FeatureObservation]:
        return iter(self.observations)

    def __len__(self) -> int:
        return len(self.observations)

    def __str__(self) -> str:
        return (
            f"{self.feature_key}@{self.competition_id}: {self.available_size}/"
            f"{self.size} disponíveis [{self.digest[:12] or '—'}]"
        )
