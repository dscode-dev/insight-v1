# ADR-0027 — PostgreSQL é a verdade; o Parquet é uma representação

**Status:** aceito · **Data:** 2026-08-18 · **Confirmado para eventos:** 2026-08-19 (PR-04.4.2)

## Contexto

O corpus histórico tem dois consumidores com necessidades opostas.

**O motor** consulta por chave e por partição: «os fatos desta partida», «a
linhagem deste resultado», «as versões que contêm esta partida». São leituras
seletivas, transacionais, com junções — e o PostgreSQL é feito para isso.

**A leitura analítica** varre: «todos os placares da Premier League desde 2015»,
«a distribuição de odds por casa». Ler dez mil partidas linha a linha pelo
PostgreSQL para calcular uma média é usar a ferramenta errada, e o custo
aparece justamente quando o corpus cresce.

Três desenhos ingênuos:

**Só PostgreSQL.** A varredura analítica compete por conexão com o plano de
consulta, e o sintoma é latência de leitura sem causa aparente. Um `COPY` para
CSV por consulta reintroduz o problema de schema que o Parquet resolve.

**Só Parquet.** Sem transação, sem constraint, sem chave estrangeira. A
integridade referencial que impede um resultado órfão passaria a ser
convenção — e convenção não recusa escrita.

**Parquet como fonte da verdade, PostgreSQL como índice.** O pior dos dois: uma
correção de fato exigiria reescrever arquivos imutáveis, e a única forma
honesta de fazer isso é publicar versão nova — o que transforma toda correção
numa republicação completa.

## Decisão

**Os fatos canônicos moram no PostgreSQL. O Parquet é uma CÓPIA COLUNAR da
versão publicada, e ela é opcional.**

```
PostgreSQL   os fatos, a pertinência, o manifesto, a linhagem.
             transacional, com constraint. É a VERDADE.

Parquet      `corpus/<dataset>/v<versão>/family=<F>/competition=<C>/season=<S>/
             part-NNNNN.parquet`
             colunar, particionado, comprimido. É uma REPRESENTAÇÃO.
```

**Apagar o bucket não perde nada.** Regerar é reexecutar a materialização sobre
a mesma versão — que é imutável (ADR-0026) —, e o conteúdo resultante é o
mesmo. É por isso que o materializador é um port OPCIONAL: uma versão publicada
sem Parquet é `READY` do mesmo jeito, porque ela tem membership, manifesto e
impressão, que é o que `READY` significa. Torná-lo obrigatório amarraria a
publicação a um object store disponível, e a indisponibilidade dele viraria «o
corpus não existe» quando o corpus existe inteiro no banco.

**O SCHEMA É DECLARADO, NUNCA INFERIDO.** Inferir do primeiro lote faz uma
coluna inteiramente nula virar `null` num arquivo e `double` noutro, e a leitura
do conjunto quebra em cima de dado que estava perfeitamente certo. Os três
schemas são constantes do módulo, e uma coluna nova é um diff.

**AUSENTE É `NULL`, E `NULL` NÃO É ZERO.** Zero é um placar; ausente é a falta
de um. Um `0` no lugar de um `NULL` produz média errada que soma perfeitamente
— o pior tipo de defeito, porque nada denuncia. Vale para gols de prorrogação,
número de camisa e instante de observação de odds.

**ODDS SÃO `decimal128(10,4)`, exatamente o `numeric(10,4)` da coluna.**
`float(Decimal("2.05"))` não é 2.05, e o erro aparece onde dói: duas casas
cotando o mesmo preço e a comparação dizendo que não.

**A partição é `family=/competition=/season=`, Hive-style.** É o predicado que
a leitura analítica poda — sem ela, responder sobre uma temporada lê o corpus
inteiro. E a VERSÃO está no caminho: uma composição nova é uma versão nova, e
uma versão nova é outro prefixo, então reescrever sob a mesma chave nunca
acontece.

**Um pedaço por LOTE, e não um arquivo por partição.** `part-00000`,
`part-00001`… Acumular uma partição inteira até o fim da varredura seria o
corpus todo em memória quando ele cabe numa competição só; escrever por lote
mantém o pico no tamanho do lote, e um diretório com vários `part-*.parquet` é
exatamente o que os leitores de Parquet esperam.

**Uma partição vazia não vira arquivo vazio.** Um Parquet de zero linha é
indistinguível, na leitura, de uma partição que ninguém escreveu — e as duas
exigem ações diferentes de quem investiga um buraco na cobertura.

**`historical_canonical_objects` grava o que foi escrito**, com SHA-256,
tamanho e contagem de linhas. Sem essa tabela, «o corpus 1.0 escreveu quais
arquivos» exigiria listar o bucket, e uma versão que falhou no meio deixaria
órfãos que ninguém encontra.

**O `manifest.json` acompanha os dados.** Quem copia o diretório do corpus para
outro lugar precisa levar junto a descrição do que copiou — senão o conteúdo
chega sem escopo, sem contagem e sem licença.

## Consequências

**Ganhamos:** leitura analítica em massa sem tocar no plano transacional, e um
artefato que viaja — o diretório do corpus é auto-descrito e legível por
qualquer ferramenta que fale Parquet.

**Pagamos:** duas representações do mesmo conteúdo, que podem divergir se
alguém escrever no bucket por fora. A defesa é a imutabilidade da versão (a
chave contém a versão) mais o SHA-256 por objeto no manifesto — divergência é
detectável, ainda que não impedida.

**Aceitamos:** o Parquet desta fase não cobre `EVENT`, `PLAYER`, `SPATIAL` nem
`TRACKING`. Não é esquecimento: o contrato fundido da V1 não carrega esses
dados, e escrever arquivos vazios para eles afirmaria uma cobertura que não
existe. O manifesto os reporta como `NOT_DECLARED`, que é a verdade.

**Emenda de 2026-08-19 (PR-04.4.2): `EVENT` passou a ser coberto**, e a decisão
deste ADR vale para ele sem mudança nenhuma. O `events.parquet` é uma
representação colunar da tabela `canonical_match_events` recortada pela versão;
**o PostgreSQL continua sendo a verdade**, e apagar o bucket não perde nada —
regerar é recompor a mesma versão, que é imutável.

Duas coisas que a emenda deixa explícitas:

- **uma versão publicada SEM Parquet continua legítima.** A pertinência de
  evento mora no PostgreSQL, e é ela que o gate reconcilia. O arquivo é
  opcional aqui como era antes;
- **`SPATIAL` não ganhou arquivo próprio.** A coordenada é atributo do evento e
  viaja nas colunas dele; uma família espacial separada seria uma tabela de
  pontos sem o que eles descrevem.

`PLAYER` e `TRACKING` continuam fora, pelas razões originais.
