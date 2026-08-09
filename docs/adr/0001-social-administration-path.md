# ADR 0001 — Como o Console administra o Insight Social

**Data:** 2026-08-07 · **Estado:** aceito, parcialmente implementado

---

## Contexto

O `insight-context.md` v2.0 diz três coisas que, juntas, não fechavam com o
código:

1. O Insight Gateway **não é responsável por** Administração, Operadores,
   Console nem Auditoria administrativa.
2. O Console **nunca acessa diretamente** os demais serviços — tudo passa pelo
   Insight Control Plane.
3. O Console tem **controle e gerência total dos módulos contidos no
   insight-social**.

O caminho real era:

```
Console → Control Plane → Gateway /v1/console/social/* → Social
```

O Gateway carregava **41 rotas administrativas** e o `SOCIAL_OPS_TOKEN`. Era um
terceiro numa conversa de dois.

E havia uma restrição de infraestrutura: o documento exige rede privada
(WireGuard/Tailscale) + mTLS entre servidores. **Não existe** — verificado no
Robozão: nenhuma interface `wg`/`tailscale`, nenhum dos binários instalado.

---

## Decisão

**Só o `insight-console-api` (Control Plane) fala com o plano do Google Cloud.**
O Social ganha uma rota de entrada própria e o Gateway sai do caminho
administrativo.

```
Console → Control Plane → Social   (/console/social/*, direto)
                        → Gateway  (só o que é de produto)
```

### O que sustenta a exposição do Social

Quatro controles independentes, porque qualquer um pode ser mal configurado:

| Controle | O quê |
|---|---|
| Path | O ingress roteia **só** `/console/social/` |
| TLS | cert-manager, emissor público |
| IP | Allow-list do endereço de saída do Robozão |
| **Token** | `SOCIAL_OPS_TOKEN` em **todas** as rotas |

> O token é o que de fato protege o dado. Os três primeiros restringem quem
> pode bater na porta; só o token decide quem é atendido. Essa ordem importa
> porque o allow-list de IP é o controle com maior chance de derivar — um
> endereço de saída muda, e a tentação é alargar.

### Duas credenciais, duas perguntas

`SOCIAL_OPS_TOKEN` prova que **quem chama** é o Control Plane.
`X-Operator-Id` diz **quem pediu**.

O Social exige o primeiro em toda rota e o segundo nas mutações, e grava o
segundo na auditoria. Um token sozinho atribuiria toda suspensão e banimento a
"o Control Plane".

---

## O que foi feito

| Mudança | Onde |
|---|---|
| Token exigido nas **15 rotas de leitura** do console | `insight-social` |
| Operador exigido e auditado nas mutações | `insight-social` |
| Ingress `/console/social/` com TLS + allow-list | `insight-social/k8s` |
| **NetworkPolicy corrigida** (ver abaixo) | `insight-social/k8s` |
| Módulo `social` com allow-list default-deny | `insight-console-api` |
| 15 proxies de leitura **removidos** | `insight-gateway` |
| Teste que trava a superfície administrativa | `insight-gateway` |
| Rate limiting no edge | `insight-gateway` |

### O bug que apareceu no caminho

A `NetworkPolicy` de produção do Social liberava a porta 8080 **só para o
Prometheus**. O Gateway chama `http://insight-social:8080` para busca (7
rotas), interações (save/boost), destaques de competição, perfil esportivo,
escrita de perfil e todas as leituras do console.

Aplicar a policy como estava cortava tudo isso em silêncio: o Gateway ficaria
pendurado até o timeout e devolveria 5xx, sem nada nos logs de nenhum dos dois
serviços apontando para a rede.

Passou despercebido porque a policy só existe no overlay de **produção** — o
`local-lab` não tem NetworkPolicy, então todo ambiente onde alguém desenvolve
se comporta diferente daquele onde importa.

---

## O que NÃO foi feito, e por quê

### 1. Moderação e Enforcement continuam no Gateway

O documento dá **Moderação** e **Enforcement** ao Social. As tabelas
(`moderation_user_state`, `moderation_hidden_content`, `moderation_reports`)
estão em `insight-gateway/migrations/00004_moderation.sql`.

As 13 rotas de comando (`ban`, `suspend`, `hide`, `restore`, `review`,
`resolve`, `dismiss`) **não são proxy** — são lógica real com autorização por
capability e espinha de auditoria, sobre dado que o Gateway possui.

> Remover a rota sem mover o dado não limpa nada: só tira o único jeito de
> alcançar um dado que continua ali.

Mover é **migração de dados entre serviços**, e não pode ser validada sem
acesso ao ambiente. Fica sequenciado abaixo.

### 2. As rotas `/v1/operator/auth/*` continuam

O Control Plane já é a autoridade de identidade. Estas permanecem como
fallback legado do Node Agent (inativo, `CONTROL_PLANE_TOKEN` preenchido) e
porque os handlers de console do próprio Gateway ainda verificam sessão contra
elas.

### 3. Nada foi verificado no ar

Não há acesso ao Google Cloud a partir deste ambiente. Tudo foi verificado por
build, `go vet` e testes locais. **Os manifests não foram aplicados.**

---

## Sequência do que falta

**A. Aplicar o que já existe** (você)
1. Preencher `whitelist-source-range` no `ingress-console.yaml` com o IP de
   saída real do Robozão.
2. Gerar `SOCIAL_OPS_TOKEN` e publicá-lo nos dois lados.
3. `SOCIAL_CONSOLE_BASE_URL` no `.env` do Robozão.
4. Aplicar a NetworkPolicy corrigida — hoje ela quebra busca e interações.

**B. Migrar moderação para o Social**
Mover as três tabelas e a lógica de enforcement. Depois disso, 13 rotas saem do
Gateway e o teste de fronteira encolhe.

**C. Encerrar `/v1/operator/auth/*`**
Quando nenhum handler do Gateway depender de sessão de operador.

**D. VPN**
Com WireGuard entre Robozão e GCloud, o ingress do Social é **deletado** e o
Control Plane passa a discar o ClusterIP. O Social sai da internet pública.

---

## Consequência aceita

Enquanto B não acontece, o Gateway continua servindo 26 rotas administrativas.
Isso é não-conformidade **conhecida e travada**: o teste
`TestAdministrativeSurfaceDoesNotGrow` fixa a lista exata, então ela só pode
diminuir. Adicionar uma rota exige editar o teste — ou seja, exige que alguém
decida.
