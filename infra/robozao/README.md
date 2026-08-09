# Robozão — infraestrutura

Host: Ubuntu em WSL2 dentro do Windows. `ssh -p 2222 ninja@172.23.207.224`.
Stack em `~/Insight` no servidor; estes arquivos são a fonte da verdade.

## Reverse proxy (nginx)

Expõe **três** superfícies e nada mais. Atlas, Explorer, Anvil, Control
Plane, Postgres, Redis e ClickHouse não têm server block — o
`insight-context.md` v2.0 exige que o plano de inteligência seja
inalcançável de fora, e a forma de garantir isso é não existir rota.

| Rota | Destino | Observação |
|---|---|---|
| `/console/` | `127.0.0.1:3001` | prefixo preservado (o Next é buildado com `NEXT_PUBLIC_BASE_PATH=/console`); SSE sem buffering |
| `/portainer/` | `127.0.0.1:9000` | prefixo removido; `sub_filter` reescreve o `<base href>` do SPA |
| `/v2/` | `127.0.0.1:5000` | registry Docker; upload sem limite e timeout de 900s |
| qualquer outra | — | **404 (default-deny)** |
| `/healthz` | — | liveness do próprio proxy, para distinguir "nginx caiu" de "console caiu" |

Instalação:

```bash
sudo install -m 0644 conf.d-insight-upgrade.conf     /etc/nginx/conf.d/insight-upgrade.conf
sudo install -m 0644 snippets-insight-proxy.conf     /etc/nginx/snippets/insight-proxy.conf
sudo install -m 0644 insight.conf                    /etc/nginx/sites-available/insight
sudo ln -sf /etc/nginx/sites-available/insight /etc/nginx/sites-enabled/insight
sudo rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/docker-registry
sudo nginx -t && sudo systemctl reload nginx
```

O site antigo `docker-registry` **precisa** sair: ele declara
`server_name 172.23.207.224`, que vence do `default_server` para esse
Host, e `/console` cairia no registry. O `/v2/` foi absorvido aqui.

Duas armadilhas do nginx que já custaram um reload falho:

- `proxy_read_timeout` e afins ficam no escopo **server**, não no snippet
  compartilhado. Um `include` inlina no bloco da location, então um
  override viraria diretiva duplicada e o `nginx -t` recusa.
- `sub_filter_types text/html` é redundante: `text/html` já é o default,
  e repetir gera warning de MIME duplicado.

## Portainer

`portainer-stack.yml` — `docker stack deploy -c portainer-stack.yml portainer`.

Duas coisas que deixam um Portainer em Swarm com a interface **vazia**:

1. **O container do Portainer precisa do socket do Docker montado.** Era
   exatamente o que faltava aqui: só `portainer_data` estava montado, e
   o log repetia `Cannot connect to the Docker daemon at
   unix:///var/run/docker.sock`. O `agent` serve para descobrir nós
   remotos; ele **não** substitui o acesso local do próprio Portainer.
2. **O socket só existe nos managers.** Sem
   `constraints: [node.role == manager]` o scheduler pode colocá-lo num
   worker, onde o mount falha. Com um nó só isso não acontece, mas a
   constraint é o que impede o problema de virar mistério quando o
   cluster crescer.

Uma pegadinha do Swarm que vale saber: ele **ignora** o endereço de bind
em `ports` (`"127.0.0.1:9000:9000"` vira `0.0.0.0:9000`) e avisa no
deploy. A routing mesh não restringe porta publicada a uma interface.
Quem impede a LAN de bater direto na 9000 é o portproxy do Windows, que
encaminha somente a porta 80.

## Acesso pela rede local

`windows/insight-lan-access.ps1`, **como administrador no Windows**.

WSL2 não fica na LAN: é NAT. `172.23.207.224` não existe para outras
máquinas. O script cria um `netsh portproxy` de `0.0.0.0:80` para o IP
atual do WSL, mais a regra de firewall (perfis Private/Domain apenas).

Ele **precisa rodar a cada boot**: o IP do WSL muda, e uma regra
apontando para um IP morto falha em silêncio — a porta aceita a conexão
e ninguém responde. Registre no logon:

```powershell
schtasks /create /tn "Insight LAN access" /sc onlogon /rl highest ^
  /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Ninja\Documents\Projetos\insight-v1\infra\robozao\windows\insight-lan-access.ps1"
```

Só a porta 80 é encaminhada. 3001/9000/5000 ficam de fora de propósito:
são alcançados via nginx, e expô-las criaria uma segunda porta que
ignora o default-deny dele.
