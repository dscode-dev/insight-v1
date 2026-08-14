# ADR-0021 — Atores humanos e de serviço

**Status:** aceito · **Data:** 2026-08-13

## Contexto

O PR-02 estabeleceu que toda mutação administrativa tem autor, e que o autor
nunca é um padrão global. O PR-03 acrescenta uma distinção que não existia:
algumas decisões são tomadas por CÓDIGO sob política declarada, e outras por
uma PESSOA que olhou dois candidatos e escolheu.

As duas são legítimas e têm garantias diferentes. Uma decisão automática é
reproduzível: mesma entrada, mesmas versões, mesmo resultado. Uma decisão
humana não é — e não precisa ser, porque ela carrega uma autoridade que o
automático não tem.

Confundi-las apaga a informação mais útil que a trilha guarda: quanto do
trabalho é automático, e quanto exige gente.

## Decisão

**`ActorKind` distingue quatro naturezas**, e duas delas são humanas:

```
HUMAN_OPERATOR   uma pessoa, pelo Control Plane
CLI              uma pessoa, por comando local
SERVICE          outro serviço do Insight
SYSTEM           um processo do próprio motor
```

`CLI` conta como humano — quem digitou o comando foi uma pessoa. O que a
distingue de `HUMAN_OPERATOR` é o CAMINHO, e a trilha registra a diferença:
«aprovou pelo console» e «rodou um comando local» são fatos distintos numa
investigação.

**Serviços são identificados pelo que SÃO:**

```
Actor.service("historical-resolution-worker")
Actor.service("historical-fusion-worker")
```

Nunca `system`. `Actor` recusa por nome — `system`, `admin`, `root`,
`unknown`, `anonymous`, `default` —, porque cada um deles, encontrado numa
trilha dois anos depois, significa exatamente «não sabemos quem fez».

**A coerência entre método e ator é COBRADA**, no domínio e no banco:

```sql
CHECK ((method = 'MANUAL_REVIEW') = (decided_by_kind IN ('HUMAN_OPERATOR','CLI')))
```

O método diz que um humano decidiu; o ator precisa concordar. E o inverso
também: um método automático atribuído a um humano é recusado, porque é assim
que a métrica de automação passa a mentir.

**A fila de revisão é humana por construção.** Um ator de serviço fechando um
item é o automático fingindo ter resolvido o que ele próprio não conseguiu.

**Isto NÃO é RBAC.** Não há papel, permissão nem política de autorização.
Construir um sistema de autorização antes de existir a segunda operação que
precisa de autorização diferente produz um sistema calibrado para um caso
hipotético.

## Consequências

**Ganhamos:** a pergunta «quanto da resolução é automática?» é uma consulta, e
«quem decidiu este merge» tem uma resposta que identifica uma pessoa.

**Pagamos:** toda operação precisa de um ator explícito, e a CLI dentro de um
contêiner — onde o usuário é `root` — falha até que alguém passe `--actor`. É
atrito real e é o atrito certo.

## Alternativas consideradas

**Um booleano `is_automated`.** Rejeitado: não distingue qual serviço, e a
trilha passaria a dizer «foi automático» sem dizer por qual código.

**Papéis e permissões desde já.** Rejeitado — ver acima.

**Aceitar `system` como identificador de processo.** Rejeitado: é o valor que
se encontra em toda trilha construída depois do fato, e ele não identifica
nada.

