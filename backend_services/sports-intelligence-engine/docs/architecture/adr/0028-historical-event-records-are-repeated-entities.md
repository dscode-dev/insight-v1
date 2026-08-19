# ADR-0028 — Registro histórico de evento é entidade repetida, não campo escalar de partida

**Status:** aceito · **Data:** 2026-08-18 · **Estendido em:** 2026-08-19 (PR-04.4.2)

## Contexto

Todo o intake histórico do motor, do PR-02 ao PR-04.3, assume uma forma só:
**uma linha do arquivo é uma partida**. O `SourceMappingDefinition` traduz
coluna → `SemanticRole`, o leitor devolve um `DatasetRecord` por linha, a
resolução traduz os identificadores daquela linha e o construtor canônico
monta os fatos daquela partida. A forma é tão constante que ela deixou de ser
visível: nada no código dizia «uma linha é uma partida», porque não havia
outra possibilidade.

Eventos não cabem nessa forma. Um jogo tem entre 1.200 e 3.500 eventos, e
cada um tem tipo, minuto, período, praticante, desfecho e — quando a fonte dá
— coordenada. A pressão para encaixá-los na forma existente é grande e tem
uma expressão concreta:

```
EVENT_1_TYPE, EVENT_1_MINUTE, EVENT_1_PLAYER,
EVENT_2_TYPE, EVENT_2_MINUTE, EVENT_2_PLAYER,
...
EVENT_1200_TYPE, ...
```

**Isso funciona por exatamente uma tarde.** Depois:

- o número de colunas passa a depender do jogo mais movimentado já visto, e
  cada jogo mais movimentado que ele quebra o schema;
- consultar «todos os gols de cabeça de 2024» vira uma varredura de 3.600
  colunas por linha, porque não há índice possível sobre a posição do evento;
- corrigir o evento 47 exige reescrever a linha inteira da partida, e a
  correção perde o que ela corrigiu;
- a `SemanticRole` deixa de ser um catálogo fechado e passa a ser um gerador
  de nomes, o que remove a única garantia que ela dava.

O erro por trás disso não é de performance. É de modelagem: **eventos são
entidades com identidade própria, e um campo de partida não tem identidade.**

## Decisão

**O registro histórico de evento é uma ENTIDADE REPETIDA. Uma linha da fonte
é um evento, e o mapeamento declara qual é a forma que ele lê.**

Três consequências concretas, e cada uma é uma peça de código:

**1. `RecordKind` torna a forma explícita.** O `SourceMappingDefinition` passa
a declarar `MATCH_RECORD` ou `EVENT_RECORD`. Ele não é um detalhe de
performance: `assert_resolvable_as_matches()` — que exige nomes de mandante e
visitante — deixa de valer para um fluxo de eventos, e aplicá-la a um faria
uma fonte perfeitamente boa ser recusada por não declarar o que a partida
declara.

```
MATCH_RECORD   uma linha = uma partida    (PR-02 … PR-04.3)
EVENT_RECORD   uma linha = um evento      (a partir daqui)
```

**2. Os papéis de evento são um sub-catálogo fechado, com prefixo.** Vinte e
dois papéis `EVENT_*`, todos nomeados, nenhum gerado. `SemanticRole.is_event`
separa os dois mundos, e `EventContractReport` recusa o mapeamento que os
mistura — declarar `HOME_SCORE` num fluxo de eventos é declaração incoerente,
não um extra inofensivo.

**3. A referência à partida é uma CHAVE ESTRANGEIRA, não um contexto.** Cada
registro de evento carrega o `MATCH_PROVIDER_ID` da partida a que pertence, e
ele é resolvido pela mesma tradução do PR-03. O papel é **reaproveitado**, não
duplicado: é o mesmo identificador, do mesmo provedor, para a mesma partida —
criar um `EVENT_MATCH_REFERENCE` faria o operador escolher entre dois nomes
certos e o resolver aceitar só um.

**A cardinalidade é declarada, e não inferida.** `RecordKind.rows_per_match`
responde «uma» ou «muitas», e é isso que permite ao motor recusar cedo, com
mensagem, em vez de descobrir na décima milésima linha que a partida já tinha
sido construída.

## Consequências

**O que fica possível.** Um provedor de eventos entra pelo mesmo intake, com
o mesmo registro de dataset, a mesma resolução de identidade e a mesma
linhagem. Nenhuma via paralela: a diferença entre os dois mundos está no
`RecordKind` e nos papéis, não numa segunda pilha de ingestão.

**O que fica proibido.** Modelar evento como campo indexado de partida —
`EVENT_1_TYPE` e parentes. Não é uma preferência de estilo: o catálogo de
papéis é fechado e não tem como gerar esses nomes, então o desenho é recusado
pelo tipo, não pela revisão de código.

**O custo que isto cobra.** Um índice de revisão que atravessa lotes. Uma
correção pode referenciar qualquer evento anterior da mesma execução, e
resolver isso indo ao banco por linha seria o N+1 que o motor não aceita. O
índice guarda `chave de origem → (id, revisão)` e é O(chaves distintas na
execução) — medido em 263 B por registro, contra mais de 1 KB se ele
guardasse o evento canônico inteiro. É o preço de o tamanho do lote não mudar
o resultado.

**O que ainda não está decidido.** Como dois provedores descrevendo o mesmo
gol terminam no mesmo evento canônico. Este ADR não resolve isso, e a
canonicalização trata cada fonte isoladamente: `UncertainSameEvent` não vira
`ForceMerge`, e a ausência de resolução cross-provider é declarada, não
contornada. **O PR-04.4.2 manteve essa fronteira na publicação**: publicar não
reconcilia, e um teste de arquitetura recusa o import que abriria a porta.

## Extensão — o registro repetido chega ao corpus (PR-04.4.2)

O ADR original parava no registro canônico. A decisão de forma se estende à
publicação, e ela é a mesma:

**A pertinência de evento também é uma ENTIDADE REPETIDA.** Uma linha por
`(versão, evento)` em `historical_canonical_event_members` — e não um array de
ids dentro da linha da partida, nem um contador. Pelas mesmas razões: um array
não tem índice para «este evento está em quais corpus?», e um contador não
responde «QUAIS eventos».

**Uma linha do `events.parquet` é um evento.** O arquivo tem a mesma
granularidade da tabela; a partição continua sendo `competition=/season=`,
porque é o predicado que a leitura analítica poda. Não há `event_1_type` no
Parquet pelo mesmo motivo pelo qual não há no catálogo de papéis.

**O que a extensão acrescentou como decisão nova:** a pertinência é DECLARADA
pela versão (`VersionInputs.event_build_run_ids`), e nunca derivada de «a
partida está no corpus». Derivar faria uma versão publicada mudar de conteúdo
quando o registro global crescesse — que é exatamente o que versionar existe
para impedir.

## Alternativas consideradas

**Eventos como JSON dentro da linha da partida.** Uma coluna `events` com um
array de objetos. Resolve o problema do schema e cria outro maior: o conteúdo
do JSON não passa por `SemanticRole` nenhuma, então o mapeamento semântico —
que é o mecanismo pelo qual o motor sabe o que uma coluna significa — para de
valer exatamente onde o dado fica mais rico. Correção e revisão voltam a
exigir reescrita da linha da partida.

**Uma segunda pilha de ingestão só para eventos.** Leitor próprio, registro
próprio, resolução própria. Duplicaria a identidade — e duas resoluções sobre
os mesmos times divergiriam, o que é pior que não ter a segunda.

**Inferir a forma pelo conteúdo do arquivo.** «Se tem coluna de minuto, é
evento». Uma heurística sobre o dado do cliente decidindo a semântica do
pipeline: quando ela errar, o erro aparece como partida construída errada, sem
nada no sistema afirmando qual forma foi assumida.
