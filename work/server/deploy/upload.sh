#!/usr/bin/env bash
# Run this from your PC (Git Bash) to copy the server up to the VM.
# It skips build junk, logs, and local caches so only what the VM needs goes up.
#
#   bash deploy/upload.sh ubuntu@YOUR_PUBLIC_IP ~/.ssh/your_oracle_key
#
set -euo pipefail

DEST="${1:?usage: upload.sh user@public_ip [ssh_key_path]}"
KEY="${2:-}"
SSH_OPTS=()
[ -n "$KEY" ] && SSH_OPTS=(-i "$KEY")

# This script lives in work/server/deploy — the server root is its parent.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Uploading $HERE  ->  $DEST:/opt/pogo"
# Create /opt/pogo owned by the login user so scp can write without sudo.
ssh "${SSH_OPTS[@]}" "$DEST" 'sudo mkdir -p /opt/pogo && sudo chown "$USER" /opt/pogo'

if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete \
    --exclude '__pycache__/' \
    --exclude 'build/' --exclude 'dist/' \
    --exclude '*.spec' \
    --exclude 'server-log.txt*' \
    --exclude 'photos/' --exclude '_probe.js' --exclude '_hook.js' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$HERE"/ "$DEST":/opt/pogo/
else
  echo "    (rsync not found; using scp — slower, no exclude)"
  scp "${SSH_OPTS[@]}" -r "$HERE"/* "$DEST":/opt/pogo/
fi

echo "==> Uploaded. Now on the VM run:"
echo "    ssh ${SSH_OPTS[*]:+${SSH_OPTS[*]} }$DEST"
echo "    sudo bash /opt/pogo/deploy/setup-vm.sh"
