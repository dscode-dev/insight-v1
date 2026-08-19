"""O contrato de uma fonte de EVENTOS — o que uma linha precisa declarar.

O QUE ELE VALIDA E O QUE ELE NÃO VALIDA. Ele confere que o MAPEAMENTO declara
as colunas sem as quais um evento não pode existir, e que ele não mistura os
dois mundos. Ele NÃO interpreta futebol: não sabe que um pênalti vem de uma
falta, não sabe quantos eventos um jogo deveria ter, e não vai saber (§74).

    contrato          «esta declaração é utilizável?»     antes de ler bytes
    validação PR-02   «este arquivo tem estas colunas?»   estrutural
    qualidade PR-04   «este evento pode entrar?»          por evento

Os três são degraus diferentes e o contrato é o primeiro. Recusar aqui custa
uma mensagem na configuração; descobrir na leitura custa metade de um dataset
processado antes de alguém perceber.

O MÍNIMO É PEQUENO DE PROPÓSITO (§7). Um evento precisa de: a partida a que
pertence, o que aconteceu, e quando. O resto — quem, onde, com que desfecho —
depende do tipo, e exigir globalmente o que só alguns tipos têm faria toda
fonte de cartões declarar coordenadas que ela não tem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.sources.records_kind import RecordKind
from sports_intelligence.domain.sources.semantics import SemanticRole

#: SEM ESTES QUATRO NÃO HÁ EVENTO, e a lista é curta por decisão:
#:
#:     a partida        um evento órfão não descreve nada
#:     o tipo           «algo aconteceu aos 34» não é um fato utilizável
#:     o período        45 do primeiro tempo e 45 do segundo são momentos
#:                      diferentes, e sem o período eles colidem
#:     o minuto         o `when` mínimo
#:
#: `MATCH_PROVIDER_ID` é reaproveitado do catálogo de partida em vez de ganhar
#: um `EVENT_MATCH_REFERENCE` próprio: é o MESMO id, do mesmo provedor, para a
#: mesma partida — dois papéis para ele fariam o operador escolher entre dois
#: nomes certos e o resolver aceitar só um.
REQUIRED_EVENT_ROLES: Final[frozenset[SemanticRole]] = frozenset(
    {
        SemanticRole.MATCH_PROVIDER_ID,
        SemanticRole.EVENT_TYPE,
        SemanticRole.EVENT_PERIOD,
        SemanticRole.EVENT_MINUTE,
    }
)

#: FORTEMENTE RECOMENDADOS, e a diferença entre isto e o obrigatório é o que
#: acontece sem eles — não uma opinião sobre qualidade.
#:
#:     EVENT_PROVIDER_ID   sem ele, reprocessar duplica: não há como saber que
#:                         este evento já entrou (§19, §24, §28)
#:     EVENT_SEQUENCE      sem ela, dois eventos no mesmo minuto empatam e o
#:                         desempate cai na ordem do arquivo (§17, §18)
RECOMMENDED_EVENT_ROLES: Final[frozenset[SemanticRole]] = frozenset(
    {SemanticRole.EVENT_PROVIDER_ID, SemanticRole.EVENT_SEQUENCE}
)

#: Pares em que declarar um lado sem o outro é declaração pela metade.
_PARES: Final[tuple[tuple[SemanticRole, SemanticRole], ...]] = (
    (SemanticRole.EVENT_X, SemanticRole.EVENT_Y),
    (SemanticRole.EVENT_END_X, SemanticRole.EVENT_END_Y),
    (
        SemanticRole.EVENT_PLAYER_OUT_PROVIDER_ID,
        SemanticRole.EVENT_PLAYER_IN_PROVIDER_ID,
    ),
)


@final
@dataclass(frozen=True, slots=True)
class EventContractReport:
    """O veredito sobre um mapeamento de eventos, com o que faltou.

    ELE SEPARA `missing` DE `weak`. O primeiro impede a leitura; o segundo a
    degrada de um jeito que quem opera precisa saber ANTES de rodar — «sem
    `EVENT_PROVIDER_ID` este dataset não pode ser reprocessado sem duplicar»
    é a frase que evita a descoberta cara.
    """

    kind: RecordKind
    missing: tuple[SemanticRole, ...] = ()
    weak: tuple[SemanticRole, ...] = ()
    misplaced: tuple[SemanticRole, ...] = ()

    @property
    def is_usable(self) -> bool:
        return not self.missing and not self.misplaced

    @property
    def is_reprocessable(self) -> bool:
        """Se reler a MESMA fonte pode ser idempotente (§24, §28).

        Sem `EVENT_PROVIDER_ID` a resposta é não, e ela é não por uma razão
        estrutural: a identidade do evento passaria a depender da posição no
        arquivo, e a mesma linha lida duas vezes seria dois eventos.
        """
        return SemanticRole.EVENT_PROVIDER_ID not in self.weak

    def assert_usable(self) -> None:
        if self.misplaced:
            nomes = ", ".join(sorted(r.value for r in self.misplaced))
            raise ValidationError(
                f"o mapeamento é {self.kind} e declara papéis do outro mundo: "
                f"{nomes}. Um arquivo descreve {self.kind.rows_per_match} linha(s) "
                "por partida, e misturar os dois faria o leitor não saber se cada "
                "linha é uma partida ou um evento dela (PR-04.4.1 §5)",
                context={"kind": self.kind.value, "misplaced": nomes},
            )
        if self.missing:
            nomes = ", ".join(sorted(r.value for r in self.missing))
            raise ValidationError(
                f"mapeamento de eventos sem {nomes}. Sem a partida, o tipo, o "
                "período e o minuto não existe evento: um deles ausente produz "
                "linhas que não descrevem fato nenhum",
                context={"missing": nomes},
            )

    def __str__(self) -> str:
        if self.is_usable and not self.weak:
            return f"{self.kind}: contrato completo"
        partes = []
        if self.missing:
            partes.append(f"faltando {sorted(r.value for r in self.missing)}")
        if self.misplaced:
            partes.append(f"fora de lugar {sorted(r.value for r in self.misplaced)}")
        if self.weak:
            partes.append(f"frágil sem {sorted(r.value for r in self.weak)}")
        return f"{self.kind}: " + " · ".join(partes)


def inspect_contract(*, kind: RecordKind, roles: frozenset[SemanticRole]) -> EventContractReport:
    """Confere um mapeamento contra o contrato do seu `RecordKind`.

    ELA NÃO LEVANTA — devolve o relatório. Quem chama decide se recusa
    (configuração) ou apenas reporta (diagnóstico), e as duas coisas precisam
    do MESMO cálculo: duas cópias divergiriam, e a divergência apareceria como
    um mapeamento aceito na configuração e recusado na leitura.
    """
    de_evento = {r for r in roles if r.is_event}

    if kind is RecordKind.MATCH_RECORD:
        # UM ARQUIVO DE PARTIDAS COM PAPEL DE EVENTO é quase sempre alguém
        # tentando encaixar `EVENT_1_TYPE` no formato antigo (§9).
        return EventContractReport(kind=kind, misplaced=tuple(sorted(de_evento)))

    faltando = REQUIRED_EVENT_ROLES - roles
    fracos = RECOMMENDED_EVENT_ROLES - roles
    for esquerda, direita in _PARES:
        if (esquerda in roles) != (direita in roles):
            faltando = faltando | {esquerda, direita} - roles
    return EventContractReport(
        kind=kind,
        missing=tuple(sorted(faltando)),
        weak=tuple(sorted(fracos)),
    )
