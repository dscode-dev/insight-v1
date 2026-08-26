"""O agregado `Dataset` — uma unidade lógica de ingestão, e nada além disso.

O QUE UM DATASET É. Uma coisa que o operador declara: "os CSVs do
football-data para a Premier League, temporadas 2019 a 2024, coletados em
agosto". Tem nome, versão, uma fonte, uma licença e um conjunto de arquivos.

O QUE UM DATASET NÃO É, E É A METADE MAIS IMPORTANTE. Ele não é futebol. Não
sabe o que é um `TeamId`, não resolve `Manchester City` para coisa nenhuma, e
não tem uma partida dentro. Ele é EVIDÊNCIA EXTERNA — bytes com ficha de
origem — e a distinção entre evidência e conhecimento canônico é a razão de
este PR existir separado do próximo.

Por isso as declarações de competição e temporada aqui são DECLARAÇÕES, e o
nome dos campos diz isso. `declared_competitions` é o que o operador afirma
que o arquivo contém. Ninguém abriu o arquivo para conferir; quando alguém
abrir, será o PR-03, com regras de resolução e fila de revisão. Chamar o campo
de `competition_id` sugeriria um vínculo verificado que não existe, e é assim
que uma suposição vira fato ao atravessar uma camada.

VERSÃO E CONTEÚDO. A identidade é derivada de (nome, versão), então registrar
o mesmo par duas vezes devolve o mesmo dataset em vez de criar um segundo —
retry de rede não duplica nada. E o conjunto de arquivos SELA quando a
validação começa: `v1.0` não pode passar a ter outro conteúdo mantendo o
número. Quem precisa mudar o conteúdo registra `v1.1`, e as duas versões
coexistem — o relatório e o manifesto de `v1.0` continuam descrevendo
exatamente o que descreviam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import ClassVar, Final, Self, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.files import DatasetFile, FileStagingState
from sports_intelligence.domain.datasets.lifecycle import (
    DatasetLifecycle,
    transition_to,
)
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: Nome de dataset: slug legível e estável. Ele entra na identidade derivada,
#: então precisa ter uma grafia só — `Premier League` e `premier league`
#: derivariam ids diferentes para a mesma coisa.
_NOME = re.compile(r"^[a-z0-9]([a-z0-9_-]{1,61})[a-z0-9]$")

MAX_DESCRIPTION_LENGTH: Final[int] = 2000
#: Teto de arquivos por dataset. Existe para que um laço de upload com defeito
#: não cresça um dataset indefinidamente; o valor real vem de settings, este é
#: o limite estrutural do agregado.
MAX_FILES_PER_DATASET: Final[int] = 512


@final
@dataclass(frozen=True, slots=True)
class Dataset:
    """Uma entrada de dados históricos, com tudo que se sabe sobre ela."""

    id: DatasetId
    name: str
    version: DatasetVersion
    source: DatasetSource
    #: O que o operador AFIRMA que o arquivo contém. Não verificado.
    declared_competitions: frozenset[CompetitionCode]
    #: Rótulos de temporada como a fonte os escreve: `2019-2020`, `2024`.
    #:
    #: RÓTULOS E NÃO `SeasonId`, e a escolha é deliberada. Um `SeasonId` exige
    #: que a temporada já exista como entidade registrada, e no momento do
    #: upload ela pode não existir — a fonte é justamente o que vai povoá-la.
    #: Exigir a entidade antes do arquivo inverteria a ordem real do trabalho,
    #: e criá-la a partir do rótulo aqui seria resolução de identidade
    #: acontecendo na camada errada.
    declared_seasons: tuple[str, ...]
    lifecycle: DatasetLifecycle
    created_at: Instant
    created_by: str
    files: tuple[DatasetFile, ...] = ()
    description: str | None = None
    #: Preenchido quando a validação corrente termina. Liga o dataset ao
    #: relatório que justificou o estado em que ele está.
    latest_validation_id: str | None = None

    def __post_init__(self) -> None:
        if not _NOME.match(self.name):
            raise ValidationError(
                f"nome de dataset {self.name!r} inválido: 3 a 63 caracteres, minúsculas, "
                "dígitos, hífen e underscore, começando e terminando por letra ou dígito"
            )
        if not self.declared_competitions:
            raise ValidationError(
                "dataset sem competição declarada: sem ela não há como saber a que "
                "parte do catálogo esta evidência se refere"
            )
        if not self.created_by.strip():
            raise ValidationError("created_by vazio: toda operação administrativa tem autor")
        if self.description is not None and len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"description com {len(self.description)} caracteres excede "
                f"{MAX_DESCRIPTION_LENGTH}"
            )
        if len(self.files) > MAX_FILES_PER_DATASET:
            raise ValidationError(
                f"{len(self.files)} arquivos excede o limite de {MAX_FILES_PER_DATASET}"
            )
        rotulos = tuple(r.strip() for r in self.declared_seasons)
        if any(not r for r in rotulos):
            raise ValidationError("rótulo de temporada vazio na declaração")
        if len(set(rotulos)) != len(rotulos):
            raise ValidationError(f"temporada declarada em duplicidade: {rotulos}")
        object.__setattr__(self, "declared_seasons", rotulos)

    # ------------------------------------------------------------- criação --

    @classmethod
    def register(
        cls,
        *,
        name: str,
        version: DatasetVersion,
        source: DatasetSource,
        declared_competitions: frozenset[CompetitionCode],
        declared_seasons: tuple[str, ...],
        created_at: Instant,
        created_by: str,
        description: str | None = None,
    ) -> Self:
        """Cria o dataset em `REGISTERED`. Nenhum byte ainda.

        A IDENTIDADE É DERIVADA DE (nome, versão), e é o que torna o registro
        idempotente de graça: a segunda chamada com o mesmo par produz o mesmo
        `DatasetId`, e o repositório encontra a linha existente em vez de
        inserir outra. Sem isso, um cliente que reenvia por timeout cria dois
        datasets idênticos com ids diferentes, e nenhum dos dois está errado
        o bastante para ser detectável depois.
        """
        return cls(
            id=DatasetId.derive(name.strip().lower(), str(version)),
            name=name.strip().lower(),
            version=version,
            source=source,
            declared_competitions=declared_competitions,
            declared_seasons=declared_seasons,
            lifecycle=DatasetLifecycle.REGISTERED,
            created_at=created_at,
            created_by=created_by,
            description=description,
        )

    # -------------------------------------------------------------- estado --

    def with_lifecycle(self, target: DatasetLifecycle, *, at: Instant, reason: str) -> Self:
        """Muda de estado pelo grafo, ou recusa.

        A ÚNICA porta. O campo `lifecycle` não é escrito em nenhum outro
        lugar, e é isso que impede um dataset de chegar a `STAGED` sem passar
        por validação — a aresta não existe.
        """
        transition_to(self.lifecycle, target, at=at, reason=reason)
        return replace(self, lifecycle=target)

    def with_files(self, files: tuple[DatasetFile, ...]) -> Self:
        return replace(self, files=files)

    def with_validation(self, validation_id: str) -> Self:
        return replace(self, latest_validation_id=validation_id)

    # ------------------------------------------------------------ arquivos --

    def assert_accepts_files(self) -> None:
        """Recusa anexar arquivo a um dataset já selado.

        SELAR NA VALIDAÇÃO, e não no staging. Se o conjunto só selasse em
        `STAGED`, um arquivo acrescentado entre a validação e o staging
        entraria sem nunca ter sido lido — e o relatório limpo passaria a
        cobrir um conteúdo que ele não examinou. O relatório precisa descrever
        o conjunto inteiro, então o conjunto para de mudar quando ele começa.
        """
        if not self.lifecycle.accepts_files:
            raise ConflictError(
                f"dataset em {self.lifecycle} não aceita mais arquivos. "
                f"A versão {self.version} está selada — para mudar o conteúdo, "
                "registre outra versão.",
                context={"state": self.lifecycle.value, "version": str(self.version)},
            )
        if len(self.stored_files) >= MAX_FILES_PER_DATASET:
            raise ConflictError(
                f"dataset já tem {len(self.files)} arquivos (limite {MAX_FILES_PER_DATASET})"
            )

    def file_with_content(self, sha256: str) -> DatasetFile | None:
        """O arquivo com estes bytes, se já existir nesta versão.

        É o ponto onde o reenvio é reconhecido, e o reconhecimento é por
        CONTEÚDO — nome diferente com os mesmos bytes cai aqui igual.
        """
        return next((f for f in self.files if f.content_hash.value == sha256), None)

    @property
    def stored_files(self) -> tuple[DatasetFile, ...]:
        """Só os arquivos cujos bytes estão confirmados.

        A propriedade que impede o `STAGED` falso. Validação, manifesto e
        contagem usam esta, nunca `files` — um arquivo em `PENDING` é uma
        promessa, e uma promessa não é evidência.
        """
        return tuple(f for f in self.files if f.staging_state.counts_as_present)

    @property
    def pending_files(self) -> tuple[DatasetFile, ...]:
        """O que a reconciliação procura: intenção sem bytes confirmados."""
        return tuple(f for f in self.files if f.staging_state is FileStagingState.PENDING)

    @property
    def has_pending_uploads(self) -> bool:
        return bool(self.pending_files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.stored_files)

    def assert_ready_for_validation(self) -> None:
        """Validar exige conteúdo confirmado e nenhuma promessa em aberto."""
        if not self.stored_files:
            raise ConflictError(
                "não há arquivo com bytes confirmados para validar",
                context={"declared_files": len(self.files)},
            )
        if self.has_pending_uploads:
            pendentes = ", ".join(f.safe_filename for f in self.pending_files)
            raise ConflictError(
                f"há upload em aberto ({pendentes}) — validar agora produziria um "
                "relatório sobre um conjunto incompleto, e ele pareceria completo",
                context={"pending": len(self.pending_files)},
            )

    # -------------------------------------------------------------- licença --

    @property
    def needs_license_review(self) -> bool:
        """Se promover este dado a uso comercial exige decisão humana.

        Delegado à fonte de propósito: a licença é da fonte, não do arquivo, e
        duplicar o campo no dataset criaria dois lugares que divergem.
        """
        return self.source.needs_license_review

    def __str__(self) -> str:
        return f"{self.name}@{self.version} [{self.lifecycle}] {len(self.stored_files)} arquivo(s)"


@final
@dataclass(frozen=True, slots=True)
class DatasetFilter:
    """Os filtros da listagem administrativa.

    UM OBJETO E NÃO SEIS PARÂMETROS SOLTOS: seis opcionais numa assinatura
    viram sete no PR seguinte, e a ordem posicional passa a ser uma armadilha.
    Aqui um filtro novo é um campo com default, e nenhuma chamada existente
    muda.
    """

    competition: CompetitionCode | None = None
    lifecycle: DatasetLifecycle | None = None
    origin: str | None = None
    source_name: str | None = None
    created_after: Instant | None = None
    created_before: Instant | None = None

    def __post_init__(self) -> None:
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after > self.created_before
        ):
            raise ValidationError(
                "janela invertida: created_after é posterior a created_before — "
                "o filtro não devolveria nada e pareceria 'nenhum dataset'"
            )


@final
@dataclass(frozen=True, slots=True)
class Page:
    """Paginação explícita, com teto.

    O TETO NÃO É NEGOCIÁVEL PELO CLIENTE. Um `limit` sem máximo é um pedido
    de `limit=1000000` esperando para acontecer, e o custo cai no banco de
    quem opera, não em quem pediu.
    """

    limit: int = 50
    offset: int = 0

    MAX_LIMIT: ClassVar[int] = 200

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= Page.MAX_LIMIT:
            raise ValidationError(f"limit={self.limit} fora de [1, {Page.MAX_LIMIT}]")
        if self.offset < 0:
            raise ValidationError(f"offset negativo: {self.offset}")


@final
@dataclass(frozen=True, slots=True)
class DatasetSummary:
    """O que a listagem devolve: o suficiente para decidir, sem os arquivos.

    Carregar os arquivos de cinquenta datasets para listar cinquenta linhas é
    a consulta que fica lenta em silêncio e só aparece quando o registro
    cresce.
    """

    id: DatasetId
    name: str
    version: DatasetVersion
    lifecycle: DatasetLifecycle
    source_name: str
    source_type: str
    license_class: str
    declared_competitions: frozenset[CompetitionCode] = field(default_factory=frozenset)
    file_count: int = 0
    total_bytes: int = 0
    created_at: Instant | None = None
