"""A linha normalizada — o que ela carrega, e as três impressões de conteúdo.

UMA LINHA NORMALIZADA É UMA LINHA CRUA COM VINTE E NOVE EIXOS REESCALADOS. Ela
tem a MESMA chave, a MESMA ordem de features e a MESMA cardinalidade: para toda
linha crua existe exatamente uma normalizada, e nenhuma some — nem quando o
artefato é degenerado, nem quando a amostra foi insuficiente, nem quando o valor
de origem não existia. A ausência é sempre LOCAL à célula.

DUAS DISPONIBILIDADES, E CONFUNDI-LAS APAGA A CAUSA:

    source availability          por que o valor CRU não existe
    normalization availability   por que a NORMALIZAÇÃO não produziu número

Um `market_1x2_home_median` sem cotação publicada é `NOT_DECLARED` na origem. O
mesmo eixo com cotação e IQR nulo na competição é `ARTIFACT_DEGENERATE_SCALE` na
normalização — e as duas exigem ações opostas: procurar a fonte, ou aceitar que
aquela liga não tem dispersão naquele mercado.

TRÊS IMPRESSÕES DE CONTEÚDO, e a do meio é a que sustenta o PR:

    normalized_content_fingerprint             tudo
    normalized_reference_content_fingerprint   só REFERÊNCIA
    normalized_evaluation_content_fingerprint  só AVALIAÇÃO

Acrescentar uma partida à avaliação MUDA a primeira e a terceira, e **não pode
mudar a segunda**. Sem a segunda, a única impressão disponível seria a global —
e ela mudaria, deixando impossível afirmar que a base de comparação ficou igual.

O DIGESTO DA LINHA USA OS BYTES IEEE-754, e não texto. `repr(float)` já mudou
entre versões de Python; a identidade de uma linha publicada não pode depender
da rotina de formatação do interpretador que a gravou.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.bridge import float64_bytes
from sports_intelligence.domain.features.normalized.ordering import (
    PartitionKey,
    PartitionOrderGuard,
    partition_of,
)
from sports_intelligence.domain.shared.canonical import canonical_json, frame
from sports_intelligence.domain.shared.errors import ValidationError

NORMALIZED_ROW_DIGEST_ALGORITHM: Final[str] = "normalized-row-sha256-ieee754-v1"
NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM: Final[str] = "normalized-content-sha256-ordered-v1"

_TAG_LINHA: Final[bytes] = b"sie.normalized.row"
_TAG_CABECALHO: Final[bytes] = b"sie.normalized.head"
_TAG_VALOR: Final[bytes] = b"sie.normalized.value"


@final
class NormalizationAvailability(StrEnum):
    """Por que a NORMALIZAÇÃO produziu — ou não — um número. Catálogo fechado.

    ELE É SEPARADO DA DISPONIBILIDADE DE ORIGEM de propósito (§62). Atribuir
    «o artefato é degenerado» à fonte faria alguém procurar um provedor de
    dados para resolver um problema de distribuição.
    """

    #: O número existe.
    AVAILABLE = "AVAILABLE"
    #: O valor CRU não existia. A normalização não tem o que transformar, e a
    #: causa é da origem — o motivo dela viaja na coluna de origem.
    SOURCE_VALUE_UNAVAILABLE = "SOURCE_VALUE_UNAVAILABLE"
    #: A competição não juntou observações suficientes para afirmar a escala.
    ARTIFACT_INSUFFICIENT_SAMPLES = "ARTIFACT_INSUFFICIENT_SAMPLES"
    #: IQR nulo: não há dispersão pela qual dividir. Sem epsilon (ADR-0035).
    ARTIFACT_DEGENERATE_SCALE = "ARTIFACT_DEGENERATE_SCALE"
    #: A competição da linha não tem pacote de artefatos no conjunto.
    ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION = "ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION"

    @property
    def is_available(self) -> bool:
        return self is NormalizationAvailability.AVAILABLE


@final
@dataclass(frozen=True, slots=True)
class NormalizedCell:
    """UM eixo de UMA linha, depois do plano.

    `value is None` SEMPRE QUE A DISPONIBILIDADE NÃO É POSITIVA, e o construtor
    recusa a combinação contrária. É a mesma guarda do dataset cru, um nível
    acima: um número sob um estado negativo seria lido por quem ignora a
    máscara e ignorado por quem a lê.
    """

    feature_key: str
    availability: NormalizationAvailability
    value: float | None = None
    #: A disponibilidade que a linha CRUA declarava. Ela viaja junto porque
    #: «não havia valor» e «havia valor e não havia escala» são coisas
    #: diferentes, e a segunda só se distingue com as duas colunas.
    source_availability: str = ""

    def __post_init__(self) -> None:
        if self.availability.is_available and self.value is None:
            raise ValidationError(
                f"célula {self.feature_key} declarada AVAILABLE sem valor: disponível "
                "é uma afirmação sobre o número"
            )
        if not self.availability.is_available and self.value is not None:
            raise ValidationError(
                f"célula {self.feature_key} indisponível carregando {self.value}: quem "
                "ler a máscara vai ignorar o número, e quem não ler vai usá-lo"
            )

    @classmethod
    def available(cls, *, feature_key: str, value: float, source_availability: str) -> Self:
        return cls(
            feature_key=feature_key,
            availability=NormalizationAvailability.AVAILABLE,
            value=value,
            source_availability=source_availability,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        feature_key: str,
        availability: NormalizationAvailability,
        source_availability: str,
    ) -> Self:
        if availability.is_available:
            raise ValidationError("`unavailable` com disponibilidade positiva")
        return cls(
            feature_key=feature_key,
            availability=availability,
            source_availability=source_availability,
        )


@final
@dataclass(frozen=True, slots=True)
class NormalizedFeatureRow:
    """Uma linha do dataset normalizado.

    ELA APONTA PARA A LINHA CRUA PELO DIGESTO, e não pela posição física
    (§95). Provar a correspondência um-para-um por posição exigiria que os dois
    datasets tivessem a mesma ordem de arquivo, e a ordem de arquivo é decisão
    de execução.

    A LINHAGEM DO ARTEFATO É POR LINHA E NÃO POR CÉLULA (§96). Gravar cento e
    cinco impressões de artefato em cada linha multiplicaria o arquivo por nada:
    a competição da linha determina o pacote, e o manifesto guarda o mapa
    `(competição, feature) → artefato`.
    """

    key: HistoricalFeatureSnapshotKey
    split: DatasetSplit
    competition: str
    season: str
    grid_index: int
    grid_label: str
    period: str
    minute: int
    source_row_digest: str
    representation_fingerprint: str
    plan_fingerprint: str
    artifact_set_fingerprint: str
    competition_bundle_fingerprint: str
    cells: tuple[NormalizedCell, ...]
    _digest: str = field(default="", compare=False, repr=False, init=False)

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValidationError(f"linha normalizada {self.key} sem célula nenhuma")
        chaves = [c.feature_key for c in self.cells]
        if len(set(chaves)) != len(chaves):
            raise ValidationError(
                f"linha normalizada {self.key} com eixo repetido: "
                f"{sorted({k for k in chaves if chaves.count(k) > 1})[:3]}"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def available_count(self) -> int:
        return sum(1 for c in self.cells if c.availability.is_available)

    def values(self) -> dict[str, float | None]:
        return {c.feature_key: c.value for c in self.cells}

    def availabilities(self) -> dict[str, str]:
        return {c.feature_key: c.availability.value for c in self.cells}

    def source_availabilities(self) -> dict[str, str]:
        return {c.feature_key: c.source_availability for c in self.cells}

    def cell_of(self, feature_key: str) -> NormalizedCell:
        for celula in self.cells:
            if celula.feature_key == feature_key:
                return celula
        raise ValidationError(f"a linha não contém o eixo {feature_key!r}")

    # ------------------------------------------------------------- digesto --

    def digest_payload(self) -> bytes:
        """Os bytes que o digesto imprime.

        OS NÚMEROS ENTRAM COMO IEEE-754, e o resto como JSON canônico. Misturar
        os dois num só JSON obrigaria a formatar `float` como texto — que é
        exatamente o que se quer evitar.
        """
        cabecalho = canonical_json(
            {
                "algorithm": NORMALIZED_ROW_DIGEST_ALGORITHM,
                "artifact_set_fingerprint": self.artifact_set_fingerprint,
                "availability": self.availabilities(),
                "competition": self.competition,
                "competition_bundle_fingerprint": self.competition_bundle_fingerprint,
                "grid_index": self.grid_index,
                "grid_label": self.grid_label,
                "match_key": self.key.match_key,
                "minute": self.minute,
                "period": self.period,
                "plan_fingerprint": self.plan_fingerprint,
                "representation_fingerprint": self.representation_fingerprint,
                "season": self.season,
                "source_availability": self.source_availabilities(),
                "source_row_digest": self.source_row_digest,
                "split": self.split.value,
            }
        )
        partes = [frame(_TAG_CABECALHO, cabecalho)]
        for celula in self.cells:
            corpo = (
                celula.feature_key.encode()
                + b"="
                + (b"\x00" if celula.value is None else b"\x01" + float64_bytes(celula.value))
            )
            partes.append(frame(_TAG_VALOR, corpo))
        return b"".join(partes)

    @property
    def digest(self) -> str:
        if not self._digest:
            object.__setattr__(self, "_digest", hashlib.sha256(self.digest_payload()).hexdigest())
        return self._digest


@final
class NormalizedContentAccumulator:
    """As três impressões, construídas numa passagem e EM ORDEM.

    TRÊS DE UMA VEZ porque separá-las em três varreduras leria o dataset três
    vezes para responder perguntas que a mesma linha responde.
    """

    __slots__ = (
        "_avaliacao",
        "_global",
        "_guarda",
        "_linhas",
        "_por_metade",
        "_referencia",
    )

    def __init__(
        self,
        *,
        representation_fingerprint: str,
        plan_fingerprint: str,
        artifact_set_fingerprint: str,
    ) -> None:
        cabecalho = frame(
            _TAG_CABECALHO,
            canonical_json(
                {
                    "algorithm": NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM,
                    "artifact_set_fingerprint": artifact_set_fingerprint,
                    "plan_fingerprint": plan_fingerprint,
                    "representation_fingerprint": representation_fingerprint,
                }
            ),
        )
        self._global = hashlib.sha256(cabecalho)
        self._referencia = hashlib.sha256(cabecalho + frame(_TAG_CABECALHO, b"REFERENCE"))
        self._avaliacao = hashlib.sha256(cabecalho + frame(_TAG_CABECALHO, b"EVALUATION"))
        self._por_metade: dict[str, int] = {s.value: 0 for s in DatasetSplit}
        self._guarda = PartitionOrderGuard(rotulo="conteúdo normalizado")
        self._linhas = 0

    def update(self, row: NormalizedFeatureRow) -> None:
        # A ORDEM CANÔNICA É A DE PARTIÇÃO (ordering.py). Exigir chave
        # globalmente crescente valeria num dataset de uma partição só e é
        # falso no de produção: as partidas são `uuid5`, e as chaves de duas
        # competições se intercalam.
        self._guarda.check(
            partition_of(
                split=row.split.value,
                competition=row.competition,
                season=row.season,
            ),
            row.key,
        )
        bloco = frame(_TAG_LINHA, f"{row.key.text}:{row.digest}".encode())
        self._global.update(bloco)
        if row.split is DatasetSplit.REFERENCE:
            self._referencia.update(bloco)
        else:
            self._avaliacao.update(bloco)
        self._por_metade[row.split.value] += 1
        self._linhas += 1

    @property
    def rows(self) -> int:
        return self._linhas

    def finalize(self) -> NormalizedContentIdentity:
        return NormalizedContentIdentity(
            fingerprint=_fechar(self._global, self._linhas),
            reference_fingerprint=_fechar(
                self._referencia, self._por_metade[DatasetSplit.REFERENCE.value]
            ),
            evaluation_fingerprint=_fechar(
                self._avaliacao, self._por_metade[DatasetSplit.EVALUATION.value]
            ),
            rows=self._linhas,
            by_split=dict(self._por_metade),
        )


def _fechar(acumulador: object, contagem: int) -> str:
    copia = acumulador.copy()  # type: ignore[attr-defined]
    copia.update(frame(b"sie.normalized.count", str(contagem).encode()))
    return str(copia.hexdigest())


@final
@dataclass(frozen=True, slots=True)
class NormalizedContentIdentity:
    """As três impressões e as contagens que as acompanham."""

    fingerprint: str
    reference_fingerprint: str
    evaluation_fingerprint: str
    rows: int = 0
    by_split: Mapping[str, int] = field(default_factory=dict)

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM,
            "by_split": dict(sorted(self.by_split.items())),
            "evaluation_fingerprint": self.evaluation_fingerprint,
            "fingerprint": self.fingerprint,
            "reference_fingerprint": self.reference_fingerprint,
            "rows": self.rows,
        }


def rebuild_normalized_content(
    rows: Iterable[tuple[PartitionKey, HistoricalFeatureSnapshotKey, DatasetSplit, str]],
    *,
    representation_fingerprint: str,
    plan_fingerprint: str,
    artifact_set_fingerprint: str,
) -> NormalizedContentIdentity:
    """As impressões reconstruídas de `(partição, chave, metade, digesto)`.

    ELA EXISTE PARA A VALIDAÇÃO. A construção calcula as impressões ESCREVENDO;
    a validação as recalcula LENDO, e as duas só coincidem se o que foi escrito
    for o que foi calculado.

    A PARTIÇÃO VEM JUNTO porque a ordem canônica é em dois níveis. Sem ela, a
    validação teria de adivinhar em que ordem a construção percorreu o dataset —
    e adivinhar errado reprovaria um dataset correto.
    """
    cabecalho = frame(
        _TAG_CABECALHO,
        canonical_json(
            {
                "algorithm": NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM,
                "artifact_set_fingerprint": artifact_set_fingerprint,
                "plan_fingerprint": plan_fingerprint,
                "representation_fingerprint": representation_fingerprint,
            }
        ),
    )
    global_hash = hashlib.sha256(cabecalho)
    referencia = hashlib.sha256(cabecalho + frame(_TAG_CABECALHO, b"REFERENCE"))
    avaliacao = hashlib.sha256(cabecalho + frame(_TAG_CABECALHO, b"EVALUATION"))
    contagem = {s.value: 0 for s in DatasetSplit}
    guarda = PartitionOrderGuard(rotulo="reconstrução do conteúdo normalizado")
    total = 0
    for particao, chave, metade, digesto in rows:
        guarda.check(particao, chave)
        bloco = frame(_TAG_LINHA, f"{chave.text}:{digesto}".encode())
        global_hash.update(bloco)
        (referencia if metade is DatasetSplit.REFERENCE else avaliacao).update(bloco)
        contagem[metade.value] += 1
        total += 1
    return NormalizedContentIdentity(
        fingerprint=_fechar(global_hash, total),
        reference_fingerprint=_fechar(referencia, contagem[DatasetSplit.REFERENCE.value]),
        evaluation_fingerprint=_fechar(avaliacao, contagem[DatasetSplit.EVALUATION.value]),
        rows=total,
        by_split=contagem,
    )


def normalization_availability_tally(
    rows: Sequence[NormalizedFeatureRow],
) -> Mapping[str, int]:
    contagem: dict[str, int] = {}
    for linha in rows:
        for estado in linha.availabilities().values():
            contagem[estado] = contagem.get(estado, 0) + 1
    return dict(sorted(contagem.items()))


#: As disponibilidades de ORIGEM que permitem transformar. Só `AVAILABLE`
#: carrega número, e é a única que o transformador do PR-05.4 aceita.
FITTABLE_SOURCE_STATES: Final[frozenset[str]] = frozenset({FeatureAvailability.AVAILABLE.value})
