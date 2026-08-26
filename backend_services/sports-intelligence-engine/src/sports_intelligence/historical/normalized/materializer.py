"""O dataset NORMALIZADO escrito em Parquet — e as três famílias de coluna.

O SCHEMA É DERIVADO DO PLANO, e nunca inferido. Três colunas por eixo:

    n_<chave>   o VALOR normalizado, `float64`, nulável
    m_<chave>   por que a NORMALIZAÇÃO não produziu número, texto, nunca nulo
    s_<chave>   por que o valor CRU não existia, texto, nunca nulo

A TERCEIRA É A QUE QUASE NÃO SE ESCREVE, e é a que faz a diferença entre
consertar a coleta e aceitar a liga. Sem ela, «não havia valor» e «havia valor e
não havia escala» chegam ao leitor como o mesmo `null` (§62): o primeiro manda
procurar um provedor de dados, o segundo manda aceitar que aquele mercado não
tem dispersão naquela competição.

TODAS AS COLUNAS DE VALOR SÃO `float64`, INCLUSIVE AS DOS EIXOS `PASS_THROUGH`.
No dataset cru uma contagem é `int64`; aqui ela é `float64` mesmo passando
direto. O motivo é que a coluna precisa ter UM tipo, e ele não pode depender do
resultado do ajuste — um eixo `ROBUST` cujo artefato saiu degenerado em toda
competição produziria uma coluna sem número nenhum, e inferir o tipo do
conteúdo faria o arquivo de uma competição discordar do da outra.

    o valor de um `PASS_THROUGH` continua EXATO. `float64` representa todo
    `int64` de magnitude de contagem de futebol sem perder um dígito, e o
    caminho não passa por `Decimal` (transform.py §78).

A PARTIÇÃO É A MESMA DO CRU — `split=/competition=/season=` — e o prefixo é
outro. Escrever o normalizado sob o prefixo do cru faria um leitor que apontasse
para a versão errada ler as duas representações como se fossem uma.

A ORDEM DAS LINHAS É A DA CHAVE, e este módulo NÃO reordena, pelo mesmo motivo
do cru: a impressão de conteúdo é ordenada.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.manifest import NormalizedObjectRef
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.features.normalized.rows import NormalizedFeatureRow
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.ports.object_store import ObjectStorePort

COMPRESSION: Final[str] = "zstd"

PARQUET_CONTENT_TYPE: Final[str] = "application/vnd.apache.parquet"

#: Os prefixos das três famílias. Eles existem para que o nome de uma feature
#: nunca colida com o de uma coluna de identidade — e para que os três nomes de
#: um mesmo eixo sejam distinguíveis num `SELECT *`.
NORMALIZED_PREFIX: Final[str] = "n_"
MASK_PREFIX: Final[str] = "m_"
SOURCE_MASK_PREFIX: Final[str] = "s_"

#: As colunas de identidade e linhagem, na ordem em que aparecem no arquivo.
IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "match_id",
    "grid_index",
    "grid_label",
    "period",
    "minute",
    "split",
    "competition",
    "season",
    "source_row_digest",
    "representation_fingerprint",
    "plan_fingerprint",
    "artifact_set_fingerprint",
    "competition_bundle_fingerprint",
    "available_count",
    "row_digest",
)

#: Quantas colunas o arquivo tem sob o plano da V1: 15 de identidade mais três
#: por eixo. É uma NOTA — o schema sai do plano —, e existe para que uma
#: mudança na largura apareça como diff aqui.
COLUNAS_ESPERADAS_NOTA: Final[int] = len(IDENTITY_COLUMNS) + 3 * 105


def normalized_schema(plan: NormalizationPlan) -> Any:
    """O schema completo, derivado do PLANO.

    ELE É CONSTRUÍDO SOB DEMANDA para não exigir pyarrow no import: o domínio
    não depende dele, e este módulo é a fronteira.
    """
    import pyarrow as pa

    campos = [
        pa.field("match_id", pa.string(), nullable=False),
        pa.field("grid_index", pa.int32(), nullable=False),
        pa.field("grid_label", pa.string(), nullable=False),
        pa.field("period", pa.string(), nullable=False),
        pa.field("minute", pa.int32(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field("competition", pa.string(), nullable=False),
        pa.field("season", pa.string(), nullable=False),
        # A LIGAÇÃO COM A LINHA CRUA É PELO DIGESTO, e não pela posição (§95).
        # Provar a correspondência por posição exigiria que os dois datasets
        # tivessem a mesma ordem de arquivo, e a ordem de arquivo é decisão de
        # execução.
        pa.field("source_row_digest", pa.string(), nullable=False),
        pa.field("representation_fingerprint", pa.string(), nullable=False),
        pa.field("plan_fingerprint", pa.string(), nullable=False),
        pa.field("artifact_set_fingerprint", pa.string(), nullable=False),
        # VAZIO QUANDO A COMPETIÇÃO NÃO TEM PACOTE. Ela aparece só na avaliação,
        # nunca teve população de referência, e as linhas dela continuam
        # existindo — com os eixos ROBUST vazios e o motivo dizendo isso.
        pa.field("competition_bundle_fingerprint", pa.string(), nullable=False),
        pa.field("available_count", pa.int32(), nullable=False),
        pa.field("row_digest", pa.string(), nullable=False),
    ]
    for transformacao in plan.transforms:
        chave = transformacao.feature_key
        campos.append(pa.field(f"{NORMALIZED_PREFIX}{chave}", pa.float64()))
        campos.append(pa.field(f"{MASK_PREFIX}{chave}", pa.string(), nullable=False))
        campos.append(pa.field(f"{SOURCE_MASK_PREFIX}{chave}", pa.string(), nullable=False))
    return pa.schema(campos)


def partition_key(
    *,
    dataset_name: str,
    version: str,
    split: DatasetSplit,
    competition: str,
    season: str,
    part_index: int = 0,
) -> str:
    """A chave do objeto. Hive-style, sob o prefixo `normalized/`."""
    return (
        f"normalized/{dataset_name}/{version}/split={split.value}/"
        f"competition={competition}/season={season}/part-{part_index:05d}.parquet"
    )


def manifest_key(*, dataset_name: str, version: str) -> str:
    return f"normalized/{dataset_name}/{version}/manifest.json"


@final
class ParquetNormalizedDatasetMaterializer:
    """Escreve as partições do dataset normalizado como Parquet."""

    def __init__(self, store: ObjectStorePort, *, plan: NormalizationPlan) -> None:
        self._store = store
        self._plan = plan
        self._schema: Any | None = None
        self._eixos = tuple(t.feature_key for t in plan.transforms)

    @property
    def plan(self) -> NormalizationPlan:
        return self._plan

    def schema(self) -> Any:
        """O schema, construído uma vez. São 330 campos sob o plano da V1 —
        reconstruí-lo por partição custaria mais que escrever algumas
        partições pequenas."""
        if self._schema is None:
            self._schema = normalized_schema(self._plan)
        return self._schema

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit,
        competition: str,
        season: str,
        part_index: int,
        rows: Sequence[NormalizedFeatureRow],
        source_object_key: str = "",
    ) -> NormalizedObjectRef | None:
        """Escreve um pedaço de partição. `None` quando não há linha nenhuma."""
        if not rows:
            # UM PARQUET DE ZERO LINHA É INDISTINGUÍVEL, na leitura, de uma
            # partição que ninguém escreveu.
            return None
        bruto = self._para_parquet(rows, split=split, competition=competition, season=season)
        chave = partition_key(
            dataset_name=dataset_name,
            version=version,
            split=split,
            competition=competition,
            season=season,
            part_index=part_index,
        )
        await self._store.put_stream(
            chave,
            iter([bruto]),
            content_type=PARQUET_CONTENT_TYPE,
            size_bytes=len(bruto),
        )
        return NormalizedObjectRef(
            object_key=chave,
            split=split,
            competition=competition,
            season=season,
            sha256=ContentHash(hashlib.sha256(bruto).hexdigest()),
            size_bytes=len(bruto),
            row_count=len(rows),
            match_count=len({linha.key.match_key for linha in rows}),
            source_object_key=source_object_key,
            content_type=PARQUET_CONTENT_TYPE,
        )

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> NormalizedObjectRef:
        if not document:
            raise ValidationError("manifesto normalizado vazio")
        chave = manifest_key(dataset_name=dataset_name, version=version)
        await self._store.put_stream(
            chave,
            iter([document]),
            content_type="application/json",
            size_bytes=len(document),
        )
        return NormalizedObjectRef(
            object_key=chave,
            split=DatasetSplit.REFERENCE,
            competition="*",
            season="*",
            sha256=ContentHash(hashlib.sha256(document).hexdigest()),
            size_bytes=len(document),
            row_count=0,
            content_type="application/json",
        )

    async def verify_object(
        self, *, object_key: str
    ) -> tuple[str, int, Sequence[tuple[str, int, str, str]]]:
        """Baixa o objeto uma vez: hash dos bytes E as quatro colunas da linha.

        QUATRO DE TREZENTAS E TRINTA, e é para isso que o formato é colunar. O
        hash sai dos mesmos bytes, então integridade e conteúdo custam um
        download só.
        """
        import pyarrow.parquet as pq

        buffer = bytearray()
        async for bloco in self._store.open_stream(object_key):
            buffer.extend(bloco)
        conteudo = bytes(buffer)
        tabela = pq.read_table(
            io.BytesIO(conteudo),
            columns=["match_id", "grid_index", "split", "row_digest"],
        )
        linhas = tuple(
            (str(partida), int(indice), str(metade), str(digesto))
            for partida, indice, metade, digesto in zip(
                tabela.column("match_id").to_pylist(),
                tabela.column("grid_index").to_pylist(),
                tabela.column("split").to_pylist(),
                tabela.column("row_digest").to_pylist(),
                strict=True,
            )
        )
        return (hashlib.sha256(conteudo).hexdigest(), len(conteudo), linhas)

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        return manifest_key(dataset_name=dataset_name, version=version)

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        return f"normalized/{dataset_name}/{version}/"

    # ------------------------------------------------------------ interno --

    def _para_parquet(
        self,
        rows: Sequence[NormalizedFeatureRow],
        *,
        split: DatasetSplit,
        competition: str,
        season: str,
    ) -> bytes:
        import pyarrow as pa
        import pyarrow.parquet as pq

        registros = [
            self._linha(linha, split=split, competition=competition, season=season)
            for linha in rows
        ]
        tabela = pa.Table.from_pylist(registros, schema=self.schema())
        buffer = io.BytesIO()
        pq.write_table(tabela, buffer, compression=COMPRESSION)
        return buffer.getvalue()

    def _linha(
        self,
        row: NormalizedFeatureRow,
        *,
        split: DatasetSplit,
        competition: str,
        season: str,
    ) -> dict[str, Any]:
        if row.split is not split:
            raise ValidationError(
                f"linha da metade {row.split} numa partição de {split}: a divisão é "
                "atômica por partida, e uma linha na partição errada quebraria a "
                "atomicidade sem que a contagem denunciasse",
                context={"match_id": row.key.match_key},
            )
        if row.competition != competition or row.season != season:
            raise ValidationError(
                f"linha de {row.competition}/{row.season} numa partição de "
                f"{competition}/{season}: a partição é o predicado que a leitura poda, "
                "e uma linha fora dela seria invisível a quem a usasse"
            )
        registro: dict[str, Any] = {
            "match_id": row.key.match_key,
            "grid_index": row.key.grid_index,
            "grid_label": row.grid_label,
            "period": row.period,
            "minute": row.minute,
            "split": split.value,
            "competition": competition,
            "season": season,
            "source_row_digest": row.source_row_digest,
            "representation_fingerprint": row.representation_fingerprint,
            "plan_fingerprint": row.plan_fingerprint,
            "artifact_set_fingerprint": row.artifact_set_fingerprint,
            "competition_bundle_fingerprint": row.competition_bundle_fingerprint,
            "available_count": row.available_count,
            "row_digest": row.digest,
        }
        vistos: set[str] = set()
        for celula in row.cells:
            chave = celula.feature_key
            vistos.add(chave)
            registro[f"{NORMALIZED_PREFIX}{chave}"] = celula.value
            registro[f"{MASK_PREFIX}{chave}"] = celula.availability.value
            registro[f"{SOURCE_MASK_PREFIX}{chave}"] = celula.source_availability
        faltando = [chave for chave in self._eixos if chave not in vistos]
        if faltando:
            # A LINHA TEM DE TER TODOS OS EIXOS DO PLANO (§94). Deixar o pyarrow
            # preencher com nulo faria um eixo ausente virar «sem valor», que é
            # exatamente a confusão que a máscara existe para desfazer.
            raise ValidationError(
                f"linha normalizada {row.key} sem os eixos {faltando[:3]}: o plano "
                "decide sobre todos, e um eixo ausente viraria «sem valor» no arquivo",
                context={"match_id": row.key.match_key, "missing": str(len(faltando))},
            )
        return registro
