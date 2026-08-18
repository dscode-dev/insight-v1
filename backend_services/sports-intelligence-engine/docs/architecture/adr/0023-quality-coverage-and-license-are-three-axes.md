# ADR-0023 — Qualidade, cobertura e licença são três eixos, e uma execução os grava

**Status:** aceito · **Data:** 2026-08-17

## Contexto

A pergunta operacional que precede o corpus histórico é «este dado pode
entrar?». A resposta natural é um número — `quality = 0.87` — e ele erra de
três maneiras diferentes ao mesmo tempo.

**Ele confunde confiança com riqueza.** Uma fonte pública de futebol costuma
ter placar impecável, identidade limpa e nenhuma escalação. Um score único a
classifica como «média», e o motor passa a rejeitar exatamente as fontes que
mais deveria querer.

**Ele confunde qualidade técnica com direito de uso.** Uma base
`RESEARCH_ONLY` pode ser tecnicamente perfeita. Tratá-la como «ruim» faz
alguém «corrigir» o número; tratar qualidade como licença faz um corpus
comercial receber dado que ninguém tinha direito de publicar. Os dois erros
são caros e o segundo é jurídico.

**Ele esconde o elo fraco.** Média de cinco eixos em 0,95 e um em 0,4 dá 0,84,
e o eixo em 0,4 é sempre o que contamina o futuro.

O PR-04.1 separou os três no domínio. O que faltava era o que torna a
separação utilizável meses depois: sobre quais entradas o veredito foi
produzido, sob qual versão de política, quando, por quem, e com quantas
partidas em cada desfecho.

## Decisão

**Três objetos, três perguntas, e nenhum substitui o outro:**

```
QualityVector    posso confiar no que está aqui?      seis eixos, elo mais fraco
CoverageReport   o que está aqui?                     NÃO reprova
UsageVerdict     tenho direito de usar, e para quê?   veredito PRÓPRIO por escopo
```

**A cobertura tem três estados e não um número.** `MEASURED` só existe quando
há denominador honesto; `AVAILABILITY_ONLY` quando há contagem e não há
denominador; `NOT_DECLARED` quando a fonte não trabalha com aquela família.
`expected_count` é `NULL` no banco nos dois últimos, e uma constraint impede
que `MEASURED` exista sem denominador — porque «0%» confunde «a fonte prometeu
e não veio nada» com «a fonte não promete isso», e as duas exigem ações
opostas.

**A licença é POR FAMÍLIA.** Com uma licença por registro, `RESEARCH_ONLY` em
qualquer campo condenaria o núcleo da partida. Com o mapa por família dá para
perguntar «e se as odds saírem?» — que é a pergunta do build comercial.

**Os RÓTULOS de identidade não contaminam o mapa de licenças.** Toda fonte
precisa trazer competição, temporada e times para que a resolução consiga casar
a linha. Mas o `Match` canônico não é construído a partir desses textos: ele
vem do registro canônico, com identidade provada no PR-03. Se a fonte restrita
desaparecesse, a mesma partida continuaria existindo com os mesmos ids.
Contá-los faria toda fonte de odds restringir o núcleo por ter dito «este jogo
é A x B».

Pela mesma razão, **desacordo de GRAFIA entre fontes não é conflito de dado**:
`Man City` e `Manchester City` já terminaram no mesmo `TeamId`, provado por
decisão com evidência, e absorver isso é literalmente o que a resolução existe
para fazer.

**A regra vale para RÓTULO e não para todo papel de identidade** — a distinção
foi afiada no PR-04.2.1, e ela é o assunto do ADR-0025. `KICKOFF` é fato: duas
fontes com 20:00 e 23:00 discordam de verdade, e quem o afirma é procedência
factual do núcleo. Generalizar «papel de identidade nunca conta» teria aberto a
porta oposta — uma fonte restrita virando origem impune de um fato canônico.

**A avaliação é uma EXECUÇÃO, não um relatório.** `QualityRun` registra as
fusões consumidas com a impressão da saída de cada uma, a versão da política,
a impressão da política inteira, o instante, o ator de serviço e as contagens
por desfecho. Uma execução concluída é **imutável**: política nova produz
execução nova, e a anterior fica exatamente como estava.

**A impressão da política acompanha a versão.** A versão pega a mudança
declarada; a impressão pega a que ninguém declarou — alguém edita um piso e
esquece de subir o número, e as duas execuções ficam rotuladas `1.0` decidindo
diferente.

**A severidade é gravada junto do problema.** Ela é da política, e o
`QualityIssue` deliberadamente não a carrega; sem a coluna, «quantos
bloqueantes esta execução encontrou» exigiria reaplicar sobre cada linha uma
política que pode ter mudado desde então.

## Consequências

**Ganhamos:** «por que esta partida não entrou no corpus» tem resposta em uma
consulta, com o número da política e o problema que a causou. E reavaliar sob
política nova é comparável — as duas execuções coexistem e a diferença entre
elas é o que mostra o que a política nova passou a enxergar.

**Pagamos:** cinco tabelas por avaliação em vez de uma coluna, e um objeto de
domínio a mais (`MatchQualityRecord`) entre o veredito e a execução. A
alternativa era o veredito carregar identificador de execução — e aí o mesmo
veredito reavaliado precisaria de outro objeto para dizer a mesma coisa.

**Aceitamos:** a avaliação é por PARTIDA e não por dataset. Um corpus 99% bom
e 1% corrompido avaliado no agregado promove o 1% junto, e o 1% é exatamente o
que vira fato histórico errado que ninguém detecta — porque tudo continua
somando.
