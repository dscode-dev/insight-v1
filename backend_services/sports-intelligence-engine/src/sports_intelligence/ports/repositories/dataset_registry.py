"""O registro de intake: dataset, arquivos, validações e manifestos.

QUATRO PORTS PEQUENOS E NÃO UM `DatasetRepository` GRANDE. A tentação é
óbvia — é tudo "dataset" — e o custo aparece no primeiro adapter: um port com
vinte métodos obriga qualquer duplo de teste a implementar vinte métodos para
exercitar um. O resultado prático é que ninguém escreve o duplo, todo mundo
mocka, e os testes passam a verificar chamadas em vez de comportamento.

A DIVISÃO SEGUE O CICLO DE VIDA DO DADO, não a tabela: o dataset e seus
arquivos mudam de estado; a validação e o manifesto são APPEND-ONLY. São
regimes de escrita diferentes, e misturá-los num port só esconderia que
`save_report` nunca sobrescreve nada.

TODA TRANSIÇÃO DE ESTADO É CONDICIONAL AO ESTADO ANTERIOR. Os métodos que
mudam `lifecycle` recebem o estado esperado e devolvem `bool`. É controle de
concorrência otimista feito onde ele funciona — no `UPDATE ... WHERE
lifecycle = $esperado` — e não em Python, onde dois processos leem o mesmo
estado, os dois acham que podem, e os dois seguem.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.manifest import DatasetManifest
from sports_intelligence.domain.datasets.models import (
    Dataset,
    DatasetFilter,
    DatasetSummary,
    Page,
)
from sports_intelligence.domain.datasets.validation import DatasetValidationReport
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class DatasetRepositoryPort(Protocol):
    """O dataset em si: criação, leitura e transição de estado."""

    async def insert_if_absent(self, dataset: Dataset) -> tuple[Dataset, bool]:
        """Insere, ou devolve o que já existe. `(dataset, foi_inserido_agora)`.

        A IDEMPOTÊNCIA DO REGISTRO MORA AQUI, e ela é do banco: a identidade
        é derivada de (nome, versão), então a segunda chamada colide na chave
        primária. Devolver o existente em vez de erro é o comportamento certo
        porque reenviar por timeout é operação normal, e transformá-la em
        conflito faz o cliente tratar sucesso como falha.

        O BOOLEANO É NECESSÁRIO e não é conveniência. Sem ele, quem chama não
        distingue "criei" de "já existia" — e a API responderia 201 para os
        dois, afirmando ter criado algo que não criou. Inferi-lo comparando
        campos do que voltou seria adivinhação.

        DEVOLVE O QUE ESTÁ NO BANCO, não o que foi passado. Se um dataset com
        aquele id já existe com outra fonte, é ELE que volta — e quem chamou
        descobre a divergência comparando, em vez de sobrescrever a fonte
        registrada por alguém.
        """
        ...

    async def by_id(self, dataset_id: DatasetId, *, with_files: bool = True) -> Dataset | None:
        """O dataset, com ou sem os arquivos.

        `with_files=False` existe porque carregar quinhentos arquivos para
        conferir um estado é a consulta que fica lenta sem ninguém notar.
        """
        ...

    async def by_name_version(self, name: str, version: DatasetVersion) -> Dataset | None: ...

    async def list(
        self, *, filters: DatasetFilter, page: Page
    ) -> tuple[Sequence[DatasetSummary], int]:
        """A página e o total.

        O TOTAL VEM JUNTO porque uma paginação sem total não permite ao
        cliente saber se acabou — ele descobre pedindo mais uma página vazia,
        que é uma consulta a mais em toda listagem.
        """
        ...

    async def transition(
        self,
        dataset_id: DatasetId,
        *,
        expected: DatasetLifecycle,
        target: DatasetLifecycle,
        at: Instant,
        reason: str,
        actor_id: str,
    ) -> bool:
        """Muda o estado SE ele ainda for o esperado. `False` se não era.

        `False` E NÃO EXCEÇÃO: perder a corrida é resultado, não erro. Duas
        validações simultâneas — uma da API, outra da CLI — é o caso real, e
        a segunda precisa poder dizer "outro já começou" com naturalidade em
        vez de subir como falha do sistema.

        O motivo e o autor entram na mesma operação porque a transição e seu
        registro histórico precisam commitar juntos: um estado que muda sem
        deixar rastro é indistinguível de um estado que sempre foi assim.
        """
        ...

    async def transitions_of(self, dataset_id: DatasetId) -> Sequence[tuple[str, str, str, str]]:
        """O histórico: (de, para, motivo, instante ISO). Para a CLI e a API."""
        ...


@runtime_checkable
class DatasetFileRepositoryPort(Protocol):
    """Os arquivos, e as duas metades do ADR-0017.

    `register_intent` e `confirm_stored` são fases separadas por decisão: o
    object store não commita com o PostgreSQL, e chamar as duas de uma vez
    esconderia a janela em que existe uma sem a outra.
    """

    async def register_intent(self, file: DatasetFile) -> DatasetFile:
        """Fase 1: a linha em `PENDING`. Idempotente por (dataset, sha256).

        DEVOLVE O REGISTRO EXISTENTE quando os mesmos bytes já foram
        anunciados. É o que faz o retry retomar em vez de duplicar: o id do
        arquivo é derivado do conteúdo, então a segunda tentativa encontra a
        primeira e continua de onde ela parou.
        """
        ...

    async def confirm_stored(self, file_id: str) -> bool:
        """Fase 3: os bytes estão lá e conferidos. `False` se já estavam."""
        ...

    async def mark_failed(self, file_id: str, *, reason: str) -> None: ...

    async def by_dataset(self, dataset_id: DatasetId) -> Sequence[DatasetFile]: ...

    async def by_content(self, dataset_id: DatasetId, sha256: str) -> DatasetFile | None:
        """O arquivo com estes bytes nesta versão, se houver.

        A detecção de duplicata FÍSICA — mesmos bytes — e só ela. Duplicata
        lógica (o mesmo jogo vindo de duas fontes) é indecidível aqui e é do
        PR-03.
        """
        ...

    async def record_inspection(self, file_id: str, *, row_count: int, column_count: int) -> None:
        """O que a inspeção mediu. Separado do resto porque só existe depois
        da validação, e um `update` genérico permitiria reescrever o hash."""
        ...

    async def pending_older_than(self, moment: Instant) -> Sequence[DatasetFile]:
        """As intenções que ficaram penduradas. A entrada da reconciliação:
        um `PENDING` de duas horas atrás é um upload que morreu no meio."""
        ...


@runtime_checkable
class DatasetValidationRepositoryPort(Protocol):
    """Relatórios e issues. APPEND-ONLY, e a ausência de `update` é o contrato.

    Revalidar não corrige um relatório: emite outro. Os dois ficam, e a
    diferença entre eles é o que mostra o que o validador novo passou a
    enxergar — informação que um `update` destruiria.
    """

    async def save_report(self, report: DatasetValidationReport) -> None: ...

    async def latest_for(self, dataset_id: DatasetId) -> DatasetValidationReport | None: ...

    async def by_id(self, report_id: str) -> DatasetValidationReport | None: ...

    async def history_for(
        self, dataset_id: DatasetId, *, limit: int = 10
    ) -> Sequence[DatasetValidationReport]: ...


@runtime_checkable
class DatasetManifestRepositoryPort(Protocol):
    """Manifestos. Também append-only, e endereçados pela impressão."""

    async def save(self, manifest: DatasetManifest) -> None: ...

    async def latest_for(self, dataset_id: DatasetId) -> DatasetManifest | None: ...

    async def by_fingerprint(self, fingerprint: str) -> DatasetManifest | None:
        """O manifesto de uma impressão. É o que torna a pergunta 'este
        resultado saiu de quais bytes' uma consulta e não uma reconstrução."""
        ...
