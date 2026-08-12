"""Processar duas vezes não pode contar duas vezes.

POR QUE ISTO É CONTRATO DE DOMÍNIO E NÃO DETALHE DE ADAPTER. A duplicata não
aparece como erro — aparece como número errado. Um gol contado duas vezes num
histórico infla o ataque do clube, o Elo, o confronto direto e a tabela, e
tudo continua somando. Só o resultado fica errado.

E ela é inevitável na operação normal: streams entregam ao menos uma vez, um
worker reiniciado reprocessa a partir do último commit, e uma reingestão
manual é exatamente a mesma entrada de novo.

TRÊS CHAVES, TRÊS PERGUNTAS DIFERENTES:

    SourceEventId    "este registro DO PROVEDOR já entrou?"
    IdempotencyKey   "esta OPERAÇÃO já foi executada?"
    ImportId         "este LOTE já foi processado?"

Confundi-las produz falsos negativos: dois provedores descrevendo o mesmo gol
têm `SourceEventId` diferentes e são a mesma coisa; o mesmo lote reenviado tem
`ImportId` igual e é a mesma coisa. A deduplicação por fato pertence à fusão
de fontes, não aqui.

O QUE ESTE MÓDULO NÃO FAZ: guardar as chaves. Isso é do adapter, e a estratégia
está documentada em `deduplication_contract` abaixo — escrita aqui porque a
regra é do domínio mesmo que a tabela não seja.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.shared.identity import ProviderId

#: Tamanho fixo do digest hexadecimal usado nas chaves derivadas.
_DIGEST_LEN: Final = 32


@final
@dataclass(frozen=True, slots=True)
class SourceEventId:
    """O registro de UM provedor, identificado como ELE o identifica.

    Escopado pelo provedor de propósito: dois provedores podem usar o id `1`
    para coisas diferentes, e sem o escopo o segundo suprimiria o primeiro.
    """

    provider: ProviderId
    external_id: str

    def __post_init__(self) -> None:
        texto = self.external_id.strip()
        if not texto:
            raise ValueError("SourceEventId sem external_id")
        object.__setattr__(self, "external_id", texto)

    @property
    def key(self) -> str:
        """A chave de deduplicação, estável entre execuções e processos."""
        return f"{self.provider}:{self.external_id}"

    def __str__(self) -> str:
        return self.key


@final
@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """A identidade de uma OPERAÇÃO — não de um dado.

    Duas execuções da mesma operação com a mesma entrada têm a mesma chave, e
    a segunda deve ser um no-op que devolve o resultado da primeira.
    """

    value: str

    def __post_init__(self) -> None:
        texto = self.value.strip()
        if len(texto) < 8:
            raise ValueError(
                f"IdempotencyKey {self.value!r} curta demais: chaves curtas colidem, "
                "e colisão aqui SUPRIME uma operação legítima"
            )
        object.__setattr__(self, "value", texto)

    @classmethod
    def derive(cls, operation: str, *parts: str) -> Self:
        """A MESMA chave para a MESMA operação sobre a MESMA entrada.

        Hash e não concatenação: as partes podem ser longas (caminhos, urls),
        e a chave vai para um índice.
        """
        if not operation.strip():
            raise ValueError("derive exige o nome da operação")
        material = "|".join([operation.strip(), *(p.strip() for p in parts)])
        digest = hashlib.blake2b(material.encode("utf-8"), digest_size=16).hexdigest()
        return cls(f"{operation.strip()}:{digest}")

    def __str__(self) -> str:
        return self.value


@final
@dataclass(frozen=True, slots=True)
class ImportId:
    """Uma execução de ingestão em lote.

    Serve para duas coisas que a chave por registro não serve: reverter um
    lote inteiro que entrou errado, e responder "de qual execução veio esta
    linha".
    """

    value: uuid.UUID

    @classmethod
    def new(cls) -> Self:
        return cls(uuid.uuid4())

    @classmethod
    def derive(cls, source: str, batch_ref: str) -> Self:
        """Determinística, para que reenviar o MESMO lote seja reconhecido.

        Sem isto, reenviar `BRA.csv` duas vezes gera dois `ImportId` e o
        segundo parece um lote novo.
        """
        material = f"{source.strip()}|{batch_ref.strip()}"
        digest = hashlib.blake2b(material.encode("utf-8"), digest_size=16).hexdigest()
        return cls(uuid.UUID(digest[:_DIGEST_LEN]))

    def __str__(self) -> str:
        return str(self.value)


#: O CONTRATO QUE OS ADAPTERS DEVEM CUMPRIR.
#:
#: Escrito como constante para que apareça no código e não só na documentação
#: — um contrato que mora só num `.md` é um contrato que a próxima
#: implementação não lê.
DEDUPLICATION_CONTRACT: Final = """
Todo adapter de ingestão deve garantir:

1. CHAVE ÚNICA NO BANCO, não checagem antes de gravar. `SELECT` seguido de
   `INSERT` tem janela de corrida, e dois workers no mesmo stream a encontram.
   A restrição de unicidade é a única garantia que sobrevive a concorrência.

2. CONFLITO É NO-OP, NÃO ERRO. Reprocessar deve ser seguro e silencioso; um
   erro em duplicata transforma o retry normal de um stream em alarme falso.

3. A CHAVE ENTRA NA MESMA TRANSAÇÃO DO EFEITO. Gravá-la depois abre a janela
   em que o efeito aconteceu e a chave não existe — e o retry duplica.

4. `ImportId` FICA NA LINHA. Sem ele não há como reverter um lote sem
   reconstruir a base inteira.

5. A DEDUPLICAÇÃO POR FATO NÃO É ESTA. Dois provedores descrevendo o mesmo gol
   são dois `SourceEventId` legítimos; uni-los é trabalho da fusão de fontes,
   que decide por identidade e precedência, não por chave de ingestão.
""".strip()
