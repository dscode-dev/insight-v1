"""`SourceRecord` → `HistoricalEventRecord`. A tradução de forma, e só ela.

POR QUE NÃO UM LEITOR NOVO. O `SourceReader` do PR-02 já lê CSV, JSONL e
Parquet em lotes, aplica o mapeamento coluna→papel e converte por `ValueKind`.
Nada disso muda porque a linha descreve um evento: o que muda é o SIGNIFICADO
dos papéis, e significado é aqui.

Um leitor paralelo teria de reimplementar streaming, formatos e conversão — e
o dia em que um deles ganhasse suporte a uma codificação nova, o outro não
ganharia. Então este módulo é fino de propósito: ele recebe o que o leitor
existente produziu e o reescreve na forma que a canonicalização entende.

O QUE ELE RECUSA, e recusa cedo:

    linha sem partida        um evento órfão não descreve nada
    linha sem tipo           «algo aconteceu aos 34» não é fato
    período desconhecido     o catálogo é fechado; um rótulo fora dele é erro
                             de mapeamento, e adivinhar produziria momento errado

E o que ele NÃO faz é decidir: uma linha que não vira registro é reportada com
o motivo, e quem chama conta e registra. Levantar aqui derrubaria o lote
inteiro por causa de uma linha.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import final

from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
    RawEventClock,
    RawEventPoint,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from sports_intelligence.domain.sources.mapping import ParsedValue
from sports_intelligence.domain.sources.records import SourceRecord
from sports_intelligence.domain.sources.semantics import SemanticRole

#: Os papéis de DETALHE que sobrevivem no `details` do registro. Fechado: o
#: dicionário não é depósito, e um papel que não está aqui não chega ao
#: construtor — que é o que impede detalhe inventado.
_PAPEIS_DE_DETALHE: tuple[SemanticRole, ...] = (
    SemanticRole.EVENT_OUTCOME,
    SemanticRole.EVENT_BODY_PART,
    SemanticRole.EVENT_XG,
    SemanticRole.EVENT_CARD_TYPE,
    SemanticRole.EVENT_PLAYER_OUT_PROVIDER_ID,
    SemanticRole.EVENT_PLAYER_IN_PROVIDER_ID,
)


@final
@dataclass(frozen=True, slots=True)
class RejectedRow:
    """Uma linha que não virou registro, com o motivo.

    ELA EXISTE PARA SER CONTADA. Uma leitura que descarta em silêncio faz o
    total de eventos não bater com o total de linhas, e a diferença aparece
    semanas depois como «o corpus tem menos eventos que o arquivo».
    """

    record_ref: str
    reason: str


@final
@dataclass(frozen=True, slots=True)
class EventRowReader:
    """Converte lotes de `SourceRecord` em registros de evento."""

    def read(
        self, records: Sequence[SourceRecord]
    ) -> tuple[tuple[HistoricalEventRecord, ...], tuple[RejectedRow, ...]]:
        aceitos: list[HistoricalEventRecord] = []
        recusados: list[RejectedRow] = []
        for registro in records:
            try:
                aceitos.append(self.convert(registro))
            except ValidationError as erro:
                recusados.append(RejectedRow(record_ref=str(registro.ref), reason=erro.message))
        return tuple(aceitos), tuple(recusados)

    def convert(self, record: SourceRecord) -> HistoricalEventRecord:
        """Uma linha. Levanta `ValidationError` quando ela não é um evento."""
        return HistoricalEventRecord(
            record_ref=record.ref,
            provider_id=record.provider_id,
            match_reference=_texto_obrigatorio(
                record, SemanticRole.MATCH_PROVIDER_ID, "referência de partida"
            ),
            raw_type=_texto_obrigatorio(record, SemanticRole.EVENT_TYPE, "tipo do evento"),
            clock=_relogio(record),
            provider_event_id=_texto(record, SemanticRole.EVENT_PROVIDER_ID),
            sequence=_inteiro(record, SemanticRole.EVENT_SEQUENCE),
            team_reference=_texto(record, SemanticRole.EVENT_TEAM_PROVIDER_ID),
            team_name=_texto(record, SemanticRole.EVENT_TEAM_NAME),
            player_reference=_texto(record, SemanticRole.EVENT_PLAYER_PROVIDER_ID),
            player_name=_texto(record, SemanticRole.EVENT_PLAYER_NAME),
            start_point=_ponto(record, SemanticRole.EVENT_X, SemanticRole.EVENT_Y),
            end_point=_ponto(record, SemanticRole.EVENT_END_X, SemanticRole.EVENT_END_Y),
            revision=_revisao(record),
            supersedes_reference=_texto(record, SemanticRole.EVENT_SUPERSEDES_PROVIDER_ID),
            details=_detalhes(record),
        )

    def read_lazily(
        self, batches: Iterator[Sequence[SourceRecord]]
    ) -> Iterator[tuple[tuple[HistoricalEventRecord, ...], tuple[RejectedRow, ...]]]:
        """Lote a lote, sem materializar o arquivo (§69).

        UM `list(all_events)` AQUI SERIA O FIM DA PROPRIEDADE. Um arquivo de
        temporada tem centenas de milhares de linhas; o gerador mantém o pico
        no tamanho do lote, e o `yield` é o que garante isso — não uma
        promessa em comentário.
        """
        for lote in batches:
            yield self.read(lote)


# =============================================================== extração ==


def _valor(record: SourceRecord, role: SemanticRole) -> ParsedValue | None:
    return record.get(role)


def _texto(record: SourceRecord, role: SemanticRole) -> str | None:
    valor = _valor(record, role)
    if valor is None or not valor.is_present:
        return None
    if valor.text is not None:
        texto = valor.text.strip()
        return texto or None
    # UM PAPEL DE REFERÊNCIA DECLARADO COMO INTEIRO continua sendo referência:
    # provedores usam ids numéricos, e o mapeamento pode tipá-los. Converter
    # aqui evita obrigar o operador a declarar `TEXT` para um número.
    if valor.integer is not None:
        return str(valor.integer)
    return None


def _texto_obrigatorio(record: SourceRecord, role: SemanticRole, nome: str) -> str:
    texto = _texto(record, role)
    if texto is None:
        raise ValidationError(
            f"{record.ref}: linha de evento sem {nome} ({role.value}) — ela não "
            "descreve fato nenhum"
        )
    return texto


def _inteiro(record: SourceRecord, role: SemanticRole) -> int | None:
    valor = _valor(record, role)
    if valor is None or not valor.is_present:
        return None
    if valor.integer is not None:
        return valor.integer
    if valor.number is not None:
        return int(valor.number)
    if valor.text is not None:
        try:
            return int(valor.text.strip())
        except ValueError:
            return None
    return None


def _decimal(record: SourceRecord, role: SemanticRole) -> Decimal | None:
    valor = _valor(record, role)
    if valor is None or not valor.is_present:
        return None
    if valor.number is not None:
        return valor.number
    if valor.integer is not None:
        return Decimal(valor.integer)
    if valor.text is not None:
        try:
            return Decimal(valor.text.strip())
        except InvalidOperation:
            return None
    return None


def _relogio(record: SourceRecord) -> RawEventClock:
    """O relógio. `45+3` continua `45+3` — o acréscimo tem coluna própria."""
    bruto = _texto_obrigatorio(record, SemanticRole.EVENT_PERIOD, "período")
    try:
        periodo = Period(bruto.strip().upper())
    except ValueError as erro:
        raise ValidationError(
            f"{record.ref}: período {bruto!r} desconhecido. O catálogo tem "
            f"{[p.value for p in Period]} — adivinhar produziria um momento "
            "que não é o do evento"
        ) from erro
    minuto = _inteiro(record, SemanticRole.EVENT_MINUTE)
    if minuto is None:
        raise ValidationError(
            f"{record.ref}: linha de evento sem minuto legível ({SemanticRole.EVENT_MINUTE.value})"
        )
    return RawEventClock(
        period=periodo,
        minute=minuto,
        stoppage=_inteiro(record, SemanticRole.EVENT_STOPPAGE) or 0,
    )


def _ponto(
    record: SourceRecord, role_x: SemanticRole, role_y: SemanticRole
) -> RawEventPoint | None:
    """A coordenada. PAR OU NADA — um `x` sem `y` é meio ponto (§93)."""
    x, y = _decimal(record, role_x), _decimal(record, role_y)
    if x is None or y is None:
        return None
    return RawEventPoint(x=x, y=y)


def _revisao(record: SourceRecord) -> EventRevisionKind:
    """O tipo de revisão. AUSENTE É `NEW`, e não uma dedução (§21).

    Um rótulo desconhecido levanta em vez de virar `NEW`: «CORRECAO» escrito
    em português numa fonte que o motor não conhece viraria evento novo em
    silêncio, e o registro teria dois gols onde houve um corrigido.
    """
    bruto = _texto(record, SemanticRole.EVENT_REVISION_TYPE)
    if bruto is None:
        return EventRevisionKind.NEW
    try:
        return EventRevisionKind(bruto.strip().upper())
    except ValueError as erro:
        raise ValidationError(
            f"{record.ref}: tipo de revisão {bruto!r} desconhecido. O catálogo tem "
            f"{[k.value for k in EventRevisionKind]}"
        ) from erro


def _detalhes(record: SourceRecord) -> dict[str, str]:
    """Os detalhes crus, por nome de papel. Fechado por `_PAPEIS_DE_DETALHE`.

    O VALOR VAI COMO TEXTO porque quem o interpreta é o construtor, com o
    contrato tipado do tipo do evento. Converter aqui exigiria saber o tipo
    antes de traduzi-lo, e a tradução acontece depois.

    TRÊS ESTADOS, E ELES CHEGAM INTEIROS AO CONSTRUTOR (§94):

        papel não mapeado    a chave não aparece      «a fonte não tem isso»
        mapeado e vazio      a chave aparece com ""   «tem, e não mediu este»
        mapeado com valor    a chave aparece cheia    a medida

    Colapsar os dois primeiros faria `xg` ausente e `xg` não publicado virarem
    a mesma coisa — e o construtor perderia a informação antes de decidir.
    """
    detalhes: dict[str, str] = {}
    for papel in _PAPEIS_DE_DETALHE:
        valor = _valor(record, papel)
        if valor is None:
            # A COLUNA NÃO EXISTE no mapeamento: a fonte não trabalha com este
            # detalhe. Diferente de existir e vir vazia — e a diferença é o
            # §94 inteiro, entre «não publica xG» e «não mediu ESTE».
            continue
        if not valor.is_present:
            detalhes[papel.value] = ""
            continue
        if valor.text is not None and valor.text.strip():
            detalhes[papel.value] = valor.text.strip()
        elif valor.number is not None:
            detalhes[papel.value] = format(valor.number, "f")
        elif valor.integer is not None:
            detalhes[papel.value] = str(valor.integer)
    return detalhes
