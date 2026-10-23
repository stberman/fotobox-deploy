#!/bin/bash
# ============================================================================
#  Fotobox - Installer / Updater fuer Raspberry Pi OS (Bookworm/Trixie, Lite
#  oder Desktop, Pi 4 / Pi 5, 64-bit empfohlen)
#
#  Erstinstallation (nach Flash + SSH-Login, ein Befehl):
#     curl -fsSL https://raw.githubusercontent.com/stberman/fotobox-deploy/main/install.sh | sudo bash
#
#  Update (irgendwann spaeter, identisch):
#     sudo ~/fotobox/install.sh          (oder derselbe curl-Befehl)
#
#  Alles ist idempotent: jeder Schritt prueft, was schon da ist.
#  Einstellbar per Umgebungsvariable, z.B.:
#     sudo AP_SSID=MeineBox AP_PASSWORD=geheim123 bash install.sh
# ============================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/stberman/fotobox-deploy.git}"
BRANCH="${BRANCH:-main}"
AP_SSID="${AP_SSID:-Fotobox}"
AP_PASSWORD="${AP_PASSWORD:-fotobox123}"
AP_CON="Fotobox-AP"
AP_IP="10.42.0.1"
HOSTNAME_WANTED="${FOTOBOX_HOSTNAME:-fotobox}"
WIFI_COUNTRY="${WIFI_COUNTRY:-DE}"
STATE_DIR=/var/lib/fotobox
PORT=5000

# ---------------------------------------------------------------------------
c_ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[1;34m[..]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[1;33m[!!]\033[0m %s\n' "$*"; }
die()    { printf '\033[1;31m[FEHLER]\033[0m %s\n' "$*" >&2; exit 1; }

main() {
[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo ausfuehren:  sudo bash install.sh"

# Zielbenutzer: der, der 'sudo' aufgerufen hat; sonst der erste normale Benutzer (UID 1000).
FB_USER="${SUDO_USER:-}"
if [ -z "$FB_USER" ] || [ "$FB_USER" = "root" ]; then
  FB_USER="$(getent passwd 1000 | cut -d: -f1 || true)"
fi
[ -n "$FB_USER" ] || die "Konnte keinen normalen Benutzer finden. Mit 'sudo' als normaler Benutzer ausfuehren."
FB_HOME="$(getent passwd "$FB_USER" | cut -d: -f6)"
[ -d "$FB_HOME" ] || die "Home-Verzeichnis von $FB_USER nicht gefunden."

# Installationsordner: liegt dieses Skript schon in einem Repo-Checkout, dann dort;
# sonst (curl | bash) ~/fotobox des Zielbenutzers.
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/app.py" ]; then
  DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  DIR="${FOTOBOX_DIR:-$FB_HOME/fotobox}"
fi

ARCH="$(dpkg --print-architecture)"
echo
echo "================  Fotobox-Installer  ================"
echo "  Benutzer : $FB_USER"
echo "  Ordner   : $DIR"
echo "  System   : $(. /etc/os-release && echo "$PRETTY_NAME") ($ARCH)"
echo "  Hotspot  : SSID '$AP_SSID'"
echo "====================================================="
echo

as_user() { sudo -u "$FB_USER" -H "$@"; }

# ---------------------------------------------------------------------------
# Ein frisch geflashter Pi hat eine falsche Uhrzeit, bis NTP greift. Dann scheitern
# apt ("Not live until ...") und pip ("certificate is not yet valid"). Also warten.
if command -v timedatectl >/dev/null 2>&1; then
  ntp_ok() { [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ]; }
  if ! ntp_ok; then
    c_info "Warte auf Zeitsynchronisation (Uhr steht auf $(date '+%d.%m.%Y %H:%M')) ..."
    timedatectl set-ntp true 2>/dev/null || true
    systemctl restart systemd-timesyncd 2>/dev/null || true
    for _ in $(seq 1 45); do ntp_ok && break; sleep 2; done
  fi
  if ntp_ok; then
    c_ok "Uhrzeit synchron: $(date '+%d.%m.%Y %H:%M:%S')"
  else
    c_warn "Keine Zeitsynchronisation (kein Internet?). Downloads koennen an Zertifikaten scheitern."
  fi
fi

# ---------------------------------------------------------------------------
c_info "Systempakete installieren ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl gphoto2 python3 python3-venv python3-pil \
  network-manager dnsmasq-base avahi-daemon nftables rfkill fonts-dejavu-core >/dev/null
c_ok "Systempakete"

# ---------------------------------------------------------------------------
if [ -d "$DIR/.git" ]; then
  c_info "Projekt aktualisieren (git pull) ..."
  as_user git -C "$DIR" pull --ff-only -q || c_warn "git pull fehlgeschlagen (lokale Aenderungen?). Mache mit vorhandenem Stand weiter."
elif [ -f "$DIR/app.py" ]; then
  c_warn "$DIR ist kein Git-Checkout (z.B. per scp kopiert) - kein Update, vorhandene Dateien werden benutzt."
else
  c_info "Projekt klonen nach $DIR ..."
  as_user git clone -q --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
chown -R "$FB_USER:" "$DIR"
chmod +x "$DIR"/install.sh "$DIR"/tunnel.sh "$DIR"/system/*.sh "$DIR"/system/90-fotobox-ap 2>/dev/null || true
c_ok "Projekt in $DIR"

# ---------------------------------------------------------------------------
c_info "Python-Umgebung ..."
# --system-site-packages: Pillow kommt vom System (python3-pil), siehe requirements.txt
if [ ! -x "$DIR/venv/bin/python" ]; then
  as_user python3 -m venv --system-site-packages "$DIR/venv"
fi
as_user "$DIR/venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
as_user "$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt" || die "pip install fehlgeschlagen (Internet/Uhrzeit pruefen: timedatectl)"
as_user "$DIR/venv/bin/python" -c "import flask, qrcode, PIL" || die "Python-Module fehlen (siehe Ausgabe oben)."
c_ok "venv + Abhaengigkeiten"

# ---------------------------------------------------------------------------
c_info "Benutzerrechte & Kamera ..."
for g in plugdev netdev video; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$FB_USER"
done
# Desktop-Images: gvfs greift sich sonst die Kamera (Lite hat die Datei nicht).
GVFS=/usr/share/gvfs/remote-volume-monitors/gphoto2.monitor
if [ -f "$GVFS" ]; then
  mv "$GVFS" "$GVFS.disabled"
  c_ok "gvfs-Kamera-Monitor deaktiviert"
fi
mkdir -p "$DIR/photos/originals" "$DIR/static/thumbs" "$DIR/overlays" "$STATE_DIR"
chown -R "$FB_USER:" "$DIR/photos" "$DIR/static" "$DIR/overlays" "$STATE_DIR"
c_ok "Gruppen (plugdev/netdev/video), Verzeichnisse"

# ---------------------------------------------------------------------------
CUR_HOST="$(hostname)"
if [ "$CUR_HOST" = "raspberrypi" ] && [ "$HOSTNAME_WANTED" != "raspberrypi" ]; then
  c_info "Hostname raspberrypi -> $HOSTNAME_WANTED ..."
  hostnamectl set-hostname "$HOSTNAME_WANTED"
  sed -i "s/\braspberrypi\b/$HOSTNAME_WANTED/g" /etc/hosts
  systemctl restart avahi-daemon 2>/dev/null || true
  CUR_HOST="$HOSTNAME_WANTED"
fi
systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
c_ok "Hostname: $CUR_HOST  (erreichbar als $CUR_HOST.local)"

# ---------------------------------------------------------------------------
c_info "WLAN / Hotspot (NetworkManager) ..."
systemctl enable --now NetworkManager >/dev/null 2>&1 || true
rfkill unblock wifi 2>/dev/null || true
if command -v raspi-config >/dev/null 2>&1 && [ -n "$WIFI_COUNTRY" ]; then
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY" >/dev/null 2>&1 || true
fi

if nmcli -t -f NAME con show | grep -qx -- "$AP_CON"; then
  # Profil existiert: nur Grundwerte sicherstellen, SSID/Passwort NICHT ueberschreiben
  # (koennen ueber die /wlan-Seite geaendert worden sein).
  nmcli con modify "$AP_CON" connection.autoconnect no ipv4.method shared \
    ipv4.addresses "$AP_IP/24" ipv6.method disabled >/dev/null
  c_ok "Hotspot-Profil '$AP_CON' vorhanden (SSID: $(nmcli -g 802-11-wireless.ssid con show "$AP_CON"))"
else
  nmcli con add type wifi ifname wlan0 con-name "$AP_CON" autoconnect no ssid "$AP_SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg \
    ipv4.method shared ipv4.addresses "$AP_IP/24" ipv6.method disabled \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PASSWORD" >/dev/null
  c_ok "Hotspot-Profil '$AP_CON' angelegt (SSID '$AP_SSID', Passwort '$AP_PASSWORD')"
fi

install -D -m 644 "$DIR/system/fotobox-captive.conf" /etc/NetworkManager/dnsmasq-shared.d/fotobox-captive.conf
install -D -m 755 "$DIR/system/90-fotobox-ap" /etc/NetworkManager/dispatcher.d/90-fotobox-ap
install -D -m 755 "$DIR/system/fotobox-wifi-check.sh" /usr/local/sbin/fotobox-wifi-check

sed "s|@USER@|$FB_USER|g" "$DIR/system/fotobox.sudoers.in" > /etc/sudoers.d/fotobox.tmp
chmod 0440 /etc/sudoers.d/fotobox.tmp
visudo -cf /etc/sudoers.d/fotobox.tmp >/dev/null || { rm -f /etc/sudoers.d/fotobox.tmp; die "sudoers-Datei ungueltig"; }
mv -f /etc/sudoers.d/fotobox.tmp /etc/sudoers.d/fotobox
# Port 80 -> 5000 sofort aktivieren (sonst erst beim naechsten Netzwerk-Ereignis)
/etc/NetworkManager/dispatcher.d/90-fotobox-ap any up || true
c_ok "Captive-Portal, Port-80-Weiterleitung, sudo-Regel"

# ---------------------------------------------------------------------------
c_info "cloudflared (externer Zugriff, optional) ..."
case "$ARCH" in
  arm64) CF_ARCH=arm64 ;;
  armhf) CF_ARCH=arm ;;
  amd64) CF_ARCH=amd64 ;;
  *)     CF_ARCH="" ;;
esac
if [ -n "$CF_ARCH" ] && { [ ! -x /usr/local/bin/cloudflared ] || [ "${UPDATE_CLOUDFLARED:-0}" = "1" ]; }; then
  if curl -fsSL --retry 2 -o /usr/local/bin/cloudflared.tmp \
       "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$CF_ARCH"; then
    chmod +x /usr/local/bin/cloudflared.tmp
    mv -f /usr/local/bin/cloudflared.tmp /usr/local/bin/cloudflared
    c_ok "cloudflared installiert"
  else
    rm -f /usr/local/bin/cloudflared.tmp
    c_warn "cloudflared-Download fehlgeschlagen (kein Internet?). Tunnel spaeter mit UPDATE_CLOUDFLARED=1 nachinstallieren."
  fi
else
  c_ok "cloudflared vorhanden ($(/usr/local/bin/cloudflared --version 2>/dev/null | head -1 || echo '?'))"
fi

# ---------------------------------------------------------------------------
c_info "systemd-Dienste ..."
render() { sed -e "s|@USER@|$FB_USER|g" -e "s|@DIR@|$DIR|g" "$1" > "$2"; }
render "$DIR/system/fotobox.service.in"        /etc/systemd/system/fotobox.service
render "$DIR/system/fotobox-tunnel.service.in" /etc/systemd/system/fotobox-tunnel.service
install -m 644 "$DIR/system/fotobox-wifi.service" /etc/systemd/system/fotobox-wifi.service
systemctl daemon-reload
systemctl enable fotobox fotobox-wifi fotobox-tunnel >/dev/null 2>&1
systemctl restart fotobox
if [ -x /usr/local/bin/cloudflared ]; then
  systemctl restart fotobox-tunnel 2>/dev/null || true
fi
# WLAN-Check nur starten, nicht neu starten: ein laufender Installer haengt sonst
# im Hotspot-Fallback selbst am SSH-WLAN.
systemctl start --no-block fotobox-wifi 2>/dev/null || true
sleep 2
c_ok "Dienste: $(systemctl is-active fotobox) fotobox, $(systemctl is-active fotobox-wifi) fotobox-wifi, $(systemctl is-active fotobox-tunnel 2>/dev/null || echo inaktiv) fotobox-tunnel"

# ---------------------------------------------------------------------------
IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | sed 's|^|http://|; s|$|:'"$PORT"'|' | tr '\n' ' ')"
echo
echo "================  Fertig!  =========================="
echo "  Tablet / Steuerung :  http://$CUR_HOST.local        (oder $IPS)"
echo "  Gaeste-Galerie     :  http://$CUR_HOST.local/galerie"
echo "  WLAN-Einstellungen :  http://$CUR_HOST.local/wlan"
echo "  Rahmen/Logo/Text   :  http://$CUR_HOST.local/rahmen"
echo
echo "  Kein bekanntes WLAN in Reichweite?  Der Pi oeffnet nach ca. 45 s"
echo "  das WLAN '$(nmcli -g 802-11-wireless.ssid con show "$AP_CON")' -> verbinden -> Seite oeffnet sich"
echo "  automatisch (sonst http://$AP_IP:$PORT/wlan)."
echo
echo "  Logs:  journalctl -u fotobox -u fotobox-wifi -u fotobox-tunnel -f"
echo "====================================================="
}

# Ganzes Skript erst einlesen, dann ausfuehren (sicher bei "curl | bash");
# stdin abkoppeln, damit kein Befehl den Rest des Skripts "frisst".
main "$@" < /dev/null
