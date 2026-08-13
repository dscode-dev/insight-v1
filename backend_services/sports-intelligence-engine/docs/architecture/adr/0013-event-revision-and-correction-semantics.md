# ADR-0013 — Revisão e correção de eventos

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Provedores corrigem. Um gol atribuído ao camisa 9 vira do camisa 11 vinte
minutos depois. Um pênalti é anulado pelo VAR. Um cartão muda de amarelo para
vermelho.

Se a correção sobrescreve o evento, duas perguntas ficam sem resposta:

- «o que sabíamos no minuto 63?» — a base só tem a versão corrigida;
- «quando soubemos que mudou?» — não há registro de que mudou.

A primeira é o que torna o replay honesto. Se a correção chegou aos 85 e o
replay do minuto 63 usa a versão corrigida, **o replay está enxergando o
futuro** — a mesma classe de vazamento que o ADR-0007 trata para o índice
histórico, por outra porta.

## Decisão

`CanonicalMatchEvent` é **imutável**. Correção é evento **novo**:

```
revisão 1  GOAL  camisa 9   status=CORRECTED  supersedes=None
revisão 2  GOAL  camisa 11  status=ACTIVE     supersedes=rev1
```

`correct_to()` devolve **os dois** — o anterior marcado e a revisão nova —
porque quem chama precisa persistir ambos; uma assinatura que devolvesse só o
novo deixaria o anterior indistinguível de uma revisão válida.

**Três status, e `CORRECTED` ≠ `CANCELLED`:** o primeiro diz "existe versão
melhor deste fato"; o segundo diz "este fato não aconteceu". Um gol anulado
pelo VAR não é um gol corrigido.

**Evento cancelado não se corrige.** Ele não aconteceu; se voltou a valer, é
evento novo.

**Revisão > 1 exige `supersedes`.** Sem isso a cadeia quebra e "o que sabíamos
antes" deixa de ter resposta.

**A procedência da correção é a de quem corrigiu**, não a do original: quem
corrigiu e quando é justamente o que se quer saber depois.

`current_truth()` filtra as ativas e ordena explicitamente por (período,
minuto, acréscimo, sequência) — a ordem de chegada não serve, porque
provedores entregam fora de ordem.

## Consequências

**Ganhamos:** replay honesto, auditoria de correção, e a capacidade de medir
quanto uma fonte corrige — que é um sinal de qualidade dela.

**Pagamos:** volume. Cada correção é uma linha a mais, e toda consulta precisa
decidir se quer a verdade atual ou o que se sabia num instante. `current_truth`
torna a primeira barata; a segunda exige filtrar por carimbo.

## Alternativas consideradas

**Update no lugar, com log de auditoria separado.** Rejeitado: reconstruir o
estado passado exigiria reprocessar o log, e o log costuma ser guardado com
retenção menor que os dados.

**Versionar a partida inteira a cada correção.** Rejeitado: o custo é
proporcional ao tamanho da partida e não ao da correção, e um jogo tem
milhares de eventos.

