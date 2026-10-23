"""Zentrale Konfiguration der Fotobox.

Alle Pfade, Limits und Tuning-Parameter an einem Ort, damit man sie nicht
quer durch den Code suchen muss.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_DIR = os.path.join(BASE_DIR, "photos")
THUMB_DIR = os.path.join(BASE_DIR, "static", "thumbs")
# Wird vom Tunnel-Skript mit der oeffentlichen URL gefuellt (Cloudflare Quick-Tunnel)
PUBLIC_URL_FILE = os.path.join(BASE_DIR, "public_url.txt")

PORT = 5000
THUMB_SIZE = (600, 600)
ALLOWED_EXT = (".jpg", ".jpeg", ".png")

# Pfade, die von aussen (ueber den Tunnel) erreichbar sind. Steuerung/Liveview NICHT.
PUBLIC_PREFIXES = ("/galerie", "/foto/", "/photos/", "/thumb/", "/qr.png",
                   "/api/photos", "/static/")

# --- Kamera / Liveview ---------------------------------------------------
STREAM_MAX_FPS = 15              # Obergrenze fuer an den Browser gesendete Frames (0 = unbegrenzt)
LIVEVIEW_READ_CHUNK = 65536      # Bytes pro stdout-Read (groesser = weniger Syscalls)
CAPTURE_TIMEOUT = 60             # s Zeitlimit fuer eine Vollbild-Aufnahme
LIVE_FRESH_SECONDS = 4.0         # Frame juenger als das => Kamera gilt als "live"
SUPERVISOR_RETRY_OK = 0.5        # s Pause nach beendetem Liveview
SUPERVISOR_RETRY_FAIL = 2.5      # s Pause, wenn keine Kamera/keine Frames
STREAM_WAIT_TIMEOUT = 5.0        # s, die ein Stream auf einen neuen Frame wartet (Keepalive)

# --- WLAN / Hotspot ------------------------------------------------------
# Laufzeit-Zustand ausserhalb des Repos (vom Installer angelegt, gehoert dem Fotobox-User).
STATE_DIR = "/var/lib/fotobox"
AUTARK_FLAG = os.path.join(STATE_DIR, "autark")        # existiert => Autark-Modus an
SCAN_CACHE = os.path.join(STATE_DIR, "scan.txt")       # letzter WLAN-Scan vor Hotspot-Start
WIFI_ERROR_FILE = os.path.join(STATE_DIR, "last_error") # Fehlertext des letzten Verbindungsversuchs

WIFI_IFACE = "wlan0"
AP_CON_NAME = "Fotobox-AP"       # Name des NetworkManager-Profils fuer den Hotspot
AP_SSID_DEFAULT = "Fotobox"      # Installer legt den Hotspot damit an; spaeter per /wlan aenderbar
AP_PASSWORD_DEFAULT = "fotobox123"
AP_IP = "10.42.0.1"              # feste Adresse des Pi im eigenen Hotspot
AP_SUBNET_PREFIX = "10.42.0."
WIFI_CONNECT_TIMEOUT = 45        # s, die ein Verbindungsversuch maximal dauern darf
NMCLI = "/usr/bin/nmcli"

# --- Rahmen / Overlay ------------------------------------------------------
OVERLAY_DIR = os.path.join(BASE_DIR, "overlays")              # Rahmen- und Logo-PNGs
OVERLAY_SETTINGS = os.path.join(BASE_DIR, "overlay_settings.json")  # aktive Einstellungen (nicht im Repo)
ORIGINALS_DIR = os.path.join(PHOTO_DIR, "originals")          # unveraenderte Aufnahmen
