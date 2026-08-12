# ADR-0001 — Modular monolith com múltiplos processos

**Status:** aceito · **Data:** 2026-08-12

## Contexto

O motor tem responsabilidades com perfis operacionais muito diferentes:
ingestão ao vivo (latência baixa, rajadas), cálculo de inteligência (CPU),
reconstrução histórica (lote longo) e leitura (alto volume, baixo custo).

Cada uma quer escalar por um eixo diferente. Nenhuma quer o próprio domínio.

## Decisão

Um monorepo modular. O código de domínio, application, features e engines é
**um conjunto de pacotes compartilhados**; `apps/` contém pontos de entrada
que compõem esses pacotes em processos separados.

Comunicação entre módulos é chamada Python através de ports. Rede interna
entra apenas quando houver motivo operacional — não por padrão.

## Consequências

**Ganhamos:** uma definição de partida, não sete. Refatoração atravessa o
sistema num commit. Escala por processo sem duplicar domínio.

**Pagamos:** disciplina de fronteiras precisa ser imposta por ferramenta, não
por convenção — daí os testes de arquitetura. E um deploy acopla os processos
enquanto forem construídos juntos.

## Alternativas consideradas

**Microserviços desde o início.** Rejeitado: o custo de rede, versionamento e
observabilidade distribuída aparece imediatamente, e o benefício — escalar
independentemente — só aparece com carga que ainda não existe. Extrair depois
é possível porque o domínio não conhece transporte; unir depois é bem mais
caro.

**Processo único.** Rejeitado: uma reconstrução histórica de horas competiria
por CPU com o cálculo ao vivo, e a leitura pagaria por ambos.

