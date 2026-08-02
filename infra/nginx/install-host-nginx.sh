#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo $0" >&2
  exit 1
fi

source_config="/home/insight/robozao/nginx/insight-robozao-console.host.conf"
available_config="/etc/nginx/sites-available/insight-robozao-console.conf"
enabled_config="/etc/nginx/sites-enabled/insight-robozao-console.conf"
docker_proxy="insight-nginx"
host_header="insight-robozao.konohalabs.lab"

rollback() {
  echo "Host Nginx validation failed; restoring the Docker proxy." >&2
  systemctl stop nginx >/dev/null 2>&1 || true
  docker start "${docker_proxy}" >/dev/null 2>&1 || true
}

trap rollback ERR

test -r "${source_config}"
curl --fail --silent --show-error \
  http://127.0.0.1:3001/console/api/health >/dev/null

install -o root -g root -m 0644 "${source_config}" "${available_config}"
ln -sfn "${available_config}" "${enabled_config}"
rm -f /etc/nginx/sites-enabled/default

nginx -t

docker stop "${docker_proxy}" >/dev/null
systemctl enable --now nginx

curl --fail --silent --show-error \
  -H "Host: ${host_header}" \
  http://127.0.0.1/console/login >/dev/null

docker update --restart=no "${docker_proxy}" >/dev/null
docker rm "${docker_proxy}" >/dev/null

trap - ERR
echo "Host Nginx is active and /console/login is healthy."
