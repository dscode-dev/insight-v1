"""A trilha administrativa: quem fez o quê, quando, e sob qual correlação.

O ESCOPO É ESTREITO DE PROPÓSITO. Isto não é um SIEM, não detecta intrusão,
não correlaciona ameaça e não guarda requisição. É uma lista de mutações
administrativas com autor — o suficiente para responder "quem promoveu este
dataset para STAGED e por quê", que é a pergunta que de fato aparece.

O QUE ENTRA: só mutação. Uma leitura administrativa também é interessante e
não é auditável no mesmo sentido — ela não muda nada, e registrar toda leitura
faz o volume da trilha ser governado pelo tráfego em vez de pelas decisões,
até que ninguém consiga achar as decisões no meio.

`correlation_id` LIGA A TRILHA AO LOG. Sem ele, a entrada de auditoria diz que
alguém validou um dataset às 14h32 e a investigação para aí; com ele, a mesma
entrada leva às linhas de log daquela execução, que é onde está o motivo.

NUNCA CONTEÚDO DE DATASET AQUI. `detail` carrega decisão — o motivo, o estado
de origem e destino, o hash do arquivo. Nunca uma linha do arquivo. A trilha é
lida por gente que tem direito de ver decisões e não necessariamente direito
de ver o dado.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Self, final

from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant


class AuditAction(StrEnum):
    """As mutações administrativas que o motor registra. Fechado.

    UM ENUM E NÃO TEXTO LIVRE. Ação como string faz `dataset.staged`,
    `DATASET_STAGED` e `stage_dataset` coexistirem na mesma tabela, e a
    consulta que procura uma delas encontra um terço do que deveria.
    """

    DATASET_REGISTERED = "DATASET_REGISTERED"
    DATASET_FILE_ATTACHED = "DATASET_FILE_ATTACHED"
    DATASET_FILE_STORED = "DATASET_FILE_STORED"
    DATASET_FILE_UPLOAD_FAILED = "DATASET_FILE_UPLOAD_FAILED"
    DATASET_VALIDATION_STARTED = "DATASET_VALIDATION_STARTED"
    DATASET_VALIDATION_COMPLETED = "DATASET_VALIDATION_COMPLETED"
    DATASET_STAGED = "DATASET_STAGED"
    DATASET_REJECTED = "DATASET_REJECTED"

    # ---- PR-04.2. O QUE ENTRA AQUI É O CICLO DE VIDA DA EXECUÇÃO, e não o
    # que ela produziu: `CanonicalBuildRecord` já é a linhagem de cada fato, e
    # auditar fato a fato faria o volume da trilha ser governado pelo tamanho
    # do corpus até que ninguém encontre as decisões no meio (§76).
    QUALITY_RUN_STARTED = "QUALITY_RUN_STARTED"
    QUALITY_RUN_COMPLETED = "QUALITY_RUN_COMPLETED"
    CANONICAL_BUILD_STARTED = "CANONICAL_BUILD_STARTED"
    CANONICAL_BUILD_COMPLETED = "CANONICAL_BUILD_COMPLETED"
    #: UMA linha por execução com o RESUMO das exclusões por licença — não uma
    #: por partida. É a pergunta que de fato se faz numa auditoria jurídica:
    #: «este build comercial descartou o quê, e sob qual licença» (§20, §76).
    CANONICAL_BUILD_FAMILY_EXCLUDED = "CANONICAL_BUILD_FAMILY_EXCLUDED"

    # ---- PR-04.3. A PUBLICAÇÃO É UMA DECISÃO, e por isso ela está aqui: um
    # corpus publicado é o que passa a ser lido por tudo que vem depois, e
    # «quem publicou a 1.0, quando, com qual escopo» precisa ter resposta sem
    # arqueologia. O CONTEÚDO da versão não entra na trilha — a membership já
    # o grava partida a partida (§114).
    CORPUS_DATASET_CREATED = "CORPUS_DATASET_CREATED"
    CORPUS_VERSION_CREATED = "CORPUS_VERSION_CREATED"
    CORPUS_VERSION_BUILT = "CORPUS_VERSION_BUILT"
    CORPUS_VERSION_PUBLISHED = "CORPUS_VERSION_PUBLISHED"
    CORPUS_VERSION_FAILED = "CORPUS_VERSION_FAILED"
    CORPUS_VERSION_SUPERSEDED = "CORPUS_VERSION_SUPERSEDED"

    # ---- PR-05.5.1. O DATASET DE FEATURES TEM AÇÕES PRÓPRIAS, e não reusa as
    # do corpus: as duas coisas são publicadas por autorizações diferentes, e
    # uma trilha que as confundisse responderia «quem publicou a 1.0?» com duas
    # publicações de objetos distintos. `VALIDATED` existe aqui e não lá porque
    # a validação do dataset é uma FASE com veredito — ela pode reprovar uma
    # versão já construída.
    FEATURE_DATASET_CREATED = "FEATURE_DATASET_CREATED"
    FEATURE_DATASET_VERSION_CREATED = "FEATURE_DATASET_VERSION_CREATED"
    FEATURE_DATASET_VERSION_BUILT = "FEATURE_DATASET_VERSION_BUILT"
    FEATURE_DATASET_VERSION_VALIDATED = "FEATURE_DATASET_VERSION_VALIDATED"
    FEATURE_DATASET_VERSION_PUBLISHED = "FEATURE_DATASET_VERSION_PUBLISHED"
    FEATURE_DATASET_VERSION_FAILED = "FEATURE_DATASET_VERSION_FAILED"
    FEATURE_DATASET_VERSION_SUPERSEDED = "FEATURE_DATASET_VERSION_SUPERSEDED"

    # ---- PR-05.5.2. O AJUSTE TEM AÇÕES PRÓPRIAS, separadas das do dataset
    # normalizado, porque são duas decisões distintas: «esta é a escala» e
    # «esta é a representação publicada». Um mesmo ajuste alimenta várias
    # representações, e uma trilha que os confundisse não saberia dizer qual
    # das duas mudou quando os números mudaram.
    NORMALIZER_ARTIFACT_SET_FITTED = "NORMALIZER_ARTIFACT_SET_FITTED"
    NORMALIZER_ARTIFACT_SET_VALIDATED = "NORMALIZER_ARTIFACT_SET_VALIDATED"
    NORMALIZER_ARTIFACT_SET_PUBLISHED = "NORMALIZER_ARTIFACT_SET_PUBLISHED"
    NORMALIZER_ARTIFACT_SET_FAILED = "NORMALIZER_ARTIFACT_SET_FAILED"
    NORMALIZED_DATASET_CREATED = "NORMALIZED_DATASET_CREATED"
    NORMALIZED_DATASET_VERSION_CREATED = "NORMALIZED_DATASET_VERSION_CREATED"
    NORMALIZED_DATASET_VERSION_BUILT = "NORMALIZED_DATASET_VERSION_BUILT"
    NORMALIZED_DATASET_VERSION_VALIDATED = "NORMALIZED_DATASET_VERSION_VALIDATED"
    NORMALIZED_DATASET_VERSION_PUBLISHED = "NORMALIZED_DATASET_VERSION_PUBLISHED"
    NORMALIZED_DATASET_VERSION_FAILED = "NORMALIZED_DATASET_VERSION_FAILED"
    NORMALIZED_DATASET_VERSION_SUPERSEDED = "NORMALIZED_DATASET_VERSION_SUPERSEDED"

    @property
    def is_decision(self) -> bool:
        """Se a ação foi um julgamento humano e não um passo mecânico.

        Separa o que alguém DECIDIU do que o sistema executou. Numa
        investigação, as decisões são a lista curta por onde se começa.
        """
        return self in (
            AuditAction.DATASET_STAGED,
            AuditAction.DATASET_REJECTED,
            # Publicar é decidir que ESTE conteúdo é o corpus a partir de
            # agora — e superar é decidir que ele deixou de ser.
            AuditAction.CORPUS_VERSION_PUBLISHED,
            AuditAction.CORPUS_VERSION_SUPERSEDED,
            # Publicar um dataset de features é decidir que ESTA população é a
            # base de comparação a partir de agora.
            AuditAction.FEATURE_DATASET_VERSION_PUBLISHED,
            AuditAction.FEATURE_DATASET_VERSION_SUPERSEDED,
            # Publicar um ajuste é decidir que ESTA é a escala sob a qual duas
            # partidas passam a ser comparáveis.
            AuditAction.NORMALIZER_ARTIFACT_SET_PUBLISHED,
            AuditAction.NORMALIZED_DATASET_VERSION_PUBLISHED,
            AuditAction.NORMALIZED_DATASET_VERSION_SUPERSEDED,
        )


#: Teto do `detail`. Um dicionário sem limite é por onde o conteúdo do dataset
#: entra na trilha — alguém acrescenta "a linha que falhou" para depurar, e
#: aquilo fica.
MAX_DETAIL_KEYS: Final[int] = 20
MAX_DETAIL_VALUE_LENGTH: Final[int] = 512


@final
@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Uma mutação administrativa registrada."""

    id: str
    actor: Actor
    action: AuditAction
    at: Instant
    dataset_id: DatasetId | None = None
    file_id: str | None = None
    correlation_id: str | None = None
    #: Por quê. Obrigatório nas ações de decisão — uma promoção sem motivo é
    #: exatamente o registro que não explica nada seis meses depois.
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action.is_decision and not (self.reason or "").strip():
            raise ValidationError(
                f"{self.action} exige motivo: é uma decisão humana, e a trilha existe "
                "para registrar por que ela foi tomada"
            )
        if len(self.detail) > MAX_DETAIL_KEYS:
            raise ValidationError(
                f"detail com {len(self.detail)} chaves excede {MAX_DETAIL_KEYS} — "
                "a trilha registra decisão, não payload"
            )
        for chave, valor in self.detail.items():
            if isinstance(valor, str) and len(valor) > MAX_DETAIL_VALUE_LENGTH:
                raise ValidationError(
                    f"detail[{chave!r}] tem {len(valor)} caracteres, acima de "
                    f"{MAX_DETAIL_VALUE_LENGTH}: conteúdo de dataset não entra na trilha"
                )

    @classmethod
    def of(
        cls,
        action: AuditAction,
        *,
        actor: Actor,
        at: Instant,
        dataset_id: DatasetId | None = None,
        file_id: str | None = None,
        correlation_id: str | None = None,
        reason: str | None = None,
        **detail: Any,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            actor=actor,
            action=action,
            at=at,
            dataset_id=dataset_id,
            file_id=file_id,
            correlation_id=correlation_id,
            reason=reason,
            detail=detail,
        )

    def __str__(self) -> str:
        alvo = f" dataset={self.dataset_id}" if self.dataset_id else ""
        return f"{self.at.isoformat()} {self.actor} {self.action}{alvo}"
