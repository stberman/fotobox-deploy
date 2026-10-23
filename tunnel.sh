#!/bin/bash
# Startet einen Cloudflare Quick-Tunnel auf die Fotobox-App und schreibt die
# zugewiesene oeffentliche URL nach public_url.txt, damit die App sie fuer die
# QR-Codes verwenden kann. Wird von fotobox-tunnel.service gestartet.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URLFILE="$DIR/public_url.txt"
PORT="${FOTOBOX_PORT:-5000}"

# Beim Beenden (Stop, Absturz) die alte URL verwerfen -> QR-Codes zeigen wieder lokal.
trap ': > "$URLFILE"' EXIT
: > "$URLFILE"

if [ -e /var/lib/fotobox/autark ]; then
  echo "[tunnel.sh] Autark-Modus aktiv - kein Tunnel."
  exit 0
fi

# --protocol http2: viele Netze blockieren QUIC/UDP 7844 -> TCP-Fallback erzwingen
/usr/local/bin/cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate --protocol http2 2>&1 |
while IFS= read -r line; do
  echo "$line"
  url=$(printf '%s' "$line" | grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' | head -1)
  if [ -n "${url:-}" ]; then
    printf '%s' "$url" > "$URLFILE"
    echo "[tunnel.sh] Oeffentliche URL: $url"
  fi
done
