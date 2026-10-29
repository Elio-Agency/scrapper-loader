#!/bin/bash
# GCP first-boot: tools only. Copy the repo, then create the venv (see create_vm.ps1).
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-pip python3-venv tmux unzip ca-certificates
touch /tmp/scrape-vm-ready
