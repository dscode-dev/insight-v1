# ADR-0035 — Normalização V1 usa artefatos exatos de mediana/IQR por competição

**Status:** aceito · **Data:** 2026-08-20

## Contexto

As features cruas do motor têm escalas incomparáveis entre si: `shots_home_5m`
vive em 0–8, `xg_home_5m` em 0–1,5, `ctx_same_comp_prev_gap_hours_home` em
centenas. Qualquer comparação entre estados — que é o destino de tudo isto —
precisa colocá-las numa escala comum.

Escalar parece um detalhe de implementação e tem quatro decisões dentro, cada
uma capaz de produzir números plausíveis e errados.

**Qual estatística.** Média e desvio pressupõem distribuição aproximadamente
simétrica. Futebol tem 7 a 1: uma partida atípica desloca a média e infla o
desvio, e o resto do corpus passa a parecer comprimido.

**Qual população.** Ajustar Premier League e La Liga juntas produz uma escala
que não descreve nenhuma das duas — um valor mediano do Brasileirão parece alto
na Inglaterra.

**Qual corte.** Ajustar com dado de maio para avaliar um jogo de março carrega o
futuro dentro da escala. E é o vazamento mais traiçoeiro do motor, porque não
aparece no valor: `+0,3` parece um número inocente.

**O que fazer quando a dispersão é nula.** `(x - mediana) / 0` quebra. A
correção óbvia — `max(iqr, 1e-6)` — faz o código parar de quebrar e **inventa
uma escala**: a distribuição sem dispersão passa a produzir valores enormes, e
eles parecem sinal.

O PR-05.1 já declarou o contrato do normalizador. O que faltava era o runtime —
e ele é onde as quatro decisões viram código.

## Decisão

**A normalização V1 é mediana/IQR por competição, ajustada de forma EXATA, e
materializada num artefato imutável com identidade própria.**

```
NormalizerFitArtifact = Fit(FeaturePopulation, Competition, Cutoff)
Normalized(x)         = (x - mediana) / IQR
```

Seis consequências:

**1. Robusta, e o nome diz isso.** O método se chama
`MEDIAN_IQR_ROBUST_SCALE_V1`, e nunca «z-score». `z` carrega uma expectativa —
média zero, desvio um, normalidade — que esta escala não sustenta; o nome
errado faria alguém aplicar a régua de três sigmas a ela.

**2. Exata, e o custo é declarado.** Nada de t-digest ou mediana em fluxo:
`O(N log N)` de tempo e `O(N)` de memória. Exatidão sobre uma população
arbitrária exige a população. O ajuste é offline, e a memória é o recurso
barato — o dia em que não for, a troca por um esboço será um método novo com
versão nova.

**3. Por competição, e `GLOBAL` é recusado.** A população é de uma competição
só, por construção do tipo. Um artefato da Premier League não normaliza La
Liga, e a tentativa levanta em vez de devolver um número plausível.

**4. A identidade depende da população REAL.** `population_digest` é o hash da
população canonizada e ordenada. Dois ajustes que produzissem a mesma mediana
por coincidência têm impressões diferentes — porque não são o mesmo ajuste.

**5. `IQR = 0` é um ESTADO, e não um erro.** O artefato existe, é válido,
publica a mediana, e declara `DEGENERATE_SCALE`. A transformação devolve
indisponível com motivo, **e o valor cru continua válido**. Sem epsilon, sem
troca automática para média/desvio.

**6. Amostra insuficiente não publica mediana.** Abaixo do mínimo declarado, o
artefato é `INSUFFICIENT_SAMPLE` e não carrega parâmetros: calculá-los sobre
uma amostra declarada inadequada seria produzir o número e negar a política. O
mínimo vem da **declaração do normalizador**, e não de uma constante no código.

**Nenhum espaço de produção é normalizado neste PR.** `MATCH_STATE_RAW_V2`
continua cru. Qual população histórica, qual grade de cortes e qual divisão de
avaliação são decisões científicas que pertencem ao PR-05.5 — sem elas,
«ajustar o normalizador» não tem população bem definida.

## Consequências

**Positivas.** A escala é resistente ao 7 a 1. Ela nunca cruza ligas. A
identidade do ajuste depende do que ele viu, então dois artefatos só são
intercambiáveis quando são o mesmo. E o valor cru sobrevive à transformação —
«este `+1,4` veio de que número?» tem resposta seis meses depois.

**Negativas, e assumidas.** A memória é `O(N)`: ajustar sobre um milhão de
observações exige o milhão em memória. Competições com poucas partidas ficam
sem artefato até acumularem trinta observações disponíveis. E features cuja
distribuição é quase constante — escanteios num minuto, por exemplo — vão
produzir `DEGENERATE_SCALE` com frequência, o que é honesto e inconveniente.

**O que esta decisão NÃO fecha.** Winsorização, transformação logarítmica e
escala por temporada continuam possíveis, cada uma como método novo com versão
própria. O esboço aproximado volta à mesa quando houver um número mostrando que
a memória é o gargalo real.

## Alternativas consideradas

**Z-score (média/desvio).** Rejeitada: sensível a extremo, e o extremo é
exatamente o que o futebol produz.

**Escopo global.** Rejeitada: apaga a diferença entre ligas, que é justamente o
que se quer medir.

**Epsilon no denominador.** Rejeitada — é o defeito central que a seção 5
existe para impedir. Ela inventa uma escala e produz valores que parecem sinal.

**Fallback automático para média/desvio quando `IQR = 0`.** Rejeitada: dois
métodos sob o mesmo nome, e os valores dos dois seriam comparados como se
fossem a mesma medida.

**Min-max.** Rejeitada: um único jogo atípico comprime todo o resto.

**T-digest ou GK desde já.** Rejeitada por antecipação: resolve um problema de
memória que ainda não foi medido, ao custo de uma escala aproximada com erro
dependente da ordem de chegada.

## Referências

- ADR-0009 — ausente nunca vira zero
- ADR-0029 — features usam semântica temporal `AS_KNOWN`
- ADR-0030 — definições e espaços de feature são contratos versionados
- ADR-0034 — o mesmo método de quantil, no consenso de mercado
- `docs/features/ROBUST_NORMALIZATION_V1.md`
- `docs/features/NORMALIZATION_CONTRACT_V1.md`
