"""O dataset de features escrito em Parquet — colunar, particionado, tipado.

AQUI O PARQUET É A FONTE DAS LINHAS (ADR-0037), e não uma cópia. Apagar o
bucket do corpus não perde fato nenhum; apagar este perde o dataset até que
alguém o reconstrua. A reconstrução é determinística — versão do corpus
imutável, políticas impressas, cálculo puro —, e é ela que torna a troca
aceitável.

O SCHEMA É DERIVADO DO CATÁLOGO, E NUNCA INFERIDO. Duas colunas por feature:

    f_<chave>   o VALOR, tipado pelo `FeatureOutputType` da definição, nulável
    a_<chave>   a DISPONIBILIDADE, texto, NUNCA nula

NULO SOZINHO NÃO BASTA, e essa é a razão da segunda coluna. `NULL` diz «não há
número» e não diz por quê — e «a fonte não publica escanteio» exige ação
diferente de «o corte proibiu o fato». Um dataset com só a primeira coluna
obrigaria quem investiga a adivinhar entre sete causas.

E NULO NUNCA VIRA ZERO (ADR-0009). `corners_home_5m = 0` é um fato: não houve
escanteio. `= NULL` é outro: não se sabe. Um `0` no lugar do segundo produz
média que soma perfeitamente e está errada, que é o pior tipo de defeito
porque nada denuncia.

OS MOTIVOS DE RECUSA TEMPORAL VÃO NUM MAPA, e não em cento e cinco colunas: o
motivo só é definido para `TEMPORALLY_UNAVAILABLE` — o domínio recusa a
combinação contrária —, então as colunas seriam quase todas nulas para carregar
um punhado de valores.

A PARTIÇÃO É `split=/competition=/season=`, NESSA ORDEM. A metade vem primeiro
porque é o predicado mais grosso e o mais usado: «a população de referência»
tem de podar a avaliação inteira sem abrir arquivo nenhum. Inverter a ordem
faria toda leitura de referência tocar as duas metades de cada temporada.

A ORDEM DAS LINHAS DENTRO DO ARQUIVO É A DA CHAVE, e este módulo NÃO reordena.
A impressão de conteúdo é ordenada; reordenar aqui faria o arquivo discordar da
impressão que a construção calculou, sem que nada denunciasse até a validação.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.manifest import FeatureObjectRef
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
    MaterializedObjectContent,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.ports.object_store import ObjectStorePort

#: ZSTD porque ela ganha de Snappy em taxa com custo de CPU parecido na
#: leitura, e o dataset é escrito uma vez e lido muitas.
COMPRESSION: Final[str] = "zstd"

PARQUET_CONTENT_TYPE: Final[str] = "application/vnd.apache.parquet"

#: Os prefixos das colunas de feature. Eles existem para que o nome de uma
#: feature nunca colida com o de uma coluna de identidade: uma feature chamada
#: `split` seria uma catástrofe silenciosa sem eles.
VALUE_PREFIX: Final[str] = "f_"
AVAILABILITY_PREFIX: Final[str] = "a_"

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
    "kickoff",
    "temporal_mode",
    "knowledge_cutoff",
    "space_name",
    "space_version",
    "space_fingerprint",
    "policy_version",
    "policy_fingerprint",
    "source_version_id",
    "corpus_fingerprint",
    "state_issue_count",
    "available_count",
    "snapshot_fingerprint",
    "row_digest",
    "unavailable_reasons",
)

#: Quantas colunas o arquivo tem sob o catálogo da V2: 23 de identidade e
#: linhagem, mais 105 valores, mais 105 disponibilidades.
#:
#: ELE É UMA NOTA, e não a fonte: o schema é derivado do catálogo, e este
#: número existe para que uma mudança na largura do arquivo apareça como um
#: diff aqui, em vez de só na primeira leitura que quebrar.
COLUNAS_ESPERADAS_NOTA: Final[int] = len(IDENTITY_COLUMNS) + 2 * 105


def _tipo_arrow(definition: FeatureDefinition, pa: Any) -> Any:
    """O tipo da coluna, DECLARADO pela definição da feature.

    `INTEGER` VIRA `int64` E NÃO `int32`. Uma contagem de eventos numa janela
    de dez minutos cabe folgada em `int32`, e o dia em que uma feature de
    contagem acumulada não couber seria um estouro silencioso num Parquet já
    gravado. O ganho de espaço de `int32` é apagado pela compressão.

    `FLOAT` VIRA `float64` porque é isso que o domínio guarda (`FeatureValue`
    carrega `float`). Gravar `float32` faria o valor lido de volta não ser o
    valor calculado, e o digesto da linha deixaria de fechar.
    """
    match definition.output_type:
        case FeatureOutputType.INTEGER:
            return pa.int64()
        case FeatureOutputType.BOOLEAN:
            return pa.bool_()
        case FeatureOutputType.CATEGORY:
            # ELA NÃO CHEGA AQUI, e o construtor a recusa antes: `FeatureValue`
            # guarda `float`, então uma feature categórica não tem como
            # carregar a própria categoria. Inventar uma coluna de texto aqui
            # gravaria o número que o domínio de fato tem, com um nome que
            # promete outra coisa.
            raise ValidationError(
                f"a feature {definition.key} é CATEGORY, e o domínio guarda todo "
                "valor como número: a coluna prometeria uma categoria e gravaria "
                "um float"
            )
        case _:
            return pa.float64()


def feature_schema(definitions: Sequence[FeatureDefinition]) -> Any:
    """O schema completo — identidade, mais duas colunas por feature.

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
        pa.field("kickoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("temporal_mode", pa.string(), nullable=False),
        # NULO NO CORTE INTRA-JOGO, E ISSO É A DECISÃO (grid.py). Um instante
        # fabricado a partir de `kickoff + minuto` pareceria prova e erraria
        # por dez a vinte minutos nos jogos irregulares.
        pa.field("knowledge_cutoff", pa.timestamp("us", tz="UTC")),
        pa.field("space_name", pa.string(), nullable=False),
        pa.field("space_version", pa.string(), nullable=False),
        pa.field("space_fingerprint", pa.string(), nullable=False),
        pa.field("policy_version", pa.string(), nullable=False),
        pa.field("policy_fingerprint", pa.string(), nullable=False),
        pa.field("source_version_id", pa.string(), nullable=False),
        pa.field("corpus_fingerprint", pa.string(), nullable=False),
        pa.field("state_issue_count", pa.int32(), nullable=False),
        pa.field("available_count", pa.int32(), nullable=False),
        pa.field("snapshot_fingerprint", pa.string(), nullable=False),
        pa.field("row_digest", pa.string(), nullable=False),
        pa.field(
            "unavailable_reasons",
            pa.map_(pa.string(), pa.string()),
            nullable=False,
        ),
    ]
    for definicao in definitions:
        campos.append(pa.field(f"{VALUE_PREFIX}{definicao.key}", _tipo_arrow(definicao, pa)))
        campos.append(
            pa.field(f"{AVAILABILITY_PREFIX}{definicao.key}", pa.string(), nullable=False)
        )
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
    """A chave do objeto. Hive-style, porque é o que os leitores entendem.

    A VERSÃO ESTÁ NO CAMINHO e é imutável — é o que garante que reescrever sob
    a mesma chave com conteúdo diferente nunca aconteça: um conteúdo novo é uma
    versão nova, e uma versão nova é outro prefixo.

    `version` CHEGA JÁ COM O PREFIXO `v` (é o `__str__` de `DatasetVersion`), e
    o template não o acrescenta: fazê-lo produzia `vv1.0`, que funcionava e
    envergonhava todo mundo que lesse um caminho do bucket.
    """
    return (
        f"features/{dataset_name}/{version}/split={split.value}/"
        f"competition={competition}/season={season}/part-{part_index:05d}.parquet"
    )


def manifest_key(*, dataset_name: str, version: str) -> str:
    return f"features/{dataset_name}/{version}/manifest.json"


@final
class ParquetFeatureDatasetMaterializer:
    """Escreve as partições do dataset de features como Parquet."""

    def __init__(self, store: ObjectStorePort, *, definitions: Sequence[FeatureDefinition]) -> None:
        if not definitions:
            raise ValidationError(
                "materializador sem definições: o schema é derivado do catálogo, e sem "
                "ele o arquivo teria as colunas que o primeiro lote sugerisse"
            )
        self._store = store
        self._definitions = tuple(definitions)
        self._schema: Any | None = None
        # O TIPO DECLARADO DE CADA FEATURE, para a conversão da escrita. O
        # domínio guarda todo valor como `float` (`FeatureValue`), e o schema
        # declara `int64` para as contagens — sem esta tabela, um `3.0` chegaria
        # a uma coluna inteira e o pyarrow levantaria no meio da gravação, com
        # uma mensagem sobre tipos que não diria qual feature.
        self._tipos: dict[str, FeatureOutputType] = {
            d.key: d.output_type for d in self._definitions
        }
        categoricas = sorted(
            d.key for d in self._definitions if d.output_type is FeatureOutputType.CATEGORY
        )
        if categoricas:
            raise ValidationError(
                f"features categóricas no catálogo a materializar: {categoricas}. "
                "`FeatureValue` guarda `float`, então a categoria não existe no "
                "domínio — gravar uma coluna de texto aqui inventaria um valor que "
                "nenhuma extração produziu"
            )

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return self._definitions

    def schema(self) -> Any:
        """O schema, construído uma vez. Ele tem 233 campos — reconstruí-lo por
        partição custaria mais que escrever algumas partições pequenas."""
        if self._schema is None:
            self._schema = feature_schema(self._definitions)
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
        rows: Sequence[MaterializedFeatureRow],
    ) -> FeatureObjectRef | None:
        """Escreve um pedaço de partição. `None` quando não há linha nenhuma."""
        if not rows:
            # UM PARQUET DE ZERO LINHA É INDISTINGUÍVEL, na leitura, de uma
            # partição que ninguém escreveu — e as duas exigem ações diferentes
            # de quem investiga um buraco.
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
        return FeatureObjectRef(
            object_key=chave,
            split=split,
            competition=competition,
            season=season,
            sha256=ContentHash(hashlib.sha256(bruto).hexdigest()),
            size_bytes=len(bruto),
            row_count=len(rows),
            match_count=len({linha.key.match_key for linha in rows}),
            content_type=PARQUET_CONTENT_TYPE,
        )

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> FeatureObjectRef:
        """Grava o `manifest.json` ao lado dos dados.

        ELE ACOMPANHA OS DADOS e não só o banco: quem copia o diretório do
        dataset precisa levar junto a descrição do que copiou, senão o conteúdo
        chega sem políticas, sem contagem e sem impressão.
        """
        if not document:
            raise ValidationError("manifesto de features vazio")
        chave = manifest_key(dataset_name=dataset_name, version=version)
        await self._store.put_stream(
            chave,
            iter([document]),
            content_type="application/json",
            size_bytes=len(document),
        )
        return FeatureObjectRef(
            object_key=chave,
            split=DatasetSplit.REFERENCE,
            competition="*",
            season="*",
            sha256=ContentHash(hashlib.sha256(document).hexdigest()),
            size_bytes=len(document),
            row_count=0,
            content_type="application/json",
        )

    async def verify_object(self, *, object_key: str) -> MaterializedObjectContent:
        """Baixa o objeto uma vez: hash dos bytes E `(chave, digesto)` por linha.

        LÊ TRÊS COLUNAS DE DUZENTAS E TRINTA E TRÊS, e é para isso que o
        formato é colunar. O hash sai dos mesmos bytes, então integridade e
        conteúdo custam um download só.
        """
        import pyarrow.parquet as pq

        bruto = bytearray()
        async for bloco in self._store.open_stream(object_key):
            bruto.extend(bloco)
        conteudo = bytes(bruto)
        tabela = pq.read_table(
            io.BytesIO(conteudo), columns=["match_id", "grid_index", "row_digest"]
        )
        partidas = tabela.column("match_id").to_pylist()
        indices = tabela.column("grid_index").to_pylist()
        digestos = tabela.column("row_digest").to_pylist()
        linhas = tuple(
            (
                HistoricalFeatureSnapshotKey(match_key=str(partida), grid_index=int(indice)),
                str(digesto),
            )
            for partida, indice, digesto in zip(partidas, indices, digestos, strict=True)
        )
        return MaterializedObjectContent(
            object_key=object_key,
            sha256=hashlib.sha256(conteudo).hexdigest(),
            size_bytes=len(conteudo),
            rows=linhas,
        )

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        return manifest_key(dataset_name=dataset_name, version=version)

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        return f"features/{dataset_name}/{version}/"

    # ------------------------------------------------------------ interno --

    def _para_parquet(
        self,
        rows: Sequence[MaterializedFeatureRow],
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
        row: MaterializedFeatureRow,
        *,
        split: DatasetSplit,
        competition: str,
        season: str,
    ) -> dict[str, Any]:
        """Uma linha do arquivo. O digesto é calculado UMA vez e vai junto."""
        if row.split is not split:
            raise ValidationError(
                f"linha da metade {row.split} numa partição de {split}: a divisão é "
                "atômica por partida, e uma linha na partição errada quebraria a "
                "atomicidade sem que a contagem denunciasse",
                context={"match_id": row.key.match_key},
            )
        if row.competition_code != competition or row.season_label != season:
            raise ValidationError(
                f"linha de {row.competition_code}/{row.season_label} numa partição de "
                f"{competition}/{season}: a partição é o predicado que a leitura poda, "
                "e uma linha fora dela seria invisível a quem a usasse"
            )
        snapshot = row.snapshot
        registro: dict[str, Any] = {
            "match_id": row.key.match_key,
            "grid_index": row.key.grid_index,
            "grid_label": row.grid_label,
            "period": row.period.value,
            "minute": row.minute,
            "split": split.value,
            "competition": competition,
            "season": season,
            "kickoff": row.kickoff,
            "temporal_mode": snapshot.as_of.mode.value,
            "knowledge_cutoff": snapshot.as_of.knowledge_cutoff,
            "space_name": snapshot.space.name,
            "space_version": str(snapshot.space.version),
            "space_fingerprint": snapshot.space.fingerprint,
            "policy_version": snapshot.policy_version,
            "policy_fingerprint": snapshot.policy_fingerprint,
            "source_version_id": snapshot.source.version_id,
            "corpus_fingerprint": snapshot.source.corpus_fingerprint.value,
            "state_issue_count": row.state_issue_count,
            "available_count": row.available_count,
            "snapshot_fingerprint": snapshot.fingerprint,
            "row_digest": row.digest,
            "unavailable_reasons": list(row.unavailable_reasons().items()),
        }
        for computada in snapshot.features:
            chave = computada.definition_key
            registro[f"{AVAILABILITY_PREFIX}{chave}"] = computada.availability.value
            # INDISPONÍVEL É `None`, SEMPRE. `numeric` já devolve `None` quando
            # não há valor, e o domínio recusa valor com disponibilidade
            # negativa — as duas guardas cobrem o mesmo defeito de lados
            # opostos, e é o defeito que mais custa.
            registro[f"{VALUE_PREFIX}{chave}"] = _no_tipo(
                computada.numeric, self._tipos.get(chave, FeatureOutputType.FLOAT)
            )
        return registro


def _no_tipo(numero: float | None, tipo: FeatureOutputType) -> Any:
    """O valor na forma que a coluna declara. `None` continua `None`.

    A CONVERSÃO É EXPLÍCITA E RECUSA O INEXATO. Uma contagem que chegasse como
    `3.5` numa coluna inteira seria arredondada em silêncio pelo `int()`, e o
    dataset passaria a discordar do snapshot que o gerou — que é exatamente o
    que o digesto da linha existe para pegar, mas tarde demais.
    """
    if numero is None:
        return None
    if tipo is FeatureOutputType.BOOLEAN:
        return bool(numero)
    if tipo is FeatureOutputType.INTEGER:
        inteiro = int(numero)
        if inteiro != numero:
            raise ValidationError(
                f"valor {numero} numa feature declarada INTEGER: converter aqui "
                "esconderia uma definição que mente sobre o próprio tipo"
            )
        return inteiro
    return numero
