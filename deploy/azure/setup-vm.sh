#!/usr/bin/env bash
# Run ONCE on a fresh Ubuntu VM, as your normal user (not root):   bash deploy/azure/setup-vm.sh
set -euo pipefail

sudo apt-get update
sudo apt-get install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

# Folder shared between the worker container and the host. The sandbox containers mount code from here.
sudo mkdir -p /var/lib/sceptic/work
sudo chmod 1777 /var/lib/sceptic/work

echo
echo "Docker installed. Your docker group id (put it in deploy/azure/.env as DOCKER_GID): $(getent group docker | cut -d: -f3)"
echo "Log out and back in now, so the docker group applies, then continue with deploy/azure/deploy.sh"
