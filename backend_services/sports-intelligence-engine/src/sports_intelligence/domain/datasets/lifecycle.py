"""O ciclo de vida de um dataset histórico, e o limite que ele protege.

O QUE ESTE GRAFO EXISTE PARA IMPEDIR. Um dataset que chega a `STAGED` está
afirmando três coisas: os bytes estão guardados, o que foi guardado confere
com o que foi declarado, e nada estruturalmente impeditivo foi encontrado.
Alcançar `STAGED` sem passar por validação faria o motor afirmar as três sem
ter verificado nenhuma — e o sintoma só apareceria muito depois, quando o
PR-03 tentasse resolver identidades num arquivo que nunca foi lido.

Por isso `REGISTERED → STAGED` não existe no grafo. Não como conferência em
tempo de execução: como aresta ausente.

`STAGED` NÃO É `HISTORICAL_ACTIVE`. É o mal-entendido mais provável deste
módulo e vale escrever antes de qualquer código. `STAGED` significa:

    o bruto foi recebido, preservado e é estruturalmente apto a ENTRAR em
    resolução de identidade e fusão.

Não significa que o dado pode alimentar o índice histórico. Entre um e outro
existem o PR-03 inteiro e a barreira do ADR-0007. Nenhum dataset deste estágio
descreve futebol ainda: ele é evidência externa, não conhecimento canônico.

POR QUE `UPLOADING` FICOU. A pergunta é legítima — para um upload simples ele
parece cerimônia. Ele ficou porque tem semântica concreta e nenhum outro
estado a tem: é a janela em que existe intenção de arquivo registrada no banco
sem bytes confirmados no object store (ou o inverso). Object store e transação
SQL não commitam juntos, e fingir que sim é a origem de um `STAGED` falso.
`UPLOADING` é o nome desse intervalo, e é o que a reconciliação procura.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
)
from sports_intelligence.domain.shared.temporal import Instant


class DatasetLifecycle(StrEnum):
    """Onde o dataset está. Fechado: não há estado fora desta lista."""

    #: Metadados e fonte declarados. Nenhum byte recebido.
    REGISTERED = "REGISTERED"
    #: Há intenção de arquivo registrada e ainda não confirmada. É a janela
    #: de inconsistência possível entre banco e object store.
    UPLOADING = "UPLOADING"
    #: Todo arquivo declarado tem bytes confirmados no arquivo bruto.
    UPLOADED = "UPLOADED"
    #: Validação estrutural em andamento. Existe para que duas validações
    #: simultâneas colidam no banco em vez de rodarem as duas.
    VALIDATING = "VALIDATING"
    #: Validado sem nenhum impeditivo. É o único estado do qual se pode subir
    #: para `STAGED`.
    VALIDATED = "VALIDATED"
    #: Bruto preservado e estruturalmente apto a entrar em resolução/fusão.
    #: NÃO é apto a alimentar inteligência — ver o cabeçalho deste módulo.
    STAGED = "STAGED"

    #: A validação encontrou impeditivo. O bruto continua guardado: ele é a
    #: evidência de que o arquivo era assim, e apagá-lo apagaria a prova.
    INVALID = "INVALID"
    #: Um humano recusou. Distinto de `INVALID`: o arquivo podia estar
    #: perfeito e a decisão foi de licença, de escopo ou de duplicidade
    #: lógica — coisas que nenhuma validação estrutural enxerga.
    REJECTED = "REJECTED"
    #: A operação falhou por causa nossa: object store fora, transação
    #: perdida, worker morto. Distinto de `INVALID` porque a ação é outra —
    #: `INVALID` se conserta com um arquivo melhor, `FAILED` com um retry.
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """Se nada mais sai daqui sem intervenção que não seja retry."""
        return self in (DatasetLifecycle.STAGED, DatasetLifecycle.REJECTED)

    @property
    def accepts_files(self) -> bool:
        """Se ainda é legítimo anexar arquivo.

        Depois de `UPLOADED` o conjunto de arquivos está selado: acrescentar
        um arquivo a um dataset já validado mudaria o conteúdo de uma versão
        cujo relatório e cujo manifesto já foram emitidos — e os dois
        passariam a descrever algo que não existe mais.
        """
        return self in (DatasetLifecycle.REGISTERED, DatasetLifecycle.UPLOADING)


#: O grafo. Fechado e escrito por extenso, não gerado por regra.
#:
#: Regra derivada é o que permite uma aresta nova aparecer sem ninguém
#: decidi-la: alguém acrescenta um estado, a regra o inclui, e a transição
#: existe antes de a decisão ser tomada.
_TRANSICOES: Final[dict[DatasetLifecycle, frozenset[DatasetLifecycle]]] = {
    DatasetLifecycle.REGISTERED: frozenset(
        {
            DatasetLifecycle.UPLOADING,
            DatasetLifecycle.REJECTED,
            DatasetLifecycle.FAILED,
        }
    ),
    DatasetLifecycle.UPLOADING: frozenset(
        {
            DatasetLifecycle.UPLOADED,
            # Volta para `UPLOADING` não existe como aresta própria: anexar
            # o segundo arquivo é uma transição de `UPLOADING` para si mesmo,
            # tratada como no-op por `transition_to`.
            DatasetLifecycle.REJECTED,
            DatasetLifecycle.FAILED,
        }
    ),
    DatasetLifecycle.UPLOADED: frozenset(
        {
            DatasetLifecycle.VALIDATING,
            # Anexar mais arquivos a um dataset que já subiu tudo é legítimo
            # enquanto ele não foi validado: o operador percebeu que faltava
            # uma temporada. Depois da validação, não.
            DatasetLifecycle.UPLOADING,
            DatasetLifecycle.REJECTED,
            DatasetLifecycle.FAILED,
        }
    ),
    DatasetLifecycle.VALIDATING: frozenset(
        {
            DatasetLifecycle.VALIDATED,
            DatasetLifecycle.INVALID,
            DatasetLifecycle.FAILED,
        }
    ),
    DatasetLifecycle.VALIDATED: frozenset(
        {
            DatasetLifecycle.STAGED,
            # Revalidar é legítimo: o validador ganhou versão nova, e o mesmo
            # bruto pode agora ser lido melhor — ou pior.
            DatasetLifecycle.VALIDATING,
            DatasetLifecycle.REJECTED,
        }
    ),
    DatasetLifecycle.INVALID: frozenset(
        {
            # O único caminho de saída é revalidar. Não há aresta para
            # `VALIDATED` direta: quem conserta manda o arquivo de novo, em
            # outra versão, e a validação decide.
            DatasetLifecycle.VALIDATING,
            DatasetLifecycle.REJECTED,
        }
    ),
    DatasetLifecycle.FAILED: frozenset(
        {
            # Retry: volta para a janela de upload e refaz o que faltou.
            DatasetLifecycle.UPLOADING,
            DatasetLifecycle.VALIDATING,
            DatasetLifecycle.REJECTED,
        }
    ),
    DatasetLifecycle.STAGED: frozenset(),
    DatasetLifecycle.REJECTED: frozenset(),
}


@final
@dataclass(frozen=True, slots=True)
class DatasetTransition:
    """Uma mudança de estado, com quem pediu e por quê.

    O MOTIVO É OBRIGATÓRIO. Um histórico de transições sem motivo responde
    "quando mudou" e não responde "por que mudou", que é a única pergunta que
    alguém faz seis meses depois ao encontrar um dataset em `REJECTED`.
    """

    from_state: DatasetLifecycle
    to_state: DatasetLifecycle
    at: Instant
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                "transição de dataset sem motivo: sem ele o histórico não explica nada"
            )


def can_transition(current: DatasetLifecycle, target: DatasetLifecycle) -> bool:
    return target in _TRANSICOES[current]


def transition_to(
    current: DatasetLifecycle,
    target: DatasetLifecycle,
    *,
    at: Instant,
    reason: str,
) -> DatasetTransition:
    """Valida e descreve a transição. Recusa o que o grafo não prevê.

    `REGISTERED → STAGED` cai aqui, e cai como aresta ausente e não como
    conferência especial — que é o que garante que a recusa continue valendo
    quando alguém acrescentar um estado no meio.
    """
    if current is target:
        raise ConflictError(
            f"o dataset já está em {current}",
            context={"state": current.value},
        )
    if not can_transition(current, target):
        raise ConflictError(
            f"transição inválida: {current} → {target}. "
            f"De {current} só se pode ir para "
            f"{', '.join(sorted(e.value for e in _TRANSICOES[current])) or '(nenhum estado)'}",
            context={"from": current.value, "to": target.value},
        )
    return DatasetTransition(from_state=current, to_state=target, at=at, reason=reason)


def assert_can_stage(state: DatasetLifecycle, *, has_blocking_issues: bool) -> None:
    """A guarda do limite de staging, nas duas metades que ele tem.

    A PRIMEIRA METADE é de estado: só `VALIDATED` sobe para `STAGED`. A
    SEGUNDA é de conteúdo: nenhum impeditivo aberto. As duas são necessárias
    e nenhuma basta — um dataset pode estar `VALIDATED` por um relatório
    antigo, e um relatório limpo não diz nada sobre um dataset que nem subiu.
    """
    if state is not DatasetLifecycle.VALIDATED:
        raise ConflictError(
            f"só um dataset VALIDATED pode ser promovido a STAGED; este está em {state}",
            context={"state": state.value},
        )
    if has_blocking_issues:
        raise ConflictError(
            "o relatório de validação tem impeditivos abertos — "
            "STAGED afirmaria que o arquivo é estruturalmente apto, e ele não é"
        )


def assert_not_intelligence_ready(state: DatasetLifecycle) -> None:
    """A afirmação que este PR NÃO faz, escrita como guarda.

    Existe para ser chamada de qualquer caminho futuro que pretenda alimentar
    o índice histórico a partir de um dataset de intake. Ela sempre recusa:
    nenhum estado deste ciclo autoriza isso, nem `STAGED`. A promoção para
    uso histórico é decisão do pipeline de resolução e fusão, sob o ADR-0007,
    e não do registro de intake.
    """
    raise InvariantViolationError(
        f"um dataset de intake em {state} não alimenta inteligência. "
        "STAGED significa apto a ENTRAR em resolução de identidade e fusão — "
        "não apto a virar conhecimento canônico. Ver ADR-0016.",
        context={"state": state.value},
    )
