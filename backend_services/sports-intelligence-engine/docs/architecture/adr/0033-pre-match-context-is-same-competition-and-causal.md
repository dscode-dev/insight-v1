# ADR-0033 — O contexto pré-jogo V1 é local à competição e mede calendário

**Status:** aceito · **Data:** 2026-08-20

## Contexto

O motor precisa de sinais que existem **antes** do apito: o time vem de quantos
dias de descanso, jogou quantas vezes no último mês. Eles são úteis
precisamente porque não dependem do que acontece dentro da partida.

A pergunta parece objetiva e esconde quatro decisões, cada uma com uma resposta
defensável e várias plausíveis:

**Escopo.** Partidas de qual competição contam? Um time que jogou a Champions
na quarta e a liga no domingo teve três dias de descanso — mas o corpus da
liga só enxerga a liga.

**Elegibilidade.** O que prova que a partida anterior aconteceu? Estar no
calendário não basta: partidas são adiadas.

**Janelas.** «Recente» é quanto? Sete dias, catorze, trinta?

**Fronteiras.** A partida exatamente no limite da janela entra?

E há uma quinta, que só aparece na primeira rodada de qualquer corpus: **zero
partidas nos últimos catorze dias** tem duas causas — o time não jogou, ou o
arquivo começa depois de `T - 14d`. As duas produzem o mesmo número.

Existe ainda uma tentação maior. Com as partidas anteriores em mãos, é natural
somar pontos, gols e vitórias: forma, Elo, confronto direto. Cada um desses é
um sinal legítimo com uma decisão estatística própria — quantas partidas, com
que peso, o que fazer com jogo adiado, como tratar promovido — e nenhuma delas
foi tomada.

## Decisão

**O contexto pré-jogo V1 mede CALENDÁRIO, é local à competição, e o nome das
features admite as duas coisas.**

```
Context(M) = f(partidas anteriores da MESMA competição, kickoff < kickoff(M))
```

Cinco consequências, e cada uma é uma regra executável:

**1. `ContextScope.SAME_COMPETITION`, e `ALL_COMPETITIONS` é recusado.** Cruzar
torneios exigiria decidir quais deles compõem a carga de qual time — uma
decisão com evidência própria. O escopo cruzado existe no catálogo para ser
negado com mensagem, e não por não ter como ser expresso.

**2. O nome diz o escopo.** `ctx_same_comp_prev_gap_hours_home`, e nunca
`rest_days_home`. A feature subconta descanso, e o nome precisa admitir isso —
senão o consumidor lê «descanso» e recebe «calendário da liga».

**3. Nenhuma feature de força, forma ou desempenho.** `PriorMatchRef` carrega
apenas `(kickoff, match_id)`: o placar da partida anterior **não chega ao
domínio**. Isso é estrutural, não disciplina — não há por onde somar pontos.

**4. O `MatchResult` da partida anterior prova conclusão, e só.** Ela terminou
antes de a atual começar, então o resultado dela já era conhecido no apito
inicial — usá-lo como prova não é vazamento. Usar o **valor** dele seria outra
feature, e ela não existe.

**5. Zero observado é distinguido de histórico ausente.** `ContextCoverage`
carrega o instante da primeira partida daquela competição naquela versão
publicada; a janela é conferida contra ele. Sem cobertura provada, o resultado
é `INSUFFICIENT_COVERAGE` — nunca `0`.

**A pertinência à versão decide.** Uma partida anterior só conta se pertencer à
mesma `HistoricalCanonicalDatasetVersion`. Existir em `matches` não basta:
senão o contexto passaria a depender de quando o build rodou em vez de qual
versão foi pedida.

## Consequências

**Positivas.** A feature mede uma coisa só, e o nome diz qual. A borda do
corpus não vira sinal falso. Nenhuma decisão estatística foi tomada por
antecipação — o dia em que houver forma, ela será uma família nova com
justificativa própria, e não uma reinterpretação silenciosa destas.

**Negativas, e assumidas.** O contexto subconta a carga real de times que
disputam mais de um torneio — exatamente os grandes, exatamente nas semanas que
mais importam. O número é honesto e menor que a verdade. A alternativa
produziria um número que parece completo e depende de uma decisão que ninguém
tomou.

**O que esta decisão NÃO fecha.** Contexto cross-competition continua possível
quando existir a decisão sobre quais torneios compõem a carga de cada time. Ele
será uma **família nova** — chave e versão próprias —, e não uma mudança de
escopo destas nove.

## Alternativas consideradas

**Cruzar todas as competições.** Rejeitada: representaria melhor o descanso
físico e exigiria decidir a composição da carga por time, além de tornar o
resultado dependente de quais torneios aquele corpus publica — dois times
idênticos em ligas com cobertura diferente teriam contextos incomparáveis.

**Medir de fim a início em vez de apito INICIAL a apito INICIAL.** Rejeitada:
o corpus não publica quando a partida anterior terminou. Estimá-la somando
noventa minutos mais acréscimos inventaria uma duração.

> **Nota de terminologia (PR-05.5.1 §132).** A redação anterior dizia «de apito
> a apito», que se lê com igual naturalidade como «do apito FINAL da anterior ao
> apito inicial da atual» — que é justamente a medida rejeitada. A medida
> implementada é **pontapé a pontapé**: `kickoff(atual) - kickoff(anterior)`. A
> conta nunca mudou; o texto é que era ambíguo.

**Contar `0` no começo do corpus.** Rejeitada — é o defeito central que a
cobertura existe para impedir. O modelo aprenderia que quem joga a primeira
rodada está sempre descansado.

**Incluir forma recente junto.** Rejeitada: são decisões estatísticas
diferentes com evidência diferente, e juntá-las faria uma passar carona na
outra.

## Referências

- ADR-0026 — versões do dataset histórico são imutáveis
- ADR-0029 — features usam semântica temporal `AS_KNOWN`
- ADR-0031 — o estado histórico é reconstruído e nunca armazenado
- `docs/features/PRE_MATCH_CONTEXT_V1.md`
- `docs/features/RAW_FEATURE_CATALOG_V2.md`
