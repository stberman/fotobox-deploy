# 📸 Fotobox

Fotobox auf Basis eines **Raspberry Pi 4B (oder Pi 5)** und einer **Canon EOS M50**.
Ein Tablet bedient über ein Webinterface den Auslöser (mit Countdown-Timer und
Live-Vorschau), Gäste rufen ihre Fotos über eine Galerie bzw. einen QR-Code ab
– lokal im WLAN oder von überall über einen Cloudflare-Tunnel.

## Funktionen
- **Live-Vorschau** der Kamera im Browser (MJPEG-Stream via `gphoto2`)
- **Auslöser + Timer** (Sofort / 3 / 5 / 10 s) mit „Cheeese!"-Anzeige bis das Foto fertig ist
- **Ergebnis-Screen** mit Foto und persönlichem **QR-Code** zum Download
- **Gäste-Galerie** mit Thumbnails, Vollbild und Download
- **Externer Zugriff** per Cloudflare Quick-Tunnel (nur Galerie/Fotos öffentlich, Steuerung bleibt lokal)
- **WLAN-Einrichtung wie beim Shelly:** kein bekanntes WLAN → der Pi öffnet sein eigenes WLAN
  „Fotobox“ mit einer Einstellungsseite
- **Autark-Modus:** eigenes WLAN dauerhaft, ohne Internet und Tunnel (für Orte ohne WLAN)
- **SD-Karten-Backup**: jedes Foto bleibt zusätzlich auf der Kamera-Karte

## Architektur
```
Canon EOS M50 ──USB──> Raspberry Pi 4B/5 ──WLAN──> Tablet / Handys
                       (gphoto2 + Flask)
                              │
                              └── cloudflared ──> Internet (Gäste von überall)
```

| Datei | Zweck |
|-------|-------|
| `install.sh` | **Installer/Updater** – richtet alles ein (ein Befehl) |
| `app.py` | Flask-Webserver, Routen (Web-Schicht) |
| `camera.py` | `CameraManager`: Liveview-Stream + Aufnahme (Kamera-Schicht) |
| `wifi.py` | WLAN-Verwaltung über NetworkManager (`nmcli`) |
| `config.py` | zentrale Konstanten & Tuning-Parameter |
| `templates/` | HTML: `control.html` (Tablet), `gallery.html`, `foto.html`, `wlan.html` |
| `tunnel.sh` | startet den Cloudflare-Tunnel, schreibt die URL in `public_url.txt` |
| `system/` | systemd-Dienste, WLAN-Check-Skript, NetworkManager-Dateien, sudo-Regel |

---

## Installation – Schritt für Schritt

### 1. SD-Karte flashen
[Raspberry Pi Imager](https://www.raspberrypi.com/software/) starten:

| Einstellung | Wert |
|---|---|
| Modell | Raspberry Pi 4 (bzw. 5) |
| Betriebssystem | **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)** – ohne Desktop, aktuell Debian 13 „Trixie“ |
| Speicher | die neue SD-Karte |

Beim Klick auf „Weiter“ → **„Einstellungen bearbeiten“** (OS-Anpassungen):

- **Allgemein:** Hostname `fotobox`, Benutzer z. B. `admin` + Passwort,
  **WLAN** (SSID + Passwort des WLANs, in dem du installierst), WLAN-Land `DE`,
  Zeitzone `Europe/Berlin`
- **Dienste:** **SSH aktivieren** (Passwort-Anmeldung)

Flashen, Karte in den Pi, Kamera noch nicht nötig. Einschalten und ca. 1–2 Minuten warten.

### 2. Installer ausführen
Vom PC aus per SSH anmelden (Windows: PowerShell):
```bash
ssh admin@fotobox.local
```
Dann **diesen einen Befehl** eingeben:
```bash
curl -fsSL https://raw.githubusercontent.com/stberman/fotobox-deploy/main/install.sh | sudo bash
```
Der Installer (ca. 3–5 Minuten) erledigt alles: Systempakete, Projekt nach `~/fotobox` klonen,
Python-Umgebung, Benutzerrechte für die Kamera, Hostname, Hotspot-Profil, Captive-Portal,
cloudflared, systemd-Dienste. Am Ende zeigt er die Adressen an.

Der Befehl kann **jederzeit erneut** ausgeführt werden – er aktualisiert dann auf den neuesten
Stand (`git pull`) und repariert fehlende Teile. Alternativ: `sudo ~/fotobox/install.sh`.

Optionale Einstellungen per Umgebungsvariable, z. B. anderer Hotspot-Name:
```bash
curl -fsSL https://raw.githubusercontent.com/stberman/fotobox-deploy/main/install.sh | sudo AP_SSID=MeineBox AP_PASSWORD=geheim123 bash
```

### 3. Kamera anschließen und loslegen
- **Tablet (Steuerung):** `http://fotobox.local` (oder `http://<pi-ip>`; Port `:5000` geht ebenfalls)
- **Galerie (Gäste):** `http://fotobox.local/galerie`
- **WLAN-Einstellungen:** `http://fotobox.local/wlan` (auch über „⚙ WLAN“ oben links im Bedien-UI)

---

## WLAN wechseln (ohne SSH)

**Fall A – der Pi ist in einem WLAN:** `http://fotobox.local/wlan` öffnen, Netz aus der Liste
antippen, Passwort eingeben, „Verbinden“. Danach das Tablet ebenfalls ins neue WLAN wechseln.

**Fall B – kein bekanntes WLAN in Reichweite (z. B. neue Location):**
1. Pi einschalten. Nach ca. 45 s ohne Verbindung öffnet er das WLAN **„Fotobox“**
   (Passwort **`fotobox123`**, sofern nicht geändert).
2. Mit Handy/Tablet verbinden → es erscheint automatisch das Fenster „Im Netzwerk anmelden“
   mit der WLAN-Seite. Falls nicht: Browser öffnen und `http://10.42.0.1:5000/wlan` eingeben.
3. Das Veranstaltungs-WLAN wählen, Passwort eingeben, „Verbinden“.
   Der Pi wechselt; das Handy verliert dabei die Verbindung zum Pi (normal).
4. Handy/Tablet ins selbe WLAN → `http://fotobox.local`.
   War das Passwort falsch, kommt nach ca. 1 Minute das WLAN „Fotobox“ zurück und die
   Seite zeigt den Fehler.

Hotspot-Name und -Passwort lassen sich auf der WLAN-Seite ändern.

## Autark-Modus (kein WLAN vor Ort)

Auf `…/wlan` → **Autark-Modus einschalten**. Der Pi macht dann *immer* sein eigenes WLAN
„Fotobox“ auf, auch wenn ein bekanntes Netz da wäre.
- Tablet mit „Fotobox“ verbinden → `http://10.42.0.1`
- QR-Codes zeigen auf `10.42.0.1` (nur im Fotobox-WLAN erreichbar), kein Internet-Tunnel
- Fotos liegen wie immer unter `~/fotobox/photos/` auf der SD-Karte des Pi
  (plus Backup auf der Kamera-SD)
- Ausschalten: wieder auf `…/wlan` → „Ausschalten“; der Pi verbindet sich mit bekannten WLANs

Die Einstellung überlebt Neustarts (Datei `/var/lib/fotobox/autark`).

---

## Fehlersuche

```bash
# Dienste und Logs
systemctl status fotobox fotobox-wifi fotobox-tunnel
journalctl -u fotobox -u fotobox-wifi -u fotobox-tunnel -f

# Netzwerk
nmcli dev status            # welche Verbindung ist aktiv?
nmcli con show              # gespeicherte Profile (Fotobox-AP = Hotspot)
sudo systemctl restart fotobox-wifi   # WLAN-Check erneut ausführen

# Kamera
gphoto2 --auto-detect       # wird die M50 gesehen?
```

- **Hotspot startet nicht:** `rfkill list` (WLAN gesperrt?), `nmcli con up Fotobox-AP` von Hand,
  Meldung lesen. Meist fehlt das WLAN-Land (`sudo raspi-config nonint do_wifi_country DE`).
- **Kein `fotobox.local`:** Windows braucht Bonjour (kommt mit iTunes/Druckertreibern) – sonst
  die IP nehmen (steht am Ende der Installer-Ausgabe oder im Router).
- **Tunnel-URL fehlt:** `cat ~/fotobox/public_url.txt`; Tunnel läuft nicht im Autark-Modus
  und braucht Internet. Nachinstallieren: `sudo UPDATE_CLOUDFLARED=1 ~/fotobox/install.sh`.
- **Fotobox-Dienst von Hand starten (Fehler sehen):**
  `cd ~/fotobox && venv/bin/python app.py`

## Kamera-Hinweise
- Objektiv **ausfahren** und Deckel ab – sonst verweigert die M50 Liveview und Auslösung.
- **Auto-Power-Off deaktivieren**; für Dauerbetrieb einen Dummy-Akku (DR-E12 + ACK-E12) verwenden.
- Eine **SD-Karte** muss eingelegt sein (für das Backup auf der Kamera).
- Kamera auf **JPG** (nicht nur RAW) stellen.

## Entwicklung
Lokal (ohne Pi) startet die App auch unter Windows/macOS: `pip install flask qrcode pillow`,
`python app.py`. Kamera- und WLAN-Funktionen melden dann Fehler, die Oberfläche ist aber testbar.
`.gitattributes` erzwingt LF-Zeilenenden, damit die Shell-Skripte auf dem Pi laufen.
