# Constituição arquitetural

Os invariantes do Insight Sports Intelligence Engine. Cada um existe porque a
alternativa falha **em silêncio** — sem erro, sem alarme, com os números
simplesmente errados.

Quando uma decisão contradiz um destes pontos, a decisão está errada ou o
ponto precisa ser revisado por escrito. Nunca contornado.

---

## 1. O motor é descritivo, não preditivo

A saída é uma frase sobre o que **aconteceu** em situações parecidas — não
sobre o que vai acontecer nesta. A diferença não é de estilo: uma afirmação
sobre o passado tem como ser conferida; uma sobre o futuro não.

## 2. Toda partida ao vivo é um dataset histórico futuro

```
bootstrap público → conhecimento histórico → partida ao vivo →
inteligência ao vivo → arquivo → reconciliação → reconstrução →
promoção → conhecimento nativo → partidas futuras
```

O dado público é combustível de arranque. O motor produz o próprio histórico
(`INSIGHT_NATIVE`), e é ele que fecha o ciclo.

## 3. Uma partida nunca alimenta o índice que ela própria consulta

**ADR-0007.** Só `HISTORICAL_ACTIVE` entra no retrieval histórico.

O sintoma da violação é traiçoeiro porque é *bom*: a similaridade fica
excelente e as métricas sobem. O sistema só falha em produção, contra partidas
que nunca viu.

## 4. Ausente nunca vira zero

**ADR-0009.** `FeatureValue` não tem `__float__`. Para obter o número é
preciso `require()` — que falha alto — ou `or_default()` — que exige escrever
o default, e por isso o deixa visível no diff.

Zero chutes **medidos** é um fato. Zero por ausência é uma invenção, e
padronizada contra um corpus ela vira um outlier que agrupa por um motivo que
não existe.

## 5. Snapshots são imutáveis

**ADR-0005.** Um snapshot é o registro do que se sabia num instante. Alterá-lo
apaga a única evidência de que a conclusão daquele momento fazia sentido com a
informação daquele momento.

Correção é snapshot **novo**, com `state_version` maior.

## 6. Toda conclusão carrega as versões que a produziram

**ADR-0008.** Sem `engine_version` e `feature_space_version` na saída,
comparar a conclusão de hoje com a de ontem mede a mudança do **código** junto
com a mudança dos **dados**, e não há como separar.

Artefatos de versões diferentes **não se comparam**. `assert_comparable`
recusa; nunca converte.

## 7. Requisição de usuário não dispara cálculo

**ADR-0010.**

```
evento → cálculo → IntelligenceSnapshot → materialização → Query API → N usuários
```

O custo escala com partidas e estados, não com audiência.

## 8. O domínio não conhece infraestrutura

**ADR-0003.** Nada em `domain`, `features`, `engines` ou `ports` importa
FastAPI, Postgres, Redis, ClickHouse, S3 ou o pacote de um provedor.

Verificado por AST em `tests/architecture/`, falhando o CI.

## 9. Determinismo

- relógio injetado (`ClockPort`) — nunca `datetime.now()` no domínio;
- aleatoriedade com semente injetada;
- ordenação explícita onde a ordem altera o resultado;
- mesma entrada + mesma versão = mesma saída.

## 10. Identidade do domínio ≠ referência de provedor

Três provedores olhando a mesma partida produzem três ids. A partida é uma.
`ProviderRef` **não converte** para `EntityId` — a passagem entre os dois é
resolução de identidade, uma etapa explícita com regras próprias e capaz de
falhar.

## 11. Procedência viaja com o dado

De onde veio, quando foi observado, e o que a licença permite. A pergunta
"posso publicar isto?" precisa ter resposta sem arqueologia — descobrir depois
que uma base era `RESEARCH_ONLY` significa reconstruir o índice.

## 12. Idempotência

Reprocessar não pode contar duas vezes. A duplicata não aparece como erro:
aparece como número errado, e tudo continua somando.

## 13. Precisão numérica

- `float64` nos cálculos internos, salvo benchmark que justifique outra coisa;
- timestamps sempre UTC, com fuso explícito — nunca suposto;
- ids nunca derivados de float;
- nenhuma conversão silenciosa de `None → 0`.

## 14. Nenhum segredo com default

Uma senha com valor padrão sobrevive ao desenvolvimento, atravessa o staging e
chega em produção sem que ninguém tenha decidido usá-la.

## 15. Abstração precisa proteger um requisito conhecido

Interface sem responsabilidade concreta e classe vazia para preencher diretório
são dívida disfarçada de estrutura. Diretório com apenas `__init__.py` é
aceitável; abstração inventada não é.
