"""A impressão semântica do corpus — SHA-256 sobre serialização ORDENADA.

POR QUE O XOR SAIU (PR-04.3.1 §4). O PR-04.3 acumulava as impressões dos
membros com XOR, e a propriedade que o justificava era boa: comutativo, então
a partição em lotes não vazava para o resultado. O problema é algébrico e não
some com constraint:

    H(A) ⊕ H(A)         = 0
    H(A) ⊕ H(A) ⊕ H(B)  = H(B)

Um item repetido se CANCELA. Hoje a duplicata é impedida — pela chave primária
`(version_id, match_id)` e por `SetFingerprint.add` recusar chave repetida —,
mas a impressão do corpus é a autoridade de entrada de toda a matemática que
vem depois, e ela não pode depender de guardas externas para não ter uma
colisão trivial. Quando o corpus ganhar mais famílias e mais formas de
pertinência, cada nova porta precisaria lembrar da mesma guarda.

O QUE ENTROU NO LUGAR: um hash SEQUENCIAL sobre uma ordem canônica explícita.
A comutatividade é substituída por uma coisa mais forte — a ordem é IMPOSTA na
leitura (`ORDER BY match_id`) e VERIFICADA na acumulação —, e o resultado
continua sendo calculável em uma passagem com memória O(lote).

    CorpusFingerprint = SHA256(
        separador de domínio ‖ cabeçalho ‖ membro₁ ‖ … ‖ membroₙ ‖ rodapé
    )

TRÊS DEFESAS QUE O XOR NÃO TINHA:

    ordem estritamente     duplicata e desordem VIRAM ERRO, em vez de virarem
    crescente              silêncio ou cancelamento
    framing por tamanho    «AB»+«C» e «A»+«BC» não colidem
    separador de domínio   a construção não é reaproveitável por acidente para
                           outro tipo de impressão

O QUE A IMPRESSÃO COBRE E O QUE ELA IGNORA está no §12 do PR-04.3.1 e é uma
decisão explícita:

    ENTRA   escopo de uso, escopo declarado, os MEMBROS (identidade, famílias
            e digest do conteúdo) e as contagens
    NÃO     nome do dataset, número da versão, impressões de política, ids de
    ENTRA   execução, carimbos de tempo, ids de linha do banco

POR QUE A POLÍTICA FICOU DE FORA (mudança em relação ao PR-04.3). Uma política
só é «relevante» para o conteúdo quando ela MUDA o conteúdo — e quando muda, os
membros já mudaram, porque o que a política decide é quais famílias entram e
quais partidas são elegíveis. Incluí-la acrescentaria apenas falsos negativos:
duas publicações de fatos idênticos sob políticas de versões diferentes
diriam «corpus diferente» sobre conteúdo igual. A política continua no
MANIFESTO, que é conteúdo + procedência.

    corpus_fingerprint   «é o mesmo CONTEÚDO?»
    manifest             «é o mesmo conteúdo, produzido do mesmo JEITO?»
    manifest_sha256      «é o mesmo ARQUIVO?»
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, final
from uuid import UUID

from sports_intelligence.domain.corpus.membership import CorpusMember, MembershipCounts
from sports_intelligence.domain.corpus.scope import CorpusScope
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.shared.errors import ValidationError

#: O nome do algoritmo, gravado no manifesto (§20, §62). Ele existe para que
#: uma impressão produzida por esta construção NUNCA seja confundida com a do
#: PR-04.3 — as duas são hex de 64 caracteres e são incomparáveis.
FINGERPRINT_ALGORITHM: Final[str] = "canonical-sha256-v1"

#: A versão do CONTRATO DE SERIALIZAÇÃO. Mudar a ordem canônica, o framing ou
#: qualquer campo do que entra exige subir isto — senão duas impressões
#: incomparáveis passam por comparáveis (§83).
FINGERPRINT_SCHEMA_VERSION: Final[str] = "1.0"

#: O SEPARADOR DE DOMÍNIO (§8). Ele impede que a mesma construção, aplicada a
#: outra coisa que também serializa membros, produza uma impressão que colida
#: com a de um corpus. Custa 50 bytes e fecha uma classe inteira de confusão.
_DOMAIN_SEPARATOR: Final[bytes] = b"INSIGHT:HISTORICAL_CANONICAL_CORPUS:FINGERPRINT:V1"

#: Quantos bytes o prefixo de tamanho ocupa. Oito é folgado para sempre, e um
#: tamanho FIXO é o que torna o enquadramento não ambíguo.
_TAMANHO_DO_PREFIXO: Final[int] = 8

#: Os rótulos de seção. Eles entram no hash junto do conteúdo, então um membro
#: nunca pode ser lido como cabeçalho nem vice-versa.
_TAG_HEADER: Final[bytes] = b"header"
_TAG_MEMBER: Final[bytes] = b"member"
_TAG_TRAILER: Final[bytes] = b"trailer"


def frame(tag: bytes, payload: bytes) -> bytes:
    """Enquadra um pedaço com rótulo e tamanho explícitos (§7).

    SEM ISSO, A CONCATENAÇÃO É AMBÍGUA: `"AB" + "C"` e `"A" + "BC"` produzem a
    mesma cadeia, e dois corpus diferentes produziriam a mesma impressão. O
    prefixo de tamanho torna a fronteira entre pedaços impossível de mover.
    """
    return (
        len(tag).to_bytes(2, "big")
        + tag
        + len(payload).to_bytes(_TAMANHO_DO_PREFIXO, "big")
        + payload
    )


def canonical_json(payload: object) -> bytes:
    """A serialização determinística de um pedaço.

    Chaves ordenadas, separador fixo, UTF-8, `ensure_ascii=False`. O que ela
    NÃO faz é resolver tipos — `uuid_text`, `instant_text` e `decimal_text`
    existem para isso, e nenhum valor chega aqui como objeto.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def uuid_text(value: UUID | str) -> str:
    """UUID em forma canônica: minúsculas, com hífens (§85).

    UMA FORMA SÓ, DECIDIDA AQUI. `str(UUID)` já produz isto, mas o texto que
    chega do banco pode vir de outro caminho — normalizar num lugar é o que
    impede duas representações do mesmo id produzirem impressões diferentes.
    """
    return str(UUID(str(value)))


def instant_text(value: datetime) -> str:
    """Instante em UTC, ISO-8601, com precisão de MICROSSEGUNDO fixa (§86).

    `datetime.isoformat()` OMITE os microssegundos quando eles são zero, então
    `20:00:00` e `20:00:00.000000` — o mesmo instante — produziriam cadeias
    diferentes conforme o caminho que trouxe o valor. A precisão fixa fecha
    isso; o fuso normalizado fecha a outra metade.
    """
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def decimal_text(value: Decimal | None) -> str | None:
    """Decimal como TEXTO normalizado, nunca float (§84).

    `2.00` e `2.0` são a mesma odd escrita de dois jeitos, e
    `float(Decimal("2.05"))` não é 2.05. A normalização escolhe uma forma; o
    expoente positivo volta a inteiro porque `normalize()` transforma 100 em
    `1E+2`.
    """
    if value is None:
        return None
    normalizado = value.normalize()
    if normalizado == normalizado.to_integral_value():
        normalizado = normalizado.quantize(Decimal(1))
    return format(normalizado, "f")


def member_payload(member: CorpusMember) -> bytes:
    """A forma canônica de UM membro, pronta para entrar no hash.

    ELA É A DO `as_canonical()` DO MEMBRO, e de propósito: uma segunda
    serialização aqui divergiria da primeira no primeiro campo novo, e a
    divergência apareceria como duas impressões diferentes sobre o mesmo
    corpus. O que este módulo acrescenta é o enquadramento, não o conteúdo.
    """
    return canonical_json(member.as_canonical())


@final
class CorpusFingerprintBuilder:
    """Acumula os membros EM ORDEM e devolve a impressão. Memória O(1).

    NÃO É `frozen` — ele é um acumulador, como o `SetFingerprint` era. O que é
    imutável é o resultado: `finish()` devolve um `ContentHash` e o objeto não
    viaja para lugar nenhum.

    A ORDEM CANÔNICA É `match_id` CRESCENTE. Ela é total (o `MatchId` é um
    UUID, único no motor inteiro), é a ordem em que a paginação por chave já
    entrega os membros, e é imposta pelo `ORDER BY` do adapter em vez de
    herdada da ordem natural do PostgreSQL. Prefixá-la com competição e
    temporada mudaria a leitura e não mudaria o determinismo — e custaria um
    cursor composto na paginação, que é complexidade sem propriedade nova.
    """

    __slots__ = ("_hasher", "_quantos", "_ultimo")

    def __init__(self, *, scope: CorpusScope) -> None:
        self._hasher = hashlib.sha256()
        self._hasher.update(_DOMAIN_SEPARATOR)
        self._hasher.update(
            frame(
                _TAG_HEADER,
                canonical_json(
                    {
                        "algorithm": FINGERPRINT_ALGORITHM,
                        "schema_version": FINGERPRINT_SCHEMA_VERSION,
                        "scope": scope.as_canonical(),
                    }
                ),
            )
        )
        self._quantos = 0
        self._ultimo: str | None = None

    def add(self, member: CorpusMember) -> None:
        """Acrescenta um membro. Exige ordem ESTRITAMENTE crescente.

        DUAS COISAS NUMA GUARDA SÓ, e as duas eram buracos do XOR:

            chave repetida     `[A, A, B]` não pode virar `[B]`. Aqui ela nem
                               entra — é erro, e o erro diz o quê e onde.
            ordem quebrada     se a leitura parar de vir ordenada, a impressão
                               mudaria em silêncio. Aqui a leitura quebrada
                               falha na primeira página fora de ordem.

        A guarda custa uma comparação de string por membro e é o que permite
        afirmar `MesmoCorpus ⇒ MesmaImpressão` sem depender de constraint de
        banco nenhuma.
        """
        chave = uuid_text(str(member.match_id))
        if self._ultimo is not None and chave <= self._ultimo:
            raise ValidationError(
                f"membro {chave} chegou depois de {self._ultimo}: a impressão do "
                "corpus exige ordem estritamente crescente de match_id. Fora de "
                "ordem ela mudaria em silêncio; repetido, o corpus teria a mesma "
                "partida duas vezes",
                context={"match_id": chave, "previous": self._ultimo},
            )
        self._ultimo = chave
        self._quantos += 1
        self._hasher.update(frame(_TAG_MEMBER, member_payload(member)))

    @property
    def count(self) -> int:
        return self._quantos

    def finish(self, counts: MembershipCounts) -> ContentHash:
        """Fecha com as contagens e devolve a impressão.

        AS CONTAGENS SÃO REDUNDANTES COM OS MEMBROS, e é de propósito: elas
        são o que um leitor confere primeiro, e um rodapé que discorde do
        corpo é um defeito que aparece na impressão em vez de aparecer meses
        depois numa consulta.
        """
        if counts.matches != self._quantos:
            raise ValidationError(
                f"a impressão absorveu {self._quantos} membro(s) e as contagens "
                f"declaram {counts.matches} — uma das duas está errada, e publicar "
                "assim faria a descrição mentir sobre o conteúdo",
                context={"absorbed": self._quantos, "declared": counts.matches},
            )
        final_hasher = self._hasher.copy()
        final_hasher.update(frame(_TAG_TRAILER, canonical_json({"counts": counts.as_canonical()})))
        return ContentHash(final_hasher.hexdigest())


def fingerprint_of(members: tuple[CorpusMember, ...], *, scope: CorpusScope) -> ContentHash:
    """A impressão de um conjunto já materializado. Para teste e para lote único.

    ELA ORDENA ANTES DE ACUMULAR, o que o acumulador não faz: o acumulador é
    alimentado por uma leitura que já vem ordenada e RECUSA o contrário, e é
    essa recusa que prova que a leitura está certa. Aqui a ordenação é a
    conveniência de quem já tem tudo em mãos.
    """
    construtor = CorpusFingerprintBuilder(scope=scope)
    for membro in sorted(members, key=lambda m: uuid_text(str(m.match_id))):
        construtor.add(membro)
    return construtor.finish(MembershipCounts.of(members))
