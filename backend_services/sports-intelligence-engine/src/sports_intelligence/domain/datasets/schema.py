"""O schema que o arquivo TEM e o schema que o operador ESPERAVA.

DUAS COISAS DIFERENTES, E NENHUMA DAS DUAS É O CANONICAL FOOTBALL MODEL.

`DatasetSchemaObservation` é descritiva: foi isto que encontramos ao abrir o
arquivo. Cinco colunas, uma delas chamada `HomeTeam`, textual, sem nulos.

`DatasetSchemaContract` é o que o operador declarou esperar antes de abrir.
Serve para que um arquivo trocado — a temporada errada, o endpoint que mudou o
layout — falhe na entrada em vez de silenciosamente entrar torto.

O QUE NENHUMA DAS DUAS FAZ. Nenhuma mapeia `HomeTeam` para `TeamId`. Nenhuma
sabe que `HomeTeam` tem a ver com futebol. Para este PR, `HomeTeam` é uma
coluna de texto com um nome, exatamente como `FTHG` ou `B365H` — e essa
ignorância é deliberada. No instante em que este módulo souber que `HomeTeam`
é um time, ele terá começado a resolver identidade sem nenhuma das garantias
que resolução de identidade exige: confiança, conflito, procedência, fila de
revisão. Isso é o PR-03.

AMOSTRAS. Guardamos valores de exemplo porque sem eles o relatório diz "coluna
`Date` é texto" e o operador não consegue saber se é `2019-08-09` ou
`09/08/19` — que é justamente a diferença que estraga uma ingestão. Mas
amostra é conteúdo de dataset vazando para um lugar onde ele não pertence, e
por isso ela é curta, truncada e limitada a poucos valores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import ValidationError

#: Quantos valores de exemplo por coluna. Três bastam para reconhecer um
#: formato de data e são poucos o bastante para não virar cópia do arquivo.
MAX_SAMPLES_PER_COLUMN: Final[int] = 3
#: Tamanho de cada amostra. Uma célula de 4 KB existe, e guardá-la inteira num
#: relatório que é lido em terminal não ajuda ninguém.
MAX_SAMPLE_LENGTH: Final[int] = 64
#: Teto de colunas descritas. Um arquivo com 5.000 colunas é um defeito de
#: origem, e descrever as 5.000 no relatório o torna ilegível.
MAX_COLUMNS_DESCRIBED: Final[int] = 256


class DetectedType(StrEnum):
    """O tipo que a inspeção viu. Grosso de propósito.

    NÃO É O SISTEMA DE TIPOS DE NINGUÉM. Não é o do Arrow, não é o do Polars,
    não é o do PostgreSQL. É um vocabulário pequeno o bastante para descrever
    CSV, JSONL e Parquet com as mesmas palavras — sem o qual o relatório de um
    CSV e o de um Parquet seriam ilegíveis lado a lado, que é exatamente
    quando alguém os compara.
    """

    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    #: Aninhado: lista, struct, mapa. JSONL e Parquet têm; CSV não.
    NESTED = "NESTED"
    #: A inspeção não conseguiu decidir. Honesto e diferente de `STRING`:
    #: dizer "é texto" quando não se sabe é afirmar o que não se mediu.
    UNKNOWN = "UNKNOWN"


@final
@dataclass(frozen=True, slots=True)
class ColumnObservation:
    """Uma coluna, como ela apareceu no arquivo."""

    name: str
    detected_type: DetectedType
    #: Se a inspeção encontrou ausência. `None` quando não foi medido — o
    #: Parquet declara nulabilidade no metadado, o CSV exigiria varrer tudo.
    nullable: bool | None = None
    null_count: int | None = None
    samples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValidationError("coluna sem nome")
        cortadas = tuple(
            (s[:MAX_SAMPLE_LENGTH] + "…" if len(s) > MAX_SAMPLE_LENGTH else s)
            for s in self.samples[:MAX_SAMPLES_PER_COLUMN]
        )
        object.__setattr__(self, "samples", cortadas)
        if self.null_count is not None and self.null_count < 0:
            raise ValidationError(f"null_count negativo: {self.null_count}")


@final
@dataclass(frozen=True, slots=True)
class DatasetSchemaObservation:
    """O schema de UM arquivo, como foi encontrado.

    POR ARQUIVO E NÃO POR DATASET. Um dataset com vinte CSVs de temporadas
    diferentes costuma ter dezenove com o mesmo layout e um com uma coluna a
    mais — a temporada em que a fonte passou a publicar xG. Um schema único
    por dataset esconderia exatamente esse arquivo, que é o único interessante.
    """

    file_id: str
    columns: tuple[ColumnObservation, ...]
    row_count: int
    truncated_columns: bool = False

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValidationError(f"row_count negativo: {self.row_count}")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def column_count(self) -> int:
        return len(self.columns)

    def duplicated_columns(self) -> tuple[str, ...]:
        """Nomes que aparecem mais de uma vez.

        DUAS COLUNAS COM O MESMO NOME é o defeito que mais atravessa
        despercebido: quase toda biblioteca resolve sozinha — renomeando para
        `Date_1` ou ficando com a última — e o dado da outra some sem aviso.
        A comparação é case-insensitive porque `Date` e `date` colidem em
        PostgreSQL e em quase todo consumidor.
        """
        vistos: dict[str, int] = {}
        for coluna in self.columns:
            chave = coluna.name.strip().lower()
            vistos[chave] = vistos.get(chave, 0) + 1
        return tuple(sorted(nome for nome, n in vistos.items() if n > 1))


@final
@dataclass(frozen=True, slots=True)
class DatasetSchemaContract:
    """O que o operador declarou esperar. Opcional, e útil quando existe.

    É UM CONTRATO DE INGESTÃO, NÃO O SCHEMA CANÔNICO. Ele fala a língua da
    fonte — `home`, `away`, `date`, `odds_h` — e continua sem dizer o que
    essas colunas significam. A tradução para o vocabulário do motor é do
    PR-03, e a distância entre os dois é justamente o trabalho que ele faz.

    O valor de existir agora: um arquivo trocado falha na entrada. Sem
    contrato, um CSV da temporada errada ou de um endpoint que mudou o layout
    é aceito, validado, marcado `STAGED` — e o erro só aparece muito depois,
    quando alguém pergunta por que faltam trinta jogos.
    """

    #: Colunas cuja AUSÊNCIA é impeditiva.
    required_columns: frozenset[str] = frozenset()
    #: O conjunto completo que se espera. Uma coluna fora disto vira aviso, e
    #: só aviso: fonte pública acrescenta coluna sem avisar, e isso não é
    #: motivo para recusar o arquivo — é motivo para alguém olhar.
    expected_columns: frozenset[str] = frozenset()
    #: Tipos declarados por coluna. Divergência é impeditiva quando a coluna
    #: também é obrigatória, e aviso quando não é.
    declared_types: dict[str, DetectedType] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expected_columns and not self.required_columns <= self.expected_columns:
            faltando = sorted(self.required_columns - self.expected_columns)
            raise ValidationError(
                f"colunas obrigatórias fora do conjunto esperado: {faltando} — "
                "o contrato se contradiz"
            )
        desconhecidas = set(self.declared_types) - (
            self.expected_columns | self.required_columns
        )
        if self.expected_columns and desconhecidas:
            raise ValidationError(
                f"tipo declarado para coluna que o contrato não espera: "
                f"{sorted(desconhecidas)}"
            )

    @property
    def is_empty(self) -> bool:
        return not (self.required_columns or self.expected_columns or self.declared_types)

    def missing_required(self, observed: DatasetSchemaObservation) -> tuple[str, ...]:
        """As obrigatórias que não apareceram.

        Comparação normalizada — sem caixa e sem espaço nas pontas — porque
        `HomeTeam` e `hometeam` são a mesma coluna para quem declarou o
        contrato, e tratá-las como diferentes produziria um impeditivo falso.
        """
        presentes = {n.strip().lower() for n in observed.column_names}
        return tuple(sorted(c for c in self.required_columns if c.strip().lower() not in presentes))

    def unexpected(self, observed: DatasetSchemaObservation) -> tuple[str, ...]:
        if not self.expected_columns:
            return ()
        esperadas = {c.strip().lower() for c in self.expected_columns}
        return tuple(
            sorted(n for n in observed.column_names if n.strip().lower() not in esperadas)
        )

    def type_mismatches(
        self, observed: DatasetSchemaObservation
    ) -> tuple[tuple[str, DetectedType, DetectedType], ...]:
        """(coluna, declarado, encontrado) para cada divergência real.

        `UNKNOWN` NÃO CONTA COMO DIVERGÊNCIA. Quando a inspeção não conseguiu
        decidir o tipo, ela não está discordando do contrato — está dizendo
        que não sabe. Tratar não-saber como discordância encheria o relatório
        de impeditivos que descrevem o limite do nosso inspetor, não o do
        arquivo.
        """
        por_nome = {c.name.strip().lower(): c for c in observed.columns}
        divergencias: list[tuple[str, DetectedType, DetectedType]] = []
        for coluna, declarado in self.declared_types.items():
            encontrada = por_nome.get(coluna.strip().lower())
            if encontrada is None or encontrada.detected_type is DetectedType.UNKNOWN:
                continue
            if encontrada.detected_type is not declarado:
                divergencias.append((coluna, declarado, encontrada.detected_type))
        return tuple(sorted(divergencias))
