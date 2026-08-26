# ADR-0037 — As linhas de feature moram no object store, e o PostgreSQL guarda ponteiros

**Status:** aceito · **Data:** 2026-08-24

## Contexto

O ADR-0027 estabeleceu, para o corpus canônico, que o PostgreSQL é a fonte da
verdade e o Parquet é uma cópia colunar: apagar o bucket não perde fato nenhum,
porque regerar é reexecutar sobre uma versão imutável.

O dataset de features parece o mesmo problema e não é. Ele tem uma ordem de
grandeza diferente e uma natureza diferente.

**A grandeza.** Dez mil partidas em noventa e um cortes são 910 mil linhas de
105 valores cada: **95 milhões de números**. E ele cresce por multiplicação —
mais partidas, mais cortes, mais dimensões — enquanto o corpus cresce só por
partidas.

**A natureza.** Nenhuma pergunta que se faz a este dado é «me dê a linha 42».
Todas são colunares e em massa: «a distribuição de `shots_home_5m` na Premier
League», «os mil vizinhos mais próximos deste estado», «a mediana desta feature
nesta competição até este corte».

As duas formas óbvias de guardá-lo no PostgreSQL falham por motivos opostos.
Uma tabela **larga** teria 210 colunas, e nenhum índice ajuda uma varredura
colunar sobre elas. Uma tabela **estreita** (`linha, chave, valor`) teria 95
milhões de linhas para responder a mesma pergunta, com o custo de junção
multiplicado por cento e cinco.

Há ainda uma diferença que muda a conta do risco: o dataset de features é
**derivado e determinístico**. O corpus canônico é a interpretação de arquivos
brutos que podem sumir; o dataset é uma função pura de `(versão do corpus,
políticas)`, e as duas são imutáveis e impressas.

## Decisão

**As linhas de feature moram no object store, em Parquet, e são a única cópia
delas. O PostgreSQL guarda identidade, políticas, contagens, rastro de execução
e ponteiros.**

```
PostgreSQL   quem é este dataset, sob quais regras, quantas linhas, onde estão
Parquet      as linhas
```

Cinco consequências:

**1. O port de materialização NÃO é opcional.** No corpus ele é: uma versão
publicada sem Parquet continua sendo `READY`, porque tem membership, manifesto e
impressão. Aqui, uma versão sem materialização é uma versão **sem conteúdo**, e
o caso de uso recusa publicá-la.

**2. Nenhuma consulta do adaptador devolve um valor de feature**, e a ausência é
o desenho: replicá-los criaria duas verdades sobre o mesmo número, e elas
divergiriam no primeiro reprocessamento parcial.

**3. A perda do bucket custa uma reconstrução, e não um fato.** É isso que torna
a troca aceitável, e é uma propriedade que precisa ser mantida: a versão do
corpus é imutável, as políticas são impressas, o cálculo é puro. Reconstruir
produz o **mesmo** `raw_content_fingerprint` — e há teste que prova isso.

**4. O digesto de cada linha é reconstrutível lendo o Parquet e mais nada.** Se
ele dependesse do `FeatureSnapshot`, conferir um arquivo exigiria reconstruir o
estado da partida, e a conferência deixaria de ser uma leitura para virar um
build. É essa propriedade que torna a validação executável em produção.

**5. A reconciliação é obrigatória, e é o preço.** Com o conteúdo fora do banco,
«o manifesto, o registro e o bucket concordam?» deixa de ser uma consequência da
transação e vira uma **fase com veredito**. Ela existe, ela pode reprovar, e ela
derruba a versão para `FAILED`.

**A partição é `split=/competition=/season=`, nessa ordem**, porque a metade é o
predicado mais grosso e o mais usado: «a população de referência» tem de podar a
avaliação inteira sem abrir arquivo nenhum.

**Duas colunas por feature**: o valor (nulável, tipado pelo catálogo) e a
disponibilidade (texto, nunca nula). `NULL` sozinho diz «não há número» e não diz
por quê, e sete causas diferentes exigem sete ações diferentes.

## Consequências

**Positivas.** O formato casa com a pergunta: leitura colunar em massa, com poda
por partição e compressão que aproveita a repetição das colunas de
disponibilidade. O banco continua pequeno e rápido para o que ele é bom —
identidade, políticas, travessia de linhagem. E o dataset é portátil: copiar o
diretório leva o conteúdo **e** o manifesto que o descreve.

**Negativas, e assumidas.** O dataset depende do object store estar de pé; uma
indisponibilidade dele é uma indisponibilidade do dataset, e não uma degradação.
Não há transação abrangendo banco e bucket, então uma construção interrompida
deixa objetos órfãos — encontráveis pelo prefixo da versão, e é para isso que
`partition_prefix` existe. Não há `UPDATE` de uma linha: corrigir uma partida
exige uma versão nova. E a leitura das colunas de tempo exige a base de fusos do
sistema — daí `tzdata` entrar como dependência declarada, e não como um detalhe
de ambiente.

**O que esta decisão NÃO fecha.** Um índice vetorial (pgvector) sobre um
subconjunto das dimensões continua possível e é assunto de outro PR — ele seria
uma **projeção** deste dataset, e não uma segunda cópia dele. Um catálogo
externo (Iceberg, Delta) também continua possível: o que este ADR fixa é onde as
linhas moram, e não qual metadado as descreve.

## Alternativas consideradas

**Tabela larga no PostgreSQL** (uma coluna por feature). Rejeitada: 210 colunas
que nenhum índice serve, e cada feature nova é um `ALTER TABLE` sobre dezenas de
milhões de linhas.

**Tabela estreita** (`version_id, match_id, grid_index, chave, valor`).
Rejeitada: 95 milhões de linhas para dez mil partidas, e toda pergunta colunar
vira uma agregação sobre elas.

**`jsonb` por linha.** Rejeitada: nenhuma poda colunar, e o valor deixa de ser
tipado — `2` e `2.0` passam a ser distinguíveis ou não conforme o serializador.

**Parquet como cópia, com o PostgreSQL mantendo as linhas** (o desenho do
ADR-0027). Rejeitada: mantém o custo das duas alternativas acima **e**
acrescenta o risco de as duas cópias divergirem.

**ClickHouse.** Rejeitada nesta fase, e não por mérito: ele responde bem à
pergunta colunar. O que ele acrescenta é um segundo sistema com estado, com
schema próprio e ciclo de vida próprio, para um dado que já é imutável e
versionado — e imutável e versionado é exatamente o caso em que o arquivo basta.
O dia em que a latência de leitura for o gargalo medido, ele volta à mesa como
**índice**, e não como fonte.

**CSV ou JSONL.** Rejeitada: sem tipo declarado, sem poda, e uma coluna
integralmente nula vira ambiguidade na leitura.

## Referências

- ADR-0027 — o Parquet do corpus é representação, e não fonte
- ADR-0009 — ausente nunca vira zero
- ADR-0026 — versões do dataset histórico são imutáveis
- ADR-0036 — a grade e a divisão que definem o conteúdo
- `docs/features/HISTORICAL_FEATURE_DATASET_V1.md`
- `migrations/0012_historical_feature_dataset.sql`
