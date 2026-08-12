# ADR-0002 — Control Plane e Execution Plane

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Existem duas classes de operação com naturezas opostas.

Administrativas: promover um dataset, corrigir uma partida, disparar
reconciliação. Raras, privilegiadas, auditadas, quase sempre humanas.

De execução: ingerir, calcular, materializar, publicar. Contínuas,
automáticas, alto volume.

## Decisão

Dois planos, separados por **processo**.

**Control Plane** (`control_api`, CLI): administração, datasets,
configuração, mappings, reconciliação, RBAC futuro.

**Execution Plane** (workers, `query_api`): ingestão, estado, cálculo,
arquivamento, promoção, leitura.

Os dois compartilham domínio e ports; nenhum importa regra de negócio do
outro.

## Consequências

**Ganhamos:** um pico de leitura não compete com uma reconciliação. A
superfície administrativa não é alcançável pelo endereço que atende usuário
final. Autorização fica concentrada onde as operações perigosas moram.

**Pagamos:** dois processos para operar e observar, e a tentação recorrente de
"só desta vez" expor uma operação administrativa no plano de execução.

## Alternativas consideradas

**Separar só por rota, no mesmo processo.** Rejeitado: não isola recurso, e um
erro de roteamento expõe administração publicamente.

**Serviços totalmente separados, com domínios próprios.** Rejeitado pelo
ADR-0001: duplicaria a definição de partida.

