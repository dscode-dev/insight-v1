# ADR-0024 — Qualidade decide, construção consome

**Status:** aceito · **Data:** 2026-08-17

## Contexto

Há duas perguntas parecidas e diferentes:

```
este dado PODE ser usado?          qualidade
então CONSTRUA — com o quê?        build
```

O caminho curto é responder as duas no mesmo lugar: o construtor olha o
candidato, confere alguns limiares e materializa. Ele funciona no primeiro
dia e produz um defeito específico e caro — duas implementações da mesma
regra. Elas divergem no primeiro ajuste, e a divergência aparece como um fato
canônico construído sob um critério que ninguém declarou e que não bate com o
que o relatório de qualidade diz.

O segundo problema é que «pode ser usado» não é uma pergunta só. A mesma
partida entra num corpus de pesquisa com odds `RESEARCH_ONLY` e num corpus
comercial sem elas. Um construtor que decidisse sozinho precisaria de um
parâmetro de escopo espalhado por dentro dele.

## Decisão

**Um contrato, numa direção só:**

```
FusedCandidate
    → HistoricalQualityPolicy   → MatchQualityAssessment
    → CanonicalBuildPolicy      → BuildDecision
    → construtores tipados      → fatos canônicos
```

**A política de build LÊ o veredito e nunca as observações que o produziram.**
Ela não importa `QualityVector`, não chama `minimum_for`, não pesa problema.
Um teste de arquitetura lê a árvore sintática do módulo e falha se qualquer
uma dessas três coisas aparecer.

**Os construtores exigem a `BuildDecision` por assinatura.** `decision` é
parâmetro obrigatório de todo `build`, e cada um recusa com
`InvariantViolationError` quando a família que lhe pediram não está incluída
na decisão. A regra deixou de ser convenção e virou tipo.

**Não existe `build_everything`.** Cada família tem construtor próprio, com
contrato de entrada tipado — `MatchIdentityFacts`, `ScoreFacts`,
`LineupDraft`, `ObservationSet`. Não há `Match(**campos)`: a tradução entre a
saída fundida e o contrato canônico é explícita, campo a campo, e a falha de
conversão vira ausência declarada — nunca zero.

**A construção não resolve identidade.** `CanonicalMatchBuilder` exige
`MatchIdentityFacts`, que só se constrói com `CompetitionId`, `SeasonId` e
`TeamId` em mãos. Uma partida sem identidade canônica é recusada com motivo,
e não criada.

**Duas políticas sobre a mesma avaliação produzem corpus diferentes, e as
duas execuções coexistem.** `CanonicalBuildRun` guarda a versão da política de
build, o escopo e a versão da política de QUALIDADE sob a qual a avaliação
rodou — um build é explicável por duas políticas, e ter de buscar a segunda em
outra tabela faz alguém não buscar.

**A exclusão de família deixa rastro.** `canonical_build_family_decisions`
grava família, desfecho, motivo do catálogo fechado e a licença quando a causa
foi licença. Sem isso, «a fonte não trouxe odds» e «tínhamos odds e não
podíamos publicá-las» ficam iguais.

**Uma execução concluída é imutável, e uma que perdeu um fato não se declara
concluída.** `records_failed > 0` leva a `FAILED`, e uma constraint no banco
repete a regra: um corpus que perdeu partidas por conflito estrutural e
informa sucesso mente exatamente onde a mentira é mais cara.

## Consequências

**Ganhamos:** «por que este Match entrou no corpus» sai de uma junção —
registro de build → avaliação → grupo de fusão → `record_ref` → arquivo →
SHA-256 do objeto bruto. E o corpus de pesquisa e o comercial são a mesma
verdade com famílias diferentes, não dois pipelines.

**Pagamos:** um objeto a mais entre a avaliação e o fato (`BuildDecision`), e
um construtor por família em vez de um método. O primeiro é o preço de a
regra existir num lugar só; o segundo é o preço de cada família ter mapeamento
legível.

**Aceitamos:** a construção depende do que o contrato fundido carrega. Eventos
não têm papel semântico nenhum na V1, então não há `CanonicalEventBuilder` — e
a ausência está declarada em `BUILDABLE_FAMILIES`, verificada por teste de
arquitetura, em vez de um construtor vazio esperando dado que não chega.
