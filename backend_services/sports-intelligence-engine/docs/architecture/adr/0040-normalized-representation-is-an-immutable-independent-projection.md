# ADR-0040 — A representação normalizada é uma projeção independente e imutável

**Status:** aceito · **Data:** 2026-08-25

## Contexto

Com o ajuste pronto, falta decidir **onde** os números normalizados moram e
**que identidade** eles têm.

A saída mais curta é acrescentar colunas ao dataset cru: ao lado de
`f_xg_home_5m` grava-se `n_xg_home_5m`, e pronto. Ela é errada por três motivos
que só aparecem depois.

**O dataset cru passaria a mudar de identidade quando o AJUSTE mudasse.** O cru
é uma função de `(versão do corpus, políticas de extração)`; ele não tem nada a
ver com escala. Refinar o plano obrigaria a reescrever 95 milhões de números que
não mudaram.

**Um mesmo cru alimenta N representações.** Reajustar sobre uma referência
estendida, ou refinar a classificação de um eixo, produz uma representação nova
sobre exatamente as mesmas linhas cruas. Com colunas no mesmo arquivo, as duas
não coexistem.

**A comparabilidade deixaria de ser afirmável.** Duas linhas normalizadas só são
comparáveis número a número se **quatro** coisas coincidirem: o espaço de
features, o plano, o conjunto de artefatos e a codificação de saída. Comparar
uma distância calculada sob os artefatos A com outra sob A' é comparar
centímetros com polegadas: os dois números existem, os dois são plausíveis, e a
comparação é falsa.

Há ainda uma decisão numérica a tomar, e ela é fácil de deixar implícita. O
dataset cru declara `float64` como o valor oficial da feature (ADR-0037); o
ajuste é exato, em `Decimal` (ADR-0035). Alguém tem de dizer como se atravessa.

## Decisão

**A representação normalizada é uma PROJEÇÃO INDEPENDENTE, com identidade
própria, materializada em Parquet sob prefixo próprio, e imutável a partir de
`READY`.**

```
HistoricalFeatureDatasetVersion              os números como foram extraídos
    ├── NormalizedFeatureDatasetVersion      (plano P, artefatos A)
    └── NormalizedFeatureDatasetVersion      (plano P, artefatos A')
```

**A identidade da representação amarra as quatro decisões.**

```
NormalizedFeatureRepresentationSpec
    space_fingerprint          quais eixos, em que ordem
    plan_fingerprint           qual eixo recebe qual transformação
    artifact_set_fingerprint   quais medianas e IQRs
    numeric_bridge             como o `Decimal` escalado virou `float64`
```

O **id** do conjunto de artefatos NÃO entra na impressão, e a impressão dele
entra: dois ajustes independentes que chegam aos mesmos artefatos sobre a mesma
referência produzem a mesma representação com ids diferentes.

**A travessia numérica é declarada e versionada.**

```
Dataset cru          float64    IEEE754_FLOAT64_EXACT_TO_DECIMAL_V1
    ↓ entrada
Ajuste               Decimal    mediana e IQR exatos (ADR-0035)
    ↓ saída
Dataset normalizado  float64    NORMALIZED_FLOAT64_V1
```

A entrada é `Decimal.from_float`, e não `Decimal(str(x))`. O dataset cru já
declarou `float64` como o valor oficial: o ajuste tem de normalizar **o número
que de fato está no arquivo**, e não uma aproximação decimal mais bonita dele.
As duas escolhas são defensáveis, e é por isso que a escolha é um contrato — duas
execuções que escolhessem diferente produziriam medianas diferentes sobre os
mesmos dados, e nada no artefato diria qual foi.

A saída volta a `float64`, e isso É uma perda declarada. Não se chama isso de
«Decimal sem perda»: a escala é calculada em `Decimal` e gravada em `float64`.

**O contrato é 1:1, e é conferido em três lugares.** Para toda linha crua existe
exatamente uma normalizada — nem quando o artefato é degenerado, nem quando a
amostra foi insuficiente, nem quando o valor de origem não existia. A ausência é
sempre LOCAL à célula. O `CHECK` da migration recusa publicar com contagem
diferente; o `__post_init__` do domínio recusa construir o objeto; a validação
confere contra o **rodapé do Parquet cru**, e não contra a coluna do banco.

**O arquivo tem três colunas por eixo.**

```
n_<chave>   o valor normalizado, float64, nulável
m_<chave>   por que a NORMALIZAÇÃO não produziu número
s_<chave>   por que o valor CRU não existia
```

A terceira é a que quase não se escreve e é a que decide o que fazer. Sem ela,
«não havia valor» e «havia valor e não havia escala» chegam ao leitor como o
mesmo `null`: o primeiro manda procurar um provedor de dados, o segundo manda
aceitar que aquele mercado não tem dispersão naquela competição.

**Todas as colunas de valor são `float64`, inclusive as dos eixos
`PASS_THROUGH`.** No cru uma contagem é `int64`; aqui ela é `float64` mesmo
passando direto, porque a coluna precisa ter UM tipo e ele não pode depender do
resultado do ajuste. O valor continua exato: `float64` representa todo `int64`
de magnitude de contagem de futebol sem perder um dígito, e o caminho do
`PASS_THROUGH` **não atravessa `Decimal`** — o contrato ali é bit a bit.

## Consequências

**Três impressões de conteúdo, e não uma.**

```
normalized_content_fingerprint             tudo
normalized_reference_content_fingerprint   só REFERÊNCIA
normalized_evaluation_content_fingerprint  só AVALIAÇÃO
```

Acrescentar uma partida à avaliação muda a primeira e a terceira, e **não pode
mudar a segunda**. Sem a do meio sobraria a global, que muda — e «a base de
comparação não mudou» viraria opinião.

**A linha aponta para a crua pelo DIGESTO, e não pela posição.** Provar a
correspondência 1:1 por posição exigiria que os dois datasets tivessem a mesma
ordem de arquivo, e a ordem de arquivo é decisão de execução.

**A linhagem do artefato é por LINHA, e não por célula.** Gravar 105 impressões
de artefato em cada uma das 91 mil linhas multiplicaria o arquivo para repetir
91 mil vezes o mesmo mapa. A linha carrega a impressão do PACOTE da competição;
o manifesto abre o pacote com o mapa `(competição, eixo) → artefato`.

**O prefixo é `normalized/` e não `features/`.** Escrever sob o prefixo do cru
faria um leitor que apontasse para a versão errada ler as duas representações
como se fossem uma.

**A escala é `numeric` no banco.** A mediana e o IQR são o insumo de toda
transformação; `double precision` faria a escala de uma competição depender do
arredondamento do driver, e o adaptador RECUSA um `float` vindo do banco em vez
de convertê-lo.

**O custo é um segundo dataset no bucket.** Ele é aceito: reconstruir é
determinístico, e o alternativo — colunas no mesmo arquivo — troca espaço por
identidade, que é a coisa que não se recupera.

## Alternativas descartadas

**Colunas normalizadas no dataset cru.** Descrito no contexto: o cru muda de
identidade por algo que não é dele, e duas representações não coexistem.

**Normalizar na leitura, sem materializar.** Toda consulta pagaria a
transformação, e a escala usada dependeria de quando a consulta rodou — o que é
o oposto de uma base de comparação.

**Guardar as linhas normalizadas no PostgreSQL.** Mesmo argumento do ADR-0037,
com o mesmo número: 95 milhões de valores numa forma que é sempre colunar e
sempre em massa.

**Uma coluna de máscara só.** Colapsa as duas famílias de ausência exatamente
onde a distinção decide entre consertar a coleta e aceitar a liga.
