# Parte 7 — Insight Console

> **Papel em uma frase:** é a única interface humana da plataforma — e
> é deliberadamente burra, porque toda a autoridade vive no Control Plane.
>
> **Repositório:** `frontend/insight-console`
> **Framework:** Next.js 14.2 (App Router) + React 18.3 + TypeScript strict
> **Porta:** 3001 · **basePath:** `/console` · **Build:** `output: "standalone"`

---

## 1. A propriedade mais importante: ele não tem poder nenhum

Antes de qualquer coisa sobre telas, entenda isto:

```
$ docker exec insight-console printenv
CONSOLE_API_BASE_URL=http://insight-console-api:3002
COOKIE_SECURE=false
HOSTNAME=0.0.0.0
NEXT_PUBLIC_BASE_PATH=/console
NODE_ENV=production
PORT=3001
```

**Seis variáveis. Nenhum token de serviço.** O console não consegue
chamar o Explorer, o Atlas, o Anvil, o Nexus ou o Node Agent — não por
disciplina, mas porque não tem credencial nem rota para isso.

Isso é intencional e é o resultado direto da correção descrita na
[Parte 6](06-insight-control-plane.md). Uma interface é a superfície mais
exposta do sistema; ela deve ser a que menos pode fazer.

> **Consequência prática para quem desenvolve:** se uma tela nova
> precisa de um dado que o Control Plane não expõe, o trabalho é no
> Control Plane. Não existe atalho pelo console — e essa fricção é o
> ponto.

---

## 2. O caminho de uma requisição

```
Navegador
    │  GET /console/atlas/quality-gate
    ▼
nginx (Robozão)  ──►  insight-console:3001
    │
    ├─ middleware.ts        carimba x-request-id, checa o cookie
    │
    ├─ Server Component     renderiza a casca no servidor
    │
    └─ Client Component
           │  fetch("/console/api/v1/…")
           ▼
       app/api/v1/**/route.ts        ← o BFF
           │  controlPlaneFetch(path, { token })
           ▼
       insight-console-api:3002      ← o Control Plane decide tudo
           │
           ▼
       Explorer · Atlas · Node Agent · Gateway
```

O componente de cliente **nunca** fala com o Control Plane diretamente.
Ele fala com o próprio Next, que é quem tem acesso ao cookie HttpOnly.

---

## 3. O middleware — e uma decisão que parece errada

`middleware.ts` roda em **toda** requisição, antes de qualquer route
handler ou server component. Faz duas coisas:

1. Carimba `x-request-id` — os logs de todos os serviços pivotam nele.
2. Redireciona para `/login` quem não tem o cookie de sessão.

O ponto que costuma gerar dúvida está no próprio arquivo:

```typescript
// NOTE: we do NOT verify the JWT here. Edge runtime + jose's verify
// would force the JWKS into the Edge bundle. Cookie presence is a
// cheap gate; the JWT is verified inside each server component +
// route handler via `currentOperator()` / `requireOperator()`.
```

Ou seja: **o middleware não é uma checagem de segurança.** Ele é uma
conveniência de UX, para não renderizar uma tela que vai falhar de
qualquer jeito. A verificação real acontece depois, e — mais importante
— acontece **no Control Plane**, que é quem realmente decide.

> Cair nessa armadilha ao contrário é comum: alguém confia no middleware
> e esquece o `requireOperator()` no route handler. O middleware é a
> primeira porta, nunca a última.

---

## 4. `lib/control-plane/` — onde mora a lógica de verdade

Das ~6.000 linhas em `lib/`, a maioria está aqui. E este é o **único**
código do console com cobertura de teste (19 arquivos de teste).

```
lib/control-plane/
├── adapters/console-api.ts    o transporte até o Control Plane
├── security/                  authorize + audit spine
├── services/                  descritores de serviço e capabilities
├── registries/
├── quality-gate-routing.ts    classificador de escrita governada
├── explorer-ops-routing.ts    classificador default-deny
├── actor.ts                   identidade do operador
└── social-command.ts          o padrão canônico de mutação governada
```

### 4.1 Os classificadores, e o bug que um deles tinha

Nem toda escrita é igual. Uma decisão de promoção do Quality Gate é
**governada** (exige capability + auditoria); listar pipelines é
**ordinária**. Quem decide é o classificador.

A primeira versão tinha um defeito sutil: quando `decisionTargetId`
saía `null`, o caminho era classificado como *não governado* — **e
mesmo assim encaminhado**. Uma escrita que deveria exigir aprovação
passava sem auditoria.

A correção foi mudar o formato do retorno, de booleano para três
estados:

```typescript
type QualityGateWrite = "governed" | "ordinary" | "refuse";
```

E a regra que fecha o buraco:

> **Qualquer path terminando em `/decision` nunca é `ordinary`.** Ou é
> governado, ou é recusado. Não existe terceira saída.

Um booleano só tem dois valores, e "não consegui classificar" não é um
deles. Foi disso que o bug nasceu.

### 4.2 A leitura de configuração em tempo de chamada

```typescript
/**
 * Read at CALL time, not module load.
 *
 * A module-level capture is invisible to anything that sets the
 * variable afterwards, which makes this module untestable and makes a
 * config change depend on process restart order rather than on config.
 */
function baseUrl(): string {
  return (process.env.CONSOLE_API_BASE_URL ?? "http://insight-console-api:3002")
    .replace(/\/+$/, "");
}
```

Parece detalhe. Não é: capturar em tempo de módulo torna o comportamento
dependente da **ordem de carregamento dos módulos** — que é justamente o
tipo de coisa que muda sozinha quando o bundler reorganiza o build.

### 4.3 O ciclo de import que quebrou o build

`session.ts` importava `console-api.ts`, que importava `session.ts`.
Funcionava por hoisting — até `next build` seguir a cadeia e falhar com
`UnhandledSchemeError: node:crypto`, porque `session.ts` puxava
`node:crypto` para dentro do bundle.

A saída foi extrair `lib/session-cookie.ts`, com a única
responsabilidade de ler o cookie. O ciclo sumiu e o `node:crypto` deixou
de vazar.

---

## 5. A faxina: de 33 telas para 16

O console tinha **33 telas**. Uma auditoria feita chamando **cada API
contra a stack no ar** — não lendo código — mostrou que **14 não podiam
funcionar**:

| Sintoma | Telas |
|---|---|
| 401 (token de serviço placeholder) | 10 de Social, moderação, usuários |
| 500 | `operations/history` |
| 404 (a rota nem existe) | `analytics/publications` |
| 400 | `providers/status` |
| `upstream_unavailable` | administração |

O operador não tinha como distinguir "esta tela está vazia porque não há
dado" de "esta tela nunca funcionou".

### O menu novo: agrupado por plano

```
Visão geral
  └ Painel

Dados (Explorer)         8 telas
  Pipelines · Coletas · Curadoria · Qualidade
  Fontes · Fontes de sinal · Tickets · Runtime

Inteligência (Atlas)     4 telas
  Quality Gate · Inteligência · Conhecimento · Datasets

Governança               3 telas
  Auditoria · Operadores · Sessões
```

O **Quality Gate vem primeiro** dentro de Inteligência, de propósito: é
onde a aprovação humana que o `ATLAS_V1_FROZEN.md` exige acontece.

### Nada foi apagado

```typescript
/**
 * Telas removidas do menu, com o motivo. O CÓDIGO NÃO FOI APAGADO —
 * elas voltam assim que a dependência for resolvida, e apagar dez telas
 * funcionais por causa de um token faltando seria destrutivo.
 *
 * | Tela                  | Estado   | O que traz de volta            |
 * |-----------------------|----------|--------------------------------|
 * | /social/* (10 telas)  | 401      | ADMIN_API_INTERNAL_TOKEN real  |
 * | /publication-center   | —        | integração com o Nexus         |
 * | /operations/history   | 500      | Node Agent aceitar o Control Plane |
 * …
 */
export const REMOVED_FROM_NAV = [...] as const;
```

A tabela é o entregável real dessa faxina: ela diz **exatamente** o que
restaura cada tela. Sem ela, "sumiu do menu" viraria "foi perdido".

### A exceção que ficou

`/administration/operators` e `/sessions` **continuam no menu**, mesmo
vindo vazias. O motivo está no comentário:

> *"elas respondem com `feature_status: "upstream_unavailable"`
> explícito, e o operador precisa de um lugar para ver que a
> administração de identidade existe e está degradada — diferente de uma
> tela que simplesmente quebra."*

Degradação declarada é informação. Tela que quebra é ruído.

---

## 6. As regras de design das telas

Três regras foram aplicadas em todas as telas reescritas. Elas parecem
detalhes de UI e são, na prática, decisões sobre honestidade de dado.

### 6.1 `null` não é zero

```tsx
{/* "—" e não 0%: sem coleta não existe taxa, e 0% sugeriria que a
    fonte entregou lixo. */}
<p>{rate === null ? "—" : `${rate.toFixed(0)}%`}</p>
```

Zero é uma **medição**. "—" é a **ausência** de medição. Confundir os
dois cria incidente falso — alguém vai investigar uma fonte que nunca
teve problema.

A mesma regra no Atlas:

```tsx
{/* null NÃO é zero: significa que o sinal não pôde ser medido, e
    mostrá-lo como 0.00 sugeriria força nenhuma quando o certo é
    "não sei". */}
{s.strength == null ? "não medido" : s.strength.toFixed(2)}
```

### 6.2 Confiabilidade antes de conclusão

Em `atlas-intelligence-workspace`, o aviso de `sample_size = 0` aparece
**antes** das conclusões, não como rodapé. Uma conclusão lida primeiro e
qualificada depois já foi absorvida.

O mesmo em Fontes:

```tsx
{rows.length > 0 && neverRan === rows.length ? (
  <ErrorBanner>
    Nenhuma das {rows.length} fontes rodou um job ainda. Cadastrar a
    fonte não inicia coleta — isso acontece quando um pipeline é
    executado, em <strong>Pipelines</strong>.
  </ErrorBanner>
) : null}
```

O aviso não só diz o que está errado: diz **onde resolver**.

### 6.3 Estrutura, não JSON

A tela de Conhecimento do Atlas despejava seis blocos de
`JSON.stringify` num `<pre>`. Todo o dado estava lá e nenhum era
legível. A reescrita renderiza cada campo conforme o que ele **significa**
— e reordena, porque a pergunta operacional real é *"posso confiar nisso
agora?"*:

1. O que limita a confiança (riscos, lacunas)
2. O que o motor mede
3. O que melhoraria
4. **Guardrails** — o que o Atlas NÃO faz
5. Evolução dos modelos

O card de guardrails é o mais importante da tela:

```tsx
<p>
  Todos bloqueados é o estado correto. Qualquer um ativo significa que o
  Atlas passou a emitir previsão, aposta ou recomendação — o que o
  contrato dele proíbe.
</p>
```

Ele existe para que ninguém peça "só uma probabilidadezinha".

---

## 7. O painel

`platform-dashboard.tsx` substituiu o `operational-command-center` de
**1.606 linhas**, que buscava sete endpoints — **quatro inexistentes**.

```tsx
/** Uma fonte do painel. `error` distingue "não medido" de "medido como zero". */
interface Source<T = Row> {
  data: T | null;
  error: string | null;
}
```

O tipo carrega a regra. Não dá para renderizar um número sem antes
passar pelo `error`.

---

## 8. O guardião de fronteiras

`npm run check:boundaries` varre todo o código atrás de dependências de
serviços aposentados:

```javascript
const LEGACY = ["playmaker", "pundit", "atrium", "plaza", "insight-magnus"];
```

E é cuidadoso ao ponto de só sinalizar o que é **acionável**:

```javascript
// Only flag actionable dependencies: import/require statements and
// service URLs — not prose in comments.
```

Um checador que reclama de comentário histórico é desligado em uma
semana. Este roda junto de lint e typecheck.

---

## 9. Verificação — e uma lacuna declarada

Node/npm não existem na máquina de desenvolvimento. Tudo roda por
Docker:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "/c/Users/.../insight-v1:/work" -w /work/frontend/insight-console \
  node:22-alpine sh -c "npm run typecheck && npm run lint && \
                        npm run check:boundaries && npm run test"
```

> Use `npm install --no-package-lock`. O `package-lock.json` está
> dessincronizado do `package.json` desde antes deste trabalho, e
> `npm ci` falha por isso.

**A lacuna, dita sem rodeio:** os ~94 testes cobrem apenas `lib/`.
**Zero** testes tocam `app/api/**/route.ts`, `middleware.ts` ou
componentes React. Uma regressão de UI passa pela suíte inteira sem ser
notada.

Foi por isso que a auditoria das 33 telas precisou ser feita **chamando
as APIs contra a stack no ar**. Não havia como saber pelo código.

---

## 10. Configuração

| Variável | Observação |
|---|---|
| `CONSOLE_API_BASE_URL` | O Control Plane. A única dependência |
| `NEXT_PUBLIC_BASE_PATH` | `/console` — o nginx monta aí |
| `COOKIE_SECURE` | `false` hoje (sem TLS ainda) |
| `PORT` / `HOSTNAME` | 3001 / `0.0.0.0` |

`ADMIN_API_BASE_URL` e `ADMIN_API_INTERNAL_TOKEN` **não são lidas** —
deliberadamente. O caminho para o Gateway da nuvem passa pelo Control
Plane (`product-plane/`), como tudo o mais.

---

## 11. Estado atual

| Item | Estado |
|---|---|
| Imagem | `konohalabs/insight-console:1.6.0`, `healthy` |
| Telas no menu | **16**, todas respondendo 200 |
| Telas preservadas fora do menu | 17, com o motivo documentado |
| Tokens de serviço no container | **0** |
| Cobertura de teste | Só `lib/` — rotas e componentes descobertos |

---

## Próximo passo

**[Parte 8 — Node Agent (Robozão)](08-node-agent.md)**: o serviço que
sabe da máquina, e o proxy HTTP que ele não deve ter.
