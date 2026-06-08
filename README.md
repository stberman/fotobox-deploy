# 📸 Fotobox

Fotobox auf Basis eines **Raspberry Pi 5** und einer **Canon EOS M50**.
Ein Tablet bedient über ein Webinterface den Auslöser (mit Countdown-Timer und
Live-Vorschau), Gäste rufen ihre Fotos über eine Galerie bzw. einen QR-Code ab
– lokal im WLAN oder von überall über einen Cloudflare-Tunnel.

## Funktionen
- **Live-Vorschau** der Kamera im Browser (MJPEG-Stream via `gphoto2`)
- **Auslöser + Timer** (Sofort / 3 / 5 / 10 s) mit „Cheeese!"-Anzeige bis das Foto fertig ist
- **Ergebnis-Screen** mit Foto und persönlichem **QR-Code** zum Download
- **Gäste-Galerie** mit Thumbnails, Vollbild und Download
- **Externer Zugriff** per Cloudflare Quick-Tunnel (nur Galerie/Fotos öffentlich, Steuerung bleibt lokal)
- **SD-Karten-Backup**: jedes Foto bleibt zusätzlich auf der Kamera-Karte

## Architektur
```
Canon EOS M50 ──USB──> Raspberry Pi 5 ──WLAN──> Tablet / Handys
                       (gphoto2 + Flask)
                              │
                              └── cloudflared ──> Internet (Gäste von überall)
```

| Datei | Zweck |
|-------|-------|
| `app.py` | Flask-Webserver, Routen (Web-Schicht) |
| `camera.py` | `CameraManager`: Liveview-Stream + Aufnahme (Kamera-Schicht) |
| `config.py` | zentrale Konstanten & Tuning-Parameter |
| `templates/` | HTML: `control.html` (Tablet), `gallery.html`, `foto.html` |
| `tunnel.sh` | startet den Cloudflare-Tunnel, schreibt die URL in `public_url.txt` |
| `*.service` | systemd-Dienste für Autostart |

## Installation (auf dem Raspberry Pi)

```bash
# 1. Systempakete
sudo apt update && sudo apt install -y gphoto2 python3-venv

# 2. Projekt + virtuelle Umgebung
cd ~/fotobox
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. gvfs-Kamera-Monitor deaktivieren (sonst belegt der Desktop die Kamera)
sudo mv /usr/share/gvfs/remote-volume-monitors/gphoto2.monitor \
        /usr/share/gvfs/remote-volume-monitors/gphoto2.monitor.disabled

# 4. Autostart-Dienst einrichten
sudo cp fotobox.service /etc/systemd/system/
sudo systemctl enable --now fotobox
```

### Externer Zugriff (optional)
```bash
# cloudflared installieren (arm64)
sudo curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 \
     -o /usr/local/bin/cloudflared && sudo chmod +x /usr/local/bin/cloudflared

sudo cp fotobox-tunnel.service /etc/systemd/system/
sudo systemctl enable --now fotobox-tunnel
```
> Hinweis: Falls das Netzwerk QUIC/UDP 7844 blockiert, nutzt `tunnel.sh` `--protocol http2`.

## Bedienung
- **Tablet (Steuerung):** `http://<pi-ip>:5000`
- **Galerie (Gäste):** `http://<pi-ip>:5000/galerie`

## Kamera-Hinweise
- Objektiv **ausfahren** und Deckel ab – sonst verweigert die M50 Liveview und Auslösung.
- **Auto-Power-Off deaktivieren**; für Dauerbetrieb einen Dummy-Akku (DR-E12 + ACK-E12) verwenden.
- Eine **SD-Karte** muss eingelegt sein (für das Backup auf der Kamera).
