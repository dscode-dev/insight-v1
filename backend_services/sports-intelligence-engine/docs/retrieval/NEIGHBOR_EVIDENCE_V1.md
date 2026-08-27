# `NeighborEvidence` — a prova mecânica de um vizinho

**PR:** 06.2 · **ADR:** [0044](../architecture/adr/0044-fixed-profile-iqr-missingness-penalty.md)

## O critério

> A partir da evidência de um vizinho, tem de ser possível **reconstruir** o
> número que o classificou, sem consultar mais nada.

```
D = (ObservedSquaredSum + MissingPenaltySum) / m
```

Se algum vizinho puder ocupar uma posição sem que essa reconstrução seja
possível, o ranking tem uma parte que ninguém consegue explicar — e um ranking
parcialmente inexplicável é indistinguível de um ranking com defeito.

Há teste de propriedade sobre toda a população e teste E2E sobre o dataset real:
`is_reconstructible` é verdadeiro para **todo** vizinho devolvido.

## O que ela carrega

```
candidate_key, candidate_row_digest      qual candidato, e o que ele continha
query_key, query_row_digest              qual query
resolved_profile_fingerprint             sob quais eixos
distance_definition_fingerprint          sob qual régua
coverage_policy_fingerprint              sob qual piso

query_mask       "111111"                posicional sobre o perfil ordenado
candidate_mask   "111000"
shared_mask      "111000"

coverage         CoverageAssessment      as contagens, e as frações derivadas
breakdown        DistanceBreakdown       as três parcelas

shared_features    (nomes dos eixos usados)
unshared_features  (nomes dos eixos ausentes)
contributions      por eixo compartilhado: q, c, δ²

evidence_fingerprint
```

### As três parcelas não são deriváveis do total

`D = 0,4` pode ser discrepância pura sobre o perfil inteiro ou incerteza pura
sobre metade dele, e as duas coisas dizem coisas **opostas** sobre a qualidade do
vizinho:

```
observed_squared_sum   Σ_S δ²             o que foi de fato medido
missing_penalty_sum    p·(m − s)          o que não foi
observed_mse           Σ_S δ² / s         a discrepância MÉDIA no observado
penalty_share          incerteza / numerador
```

**Um vizinho de 95 % de incerteza não é um vizinho de 5 %.** Os dois podem ter o
mesmo `D`, e o primeiro está dizendo «quase não te medi».

`observed_mse` é `None` quando `s = 0` — uma média de zero termos não é zero.
`penalty_share` é `None` quando o numerador é zero — o par é idêntico e
completo, e não há de que tirar fração.

## As máscaras são texto posicional

`"111000"`, e não `{"xg_home_10m", "xg_away_10m", "xg_diff_10m"}`:

```
posição     a posição i é o eixo i do perfil, que é o eixo i da soma
tamanho     um perfil de cem eixos são cem caracteres
impressão   um `set[str]` serializado depende da ordem de iteração de um dict
```

E elas são **consistentes entre si** por teste: `shared[i] = 1` se e só se
`query[i] = 1` e `candidate[i] = 1`.

## A impressão

Cobre identidade das duas linhas (por chave e digesto), as três impressões de
régua, as três máscaras, as **contagens** de cobertura e os números canônicos.

**As contribuições ficam de fora**: são derivadas exatas dos valores das duas
linhas sob a máscara, e as duas linhas já entram por digesto. Incluí-las
duplicaria informação e faria a impressão mudar conforme o retriever tenha ou
não decidido montá-las.

**As frações de cobertura também ficam de fora** — `coverage.as_canonical()`
carrega só `int`, porque as frações são derivadas exatas deles.

**E ela distingue máscaras com o mesmo `D`.** Dois vizinhos podem valer `0,2` —
um com quatro eixos exatos e um ausente, outro com cinco eixos e `δ² = 1` num
deles. O número é o mesmo e a evidência não é, e a impressão diz isso. É por
isso que a impressão do RESULTADO inclui a impressão da evidência de cada
vizinho.

## O que ela NÃO carrega

```
vencedor              gol seguinte          rótulo
placar final          trajetória futura     probabilidade
confiança             tendência             previsão
```

Cada ausência é a mesma decisão do PR-06.1, e há guarda arquitetural sobre o
vocabulário: um vizinho que carregasse o resultado faria a recuperação e a
inteligência compartilharem um objeto — e o dia em que alguém filtrasse
candidatos por rótulo, o vazamento estaria dentro do contrato.

## Isto não é explicabilidade

Não há frase, não há «este vizinho é parecido porque a pressão estava alta», não
há narrativa. Há máscaras, contagens e somas.

A explicabilidade é do PR-06.7, e ela vai ser construída **sobre** isto — o que é
diferente de ser isto. E a confiança também: `coverage` e `penalty_share` são o
insumo dela, e a conversão é uma decisão que ainda não tem com o que ser
calibrada.

## A memória

As contribuições por eixo são montadas **no fim**, para os `K` sobreviventes — e
não durante a varredura:

```
durante a varredura   O(lote + K·(1 linha + 4 números))
no fim                O(K · m) para as contribuições
nunca                 O(universo · m)
```

Montá-las para todo candidato faria a alocação seguir o universo, que é
exatamente o que o §66 proíbe. Medido: 13,7 MB de pico para cem queries sobre um
universo de 47 candidatos por query.
