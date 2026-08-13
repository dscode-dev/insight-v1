# ADR-0011 — Identidade canônica futebolística

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Três provedores descrevendo a mesma partida a chamam de três coisas. O mesmo
clube aparece como `Manchester City`, `Man City`, `Manchester City FC` e `MCI`.
O mesmo jogador tem grafias com e sem acento, com e sem sobrenome.

A tentação é derivar identidade do nome — `uuid5("man city")` — porque é
barato e determinístico. O custo é que três grafias viram três clubes, cada um
com um terço do histórico, e **o número continua fechando**: a tabela soma, a
média fecha, nada falha.

Há também o caso oposto, igualmente caro: dois jogadores homônimos fundidos
num só, com carreiras somadas.

## Decisão

**Identidade de entidade futebolística é opaca e sorteada.** `Team.register` e
`Player.register` chamam `uuid4`; **não existe** `Team.derive`.

**Exceção declarada: o catálogo de competições.** A identidade de `Competition`
é derivada do **código** (`PREMIER_LEAGUE`), não do nome. O código é estável
por construção — tem uma grafia só, e mudá-lo é editar um arquivo. O nome muda
com patrocinador e tradução.

`Season` também deriva, de (competição, label), para que reingerir a mesma
temporada não crie uma segunda.

**`ProviderRef` continua inconversível para `EntityId`.** Não há
`.to_entity_id()`, e a ausência é o contrato: a passagem entre os dois é
resolução de identidade — etapa com regras próprias, capaz de falhar e de pedir
revisão humana.

**`MatchIdentityCandidate` descreve o problema sem resolvê-lo.** Ele lista os
elementos que futuramente identificam a mesma partida entre provedores e não
tem `matches()`, `merge_with()` nem `similarity_to()`. Merge automático por
semelhança é como duas partidas viram uma.

## Consequências

**Ganhamos:** impossível fundir clubes por grafia ou dividir um clube em três.
Renomear um clube preserva o histórico dele por construção.

**Pagamos:** ingerir uma fonte nova exige resolução de identidade explícita —
não dá para "só derivar do nome e seguir". É trabalho real, e é o trabalho
certo.

## Alternativas consideradas

**Derivar tudo de chave natural.** Rejeitado: funciona para competição, cujo
código é estável, e falha para clube e jogador, cujos nomes não são.

**Aceitar o id do provedor como identidade.** Rejeitado: amarra o domínio ao
primeiro provedor, e o segundo passa a ser traduzido para o vocabulário do
primeiro.

