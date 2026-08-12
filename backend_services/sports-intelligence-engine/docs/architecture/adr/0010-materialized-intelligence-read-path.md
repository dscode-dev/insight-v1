# ADR-0010 — Caminho de leitura materializado

**Status:** aceito · **Data:** 2026-08-12

## Contexto

O cálculo de inteligência é caro: features, similaridade sobre o histórico,
cinco lentes, confiança. Uma partida popular pode ser consultada por milhares
de pessoas simultaneamente.

Se cada consulta dispara cálculo, o custo escala com **audiência** — e o pico
de audiência coincide exatamente com o pico de carga de cálculo ao vivo.

## Decisão

Separação estrita entre caminho de escrita/cálculo e caminho de leitura:

```
evento ao vivo → cálculo → IntelligenceSnapshot → materialização (Redis)
                                                        ↓
                                                   Query API → N usuários
```

**Requisição de usuário nunca dispara cálculo do motor.** O `query_api` lê o
que já foi materializado. O cálculo roda quando o **estado muda** — uma vez
por estado, independentemente de quantos estejam olhando.

## Consequências

**Ganhamos:** custo proporcional a partidas e estados, não a audiência.
Latência de leitura previsível. Um pico de audiência não derruba o cálculo.

**Pagamos:** a leitura é eventualmente consistente — há uma janela entre o
estado mudar e a materialização atualizar. E existe um caminho a mais para
operar e observar.

## Alternativas consideradas

**Calcular sob demanda com cache.** Rejeitado: o primeiro leitor de cada
estado paga o cálculo inteiro, e num pico há muitos "primeiros leitores" ao
mesmo tempo — o efeito manada que a materialização evita.

**Calcular sob demanda sem cache.** Rejeitado: custo linear em usuários, que é
exatamente o que a restrição arquitetural proíbe.

