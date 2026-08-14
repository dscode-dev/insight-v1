# ADR-0017 — Consistência entre banco e object store

**Status:** aceito · **Data:** 2026-08-13

## Contexto

Um upload precisa gravar duas coisas: os bytes no object store e a linha no
PostgreSQL. **Não existe transação distribuída entre os dois.**

Qualquer desenho que finja o contrário produz, mais cedo ou mais tarde, um
destes estados:

```
linha no banco, bytes ausentes    →  o dataset «tem» um arquivo vazio
bytes no store, linha ausente     →  bytes órfãos, invisíveis ao registro
```

**O primeiro é o perigoso.** Um dataset com uma linha de arquivo sem bytes
passa por qualquer contagem — `len(files) == 3` — e chega a `STAGED` afirmando
que três arquivos foram preservados quando dois foram. O relatório fecha, o
manifesto lista os três, e a falha só aparece no PR-03, ao tentar ler o
terceiro.

O segundo é inofensivo: nenhuma consulta alcança bytes que não têm linha
apontando para eles.

## Decisão

**Protocolo de três fases, com um estado que diz que a janela está aberta.**

```
1.  lê o stream, calcula SHA-256 e tamanho      memória constante
2.  INSERE a linha em PENDING                   transacional
3.  grava os bytes no arquivo bruto             NÃO transacional
4.  CONFIRMA a linha para STORED                transacional
```

**A regra que faz o protocolo funcionar: um arquivo em `PENDING` não conta.**
Não entra em validação, não entra no manifesto, e não deixa o dataset sair de
`UPLOADING`. `Dataset.stored_files` — e nunca `Dataset.files` — é o que a
validação, o manifesto e as contagens usam.

**A ordem inversa foi rejeitada.** Gravar antes de registrar pareceria mais
simples e produziria bytes órfãos que nenhuma consulta enxerga. O órfão que
este desenho produz é o outro: uma linha visível, marcada, que a reconciliação
encontra.

**Convergência por reenvio.** Como a chave contém o hash, reenviar os mesmos
bytes escreve no mesmo lugar o mesmo conteúdo:

| Falha | O que fica | Como converge |
|---|---|---|
| entre 2 e 3 | linha `PENDING`, sem bytes | o reenvio retoma da fase 3 |
| entre 3 e 4 | bytes gravados, linha `PENDING` | o reenvio vê o objeto, não regrava, confirma |

**`ReconcilePendingUploads` fecha a janela sem depender de reenvio.** Para
cada `PENDING` antigo, pergunta ao arquivo bruto se os bytes chegaram:
confirma se sim, marca `FAILED` se não.

**Ela não apaga nada.** Uma linha que desaparece depois de falhar leva junto a
informação de que alguém tentou enviar aquele arquivo — e é esse rastro que
explica, depois, por que o dataset está incompleto. Bytes órfãos também não
são tocados: apagar objeto do arquivo bruto é a única operação que este PR
deliberadamente não oferece por caminho de código (ADR-0014).

**O `UnitOfWorkPort` cobre só o relacional, e o contrato diz isso.** O que ele
garante é que a transição de `VALIDATING` para `VALIDATED` e a gravação do
relatório que a justifica commitem juntas — sem isso, o dataset ficaria
validado sem relatório, e a próxima leitura procuraria o motivo do estado sem
encontrar nada.

## Consequências

**Ganhamos:** nenhum estado intermediário é invisível. Toda inconsistência
possível tem nome (`PENDING`), tem consulta (índice parcial em
`dataset_files`) e tem rotina que a resolve.

**Pagamos:** uma escrita a mais por upload e um estado a mais no arquivo. E a
reconciliação precisa de alguém que a chame — neste PR ela existe e é
chamável; nada a dispara periodicamente ainda. É dívida declarada.

## Alternativas consideradas

**Two-phase commit / transação XA.** Rejeitado: o S3 não participa, e
implementar um coordenador para dois recursos é mais complexidade do que a
janela que ele fecharia.

**Outbox transacional.** É o desenho certo quando o segundo recurso é um
barramento com consumidor. Aqui o segundo recurso é armazenamento de blobs, e
o efeito colateral não é «publicar uma mensagem» — é gravar gigabytes. A
outbox guardaria os bytes no banco para reenviá-los depois, que é exatamente o
que não se pode fazer.

**Gravar primeiro, registrar depois.** Rejeitado — ver acima: produz o órfão
que ninguém enxerga em vez do órfão que a reconciliação encontra.

