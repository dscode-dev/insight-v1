"""A projeção de uma linha normalizada em linha indexada — e a contabilidade dela.

O QUE ESTE MÓDULO GARANTE, E É O §11: **nenhuma linha desaparece em silêncio.**
Toda linha de REFERÊNCIA lida cai em exatamente um balde:

    indexada          virou linha do índice
    recusada          não pôde virar, e o MOTIVO está dito

Um construtor que simplesmente pulasse as linhas problemáticas produziria um
índice menor que a origem sem que ninguém soubesse por quê — e o recall medido
depois seria contra um universo que já estava incompleto antes do ANN existir.

ELE É PURO. Nada aqui conhece SQL, pgvector ou Parquet: a entrada é uma linha
de domínio e a saída é uma estrutura de domínio. O adapter escreve; este módulo
decide O QUE escrever, e é por isso que a impressão de conteúdo pode ser
calculada antes de qualquer `INSERT`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import final

from sports_intelligence.domain.features.normalized.rows import NormalizationAvailability
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.projection.contract import PROJECTION_CONTENT_ALGORITHM
from sports_intelligence.domain.retrieval.projection.payload import ExactStatePayload
from sports_intelligence.domain.retrieval.projection.spec import ProjectionAxisSpec
from sports_intelligence.domain.retrieval.timepoint import GRID_SEQUENCE, GRID_STOPPAGE
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError


@final
class IndexRowRejection(StrEnum):
    """Por que uma linha de referência não virou linha indexada. FECHADO.

    OS TRÊS MOTIVOS SÃO DE NATUREZA DIFERENTE, e contá-los juntos esconderia a
    diferença: o primeiro é atrição normal de dado, o segundo é defeito de
    dataset e o terceiro é engano de configuração. Só o primeiro é esperado.
    """

    #: A linha não tem eixo utilizável nenhum. Indexá-la gastaria espaço com um
    #: vetor de zeros que nunca seria elegível — e o prefiltro seguro já a
    #: recusaria em toda consulta.
    NO_USABLE_AXIS = "NO_USABLE_AXIS"
    #: Máscara e valor discordam. É defeito, e o construtor PARA.
    AVAILABILITY_INCONSISTENCY = "AVAILABILITY_INCONSISTENCY"
    #: A linha é de AVALIAÇÃO. Ela nunca é candidata (§16 do PR anterior).
    NOT_REFERENCE = "NOT_REFERENCE"


@final
@dataclass(frozen=True, slots=True)
class StateIndexRow:
    """Uma linha pronta para a projeção de estado — payload e filtros do universo."""

    semantic_key: str
    match_id: str
    competition: str
    season: str
    period: str
    minute: int
    stoppage: int
    tie_break: str
    payload: ExactStatePayload

    @property
    def usable_axes(self) -> int:
        return self.payload.usable_count

    @property
    def row_digest(self) -> str:
        return self.payload.row_digest

    def content_entry(self) -> tuple[str, str]:
        """`(chave, digesto)` — o par que entra na impressão de conteúdo (§24)."""
        return (self.semantic_key, self.payload.digest)


@final
@dataclass(slots=True)
class BuildAccounting:
    """A contabilidade do construtor. Toda linha lida cai em um balde."""

    rows_read: int = 0
    rows_indexed: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    by_competition: dict[str, int] = field(default_factory=dict)

    def indexed(self, competition: str) -> None:
        self.rows_read += 1
        self.rows_indexed += 1
        self.by_competition[competition] = self.by_competition.get(competition, 0) + 1

    def rejected_as(self, reason: IndexRowRejection) -> None:
        self.rows_read += 1
        self.rejected[reason.value] = self.rejected.get(reason.value, 0) + 1

    @property
    def rejected_total(self) -> int:
        return sum(self.rejected.values())

    def assert_reconciles(self) -> None:
        """§11 — o que entrou é o que saiu, mais o que foi recusado COM motivo."""
        if self.rows_read != self.rows_indexed + self.rejected_total:
            raise ValidationError(
                f"contabilidade não fecha: {self.rows_read} lidas, "
                f"{self.rows_indexed} indexadas e {self.rejected_total} recusadas. "
                "Uma linha sem balde é uma linha que sumiu sem motivo"
            )

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "by_competition": dict(sorted(self.by_competition.items())),
            "rejected": dict(sorted(self.rejected.items())),
            "rejected_total": self.rejected_total,
            "rows_indexed": self.rows_indexed,
            "rows_read": self.rows_read,
        }


def state_semantic_key(row: CandidateRow) -> str:
    """A identidade semântica de uma linha de estado (§53 do gate anterior).

    É A CHAVE DO SNAPSHOT, e ela já é única no dataset: partida mais índice da
    grade. Acrescentar competição ou temporada aqui seria redundante — as duas
    são função da partida — e tornaria a chave dependente de dados que podem
    ser corrigidos sem que a linha mude.
    """
    return row.key.text


def build_state_row(
    row: CandidateRow,
    *,
    spec: ProjectionAxisSpec,
) -> StateIndexRow | IndexRowRejection:
    """Uma linha de referência vira linha indexada — ou um motivo de recusa.

    A DISPONIBILIDADE É RELIDA DO DATASET, e não inferida do valor. `AVAILABLE`
    com valor ausente e valor presente com máscara indisponível são as duas
    contradições que o PR-06.2 já recusava; aqui elas viram motivo tipado em
    vez de exceção, porque o construtor precisa CONTAR quantas houve antes de
    decidir se o dataset presta.
    """
    if row.split.value != "REFERENCE":
        return IndexRowRejection.NOT_REFERENCE

    valores: dict[str, float | None] = {}
    usaveis: dict[str, bool] = {}
    for chave in spec.axis_keys:
        declarada = row.availabilities.get(chave)
        valor = row.values.get(chave)
        disponivel = declarada == NormalizationAvailability.AVAILABLE.value
        if not disponivel:
            if valor is not None:
                return IndexRowRejection.AVAILABILITY_INCONSISTENCY
            usaveis[chave] = False
            valores[chave] = None
            continue
        if valor is None:
            return IndexRowRejection.AVAILABILITY_INCONSISTENCY
        usaveis[chave] = True
        valores[chave] = valor

    if not any(usaveis.values()):
        return IndexRowRejection.NO_USABLE_AXIS

    celulas = [valores[chave] for chave in spec.axis_keys]
    mascara = [usaveis[chave] for chave in spec.axis_keys]
    payload = ExactStatePayload(
        axis_keys=spec.axis_keys,
        # O PAYLOAD GUARDA UM NÚMERO EM TODA POSIÇÃO porque `bytes` não tem
        # buraco; a MÁSCARA é o que devolve a ausência ao domínio na leitura.
        # O zero aqui nunca é lido como medição — `values_by_key` o converte de
        # volta a `None` exatamente onde a máscara diz que não há valor.
        values=tuple(0.0 if v is None else v for v in celulas),
        mask=tuple(mascara),
        row_digest=row.row_digest,
        representation_fingerprint=row.representation_fingerprint,
    )
    return StateIndexRow(
        semantic_key=state_semantic_key(row),
        match_id=row.match_id,
        competition=row.competition,
        season=row.season,
        period=row.position.period.value,
        minute=row.position.minute,
        # A GRADE FIXA OS DOIS (PR-06.1). `GridTimePoint` não os carrega porque
        # eles não variam: acréscimo é sempre zero e desempate é sempre o
        # sentinela. Gravá-los mesmo assim é o que permite ao `WHERE` do ANN
        # escrever a conjunção INTEIRA de `EXACT_MATCH_TIME_POINT` — e é o que
        # tornará a coluna útil no dia em que a grade deixar de fixá-los.
        stoppage=GRID_STOPPAGE,
        tie_break=str(GRID_SEQUENCE),
        payload=payload,
    )


def content_fingerprint(entries: Iterable[tuple[str, str]]) -> str:
    """A impressão do CONTEÚDO indexado — sobre as chaves ORDENADAS (§24, §56).

    A ORDENAÇÃO É O QUE TORNA A IMPRESSÃO INDEPENDENTE DA ESCRITA. Se ela
    seguisse a ordem de chegada, um lote de mil linhas produziria identidade
    diferente de dois lotes de quinhentas sobre exatamente o mesmo conteúdo — e
    a impressão deixaria de responder «é o mesmo dado?» para responder «foi a
    mesma execução?», que não é a pergunta.

    O `version_id` E O CARIMBO DE TEMPO NÃO ENTRAM, pelo mesmo motivo: duas
    construções independentes do mesmo dataset têm de colidir aqui.
    """
    ordenadas = sorted(set(entries))
    digestor = hashlib.sha256()
    digestor.update(
        canonical_json({"algorithm": PROJECTION_CONTENT_ALGORITHM, "count": len(ordenadas)})
    )
    for chave, digesto in ordenadas:
        digestor.update(canonical_json({"digest": digesto, "key": chave}))
    return digestor.hexdigest()


def assert_axis_count(spec: ProjectionAxisSpec, *, expected: int) -> None:
    """§3 — `R != 29` é FAIL CLOSED, e nunca truncamento silencioso.

    A COLUNA FÍSICA TEM DIMENSÃO FIXA. Um plano com trinta eixos robustos
    produziria um vetor de sessenta posições que não cabe em `vector(58)`;
    cortar o excedente, preencher com zeros ou reordenar produziria vetores
    cujas posições significam outra coisa — e o índice continuaria respondendo,
    com vizinhos calculados sobre eixos trocados.
    """
    if spec.axis_count != expected:
        raise ValidationError(
            f"o plano tem {spec.axis_count} eixos robustos e o esquema físico foi "
            f"criado para {expected}. Truncar, preencher ou reordenar produziria um "
            "vetor cujas posições significam outros eixos; uma dimensão nova exige "
            "nova versão de spec e nova migration",
            context={"actual": spec.axis_count, "expected": expected},
        )


def state_rows_to_records(rows: Sequence[StateIndexRow]) -> list[dict[str, object]]:
    """As linhas no formato que o escritor do adapter espera.

    A TRADUÇÃO MORA AQUI, E NÃO NO ADAPTER, porque ela é sobre o CONTEÚDO — quais
    campos existem e o que cada um significa. O adapter cuida de como levá-los
    ao PostgreSQL, que é outra pergunta.
    """
    registros: list[dict[str, object]] = []
    for linha in rows:
        valores, mascara = linha.payload.encode()
        registros.append(
            {
                "semantic_key": linha.semantic_key,
                "competition": linha.competition,
                "season": linha.season,
                "match_id": linha.match_id,
                "period": linha.period,
                "minute": linha.minute,
                "stoppage": linha.stoppage,
                "tie_break": linha.tie_break,
                "usable_axes": linha.usable_axes,
                "exact_values": valores,
                "exact_mask": mascara,
                "exact_payload_digest": linha.payload.digest,
                "row_digest": linha.payload.row_digest,
                "representation_fingerprint": linha.payload.representation_fingerprint,
            }
        )
    return registros
