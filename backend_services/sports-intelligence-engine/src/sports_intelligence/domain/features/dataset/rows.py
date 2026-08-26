"""A linha materializada — a chave dela, o digesto dela, e o que ela carrega.

UMA LINHA É UM `FeatureSnapshot` COM COORDENADAS DE ARQUIVO. O snapshot já sabe
tudo sobre o cálculo; a materialização acrescenta onde ele mora — de qual
versão, de qual metade, em que posição da grade, sob qual competição e
temporada. As duas coisas juntas são o que o Parquet guarda.

DOIS DIGESTOS, E CONFUNDI-LOS CUSTA CARO (§84 ao §96):

    snapshot_fingerprint      a impressão do CÁLCULO (PR-05.1). Ela responde
                              «duas execuções calcularam a mesma coisa?»
    materialized_row_digest   a impressão da LINHA GRAVADA. Ela responde «o
                              que está no arquivo é o que se pretendia gravar?»

O segundo é reconstrutível LENDO O PARQUET E MAIS NADA — é essa propriedade que
o torna útil na validação. Se ele dependesse do snapshot, conferir um arquivo
exigiria reconstruir o estado da partida, e a conferência deixaria de ser uma
leitura para virar um build.

`raw_content_fingerprint` É ORDENADO E EM FLUXO (§92). Ele encadeia os digestos
das linhas na ordem canônica de materialização, e RECUSA receber uma chave fora
de ordem. A alternativa comum — somar ou XOR os digestos, para ficar comutativo
— torna a impressão insensível a permutação, e permutação é exatamente um dos
defeitos que a impressão existe para pegar (duas linhas trocadas entre
partições).

AUSENTE NÃO VIRA ZERO NEM AQUI (ADR-0009). O valor de uma feature indisponível
é `None`, e a coluna de disponibilidade diz por quê. Gravar `0.0` produziria um
Parquet que soma perfeitamente e mente.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.shared.canonical import (
    canonical_json,
    decimal_text,
    frame,
    instant_text,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant, Period

#: O algoritmo, escrito dentro da própria forma canônica. Sem ele, trocar de
#: hash produziria impressões diferentes sem nenhum sinal de que o método
#: mudou — e a comparação diria «conteúdo diferente».
ROW_DIGEST_ALGORITHM: Final[str] = "SHA256_CANONICAL_JSON_V1"

#: O algoritmo da impressão do dataset inteiro. `ORDERED` está no nome porque a
#: ordem é uma propriedade do método, e não um detalhe da execução.
CONTENT_FINGERPRINT_ALGORITHM: Final[str] = "SHA256_ORDERED_ROW_CHAIN_V1"

#: As marcas de enquadramento da cadeia. Enquadrar impede que dois digestos
#: concatenados sejam confundidos com um digesto de tamanho dobrado.
_TAG_LINHA: Final[bytes] = b"sie.feature.row"
_TAG_CABECALHO: Final[bytes] = b"sie.feature.dataset"


@final
@dataclass(frozen=True, slots=True, order=True)
class HistoricalFeatureSnapshotKey:
    """A identidade de UMA linha dentro de uma versão do dataset.

    A ORDEM DOS CAMPOS É A ORDEM DE MATERIALIZAÇÃO, e `order=True` a usa: a
    cadeia de impressão exige chaves estritamente crescentes, e a comparação
    precisa ser total e óbvia. Por isso `match_id` entra como TEXTO — `MatchId`
    não tem ordem total, e ordenar por ele daria erro no lugar mais distante da
    causa.

    `grid_index` E NÃO `(período, minuto)` como coordenada de ordenação: o
    índice já embute a ordem do jogo, e ordenar por período exigiria uma tabela
    de precedência repetida aqui.
    """

    match_key: str
    grid_index: int

    @classmethod
    def of(cls, match_id: MatchId, *, grid_index: int) -> Self:
        if grid_index < 0:
            raise ValidationError(f"índice de grade negativo: {grid_index}")
        return cls(match_key=str(match_id), grid_index=grid_index)

    @property
    def text(self) -> str:
        return f"{self.match_key}#{self.grid_index:04d}"

    def __str__(self) -> str:
        return self.text


@final
@dataclass(frozen=True, slots=True)
class MaterializedFeatureRow:
    """Um snapshot pronto para virar linha de Parquet.

    ELE NÃO COPIA OS VALORES. O `snapshot` continua sendo a fonte deles; o que
    esta classe acrescenta são as coordenadas de materialização e as duas
    projeções que o arquivo precisa (valores e disponibilidades).
    """

    key: HistoricalFeatureSnapshotKey
    snapshot: FeatureSnapshot
    split: DatasetSplit
    competition_code: str
    season_label: str
    kickoff: Instant
    grid_label: str
    #: Quantos problemas a reconstrução do estado reportou para esta partida.
    #: Ele é da PARTIDA e se repete nas 91 linhas — de propósito: quem lê uma
    #: linha isolada precisa saber que ela veio de um estado degradado sem ter
    #: de ir buscar a partida inteira.
    state_issue_count: int = 0
    #: O digesto, MEMOIZADO pelo mesmo motivo do snapshot: ele é pedido no
    #: acumulador de impressão e de novo na coluna do Parquet, e cada cálculo
    #: serializa cento e cinco valores.
    _digest: str = field(default="", compare=False, repr=False, init=False)

    def __post_init__(self) -> None:
        if self.key.match_key != str(self.snapshot.as_of.match_id):
            raise ValidationError(
                f"linha com chave da partida {self.key.match_key} carregando snapshot "
                f"de {self.snapshot.as_of.match_id}: a chave é o que ordena a cadeia "
                "de impressão, e uma chave errada a ordenaria pela partida errada"
            )
        if not self.competition_code.strip() or not self.season_label.strip():
            raise ValidationError(
                "linha sem competição ou temporada: elas são a partição do arquivo, e "
                "sem elas a linha não tem onde ser gravada"
            )

    # ------------------------------------------------------------ projeções --

    @property
    def period(self) -> Period:
        return self.snapshot.as_of.position.period

    @property
    def minute(self) -> int:
        return self.snapshot.as_of.position.minute

    def values(self) -> dict[str, str | None]:
        """`chave → número canônico`, com `None` onde não há número.

        O NÚMERO SAI COMO TEXTO DECIMAL porque é assim que ele entra na
        impressão: `float` não tem representação estável entre plataformas do
        jeito que um hash exige, e `0.1 + 0.2` já custou defeito em tempo
        demais de gente demais.
        """
        return {f.definition_key: _texto(f.numeric) for f in self.snapshot.features}

    def availabilities(self) -> dict[str, str]:
        """`chave → disponibilidade`. NUNCA vazio, e nunca omitido."""
        return {f.definition_key: f.availability.value for f in self.snapshot.features}

    def unavailable_reasons(self) -> dict[str, str]:
        """`chave → motivo de recusa temporal`, só onde ele existe (§78).

        POR QUE ESPARSO E NÃO UMA COLUNA POR FEATURE. O motivo só é definido
        para `TEMPORALLY_UNAVAILABLE` — o domínio recusa a combinação
        contrária —, então 105 colunas dele seriam 105 colunas quase sempre
        nulas para carregar um punhado de valores. O mapa guarda os que
        existem e nada mais.
        """
        return {
            f.definition_key: f.leakage_reason.value
            for f in self.snapshot.features
            if f.leakage_reason is not None
        }

    @property
    def available_count(self) -> int:
        return sum(1 for f in self.snapshot.features if f.is_available)

    # ------------------------------------------------------------- digesto --

    def as_canonical(self) -> dict[str, object]:
        """A forma que o digesto imprime — E ELA É RECONSTRUTÍVEL DO PARQUET.

        Cada chave desta forma corresponde a colunas do arquivo. Nenhuma delas
        exige o snapshot em memória, e nenhuma delas carrega instante de
        gravação, id de execução ou nome de arquivo: duas materializações do
        mesmo conteúdo têm de produzir o mesmo digesto.
        """
        return {
            "algorithm": ROW_DIGEST_ALGORITHM,
            "as_of": self.snapshot.as_of.as_canonical(),
            "availability": self.availabilities(),
            "competition_code": self.competition_code,
            "feature_space": {
                "fingerprint": self.snapshot.space.fingerprint,
                "name": self.snapshot.space.name,
                "version": str(self.snapshot.space.version),
            },
            "grid_index": self.key.grid_index,
            "grid_label": self.grid_label,
            "kickoff": instant_text(self.kickoff),
            "match_id": self.key.match_key,
            "season_label": self.season_label,
            "snapshot_fingerprint": self.snapshot.fingerprint,
            "split": self.split.value,
            "state_issue_count": self.state_issue_count,
            "temporal_policy": {
                "fingerprint": self.snapshot.policy_fingerprint,
                "version": self.snapshot.policy_version,
            },
            "unavailable_reasons": self.unavailable_reasons(),
            "values": self.values(),
        }

    @property
    def digest(self) -> str:
        if not self._digest:
            object.__setattr__(
                self,
                "_digest",
                hashlib.sha256(canonical_json(self.as_canonical())).hexdigest(),
            )
        return self._digest


def _texto(numero: float | None) -> str | None:
    """O número na forma canônica decimal, ou `None`. NUNCA `0` por falta."""
    if numero is None:
        return None
    from decimal import Decimal

    return decimal_text(Decimal(str(numero)))


@final
class OrderedRowFingerprint:
    """A impressão do conteúdo cru, construída em fluxo e EM ORDEM (§92).

    ELA NÃO ACUMULA AS LINHAS. Um dataset de dez milhões de linhas não cabe em
    memória para ser ordenado no fim, e ordenar no fim seria admitir que a
    materialização não tem ordem — que é justamente o que a impressão precisa
    provar. Aqui a ordem é exigida na entrada: uma chave que não seja
    estritamente maior que a anterior levanta.

    O CABEÇALHO ENTRA NA CADEIA. Sem ele, dois datasets com as mesmas linhas
    sob grades diferentes teriam a mesma impressão — e a grade é parte do que o
    dataset É.
    """

    __slots__ = ("_hash", "_linhas", "_ultima")

    def __init__(
        self,
        *,
        space_name: str,
        space_version: str,
        grid_fingerprint: str,
        split_fingerprint: str,
    ) -> None:
        self._hash = hashlib.sha256()
        self._hash.update(
            frame(
                _TAG_CABECALHO,
                canonical_json(
                    {
                        "algorithm": CONTENT_FINGERPRINT_ALGORITHM,
                        "grid_fingerprint": grid_fingerprint,
                        "space_name": space_name,
                        "space_version": space_version,
                        "split_fingerprint": split_fingerprint,
                    }
                ),
            )
        )
        self._ultima: HistoricalFeatureSnapshotKey | None = None
        self._linhas = 0

    def update(self, key: HistoricalFeatureSnapshotKey, digest: str) -> None:
        if self._ultima is not None and key <= self._ultima:
            raise ValidationError(
                f"linha {key} materializada depois de {self._ultima}: a impressão de "
                "conteúdo é ordenada, e aceitar a inversão faria dois datasets com as "
                "mesmas linhas em ordens diferentes parecerem o mesmo",
                context={"key": key.text, "previous": self._ultima.text},
            )
        self._hash.update(frame(_TAG_LINHA, f"{key.text}:{digest}".encode()))
        self._ultima = key
        self._linhas += 1

    @property
    def rows(self) -> int:
        return self._linhas

    def finalize(self) -> str:
        """A impressão. Ela INCLUI a contagem, para que truncamento apareça."""
        final_hash = self._hash.copy()
        final_hash.update(frame(b"sie.feature.count", str(self._linhas).encode()))
        return final_hash.hexdigest()


def rebuild_content_fingerprint(
    rows: Iterable[tuple[HistoricalFeatureSnapshotKey, str]],
    *,
    space_name: str,
    space_version: str,
    grid_fingerprint: str,
    split_fingerprint: str,
) -> str:
    """Reconstrói a impressão a partir de `(chave, digesto)` já materializados.

    ELA EXISTE PARA A VALIDAÇÃO (§115). A construção calcula a impressão
    enquanto escreve; a validação a recalcula LENDO — e as duas só coincidem se
    o que foi escrito for o que foi calculado.
    """
    acumulador = OrderedRowFingerprint(
        space_name=space_name,
        space_version=space_version,
        grid_fingerprint=grid_fingerprint,
        split_fingerprint=split_fingerprint,
    )
    for chave, digesto in rows:
        acumulador.update(chave, digesto)
    return acumulador.finalize()


def availability_tally(rows: Iterable[MaterializedFeatureRow]) -> Mapping[str, int]:
    """Quantos valores em cada estado de disponibilidade. Contados, nunca estimados."""
    contagem: dict[str, int] = {}
    for linha in rows:
        for estado in linha.availabilities().values():
            contagem[estado] = contagem.get(estado, 0) + 1
    return dict(sorted(contagem.items()))


#: Os estados que NÃO carregam valor. A lista existe para a guarda de
#: materialização: uma linha com valor sob um destes estados é um `0` disfarçado.
UNAVAILABLE_STATES: Final[frozenset[FeatureAvailability]] = frozenset(
    estado for estado in FeatureAvailability if not estado.is_available
)


@final
@dataclass(frozen=True, slots=True)
class MaterializedObjectContent:
    """O que uma leitura de conferência extrai de UM objeto gravado.

    UMA LEITURA, DUAS RESPOSTAS. Conferir um Parquet exige o hash dos bytes E
    as chaves com os digestos; fazer duas chamadas baixaria o arquivo duas
    vezes, e um dataset de mil objetos pagaria o dobro do tráfego para
    responder a mesma pergunta.
    """

    object_key: str
    sha256: str
    size_bytes: int
    rows: tuple[tuple[HistoricalFeatureSnapshotKey, str], ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def out_of_order(self) -> tuple[HistoricalFeatureSnapshotKey, ...]:
        """As chaves que aparecem fora de ordem DENTRO do arquivo.

        ELA É UM DEFEITO PRÓPRIO, e não um sintoma da impressão global: um
        arquivo desordenado ainda produz a impressão certa depois de a
        validação ordenar tudo, e o que ele quebra é a leitura em fluxo de quem
        confia na ordem declarada.
        """
        fora: list[HistoricalFeatureSnapshotKey] = []
        anterior: HistoricalFeatureSnapshotKey | None = None
        for chave, _ in self.rows:
            if anterior is not None and chave <= anterior:
                fora.append(chave)
            anterior = chave
        return tuple(fora)
