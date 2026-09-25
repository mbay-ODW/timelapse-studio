#!/usr/bin/env bash
# Baut das Image auf dem Docker-Host und redeployt den Portainer-Stack.
# Nutzung: ./scripts-deploy.sh <ssh-host> <stack-id>
set -euo pipefail
HOST=${1:?ssh-host}; STACK=${2:?stack-id}
SSH="ssh -i $HOME/.ssh/id_ed25519_truenas -p 5022 $HOST"
TMP=$(mktemp -d)
git archive --format=tar.gz -o "$TMP/tls.tar.gz" HEAD
scp -q -i "$HOME/.ssh/id_ed25519_truenas" -P 5022 "$TMP/tls.tar.gz" docker-compose.yml "$HOST:/tmp/"
$SSH 'set -e; rm -rf /tmp/tls-build && mkdir /tmp/tls-build && tar -xzf /tmp/tls.tar.gz -C /tmp/tls-build
  cd /tmp/tls-build && sudo -n docker build -q -t timelapse-studio:latest . >/dev/null
  cp /tmp/docker-compose.yml /tmp/tls-compose.yml; rm -rf /tmp/tls-build /tmp/tls.tar.gz'
$SSH "python3 /tmp/tls-deploy.py update $STACK"
rm -rf "$TMP"
