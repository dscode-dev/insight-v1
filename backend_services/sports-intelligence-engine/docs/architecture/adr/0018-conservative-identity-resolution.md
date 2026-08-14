# ADR-0018 — Resolução conservadora de identidade

**Status:** aceito · **Data:** 2026-08-13

## Contexto

O motor precisa decidir que `Man City` numa planilha e `Manchester City FC`
noutra são o mesmo clube. A tentação é maximizar merges: quanto mais linhas se
juntam, mais completo o histórico parece.

O problema é a assimetria dos erros.

Um registro **não resolvido** é visível: ele aparece na contagem da execução,
entra numa fila, e alguém o conserta. Custa trabalho.

Um **merge errado** não é visível. Dois `João Silva` viram um jogador com duas
carreiras somadas; três grafias de um clube viram um clube com o histórico de
três. Nada falha — a tabela soma, a média fecha, o vetor tem a dimensão certa.
E a contaminação se propaga: influência de jogador, força de elenco, estados
históricos, grafo tático. Quando alguém desconfia, meses depois, não há como
saber quais conclusões dependiam do merge errado.

O motor anterior teve exatamente isso: três colisões de identidade de clube
entre continentes, 591 partidas atribuídas ao clube errado, descobertas por
acaso — uma distância de viagem impossível de 11.524 km «dentro da Argentina».

## Decisão

```
Custo(falso merge)  >  Custo(não resolvido)
```

**Na dúvida, `REVIEW_REQUIRED`.** E «dúvida» é definida por três guardas, não
por um limiar só:

1. **evidência obrigatória por sujeito** — temporada exige competição;
   partida exige competição e temporada;
2. **corroboração mínima** — o nome é UMA evidência. Jogador exige três;
3. **margem mínima** — dois candidatos a 0,91 e 0,90 viram `AMBIGUOUS`, porque
   0,01 não é informação, é ruído da régua.

A ordem das guardas importa: elas vêm ANTES do limiar de confiança, para que
um score alto obtido por uma evidência só nunca ultrapasse a exigência de
corroboração. É exatamente o caso do homônimo — o nome bate perfeitamente, e é
por isso que não se pode resolver.

**Similaridade nunca decide sozinha.** O peso do nome é alto o bastante para
levar à revisão e baixo o bastante para não resolver.

**Fora do catálogo é `REJECTED`, não `UNRESOLVED`.** A distinção é
operacional: `UNRESOLVED` diz «talvez ache depois» e mantém o caso vivo;
`REJECTED` diz «decidi que isto não é uma das cinco». Sem ela, a fila cresceria
com casos que nunca resolvem.

## Consequências

**Ganhamos:** a taxa de merges errados tende a zero, e os casos duvidosos
ficam contáveis. A meta não é maximizar merges — é maximizar a confiabilidade
dos merges permitidos.

**Pagamos:** trabalho humano. Uma fonte nova produz fila de revisão até que os
aliases acumulem. É trabalho real, e é o trabalho certo: cada decisão humana
grava um alias, e a próxima execução resolve sozinha.

## Alternativas consideradas

**Limiar único, alto, para tudo.** Rejeitado: competição tem catálogo fechado
de cinco e casa exato quase sempre; jogador tem homônimos. Um limiar que serve
para os dois é frouxo para um e apertado para o outro.

**Resolver e marcar com confiança baixa, deixando o consumidor decidir.**
Rejeitado: na prática ninguém filtra por confiança, e uma referência canônica
gravada é usada como se fosse verdade. É por isso que só `RESOLVED` produz
referência.

**Aprender os limiares a partir do corpus.** Rejeitado por ora: exigiria um
conjunto rotulado que não existe, e um limiar ajustado aos dados muda quando
os dados mudam — enquanto a pergunta «este clube é aquele» precisa ter a mesma
resposta amanhã.

