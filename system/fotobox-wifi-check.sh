#!/bin/bash
# Fotobox WLAN-Check (laeuft als root ueber fotobox-wifi.service).
#
# Beim Boot und bei jedem 'systemctl restart fotobox-wifi':
#   * Autark-Flag gesetzt      -> Hotspot sofort starten, Tunnel stoppen
#   * sonst bis WAIT Sekunden  -> warten, ob NetworkManager ein bekanntes WLAN
#                                 (oder Kabel) verbindet; dann Tunnel starten
#   * kein Netz gefunden       -> WLAN-Scan zwischenspeichern (im Hotspot-Modus
#                                 kann wlan0 nicht scannen) und Hotspot starten
#
# Der Hotspot ist ein normales NetworkManager-Profil ("Fotobox-AP", vom
# Installer angelegt, autoconnect=no), damit er nie von selbst startet.
set -u

STATE_DIR=/var/lib/fotobox
AP_CON="${AP_CON:-Fotobox-AP}"
WAIT="${WAIT:-45}"

log() { echo "[fotobox-wifi] $*"; }

ap_active() {
  nmcli -t -f NAME con show --active 2>/dev/null | grep -qx -- "$AP_CON"
}

# true, wenn eine "echte" Verbindung steht (WLAN-Client oder Ethernet, nicht der Hotspot)
online() {
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status 2>/dev/null |
    awk -F: -v ap="$AP_CON" '($2=="wifi"||$2=="ethernet") && $3=="connected" && $4!=ap {f=1} END{exit !f}'
}

cache_scan() {
  # Scan-Ergebnis fuer die /wlan-Seite sichern, solange wlan0 noch scannen kann.
  mkdir -p "$STATE_DIR"
  if nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list --rescan yes 2>/dev/null > "$STATE_DIR/scan.txt.tmp"; then
    mv -f "$STATE_DIR/scan.txt.tmp" "$STATE_DIR/scan.txt"
  else
    rm -f "$STATE_DIR/scan.txt.tmp"
  fi
}

ap_up() {
  systemctl stop --no-block fotobox-tunnel 2>/dev/null || true
  if ap_active; then
    log "Hotspot laeuft bereits."
    return 0
  fi
  cache_scan
  if nmcli con up "$AP_CON" >/dev/null 2>&1; then
    log "Hotspot '$AP_CON' gestartet."
  else
    log "FEHLER: Hotspot '$AP_CON' konnte nicht gestartet werden (nmcli con show $AP_CON pruefen)."
    return 1
  fi
}

mkdir -p "$STATE_DIR"
rfkill unblock wifi 2>/dev/null || true

if [ -e "$STATE_DIR/autark" ]; then
  log "Autark-Modus aktiv -> eigener Hotspot."
  ap_up
  exit $?
fi

if ap_active; then
  # z.B. nach Abschalten des Autark-Modus: Hotspot beenden, damit NetworkManager
  # die gespeicherten WLANs automatisch probiert.
  log "Hotspot beenden, bekannte Netze probieren ..."
  nmcli con down "$AP_CON" >/dev/null 2>&1 || true
fi

for ((i = 0; i < WAIT; i++)); do
  if online; then
    log "Netzwerk verbunden: $(nmcli -t -f NAME con show --active | grep -vx -- "$AP_CON" | tr '\n' ' ')"
    systemctl start --no-block fotobox-tunnel 2>/dev/null || true
    exit 0
  fi
  sleep 1
done

log "Nach ${WAIT}s kein bekanntes Netz -> Hotspot als Fallback."
ap_up
