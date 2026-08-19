# ADR-0031 — O estado histórico da partida é RECONSTRUÍDO, e nunca armazenado

**Status:** aceito · **Data:** 2026-08-19

## Contexto

O motor precisa responder «como esta partida estava aos 63 minutos» para
dezenas de milhares de partidas e para vários cortes por partida. A resposta
alimenta tudo o que vem depois: features, vetores, comparação com jogo ao vivo.

Reconstruir esse estado a partir dos eventos publicados custa tempo. A
tentação óbvia — e ela apareceu já no desenho — é gravar o resultado: uma
tabela `historical_match_states` com placar, elenco em campo e cartões por
corte, preenchida uma vez e lida barato para sempre.

**Por que a tentação é forte.** O estado parece um fato consolidado. A partida
acabou; o que aconteceu aos 63 minutos não vai mudar. Gravar um fato imutável
é a coisa mais natural do mundo, e o ganho de leitura é real.

**Por que ela está errada, e o erro é silencioso.** O estado NÃO é função só da
partida. Ele é função de quatro coisas:

```
HistoricalMatchState = f(corpus publicado, as-of, política temporal, política de disponibilidade)
```

O corpus muda: uma versão nova republica a mesma partida com um evento
corrigido, com uma família a mais, ou com um provedor excluído por licença. A
política temporal muda: `AS_KNOWN` e `CANONICAL_FINAL` produzem estados
diferentes para o mesmo minuto, e a política de disponibilidade decide se uma
cotação sem carimbo entra ou não.

Uma linha gravada não carrega nenhuma dessas dependências de forma acionável.
Ela carrega um placar. E no dia em que o corpus for republicado, essa linha
continuará ali — descrevendo um passado que não existe mais, e sem nada que
denuncie. O consumidor leria `1-1` de um corpus que hoje diz `1-0`, e o
treinamento aprenderia sobre um mundo que ninguém pode reproduzir.

**A alternativa «grave com a impressão junto»** só empurra o problema: agora é
preciso decidir invalidação, expiração, republicação e reprocessamento em
massa. São quatro decisões de produto que nenhum PR tomou, e tomá-las por
antecipação para economizar leitura seria pagar caro por barato.

## Decisão

**O `HistoricalMatchState` é reconstruído sob demanda, é imutável em memória,
e não tem tabela, cache nem migração.**

```
State_t = Reduce(InitialState, EffectiveCanonicalFacts<=t)
```

Quatro consequências, e cada uma é uma regra executável:

**1. Nenhuma migração acompanha este PR.** O esquema mais recente continua
sendo `0011_event_corpus_membership.sql`, e há um teste de arquitetura que
falha se aparecer uma migração nova sem que a decisão acima seja revista.

**2. A identidade do estado inclui a origem.** A impressão é
`sha256` sobre corpus, política, `as-of` e conteúdo — não só sobre o placar.
Dois estados com o mesmo `1-1` obtidos de gols diferentes, ou do mesmo corpus
sob políticas diferentes, são estados diferentes, e a impressão diz isso. Um
`1-1` que «parece igual» a outro seria coincidência, e reprodutibilidade não
se apoia em coincidência.

**3. O placar vem dos eventos, e nunca do `MatchResult` publicado.** O
resultado final é lido — a leitura o traz sempre — e usado apenas para
CONFERIR num corte pós-jogo. Quando os dois discordam, o estado continua sendo
o que os eventos dizem e a divergência vira problema tipado. Usar o resultado
para «consertar» o placar seria vazamento retroativo com desculpa de auditoria.

**4. A disponibilidade é por componente.** Um estado não é «disponível» ou
«indisponível»: o placar pode ser afirmável enquanto a escalação não foi
publicada. `ObservedZero ≠ Unavailable` — zero cartões aos 63 minutos é um fato
quando há evento publicado, e é a ausência de qualquer observação quando não
há.

## Consequências

**Positivas.** O estado nunca envelhece: ele é sempre o que o corpus pedido diz
hoje. Republicar o corpus não exige reprocessar nada, porque não há nada
gravado para reprocessar. A causalidade é auditável, porque a política sob a
qual o estado foi feito está dentro da identidade dele. E o motor não carrega
uma tabela cuja verdade depende de um job que alguém precisa lembrar de rodar.

**Negativas, e assumidas.** Reconstruir custa. O benchmark do PR-05.2 mede
esse custo sobre dez mil partidas justamente para que ele seja um número
conhecido, e não uma surpresa. A leitura é em lote — cinco consultas por lote,
nunca por partida — porque com N+1 o custo seria proibitivo de um jeito que
levaria de volta à tabela.

**O que esta decisão NÃO fecha.** Materializar features derivadas do estado é
outra pergunta, e ela tem outra resposta possível: uma feature tem definição,
versão, população e normalizador declarados — ela carrega o suficiente para ser
invalidada com precisão, e o estado não carrega. Se um dia houver
materialização, ela será de `FeatureSnapshot` sob uma `FeatureSpaceVersion`, e
não de estado bruto. Esta ADR não a autoriza nem a proíbe; ela diz apenas que o
estado, sozinho, não é candidato.

## Alternativas consideradas

**Tabela de estado por corte.** Rejeitada pelo motivo central acima: a linha
não carrega as dependências, e a invalidação viraria um problema permanente.

**Cache em Redis com chave derivada do corpus e da política.** Rejeitada por
enquanto. Ela resolve a invalidação — a chave muda quando a dependência muda —
e introduz uma dependência de infraestrutura na camada de domínio-adjacente
sem que exista pressão medida que a justifique. É reversível: o dia em que o
benchmark mostrar que reconstruir é o gargalo real de um caso de uso concreto,
ela volta à mesa com um número em vez de uma intuição.

**Guardar só o `StructuralState` reduzido, sem contexto.** Rejeitada: é a
mesma tabela com menos colunas, e com o mesmo defeito.

## Referências

- ADR-0026 — versões do dataset histórico são imutáveis
- ADR-0029 — features usam semântica temporal `AS_KNOWN`
- ADR-0030 — definições e espaços de feature são contratos versionados
- `docs/features/HISTORICAL_MATCH_STATE_V1.md`
- `docs/features/MATCH_STATE_RECONSTRUCTION.md`
- `docs/features/STATE_COMPONENT_AVAILABILITY.md`
