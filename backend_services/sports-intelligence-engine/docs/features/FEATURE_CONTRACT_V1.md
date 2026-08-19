# Contrato de feature — V1

O que uma feature declara antes de existir. Implementado em **PR-05.1**.

> **Nenhuma feature de produção existe ainda.** Não há `shots_home_5m`, nem
> pressão, nem força de time. O que existe é o contrato que elas vão cumprir —
> e definições de teste, que vivem nos testes.

---

## A identidade

```
FeatureIdentity  =  Key + Version + ContentFingerprint
```

**Chave e versão são declaração humana, e podem mentir.** Alguém muda a janela
de 5 para 10 minutos e esquece de subir a versão; dois números com o mesmo nome
passam a significar coisas diferentes, e o histórico compara um com o outro sem
nada denunciar.

A impressão não deixa: o conteúdo mudou, a identidade mudou, e a comparação
entre o antes e o depois passa a ser explicitamente entre coisas diferentes.

---

## `FeatureDefinition`

| campo | existe para impedir |
|-------|---------------------|
| `key` / `version` | duas features com o mesmo nome significando coisas diferentes |
| `output_type` | um booleano virando `0.0` num vetor sem ninguém decidir isso |
| `unit` | comparar «minutos» com «segundos» como se fosse a mesma escala |
| `scope` | somar feature de mandante com feature de visitante |
| `temporal_class` | calcular estado intra-jogo com placar final |
| `required_families` | descobrir na décima milésima partida que o corpus não publica eventos |
| `required_fact_kinds` | a mesma coisa, na régua temporal |
| `parameters` | «a janela mudou de 5 para 10 e a identidade não» |
| `fail_closed` | o valor que aparece quando não deveria |
| `normalizer_key` | normalizar sem declarar com o quê |
| `depends_on_features` | dependência para o vazio, e ciclo |

### O que entra na impressão

```
key · version · output_type · scope · temporal_class ·
required_families · required_fact_kinds · parameters ·
fail_closed · normalizer_key · depends_on_features
```

### O que NÃO entra

```
description        reescrever um comentário não é quebra de compatibilidade
created_at         muda entre duas execuções do mesmo cálculo
endereço, repr     não são estáveis nem entre processos
```

---

## Os catálogos fechados

**`FeatureOutputType`** — `FLOAT`, `INTEGER`, `BOOLEAN`, `CATEGORY`.

Não há `VECTOR`, e a ausência é a decisão: o vetor é a representação do
ESPAÇO, montada a partir de features escalares ordenadas — não o tipo de saída
de uma feature. Introduzi-lo agora anteciparia o `MatchStateVector`.

**`FeatureScope`** — `MATCH`, `HOME_TEAM`, `AWAY_TEAM`, `TEAM`, `PLAYER`.

`HOME_TEAM` e `AWAY_TEAM` são posições da partida; `TEAM` é uma feature
calculada para um time identificado. `PLAYER` existe no catálogo e não tem
motor — declará-lo não implementa nada, e omiti-lo obrigaria a mudar o enum
quando o PR de jogador chegar.

**`FeatureTemporalClass`** — `PRE_MATCH`, `INTRA_MATCH_CAUSAL`, `POST_MATCH`.

Ela não é a classe do FATO (`TemporalAvailability`): aquela descreve quando um
fato pode ser conhecido; esta declara o que a FEATURE exige de quem a alimenta.

---

## O valor

```
FeatureValue      «o número existe? qual é? por que não?»     (PR-01)
ComputedFeature   «de qual feature, sob qual corte, com qual procedência»
```

**Duas ausências diferentes, e as duas sobrevivem:**

```
Unavailability        por que o NÚMERO não existe    NOT_PUBLISHED, …
FeatureAvailability   por que a FEATURE não existe   TEMPORALLY_UNAVAILABLE, …
```

Um chute sem xG publicado é o primeiro. Uma feature que não pôde ser calculada
porque o fato era do futuro é o segundo. Colapsá-las faria «a fonte não mediu»
e «o corte proibiu» virarem a mesma coisa.

### `missing ≠ zero`, e continua absoluto

```
red_cards_home = 0             ninguém foi expulso        FATO
red_cards_home = unavailable   não se sabe                AUSÊNCIA
```

Um `0` no lugar do segundo produz média que soma perfeitamente e está errada —
o pior tipo de defeito, porque nada denuncia.

### A máscara é de primeira classe

`FeatureAvailabilityMask` acompanha o valor **até a similaridade e o
retrieval**. Comparar dois estados em que uma dimensão está ausente exige saber
que ela está ausente; um vetor que já esqueceu isso força quem compara a tratar
o buraco como zero.

Os estados: `AVAILABLE`, `NOT_DECLARED`, `NOT_APPLICABLE`, `SOURCE_UNAVAILABLE`,
`TEMPORALLY_UNAVAILABLE`, `BLOCKED_BY_POLICY`, `INSUFFICIENT_COVERAGE`.

---

## A procedência

```
classe          o que este número É — observado, derivado, normalizado, imputado
contribuições   QUAIS fatos canônicos entraram
digest          a impressão determinística do conjunto INTEIRO
```

**Ela é limitada por desenho.** Uma contagem sobre dez minutos de jogo
movimentado pode ter centenas de contribuintes; carregar todos dentro de cada
valor multiplicaria o custo de um vetor por três ordens de grandeza. O que
viaja é: quantos foram (exato), uma amostra de até 16, e o digest do conjunto
completo.

```
mesmo conjunto (em qualquer ordem)  ⇒  mesmo digest
conjuntos diferentes                ⇒  digests diferentes
```

`IMPUTED` existe no catálogo e **nenhum caminho o produz** (§101). Ele está lá
para que, no dia em que alguém imputar, o valor não possa se passar por
observado.

---

## O calculador

```
Feature = f(Definition, AsOf, CanonicalContext)
```

Três entradas, uma saída, **sem I/O**. Nenhuma conexão de banco, nenhum
repositório, nenhum cliente de object store — e a ausência não é economia de
parâmetros: um calculador que pudesse ler o corpus poderia ler o FUTURO dele, e
todas as guardas temporais passariam a depender de disciplina.

**Ele devolve `ComputedFeature` e nunca levanta por ausência.** Fato faltando,
corte proibindo ou cobertura insuficiente produzem valor indisponível com
motivo. A exceção fica para o que é defeito nosso.

---

## O contexto

`CanonicalFeatureContext` é **match-scoped e as-of-scoped**. Três coisas que
ele não tem, e cada ausência é a decisão:

| ausente | porquê |
|---------|--------|
| o corpus inteiro | uma feature «média da liga» carregaria dez mil partidas para dentro do cálculo de uma |
| o resultado final | `result` só é entregue quando o corte é pós-jogo |
| o evento cru | os eventos vêm pela **projeção efetiva**, não pela lista canônica final |

---

## Relacionados

- [ADR-0030 — features e espaços são contratos versionados](../architecture/adr/0030-feature-definitions-and-spaces-are-versioned-contracts.md)
- [Espaço de features](FEATURE_SPACE_V1.md)
- [Semântica temporal](TEMPORAL_SEMANTICS_V1.md)
