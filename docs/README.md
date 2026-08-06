# Apostila da Plataforma Insight

Documentação de engenharia da plataforma Insight, escrita para ser lida
por quem está chegando agora. Não assume conhecimento prévio do projeto.

**Como usar:** leia na ordem. Cada parte pressupõe apenas as anteriores.
Se você só precisa mexer num serviço específico, leia as Partes 0 e 1
(que dão o mapa) e depois pule direto para a parte dele.

**Convenção de idioma:** o texto é em português. Nomes de código,
métodos, arquivos, variáveis de ambiente e trechos de código ficam em
inglês, como estão no repositório — traduzir isso só criaria uma segunda
nomenclatura que não existe em lugar nenhum.

---

## Ordem recomendada

### Fundamentos — leia antes de qualquer coisa

| Parte | Assunto | Por que vem aqui |
|---|---|---|
| [0](00-visao-geral.md) | Visão geral e os dois planos | O mapa. Sem ele, nenhum serviço faz sentido isolado |
| [1](01-conceitos-e-fluxos.md) | Conceitos e fluxos ponta a ponta | O vocabulário do projeto e como um dado atravessa a plataforma |

### Plano de Inteligência — o núcleo do produto

Vem antes do Product Plane porque é onde está a lógica que dá valor à
plataforma. O Product Plane, em boa medida, existe para entregar o que
esta camada produz.

| Parte | Serviço | Papel em uma frase |
|---|---|---|
| [2](02-insight-explorer.md) | `insight-explorer` | Descobre e normaliza dados externos |
| [3](03-insight-atlas.md) | `insight-atlas` | Transforma dados em inteligência (similaridade, contexto) |
| [4](04-insight-anvil.md) | `insight-anvil` | Persiste histórico analítico no ClickHouse |
| [5](05-insight-nexus.md) | `insight-nexus` | Orquestra agentes de IA que publicam |

### Plano de Controle — como se opera a plataforma

| Parte | Serviço | Papel em uma frase |
|---|---|---|
| [6](06-insight-control-plane.md) | `insight-console-api` | **É o Control Plane.** Autentica operadores, autoriza, audita, encaminha |
| [7](07-insight-console.md) | `insight-console` | A interface administrativa (Next.js) |
| [8](08-node-agent-robozao.md) | `insight-robozao-gateway` | Representa a máquina física perante o Control Plane |

### Plano de Produto — o que o usuário final vê

| Parte | Serviço | Papel em uma frase |
|---|---|---|
| [9](09-insight-gateway.md) | `insight-gateway` | Porta de entrada pública das APIs |
| [10](10-insight-social.md) | `insight-social` | A rede social |
| [11](11-insight-sport-hub.md) | `insight-sport-hub` | Ingestão de dados esportivos dos provedores |

### Operação

| Parte | Assunto |
|---|---|
| [12](12-infraestrutura-robozao.md) | O servidor Robozão: Docker, nginx, Swarm, acesso |
| [13](13-deploy-e-migrations.md) | Como subir, migrar e verificar |
| [14](14-decisoes-e-armadilhas.md) | Decisões arquiteturais e armadilhas já pagas |

---

## O que esta apostila NÃO é

- **Não é referência de API.** Contratos vivem no código e nos
  `.proto`; duplicá-los aqui garante que uma das duas cópias estará
  errada em duas semanas.
- **Não é changelog.** O histórico está no git.
- **Não descreve o que queremos ter.** Descreve o que existe hoje.
  Quando algo está incompleto, isso é dito explicitamente, com o motivo
  — um documento que descreve o estado desejado como se fosse o atual é
  pior do que não ter documento.

## Estado desta apostila

Escrita em 2026-08-06. As partes marcadas com **(pendente)** no índice
ainda não foram escritas; as demais refletem o código na data acima.

Se você encontrar divergência entre a apostila e o código, **o código
está certo** — abra correção aqui.
