# ADR-0005 — Snapshots imutáveis

**Status:** aceito · **Data:** 2026-08-12

## Contexto

O motor conclui coisas a partir do estado de uma partida num instante. Duas
perguntas aparecem sempre depois:

- por que ele disse aquilo naquele momento?
- o que a versão nova diria sobre o mesmo momento?

As duas exigem que o estado daquele momento ainda exista.

## Decisão

`StateSnapshot` e `IntelligenceSnapshot` são **imutáveis**. Correção é
snapshot novo com `state_version` maior; o anterior permanece.

`state_version` é monotônica por partida e é ela que ordena — não o carimbo de
tempo, que empata quando um provedor corrige um evento.

O `IntelligenceSnapshot` guarda o `state_version` **de entrada**, amarrando a
conclusão ao estado exato que a gerou.

## Consequências

**Ganhamos:** auditoria real, reprocessamento com engine nova sobre o passado,
e regressão comparável entre versões.

**Pagamos:** volume — daí o ClickHouse. E a disciplina de nunca "só corrigir"
uma linha.

## Alternativas consideradas

**Atualizar no lugar.** Rejeitado: apaga a evidência que justifica a conclusão
anterior, e sem ela nenhuma auditoria é possível.

**Guardar só o último.** Rejeitado: torna impossível responder "o que o motor
sabia no minuto 63" sem recalcular a partida inteira.

