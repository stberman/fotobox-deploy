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
LIVEVIEW_READ_CHUNK = 65536      # Bytes pro stdout-Read (groesser = weniger Syscalls)
CAPTURE_TIMEOUT = 60             # s Zeitlimit fuer eine Vollbild-Aufnahme
LIVE_FRESH_SECONDS = 4.0         # Frame juenger als das => Kamera gilt als "live"
SUPERVISOR_RETRY_OK = 0.5        # s Pause nach beendetem Liveview
SUPERVISOR_RETRY_FAIL = 2.5      # s Pause, wenn keine Kamera/keine Frames
STREAM_WAIT_TIMEOUT = 5.0        # s, die ein Stream auf einen neuen Frame wartet (Keepalive)
