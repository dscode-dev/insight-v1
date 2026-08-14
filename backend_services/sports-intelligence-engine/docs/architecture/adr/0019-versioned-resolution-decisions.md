# ADR-0019 — Decisões de resolução versionadas e imutáveis

**Status:** aceito · **Data:** 2026-08-13

## Contexto

O resolver vai melhorar. A normalização vai mudar. Os limiares vão ser
ajustados. E cada uma dessas mudanças faz o mesmo registro produzir uma
decisão diferente.

Duas perguntas ficam sem resposta se as decisões forem sobrescritas:

- «por que este registro resolveu agora e não em janeiro?»
- «qual das três mudanças causou a diferença?»

E há uma terceira, pior: se a decisão de janeiro foi sobrescrita, não há como
saber se ela estava certa. A comparação seria contra si mesma.

## Decisão

**Toda decisão é imutável e carrega TRÊS versões:**

```
ResolverVersion     a lógica — que evidências, em que ordem, como compõe
NormalizerVersion   a preparação do texto — mudá-la re-chaveia todo alias
PolicyVersion       os limiares e pesos
```

Três e não uma. Um resolver melhorado com a mesma política produz decisões
diferentes; uma política afrouxada com o mesmo resolver também. Com uma versão
só, as duas mudanças ficariam indistinguíveis.

**Reprocessar produz uma execução NOVA.** `ResolutionRun` é entidade própria —
não um estado em `DatasetLifecycle` —, e o mesmo dataset passa por várias, com
versões diferentes, todas coexistindo.

**O peso de cada evidência é gravado COM a evidência.** Sem isso, reler uma
decisão antiga aplicaria os pesos de hoje ao raciocínio de ontem.

**Confianças de versões diferentes não se comparam.** São réguas diferentes, e
`assert_comparable` recusa — a mesma regra que o ADR-0008 estabelece para
features.

**A impressão do manifesto viaja na decisão.** Sem ela, «esta decisão veio do
dataset X» é uma afirmação sobre um dataset que pode ter mudado desde então.

**Determinismo é requisito, não consequência.** Mesma entrada + mesmas versões
+ mesmo estado do registro → as mesmas decisões, na mesma ordem. Nenhum
`random`, nenhum relógio dentro do resolver, e todo desempate explícito: score
decrescente, depois id da entidade.

## Consequências

**Ganhamos:** a capacidade de rodar o resolver novo ao lado do antigo e medir
a diferença antes de confiar nele. É o que torna possível melhorar a resolução
sem apostar.

**Pagamos:** volume. Cada reprocessamento é um conjunto novo de decisões, e o
dataset de cem mil registros gera cem mil linhas por execução. É barato
comparado a não conseguir explicar uma decisão de identidade.

## Alternativas consideradas

**Sobrescrever com log de auditoria separado.** Rejeitado: reconstruir a
decisão passada exigiria reprocessar o log, e o log costuma ter retenção menor
que os dados.

**Uma versão só, combinada.** Rejeitado — ver acima: as três mudam
independentemente, e é a independência que torna o diagnóstico possível.

**Versionar só quando o resultado muda.** Rejeitado: exigiria comparar todas as
decisões antes de decidir se versiona, o que é o próprio reprocessamento.

