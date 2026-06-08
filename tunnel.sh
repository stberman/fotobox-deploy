#!/bin/bash
# Startet einen Cloudflare Quick-Tunnel auf die Fotobox-App und schreibt die
# zugewiesene oeffentliche URL nach public_url.txt, damit die App sie fuer die
# QR-Codes verwenden kann.
set -u
URLFILE="/home/admin/fotobox/public_url.txt"
: > "$URLFILE"

# --protocol http2: viele Netze blockieren QUIC/UDP 7844 -> TCP-Fallback erzwingen
/usr/local/bin/cloudflared tunnel --url http://localhost:5000 --no-autoupdate --protocol http2 2>&1 |
while IFS= read -r line; do
  echo "$line"
  url=$(printf '%s' "$line" | grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' | head -1)
  if [ -n "${url:-}" ]; then
    printf '%s' "$url" > "$URLFILE"
    echo "[tunnel.sh] Oeffentliche URL: $url"
  fi
done
