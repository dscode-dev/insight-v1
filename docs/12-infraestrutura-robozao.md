# Parte 12 — Infraestrutura do Robozão

> **O que é o Robozão:** um Ubuntu Server rodando dentro do WSL2, numa
> máquina Windows. É onde vive todo o plano de inteligência e o plano de
> controle.
>
> **Arquivos:** `infra/robozao/`
> **Acesso:** `ssh -p 2222 ninja@172.23.207.224`

---

## 1. O que roda lá

```
$ docker ps
insight-console            1.6.0        (healthy)
insight-console-api        1.4.0        (healthy)   ← Control Plane
insight-atlas              1.0.4        (healthy)
insight-explorer           1.0.1        (healthy)
insight-anvil              0.0.4        (healthy)
insight-nexus              0.0.2        (healthy)
insight-sport-hub          0.0.3        (healthy)
insight-robozao-gateway    0.1.0        (healthy)   ← Node Agent
insight-postgres           pgvector/pgvector:pg16
insight-clickhouse         24.8-alpine
insight-redis              7.4-alpine
insight-qwen-runtime       ollama/ollama
portainer + agent          2.21.5                   ← Swarm
registry                   :2                       ← Swarm
```

Um Postgres com quatro schemas (`atlas`, `nexus`, `control_plane`,
`insight_social`), um Redis compartilhado por Atlas/Anvil/Nexus/Sport
Hub, um ClickHouse só do Anvil.

O `insight-qwen-runtime` é resíduo: nada o consome desde que o Nexus
passou a usar só provedores privados ([Parte 5](05-insight-nexus.md),
seção 6.3).

---

## 2. O nginx — default-deny por construção

A decisão central está no cabeçalho do `nginx/insight.conf`:

> *"Atlas, Explorer, Anvil, the Control Plane, Postgres, Redis and
> ClickHouse stay on the Docker network only — insight-context.md v2.0
> requires the Intelligence plane to be unreachable from outside, and
> **the way to guarantee that is to have no server block for it**."*

Três superfícies expostas, e nada mais:

| Caminho | Vai para |
|---|---|
| `/console/` | `127.0.0.1:3001` |
| `/portainer/` | `127.0.0.1:9000` |
| `/v2/` | `127.0.0.1:5000` (registry) |
| `/healthz` | o próprio nginx |
| **qualquer outra coisa** | **404** |

```nginx
# Default-deny. A request that matches no location above reaches no
# service — which is the whole point of listing the three that are
# allowed.
location / {
    return 404;
}
```

Uma allow-list de três entradas é auditável de relance. Uma deny-list
nunca está completa.

### 2.1 Console e Portainer, prefixos opostos

Isso confunde e vale fixar:

```nginx
# Console: prefixo PASSA (o app foi construído com basePath=/console)
location /console/ { proxy_pass http://insight_console; }

# Portainer: prefixo é REMOVIDO (a barra final no proxy_pass)
location /portainer/ { proxy_pass http://insight_portainer/; }
```

A diferença é **uma barra**. Ela existe porque o Next foi buildado com
`NEXT_PUBLIC_BASE_PATH=/console` e já emite URLs com o prefixo —
removê-lo quebraria todo asset que o HTML referencia. O Portainer serve
da raiz e **não suporta base path**.

E como o Portainer é uma SPA que monta URLs em JavaScript, remover o
prefixo não basta:

```nginx
sub_filter '<base href="/"' '<base href="/portainer/"';
```

Sem isso o Portainer pede `/api/...` na raiz e toma 404 atravessando o
proxy.

### 2.2 Onde os timeouts moram, e por quê

```nginx
# Timeouts are NOT set here. An `include` inlines into the location
# block, so a location that needs a longer read timeout (SSE, registry
# layers) would be declaring a duplicate rather than an override.
```

Um `include` do nginx é **inserção textual**, não herança. Timeout no
snippet compartilhado + timeout na location = diretiva duplicada, e o
nginx recusa a config. Por isso os padrões ficam no escopo `server` e as
locations sobrescrevem.

Foi um erro real de configuração; o comentário existe para não se
repetir.

### 2.3 O `map` que precisa ficar fora do server

```nginx
# conf.d-insight-upgrade.conf
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

Mandar `Connection: upgrade` em toda requisição quebra keep-alive nas
comuns. O valor tem que ser derivado de o cliente ter pedido upgrade —
e `map` só existe em escopo `http`, o que obriga esse arquivo a viver em
`conf.d/`, não junto do server block.

### 2.4 SSE

```nginx
location /console/ {
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

Com buffering ligado, o nginx segura cada evento até o buffer encher — o
tempo real vira lote. E o timeout padrão de 60s derrubaria uma conexão
saudável que está apenas esperando o próximo evento.

---

## 3. Chegar até lá da rede local

Esta é a parte que mais confunde, porque envolve três camadas de rede.

```
Celular na LAN                  192.168.x.x:80
      │
      ▼
Windows (portproxy)             netsh: 0.0.0.0:80 → <IP do WSL>:80
      │
      ▼
WSL2 / Ubuntu (nginx)           :80
      │
      ▼
Docker                          console:3001 · portainer:9000 · registry:5000
```

**O WSL2 não está na LAN.** Ele fica atrás de um switch virtual com NAT
— `172.23.207.224` não significa nada para outra máquina. Ligar o
console em `0.0.0.0` o tornou alcançável **deste** Windows, e de mais
nenhum lugar.

O script `windows/insight-lan-access.ps1` resolve com
`netsh interface portproxy`, e três decisões dele merecem nota:

**Só a porta 80 é encaminhada.**

```powershell
# Only what the reverse proxy serves. 3001/9000/5000 are deliberately
# NOT forwarded: they are reached through nginx on 80, so exposing them
# too would create a second door that bypasses its default-deny.
$Ports = @(80)
```

**A regra é reconstruída do IP atual, toda vez.** O IP do WSL muda a cada
boot, e uma regra apontando para um IP morto falha **em silêncio**: a
porta aceita a conexão e ninguém responde. Por isso o script faz
`delete` antes de `add` — `add` não substitui.

**O firewall abre só em Private/Domain.**

```powershell
# Scoped to private/domain profiles: this opens a port to the local
# network, and it should not follow the machine onto a coffee-shop
# Wi-Fi marked Public.
-Profile Private,Domain
```

Um notebook viaja. A regra não deve viajar junto.

> Para rodar no logon: registre com `schtasks /create /tn "Insight LAN
> access" /sc onlogon /rl highest ...` (o comando completo está no
> cabeçalho do script). Sem isso, é preciso rodar como admin depois de
> cada boot.

---

## 4. Portainer no Swarm — duas armadilhas

Ambas estão documentadas no `portainer-stack.yml`, porque ambas custaram
tempo.

### 4.1 O socket do Docker

```yaml
portainer:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock   # ← isto
```

Sem o socket montado, o log mostra *"Cannot connect to the Docker daemon
at unix:///var/run/docker.sock"* e **a interface fica vazia mesmo com o
agent respondendo**.

O engano é natural: se o `portainer/agent` está de pé e saudável, parece
que a comunicação existe. Mas **o agent serve para nós remotos** — ele
não substitui o acesso local do próprio Portainer. Dois mecanismos
diferentes que resolvem coisas diferentes.

### 4.2 A constraint de placement

```yaml
deploy:
  placement:
    constraints: [node.role == manager]
```

O socket do Docker só existe nos **managers**. Sem a constraint, o
scheduler pode colocar o Portainer num worker, onde o mount falha.

Hoje o cluster tem um nó só — a constraint é inerte. Ela existe para o
dia em que crescer, quando o sintoma seria "o Portainer parou de
funcionar e ninguém mexeu nele".

### 4.3 O Swarm ignora o endereço de bind

```yaml
ports:
  # ATENÇÃO: o Swarm IGNORA o endereço de bind aqui e publica em
  # 0.0.0.0 ("ignoring IP-address ... service will listen on 0.0.0.0").
  - "9000:9000"
```

No compose, `127.0.0.1:9000:9000` restringe à interface local. **No
Swarm, não** — a routing mesh não sabe fazer isso, e a porta fica
publicada em todas as interfaces.

O que de fato impede a LAN de bater direto na 9000 **não é essa linha**:
é o portproxy do Windows encaminhar somente a porta 80. Vale saber
exatamente qual controle está protegendo o quê — confiar no controle
errado é como se descobre tarde que não havia proteção nenhuma.

---

## 5. Estado atual e o que falta

| Item | Estado |
|---|---|
| nginx reverse proxy | **Configurado e no ar**, default-deny |
| Acesso pela LAN | **Funcionando** (portproxy + firewall) |
| Portainer | **No ar** em `/portainer/`, com socket montado |
| Registry | No ar em `/v2/` |
| Swarm | Inicializado — **só Portainer e registry** estão nele |
| TLS | **Ausente**, por decisão. `COOKIE_SECURE=false` |
| Stack da aplicação | Ainda em `docker compose`, não em Swarm |

### O que falta para fechar

**Converter a stack para Swarm.** Atlas, Explorer e Control Plane são os
candidatos a réplica e restart policy declarativos. O compose atual
funciona, mas não dá resiliência — um container que morre fica morto.

**TLS.** O nginx foi escrito para receber:

> *"When it lands: keep these blocks, add a 443 server, and redirect
> 80 → 443. Nothing here changes."*

Quando entrar, `COOKIE_SECURE=true` também muda — hoje é `false` porque
um cookie `Secure` sobre HTTP simplesmente não é enviado, e o login
falharia sem mensagem de erro útil.

---

## Próximo passo

**[Parte 13 — Deploy e migrations](13-deploy-e-migrations.md)**: como
subir, migrar e — principalmente — como verificar que subiu de verdade.
