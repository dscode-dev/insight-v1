# Semântica das janelas móveis — V1

> `Window_w(t) = (t - w, t]`, sobre tempo **efetivo**, **local ao período**.

---

## 1. A definição

```
e ∈ Window_w(t)   ⟺   period(e) = period(t)
                  ∧   t - w < EffectiveTime(e) ≤ t
```

Três condições, e nenhuma é decorativa.

| condição | o que ela impede |
|---|---|
| `period(e) = period(t)` | uma janela que atravessa o intervalo usando uma duração que o corpus não publica |
| `EffectiveTime(e) ≤ t` | contar um fato do futuro |
| `t - w < EffectiveTime(e)` | contar o instante inicial duas vezes quando duas janelas são somadas |

---

## 2. A fronteira

**Início exclusivo, fim inclusivo.**

```
corte:  SECOND_HALF 63'
janela: 5 minutos      →  (58', 63']

58'  fora     ← exatamente t - w
59'  dentro
63'  dentro   ← exatamente t
64'  fora
```

A escolha é uma convenção, e o que importa é ela ser **uma só**. Janelas
adjacentes particionam o tempo sem sobreposição: `(50,55]` e `(55,60]` não
compartilham nenhum instante, o que importa no dia em que alguém somar duas.

A janela de um minuto é a que mais expõe a convenção: `(62, 63]` contém
**apenas** o minuto 63. Com `[t-w, t]` ela conteria dois minutos, e toda a
família de um minuto dobraria de contagem.

---

## 3. Por que local ao período

O corpus publica `(fase, minuto, acréscimo)`. Ele **não** publica a duração do
intervalo, e não há relógio de parede por evento.

```
FIRST_HALF  45+3    →  «minuto global 48»?
SECOND_HALF 46      →  «minuto global 46»?
```

O primeiro aconteceu **antes** do segundo e ficaria **depois** na linha
inventada. Uma janela construída sobre ela erraria exatamente perto do
intervalo — onde o futebol é mais interessante.

Então: aos 47 do segundo tempo, `(42, 47]` enxerga o segundo tempo e nada
mais. Os 45+3 do primeiro **não entram**, por mais próximos que estejam no
relógio da TV.

**Isso subconta, e a subcontagem é declarada.** Uma janela de dez minutos aos 3
do segundo tempo enxerga três minutos de jogo. O número é honesto e menor do
que um leitor desatento espera. A alternativa produziria um número que parece
completo e é fabricado.

---

## 4. A régua

`PeriodLocalTime` mede em **segundos inteiros** dentro de um período:

```
elapsed_seconds = (minute + stoppage) * 60
```

**Por que isso é monotônico.** O primeiro tempo vai de 0 a 45 e continua em
45+1, 45+2 — que dão 46, 47 —, e nenhum minuto regular do primeiro tempo chega
a 46. O segundo termina em 90 e continua em 90+1. Dentro de um período não há
colisão entre minuto regular e acréscimo, e é só dentro dele que a conta é
usada.

**Por que segundos e não minutos.** Custam o mesmo e deixam a régua pronta para
uma fonte mais fina sem que a definição de janela mude de unidade — o tipo de
mudança que reescreveria toda impressão de feature. Continua sendo inteiro:
`float` traria `0.1 + 0.2` para dentro de uma comparação de fronteira.

**A resolução do corpus continua sendo o minuto.** `RollingWindow` recusa
janela que não seja múltipla de 60 segundos: uma de noventa segundos
aparentaria uma precisão que o dado não tem.

**A sequência não entra na régua.** `sequence` desempata fatos do mesmo minuto;
ela não mede tempo. Usá-la aqui faria dois eventos do minuto 63 estarem «a uma
unidade» um do outro, o que não é duração de coisa nenhuma.

---

## 5. Tempo efetivo ≠ tempo de conhecimento

```
membresia na janela  ←  EffectiveTime
visibilidade do fato ←  KnowledgeTime
```

As duas perguntas são resolvidas em lugares diferentes, e nessa ordem:

```
eventos canônicos
      ↓  EffectiveEventProjection (PR-05.1)     ← KnowledgeTime decide aqui
fatos efetivos no corte
      ↓  RollingWindow                          ← EffectiveTime decide aqui
fatos da janela
```

**O caso que isto existe para resolver.** Um chute aos 58' cuja correção só
ficou conhecida aos 64'. Num snapshot de 65' com janela de 5 minutos:

- a correção **é visível** (o conhecimento alcançou o corte);
- o fato **continua sendo dos 58'**, e `(60', 65']` não o contém.

A correção muda o **valor** — o xG corrigido — e nunca a **posição**. Sem essa
separação, toda correção tardia criaria um pico de atividade recente que
aconteceu no processamento, e não no campo.

---

## 6. Períodos sem cronômetro

`MatchClock` recusa minuto diferente de zero onde a bola não rola. Consequência
para as janelas:

| período do corte | comportamento |
|---|---|
| `FIRST_HALF`, `SECOND_HALF`, `EXTRA_TIME_FIRST`, `EXTRA_TIME_SECOND` | janela normal |
| `PRE_MATCH` | zero **`AVAILABLE`** quando `EVENT` está publicado — antes do apito não houve fato nenhum |
| `HALF_TIME`, `EXTRA_TIME_BREAK` | `NOT_APPLICABLE` |
| `PENALTY_SHOOTOUT` | `NOT_APPLICABLE` — a disputa fica fora das famílias móveis da V1 |
| `FULL_TIME` | `NOT_APPLICABLE` |

**Por que `NOT_APPLICABLE` e não zero.** No intervalo, «chutes nos últimos cinco
minutos» naturalmente significa o fim do primeiro tempo. Responder `0` seria
responder outra pergunta, com um número que parece uma medição.

**Por que `NOT_APPLICABLE` e não `TEMPORALLY_UNAVAILABLE`.** Neste motor,
`TEMPORALLY_UNAVAILABLE` significa «o fato existe e não podia ser conhecido no
corte», e exige um `LeakageReason` tipado dizendo qual guarda recusou. Aqui não
houve guarda nenhuma: o período simplesmente não tem eixo. Usar o outro estado
mandaria quem investiga procurar um vazamento que nunca aconteceu.

---

## 7. As janelas de produção

```
1m    60s
3m   180s
5m   300s
10m  600s
```

Elas são **aninhadas** — `(62,63] ⊂ (60,63] ⊂ (58,63] ⊂ (53,63]` — e o
extrator conta com isso: um evento a `d` segundos do corte pertence a todas as
janelas `w > d`, que é um sufixo da lista ordenada. Uma busca binária acha onde
o sufixo começa, e os eventos são percorridos **uma vez** em vez de quatro.

A duração entra na impressão da feature (`window_seconds`). Trocar 5 por 10
muda a identidade, e o registro de produção recusa duas definições com a mesma
chave e conteúdos diferentes.

---

## 8. Determinismo

A seleção **impõe** a ordem canônica — `(posição, id)` — em vez de herdar a da
entrada. Duas leituras do mesmo corpus podem devolver os mesmos eventos em
ordens diferentes (plano de consulta, ordem de arquivo), e a janela precisa
produzir a mesma sequência nos dois casos: senão o digest de procedência da
feature mudaria sem o conteúdo mudar.

Provado por permutação exaustiva de um recorte em
`tests/property/test_feature_snapshot_causality.py`.

---

## 9. Defesa em profundidade

A projeção já removeu o futuro. Mesmo assim, o seletor **recusa e conta**
qualquer evento posterior ao corte que chegue até ele (`refused_future`).
Contar em silêncio faria a feature enxergar o futuro sem que nada no resultado
denunciasse; levantar exceção mataria um lote de dez mil partidas por causa de
uma.

---

## 10. Documentos relacionados

- ADR-0032 — a decisão e as alternativas rejeitadas
- `RAW_FEATURE_CATALOG_V1.md` — as features que usam estas janelas
- `MATCH_FEATURE_EXTRACTION.md` — como a extração as aplica
- `TEMPORAL_SEMANTICS_V1.md` — `EffectiveTime ≠ KnowledgeTime` no nível do motor
