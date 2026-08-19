"""O corpus escrito em Parquet — colunar, particionado, com schema explícito.

O PARQUET NÃO É A FONTE DA VERDADE (ADR-0027). Os fatos canônicos moram no
PostgreSQL; isto é uma cópia colunar feita para leitura analítica em massa.
Apagar o bucket não perde nada — regerar é reexecutar sobre a mesma versão, que
é imutável, e o resultado tem o mesmo conteúdo.

O SCHEMA É DECLARADO, NUNCA INFERIDO (§45). Inferir do primeiro lote faz uma
coluna toda nula virar `null` num arquivo e `double` noutro, e a leitura do
conjunto quebra em cima de dado que estava perfeitamente certo. Aqui os três
schemas são constantes deste módulo, e uma coluna nova é um diff.

AUSENTE É `NULL`, E `NULL` NÃO É ZERO (§46). Zero é um placar; ausente é a
falta de um. Um `0` no lugar de um `NULL` produz média errada que soma
perfeitamente — o pior tipo de defeito, porque nada denuncia. Nos eventos a
mesma regra tem um caso próprio: `xg = 0.0` é um chute que a fonte MEDIU como
quase impossível, e `xg` ausente é um chute que ela não mediu (PR-04.4.2 §24).

ODDS SÃO `decimal128` E NUNCA `double` (§47). `float(Decimal("2.05"))` não é
2.05, e o erro aparece exatamente onde dói: duas casas cotando o mesmo preço
e a comparação dizendo que não.

A PARTIÇÃO É `competition=/season=` (§43) porque é o predicado que a leitura
analítica poda. Sem ela, responder sobre uma temporada lê o corpus inteiro.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from typing import Any, Final, final

from sports_intelligence.domain.corpus.composition import ComposedMatchCorpusFacts
from sports_intelligence.domain.corpus.manifest import CorpusObjectRef
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.ports.object_store import ObjectStorePort

#: A compressão. ZSTD porque ela ganha de Snappy em taxa com custo de CPU
#: parecido na leitura, e o corpus é escrito uma vez e lido muitas.
COMPRESSION: Final[str] = "zstd"

#: O tipo MIME do Parquet, para o object store e para o manifesto.
PARQUET_CONTENT_TYPE: Final[str] = "application/vnd.apache.parquet"

#: Precisão e escala das odds. `decimal128(10, 4)` é exatamente o
#: `numeric(10, 4)` da coluna do PostgreSQL — divergir aqui reintroduziria o
#: arredondamento que a coluna evita.
_ODDS_PRECISION: Final[int] = 10
_ODDS_SCALE: Final[int] = 4


def _schemas() -> dict[CoverageFamily, Any]:
    """Os schemas, construídos sob demanda para não exigir pyarrow no import.

    O DOMÍNIO NÃO DEPENDE DE PYARROW, e este módulo é a fronteira: importá-lo
    no topo faria todo teste unitário de domínio carregar a biblioteca inteira
    para não usá-la.
    """
    import pyarrow as pa

    return {
        CoverageFamily.MATCH: pa.schema(
            [
                pa.field("match_id", pa.string(), nullable=False),
                pa.field("competition", pa.string(), nullable=False),
                pa.field("competition_id", pa.string(), nullable=False),
                pa.field("season", pa.string(), nullable=False),
                pa.field("season_id", pa.string(), nullable=False),
                pa.field("stage", pa.string(), nullable=False),
                pa.field("home_team_id", pa.string(), nullable=False),
                pa.field("away_team_id", pa.string(), nullable=False),
                pa.field("scheduled_kickoff", pa.timestamp("us", tz="UTC"), nullable=False),
                # NULO QUANDO A PARTIDA NÃO COMEÇOU NO HORÁRIO MARCADO e a
                # fonte não diz quando começou. Nunca igual ao marcado.
                pa.field("actual_kickoff", pa.timestamp("us", tz="UTC")),
                pa.field("lifecycle", pa.string(), nullable=False),
                pa.field("venue", pa.string()),
                pa.field("neutral_venue", pa.bool_(), nullable=False),
                # NULO QUANDO NÃO HÁ RESULTADO. Um `0` aqui significaria «não
                # marcaram», e a diferença é a de um jogo sem placar para um
                # jogo que terminou 0-0.
                pa.field("home_goals", pa.int32()),
                pa.field("away_goals", pa.int32()),
                pa.field("extra_time_home_goals", pa.int32()),
                pa.field("extra_time_away_goals", pa.int32()),
                pa.field("penalty_home_goals", pa.int32()),
                pa.field("penalty_away_goals", pa.int32()),
                pa.field("outcome", pa.string()),
            ]
        ),
        CoverageFamily.LINEUP: pa.schema(
            [
                pa.field("match_id", pa.string(), nullable=False),
                pa.field("competition", pa.string(), nullable=False),
                pa.field("season", pa.string(), nullable=False),
                pa.field("team_id", pa.string(), nullable=False),
                pa.field("formation", pa.string()),
                pa.field("player_id", pa.string(), nullable=False),
                pa.field("status", pa.string(), nullable=False),
                # NULO QUANDO A FONTE NÃO PUBLICA O NÚMERO. Nunca `0`: um
                # número de camisa 0 não existe (Constituição §4).
                pa.field("shirt_number", pa.int32()),
                pa.field("position", pa.string()),
                pa.field("tactical_role", pa.string()),
                pa.field("captain", pa.bool_(), nullable=False),
            ]
        ),
        # ------------------------------------------------------- eventos --
        #
        # UMA LINHA É UM EVENTO (ADR-0028). Não há coluna `event_1_type`, não
        # há array de eventos dentro da partida: a granularidade do arquivo é a
        # do fato, e é ela que permite «todos os chutes de cabeça de 2024» ser
        # uma varredura com poda em vez de uma leitura do corpus inteiro.
        #
        # NÃO EXISTE COLUNA `second`. O relógio canônico é
        # `(período, minuto, acréscimo)`; uma coluna de segundos teria de ser
        # sempre nula, e uma coluna sempre nula afirma que o dado poderia estar
        # ali — quando o motor nunca o recebeu (§19, PR-04.4.1).
        CoverageFamily.EVENT: pa.schema(
            [
                pa.field("event_id", pa.string(), nullable=False),
                pa.field("match_id", pa.string(), nullable=False),
                pa.field("competition", pa.string(), nullable=False),
                pa.field("season", pa.string(), nullable=False),
                # NULO QUANDO O EVENTO NÃO PERTENCE A UM TIME — o apito final
                # não é do mandante —, e nunca um UUID inventado (§23).
                pa.field("team_id", pa.string()),
                # NULO QUANDO NÃO HÁ EXECUTANTE. Um gol contra registrado só
                # pelo time é um gol; forçar um jogador aqui atribuiria o fato
                # a quem não o praticou.
                pa.field("player_id", pa.string()),
                pa.field("event_type", pa.string(), nullable=False),
                pa.field("period", pa.string(), nullable=False),
                pa.field("minute", pa.int32(), nullable=False),
                pa.field("stoppage", pa.int32(), nullable=False),
                pa.field("sequence", pa.int32(), nullable=False),
                pa.field("status", pa.string(), nullable=False),
                pa.field("revision", pa.int32(), nullable=False),
                # NULO NA REVISÃO 1. Uma cadeia começa em algum lugar.
                pa.field("supersedes_event_id", pa.string()),
                # NULO QUANDO A FONTE NÃO DÁ COORDENADA. Nunca `0.0`, que é o
                # canto do campo — uma posição perfeitamente válida (§23, §25).
                pa.field("start_x", pa.float64()),
                pa.field("start_y", pa.float64()),
                pa.field("end_x", pa.float64()),
                pa.field("end_y", pa.float64()),
                # O REFERENCIAL VIAJA COM O PONTO (ADR-0012): `0.8` sob
                # referenciais diferentes quer dizer coisas opostas.
                pa.field("coordinate_frame", pa.string()),
                # O DETALHE TIPADO EM DUAS COLUNAS (§20): o discriminador
                # separado do payload. Assim «todos os chutes» é um predicado
                # sobre uma coluna de string, e não um `LIKE` dentro de JSON.
                pa.field("detail_kind", pa.string()),
                pa.field("detail", pa.string()),
                pa.field("detail_schema_version", pa.string()),
                # O xG SOBE PARA COLUNA PRÓPRIA, e continua dentro do detalhe.
                # A duplicação é deliberada: o JSON é o payload tipado
                # COMPLETO, e a coluna é o escalar que a leitura analítica
                # filtra sem abrir JSON nenhum.
                #
                # TRÊS ESTADOS, E OS TRÊS SOBREVIVEM (§23, §24):
                #     0.0  medido, e quase impossível
                #     NULL com motivo   a fonte declarou e não veio
                #     NULL sem motivo   este tipo de detalhe não fala de xG
                pa.field("xg", pa.float64()),
                pa.field("xg_unavailable_reason", pa.string()),
                pa.field("license_class", pa.string(), nullable=False),
            ]
        ),
        CoverageFamily.ODDS: pa.schema(
            [
                pa.field("match_id", pa.string(), nullable=False),
                pa.field("competition", pa.string(), nullable=False),
                pa.field("season", pa.string(), nullable=False),
                pa.field("bookmaker", pa.string(), nullable=False),
                pa.field("market", pa.string(), nullable=False),
                pa.field("selection", pa.string(), nullable=False),
                pa.field(
                    "decimal_odds",
                    pa.decimal128(_ODDS_PRECISION, _ODDS_SCALE),
                    nullable=False,
                ),
                pa.field("line", pa.decimal128(_ODDS_PRECISION, _ODDS_SCALE)),
                # `None` QUANDO A FONTE NÃO DECLARA. Nunca o kickoff, nunca a
                # hora em que NÓS lemos o arquivo (§44).
                pa.field("observed_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
    }


def partition_key(
    *,
    dataset_name: str,
    version: str,
    family: CoverageFamily,
    competition: str,
    season: str,
    part_index: int = 0,
) -> str:
    """A chave do objeto. Hive-style, porque é o que os leitores entendem.

    A VERSÃO ESTÁ NO CAMINHO e é imutável — é o que garante que reescrever sob
    a mesma chave nunca aconteça: uma composição nova é uma versão nova, e uma
    versão nova é outro prefixo.

    `version` CHEGA JÁ COM O PREFIXO `v` (é o `__str__` de `DatasetVersion`), e
    por isso o template não o acrescenta: fazê-lo produzia `vv1.0`, que
    funcionava e envergonhava todo mundo que lesse um caminho do bucket.
    """
    return (
        f"corpus/{dataset_name}/{version}/family={family.value}/"
        f"competition={competition}/season={season}/part-{part_index:05d}.parquet"
    )


def manifest_key(*, dataset_name: str, version: str) -> str:
    return f"corpus/{dataset_name}/{version}/manifest.json"


@final
class ParquetCorpusMaterializer:
    """Escreve as partições do corpus como Parquet no object store."""

    def __init__(self, store: ObjectStorePort) -> None:
        self._store = store

    async def materialize_partition(
        self,
        *,
        dataset_name: str,
        version: str,
        family: CoverageFamily,
        competition: str,
        season: str,
        part_index: int,
        facts: Sequence[ComposedMatchCorpusFacts],
    ) -> CorpusObjectRef | None:
        """Escreve um pedaço de partição. `None` quando não há linha nenhuma."""
        linhas = [linha for fatos in facts for linha in fatos.rows_for(family)]
        if not linhas:
            # UM PARQUET DE ZERO LINHA É INDISTINGUÍVEL, na leitura, de uma
            # partição que ninguém escreveu — e as duas exigem ações
            # diferentes de quem investiga um buraco na cobertura.
            return None

        bruto = _para_parquet(linhas, family)
        chave = partition_key(
            dataset_name=dataset_name,
            version=version,
            family=family,
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
        return CorpusObjectRef(
            object_key=chave,
            family=family.value,
            competition=competition,
            season=season,
            sha256=ContentHash(hashlib.sha256(bruto).hexdigest()),
            size_bytes=len(bruto),
            row_count=len(linhas),
            content_type=PARQUET_CONTENT_TYPE,
        )

    async def write_manifest(
        self, *, dataset_name: str, version: str, document: bytes
    ) -> CorpusObjectRef:
        """Grava o `manifest.json` ao lado dos dados (§56)."""
        if not document:
            raise ValidationError("manifesto vazio")
        chave = manifest_key(dataset_name=dataset_name, version=version)
        await self._store.put_stream(
            chave,
            iter([document]),
            content_type="application/json",
            size_bytes=len(document),
        )
        return CorpusObjectRef(
            object_key=chave,
            family="MANIFEST",
            competition="*",
            season="*",
            sha256=ContentHash(hashlib.sha256(document).hexdigest()),
            size_bytes=len(document),
            row_count=1,
            content_type="application/json",
        )

    def manifest_key(self, *, dataset_name: str, version: str) -> str:
        return manifest_key(dataset_name=dataset_name, version=version)

    def partition_prefix(self, *, dataset_name: str, version: str) -> str:
        return f"corpus/{dataset_name}/{version}/"


def _para_parquet(linhas: Sequence[dict[str, Any]], family: CoverageFamily) -> bytes:
    """Serializa as linhas sob o schema DECLARADO da família.

    O SCHEMA VAI EXPLÍCITO PARA `from_pylist`, e é isso que faz uma coluna
    inteiramente nula continuar sendo `int32` em vez de virar `null` — que é o
    defeito que só aparece quando alguém lê dois arquivos juntos.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _schemas()[family]
    tabela = pa.Table.from_pylist(list(linhas), schema=schema)
    buffer = io.BytesIO()
    pq.write_table(tabela, buffer, compression=COMPRESSION)
    return buffer.getvalue()
