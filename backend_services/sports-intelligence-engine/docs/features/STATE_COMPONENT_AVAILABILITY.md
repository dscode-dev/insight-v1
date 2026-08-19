# Disponibilidade por componente

> Um estado não é «disponível» ou «indisponível». Cada parte dele responde por
> si, e é isso que permite usar o que existe sem fingir o que falta.

---

## 1. O problema que isto resolve

Um booleano global obrigaria quem consome a descartar tudo por causa de uma
parte:

```
score       AVAILABLE                ← o placar é confiável
on_field    NOT_DECLARED             ← a versão não publica escalação
discipline  AVAILABLE                ← os cartões são confiáveis
odds        TEMPORALLY_UNAVAILABLE   ← há cotação, e não neste corte
```

Este estado é **parcial**, e continua sendo útil. Rejeitá-lo inteiro faria o
motor descartar um placar correto por causa de uma escalação ausente.

---

## 2. Os estados de disponibilidade

Herdados do contrato do PR-05.1 (`FeatureAvailability`):

| estado | significa |
|---|---|
| `AVAILABLE` | o componente foi observado e pode ser afirmado |
| `NOT_DECLARED` | a versão do corpus não publica essa família |
| `SOURCE_UNAVAILABLE` | a família é publicada e esta partida não tem o dado |
| `TEMPORALLY_UNAVAILABLE` | o dado existe e não é elegível NESTE corte |
| `POLICY_EXCLUDED` | a política de licença ou qualidade o excluiu |
| `UPSTREAM_ERROR` | a origem falhou |
| `UNKNOWN` | não se sabe, e não se finge que se sabe |

---

## 3. A distinção central: `ObservedZero ≠ Unavailable`

Esta é a regra que mais custa quando se perde, porque os dois casos têm a
**mesma aparência numérica**.

```
zero cartões observados até os 63'      →  0, AVAILABLE
zero cartões porque não há cobertura     →  0, NOT_DECLARED
```

Um consumidor que os confundisse aprenderia que **partidas sem cobertura são
partidas disciplinadas** — uma correlação inteiramente falsa, produzida pelo
arnês e não pelo futebol. E ela seria invisível: os dois valem `0`.

Por isso a forma canônica de cada componente carrega a disponibilidade, e as
duas versões produzem impressões diferentes.

O mesmo vale para o resto:

| leitura ingênua | o que de fato são |
|---|---|
| «placar 0-0» | `0-0 AVAILABLE` no pré-jogo · `0-0 NOT_DECLARED` sem `EVENT` |
| «zero cotações» | `SOURCE_UNAVAILABLE` (publicamos, não veio) · `NOT_DECLARED` (não publicamos) · `TEMPORALLY_UNAVAILABLE` (existe, fora do corte) |
| «campo vazio» | escalação não publicada · escalação parcial · conflito de elenco |

Um componente indisponível **não carrega valor utilizável**: `TeamOnFieldState`
degradado tem a lista de jogadores vazia. Um campo «indisponível» que ainda
carregasse dez nomes seria usado como se fossem dez nomes.

---

## 4. A degradação é LOCAL

Um problema atinge o componente afetado, e só ele.

| problema | degrada | preserva |
|---|---|---|
| escalação não publicada | `on_field` (os dois lados) | placar, disciplina, odds |
| escalação de um time ausente | `on_field` daquele lado | o outro lado, placar |
| escalação com dez titulares | `on_field` daquele lado | o outro lado, placar |
| jogador nos dois times | `on_field` (os dois) | **placar**, disciplina |
| substituição impossível | `on_field` daquele lado | o outro lado, placar |
| expulsão de quem não está em campo | `on_field` daquele lado | disciplina (ela conta) |
| gol de time desconhecido | `score` | campo, disciplina |
| cotação fora do corte | `odds` | todo o resto |
| resultado discorda do placar | **nada** (`NOTED`) | tudo |

O caso do jogador nos dois times é o mais instrutivo: é um defeito de
resolução de identidade, quase certamente duas pessoas fundidas numa. Ele
torna o elenco não afirmável — e **não diz nada sobre o placar**, que não
depende de quem está em campo.

---

## 5. Sem `EVENT`, o que depende de evento cai junto

Quando a versão não publica a família `EVENT`:

```
score           NOT_DECLARED
discipline      NOT_DECLARED   (nos dois times)
substitutions   NOT_DECLARED
events          NOT_DECLARED
on_field        depende de LINEUP, e não de EVENT
odds            depende de ODDS
```

«Zero cartões» só é um fato quando há evento publicado. Sem ele, a contagem
zerada não é observação: é a ausência de qualquer observação.

Repare que `on_field` **não** cai: a escalação inicial vem da família `LINEUP`,
e um corpus pode publicar escalação sem publicar eventos. Nesse caso o estado
sabe quem começou jogando e não sabe quem saiu — o que é honesto, e diferente
de não saber nada.

---

## 6. `is_partial`

```python
state.is_partial  # algum componente não pôde ser afirmado
```

Um estado parcial **não é um estado errado**: é um estado que declara o que não
pôde afirmar. Chamá-lo de completo obrigaria quem consome a descobrir a
ausência por conta própria, olhando o valor zero — que é exatamente o erro que
a seção 3 descreve.

Na prática, quase todo estado real é parcial: corpus com todas as famílias
publicadas e todas as partidas cobertas é a exceção, não a regra.

---

## 7. Como consumir

```python
resultado = await BuildHistoricalMatchState(source, policy).execute(
    source_corpus=origem, as_of=corte
)

if resultado.state.score.is_available:
    diferenca = resultado.state.score.difference
# senão: NÃO trate como 0. O componente disse que não sabe.

for problema in resultado.issues:
    ...  # code, severity, component, detail
```

Os problemas estão em **dois lugares** de propósito: dentro do estado, porque
fazem parte do que ele é; e no resultado da construção, porque quem chamou
precisa poder contá-los sem abrir cada estado — que é o que o caminho em lote
faz, agregando por código.

---

## 8. Documentos relacionados

- `HISTORICAL_MATCH_STATE_V1.md` — o contrato do estado
- `MATCH_STATE_RECONSTRUCTION.md` — como cada componente é montado
- `FEATURE_CONTRACT_V1.md` — `FeatureAvailability` e `missing ≠ zero` no nível
  da feature
