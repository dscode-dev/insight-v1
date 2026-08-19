# Modelo de vazamento temporal

O que pode vazar, como o motor recusa, e como se prova que não vazou.
Implementado em **PR-05.1**.

> **O objetivo deste PR não é produzir muitas features.** É tornar difícil ou
> impossível produzir uma feature temporalmente inválida sem que o arnês
> detecte.

---

## As sete formas de vazar

| # | vazamento | exemplo | recusa |
|---|-----------|---------|--------|
| 1 | evento futuro | gol aos 78 num estado de 63 | `EFFECTIVE_TIME_AFTER_CUTOFF` |
| 2 | conhecimento futuro | correção conhecida às 64:10 aplicada às 63:30 | `KNOWLEDGE_TIME_AFTER_CUTOFF` |
| 3 | fato pós-jogo | placar final, vencedor | `POST_MATCH_ONLY` |
| 4 | agregado final | `HOME_SHOTS = 14` como estado dos 63 | `POST_MATCH_ONLY` |
| 5 | retrospectivo sem prova | correção sem carimbo aplicada de qualquer jeito | `RETROSPECTIVE_ONLY` |
| 6 | disponibilidade desconhecida | cotação de fechamento tratada como pré-jogo | `UNKNOWN_AVAILABILITY` |
| 7 | ajuste de normalizador | z-score de maio avaliando março | `NORMALIZER_FUTURE_FIT` |

**O quarto é o mais fácil de cometer e o mais difícil de ver.** `HOME_SHOTS =
14` é um número verdadeiro sobre a partida, e ele simplesmente não é o número
do minuto 63. Nada no dado denuncia: a coluna existe, o valor é plausível, e a
feature resultante parece razoável — só está errada em todos os cortes menos
um.

---

## A ordem das guardas

```
1. a CLASSE do fato        pós-jogo? retrospectivo? desconhecido?
2. a OCORRÊNCIA            a posição na partida contra o corte
3. o CONHECIMENTO          o carimbo de parede contra o corte
```

A classe vem primeiro porque é **categórica**: um `MatchResult` não deixa de
ser pós-jogo por ter «acontecido antes» do corte em algum sentido. A ocorrência
vem antes do conhecimento porque é a régua que **todo** fato intra-jogo tem — e
o conhecimento é a que quase nenhum tem.

---

## `EffectiveEventProjection`

O caso que ela resolve:

```
63:21  GOAL E1
64:10  correção E2, que substitui E1

replay às 63:30  →  enxerga E1              (E2 não existia para ninguém)
replay às 64:30  →  enxerga E2, E1 corrigido
```

```
EffectiveEventProjection  ≠  CanonicalEventHistory
```

**A projeção é derivada e não muta nada.** O corpus continua append-only: nenhum
evento é apagado, nenhum status é reescrito. O que ela faz é decidir, para um
corte, quais eventos entram e em que estado.

Três resultados possíveis para um evento corrigido:

| situação | o que a projeção mostra |
|----------|-------------------------|
| a correção entrou | o **sucessor**; o original sai da visão |
| a correção não entrou | o **original**, marcado `correction_withheld` |
| o evento foi cancelado | **nada** — um gol anulado não é estado do jogo |

O terceiro caso merece o nome que tem: quem lê precisa distinguir «não foi
corrigido» de «a correção ainda não era sabida».

---

## As propriedades executáveis

Estes são os invariantes que o arnês verifica — e eles provam mais que casos
isolados, porque falam de **conjuntos inteiros**:

```
Snapshot(F<=t)  =  Snapshot(F<=t mais F>t)              §160
KnownAt_t(F)    =  KnownAt_t(F mais Corrections>t)      §161
Unavailable     ≠  0   e   NotDeclared ≠ MeasuredZero   §162
mesmos quatro insumos  ⇒  mesma impressão de snapshot   §163
```

### O sentinela

O cenário de teste carrega **999 eventos extras aos 80 minutos**. Qualquer
feature causal que os enxergue salta de 4 para mais de mil — um número
impossível de confundir com ruído ou arredondamento.

Ele existe porque «o teste passou» é fraco demais como garantia: um cálculo que
por acaso não usa o futuro passa pelo mesmo teste que um cálculo que
estruturalmente não pode usá-lo. O sentinela transforma «passou» em «passou por
bom motivo».

---

## O que fazer quando a recusa acontece

```
DENIED / EFFECTIVE_TIME_AFTER_CUTOFF   o corte está errado, ou a feature
                                       declara depender de algo que não
                                       poderia existir ali
DENIED / POST_MATCH_ONLY               a feature é pós-jogo e foi usada num
                                       espaço intra-jogo
UNKNOWN / MISSING_OBSERVATION_TIMESTAMP  a fonte não carimba; ou se aceita a
                                       classificação por ocorrência, ou a
                                       feature fica indisponível
UNKNOWN / MISSING_KNOWLEDGE_CUTOFF     o `as-of` não declarou até quando o
                                       conhecimento vale
```

**Nenhuma delas se conserta afrouxando o guarda.** Elas se consertam mudando o
corte, a definição da feature, ou a política — e a política é versionada e
impressa, então afrouxá-la é uma mudança visível.

---

## Relacionados

- [Semântica temporal](TEMPORAL_SEMANTICS_V1.md)
- [ADR-0029 — semântica temporal as-known](../architecture/adr/0029-feature-generation-uses-as-known-temporal-semantics.md)
- [Contrato de normalização](NORMALIZATION_CONTRACT_V1.md) — o sétimo vazamento
