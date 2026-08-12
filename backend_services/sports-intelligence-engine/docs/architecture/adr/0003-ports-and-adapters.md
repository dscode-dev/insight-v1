# ADR-0003 — Ports and adapters

**Status:** aceito · **Data:** 2026-08-12

## Contexto

A stack alvo tem cinco tecnologias de persistência e um número desconhecido de
provedores externos. Todas vão mudar — provedores por contrato, bancos por
escala.

Se o domínio conhece a tecnologia, cada troca vira reescrita.

## Decisão

Hexagonal pragmática. O domínio declara o que precisa (`ports`); os adapters
implementam com a tecnologia escolhida.

```
apps → application → domain / features / engines
                          ↑
                        ports
                          ↑
                      adapters
```

Adapters conhecem ports. **Nunca o inverso.**

Interfaces nascem pequenas e só com responsabilidade concreta já conhecida.

## Consequências

**Ganhamos:** domínio testável sem infraestrutura, e trocar de tecnologia é
escrever um adapter. O tipo de um provedor não atravessa a fronteira.

**Pagamos:** uma indireção a mais, e a disciplina de não vazar detalhe pela
assinatura — um port que devolve `Row` do SQLAlchemy é um port que já escolheu.

## Alternativas consideradas

**Repositórios concretos, sem interface.** Rejeitado: teste de domínio passaria
a exigir banco, e a suíte deixaria de ser rápida — que é o que faz alguém
rodá-la.

**Hexagonal dogmática, com port para tudo.** Rejeitado: abstração sem requisito
conhecido é dívida disfarçada de estrutura.

