"""O registro de fonte: estruturado, ainda não canônico.

O ESTADO INTERMEDIÁRIO QUE FALTAVA. O PR-02 tem bytes; o PR-01 tem entidades.
Entre os dois existe uma coisa que não é nenhum dos dois: uma linha já lida,
com os papéis semânticos identificados, e ainda sem nenhuma identidade
resolvida. `SourceRecord` é isso.

ELE NÃO É ENTIDADE CANÔNICA, e o tipo impede que seja confundido com uma: não
tem `EntityId` nenhum, e os valores são `ParsedValue`, não `TeamId`. A
passagem entre um e outro é a `ResolutionDecision`.

O RAW NÃO É COPIADO PARA TODA TABELA (§37). Um dataset de cem mil linhas com
vinte colunas copiado para decisões, evidências e grupos de fusão viraria
milhões de linhas de texto duplicado. O que viaja é `DatasetRecordRef` —
dataset, arquivo, número da linha — e apenas os campos que a resolução de
fato compara. Quem precisar do registro inteiro relê o arquivo bruto, que é
imutável e continua lá (ADR-0014).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import ParsedValue
from sports_intelligence.domain.sources.semantics import SemanticRole

_REF = re.compile(r"^([0-9a-f-]{36}):([0-9a-f-]{36}):(\d+)$")


@final
@dataclass(frozen=True, slots=True)
class DatasetRecordRef:
    """Onde uma linha está, sem carregar a linha.

    A REFERÊNCIA É O QUE VIAJA. Ela cabe numa coluna de texto, é indexável, e
    permite voltar ao arquivo bruto quando alguém precisar do conteúdo — que
    é raro, e quando acontece é uma leitura só.

    O NÚMERO DA LINHA É O DO ARQUIVO, contando o cabeçalho como linha 1. É
    assim que um editor de texto conta, e é lá que quem investiga vai olhar.
    """

    dataset_id: DatasetId
    file_id: str
    record_number: int

    def __post_init__(self) -> None:
        if self.record_number < 1:
            raise ValidationError(
                f"número de registro {self.record_number}: a contagem começa em 1, "
                "como num editor de texto"
            )

    @classmethod
    def parse(cls, raw: str) -> Self:
        casou = _REF.match(raw.strip())
        if casou is None:
            raise ValidationError(
                f"{raw!r} não é uma referência de registro (dataset:arquivo:linha)"
            )
        return cls(
            dataset_id=DatasetId.parse(casou.group(1)),
            file_id=casou.group(2),
            record_number=int(casou.group(3)),
        )

    def __str__(self) -> str:
        return f"{self.dataset_id}:{self.file_id}:{self.record_number}"


@final
@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Uma linha lida, com papéis identificados e identidade ainda em aberto.

    `values` É POR PAPEL SEMÂNTICO, não por nome de coluna. É o que permite
    ao resolver conhecer `HOME_TEAM_NAME` sem nunca saber que a fonte chama
    aquilo de `HomeTeam`, `home` ou `Mandante`.
    """

    ref: DatasetRecordRef
    dataset_version: DatasetVersion
    provider_id: ProviderId
    values: dict[SemanticRole, ParsedValue]
    provenance: DataProvenance
    #: A impressão do manifesto sob o qual esta linha foi lida. Fecha a
    #: linhagem: a decisão derivada daqui sabe de quais bytes veio.
    manifest_fingerprint: ContentHash

    def get(self, role: SemanticRole) -> ParsedValue | None:
        """O valor de um papel, ou `None` se a fonte não o mapeia.

        `None` E `ParsedValue.absent` SÃO COISAS DIFERENTES, e a distinção
        importa: `None` significa «esta fonte não tem esta coluna»;
        `absent` significa «tem a coluna, e esta linha está vazia». A
        primeira é característica da fonte, a segunda é do registro.
        """
        return self.values.get(role)

    def text_of(self, role: SemanticRole) -> str | None:
        valor = self.values.get(role)
        return valor.as_text() if valor is not None else None

    def has(self, role: SemanticRole) -> bool:
        valor = self.values.get(role)
        return valor is not None and valor.is_present

    @property
    def invalid_roles(self) -> tuple[SemanticRole, ...]:
        """Os papéis cuja célula não converteu. Vão para o relatório."""
        return tuple(sorted((r for r, v in self.values.items() if v.is_invalid), key=str))

    @property
    def identity_values(self) -> dict[SemanticRole, ParsedValue]:
        return {r: v for r, v in self.values.items() if r.is_identity}

    @property
    def observation_values(self) -> dict[SemanticRole, ParsedValue]:
        return {r: v for r, v in self.values.items() if r.is_observation}

    def __str__(self) -> str:
        return f"registro {self.ref} · {len(self.values)} papel(éis)"


@final
@dataclass(frozen=True, slots=True)
class SourceBatch:
    """Um lote de registros. A unidade de trabalho do pipeline.

    O LOTE EXISTE PARA MATAR O N+1. O caminho ingênuo — resolver linha a
    linha, consultando o banco por linha — produz sete consultas por registro
    e setecentas mil para cem mil linhas. Com lote, os candidatos de todas as
    linhas são carregados de uma vez, e a resolução acontece em memória sobre
    o que foi carregado.

    O tamanho vem de configuração: ele troca memória por número de idas ao
    banco, e o ponto certo depende da máquina.
    """

    records: tuple[SourceRecord, ...]
    batch_index: int

    def __post_init__(self) -> None:
        if self.batch_index < 0:
            raise ValidationError(f"índice de lote {self.batch_index} inválido")

    def distinct_texts(self, role: SemanticRole) -> tuple[str, ...]:
        """Os valores DISTINTOS de um papel no lote, em ordem determinística.

        DISTINTOS porque um lote de mil linhas de Premier League tem vinte
        nomes de clube: consultar mil vezes o que são vinte buscas é o
        desperdício que o lote existe para evitar.

        ORDENADOS porque a ordem da consulta afeta a ordem dos candidatos
        empatados, e o reprocessamento precisa ser reproduzível (§33).
        """
        vistos = {
            texto
            for registro in self.records
            if (texto := registro.text_of(role)) is not None
        }
        return tuple(sorted(vistos))

    def __len__(self) -> int:
        return len(self.records)


#: Teto estrutural do lote. O valor real vem de settings; este é o limite
#: acima do qual a promessa de memória constante deixa de valer.
MAX_BATCH_SIZE: Final[int] = 20_000
