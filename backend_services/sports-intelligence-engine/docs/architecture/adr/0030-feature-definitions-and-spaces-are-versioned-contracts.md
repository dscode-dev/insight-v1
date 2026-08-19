# ADR-0030 — Definições e espaços de feature são contratos semânticos versionados

**Status:** aceito · **Data:** 2026-08-19

## Contexto

Uma feature parece um nome com um cálculo pendurado: `shots_home_5m` conta
finalizações do mandante nos últimos cinco minutos. A aparência engana em dois
pontos, e os dois custam caro meses depois.

**O primeiro: o nome não define a semântica.** «Últimos cinco minutos» a partir
de quando — do relógio do jogo ou do tempo corrido? Inclui o minuto do corte?
Conta finalização bloqueada? Cada resposta é uma feature diferente com o mesmo
nome, e a troca de uma pela outra não quebra nada visível: o número continua
sendo um número plausível.

**O segundo: um conjunto de features não é um saco de features.** Ele vira um
vetor, e um vetor tem ORDEM. `[f1, f2, f3]` e `[f3, f1, f2]` carregam os mesmos
números em eixos diferentes; a distância entre um vetor de um e um vetor do
outro é aritmética sobre dimensões trocadas. Ela **não falha — mente**.

O sistema já resolveu esse tipo de problema três vezes, e sempre do mesmo
jeito: política de resolução, política de qualidade e política de build têm
versão e impressão. O que faltava era aplicar a mesma regra às features.

## Decisão

**Uma `FeatureDefinition` é um contrato semântico com identidade de três
partes, e um `FeatureSpaceDefinition` é um conjunto ORDENADO com identidade
própria.**

```
FeatureIdentity       = Key + Version + ContentFingerprint
FeatureSpaceIdentity  = Nome + Versão + Impressão(ordem + conteúdo)
```

**1. A impressão fecha o que a declaração deixa aberto.** Chave e versão são
declaração humana e podem mentir — alguém muda a janela de 5 para 10 e esquece
de subir a versão. A impressão não deixa: o conteúdo mudou, a identidade mudou,
e a comparação entre o antes e o depois passa a ser explicitamente entre coisas
diferentes.

O que entra: tipo de saída, escopo, classe temporal, famílias exigidas,
parâmetros, semântica de ausência, contrato de normalização. O que **não**
entra: descrição, carimbo de criação, `repr` de objeto — coisas que mudam sem
mudar o que a feature calcula.

**2. A ordem do espaço é conteúdo.** Ela entra na impressão com a posição de
cada feature. Dois espaços com as mesmas features em ordens diferentes têm
impressões diferentes, e é isso que impede vetores incomparáveis de se
passarem por comparáveis.

**3. O registro recusa identidade ambígua.** Mesma chave e versão com
impressões diferentes é erro — não uma coincidência a resolver na leitura.

**4. As exigências de corpus são declaradas, e conferidas antes do cálculo.**
`requires EVENT` é uma afirmação sobre a VERSÃO do corpus publicar a família, e
não sobre toda partida ter eventos. A incompatibilidade aparece antes de compor,
e não na décima milésima partida.

**5. O snapshot herda as quatro identidades.**

```
SameCorpus + SameFeatureSpace + SameAsOf + SameTemporalPolicy
    ⇒  SameFeatureSnapshot
```

Nada incidental entra: id de execução, carimbo, id de processo, id de linha. Um
snapshot que mudasse de identidade por ter sido recalculado não serviria para
comparar nada.

## Consequências

**O que fica possível.** Afirmar, meses depois, que dois números chamados
`shots_home_5m` são a mesma medida — ou provar que não são. E comparar dois
estados históricos sabendo que os eixos deles são os mesmos.

**O que fica proibido.** Mudar a semântica de uma feature mantendo a
identidade; montar um espaço com features de mesma chave; declarar um espaço
comparável ao vivo com features pós-jogo ou verdade retrospectiva.

**O custo que isto cobra.** Toda mudança de parâmetro é uma identidade nova, e
uma identidade nova invalida comparações com o histórico anterior. É o custo
certo: a alternativa é comparar coisas diferentes sem saber.

**O que este ADR NÃO decide.** Como o vetor será representado, se haverá
`float32`, como as dimensões serão pesadas na distância. Isso é PR-05.2/05.3 e
PR-06 — e por isso `FeatureOutputType` não tem `VECTOR`: introduzi-lo agora
tomaria essa decisão por antecipação.

## Alternativas consideradas

**Catálogo de features em PostgreSQL.** Responderia «quais features existem» de
um jeito que o código-fonte já responde, e criaria uma segunda verdade: a linha
diz janela de 5 e a definição no código diz 10. O registro declarativo é
reproduzível por construção e versionado pelo git.

**Identificar features só por `key@version`.** Metade da proteção. É
exatamente o caso em que alguém muda a semântica e esquece a versão — o mais
comum, e o que a impressão pega.

**Deixar a ordem fora da identidade do espaço, e ordenar por nome na
serialização.** Funcionaria enquanto ninguém renomeasse uma feature. No dia em
que alguém renomeasse, todos os vetores gravados trocariam de eixos em silêncio.
