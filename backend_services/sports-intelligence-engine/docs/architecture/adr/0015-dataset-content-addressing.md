# ADR-0015 — Endereçamento por conteúdo e idempotência

**Status:** aceito · **Data:** 2026-08-13

## Contexto

Ingestão manual gera, na primeira semana de operação, três situações:

```
o operador reenvia o mesmo arquivo        (achou que falhou)
ele renomeia e reenvia                    E0.csv → premier_2019.csv
ele corrige o arquivo e mantém o nome     E0.csv, conteúdo outro
```

Com identidade baseada em nome, a primeira duplica, a segunda duplica, e a
terceira **sobrescreve em silêncio** — a pior das três, porque destrói a
evidência anterior sem deixar rastro.

E as duplicatas não falham: elas fazem cada jogo daquela temporada entrar duas
vezes no que vier depois. A tabela soma, a média fecha, nada dispara.

## Decisão

**O SHA-256 dos bytes recebidos é a identidade do conteúdo.**

```
DatasetId       uuid5(nome, versão)              registrar 2x → o mesmo
DatasetFileId   uuid5(dataset, versão, sha256)   reenviar 2x  → o mesmo
object_key      contém o sha256                  regravar     → mesmo lugar
```

**Dos bytes recebidos, e não do conteúdo lógico.** Um CSV com CRLF e o mesmo
CSV com LF são conteúdos lógicos idênticos e bytes diferentes, e este hash os
distingue. Normalizar antes de hashear seria afirmar que recebemos algo que
não recebemos — e a função desta camada é provar o que chegou.

**O hash NÃO é o `DatasetId`.** Um dataset é uma unidade lógica declarada pelo
operador, e continua sendo a mesma coisa quando um arquivo é acrescentado.
Amarrar sua identidade ao conteúdo faria cada correção criar outro dataset, e
o histórico de decisões sobre ele se perderia.

**Nem é identidade de linha.** Duas linhas idênticas em fontes diferentes
podem descrever a mesma partida ou duas partidas distintas, e decidir isso é
resolução de identidade — PR-03. Aqui o hash identifica BYTES, e só.

**A idempotência é imposta pelo banco.** `UNIQUE (dataset_id, sha256)` e
`ON CONFLICT DO NOTHING`. Lógica Python não protege contra dois processos
concorrentes: os dois consultam, os dois não encontram, os dois inserem.

**O nosso SHA-256 é a autoridade.** Quando o S3 devolve o próprio checksum,
ele é confrontado — e perde. O dele foi calculado sobre o que chegou ao
bucket; o nosso, sobre o que chegou ao motor.

**Duplicata física ≠ duplicata lógica.** O hash detecta a primeira. A segunda —
o mesmo jogo vindo de duas fontes — é indecidível aqui, e este PR não tenta.

## Consequências

**Ganhamos:** retry idempotente de graça, em todas as camadas. Reenviar não
duplica registro nem tráfego; o objeto já está na chave que aquele conteúdo
produz.

**Pagamos:** o hash exige ler todos os bytes antes de saber onde gravá-los, e
o stream só se lê uma vez. A saída é um buffer que transborda para disco —
custo de I/O em troca de pico de memória constante.

## Alternativas consideradas

**Chave por `dataset/nome-do-arquivo`.** Rejeitado: dois nomes iguais com
conteúdos diferentes disputam a mesma chave, e a segunda gravação apaga a
primeira.

**Chave com timestamp.** Rejeitado: o retry deixa de ser idempotente — cada
tentativa vira um objeto, e o custo de tráfego de um cliente instável não tem
teto.

**Confiar no ETag do S3.** Rejeitado: ele não é SHA-256 e muda com o esquema
de multipart, então o mesmo conteúdo pode ter ETags diferentes conforme o
tamanho do bloco.

