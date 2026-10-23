#!/usr/bin/env python3
"""Fotobox - Flask-Webapp fuer Raspberry Pi 5 + Canon EOS M50.

Web-Schicht: Routen fuer das Tablet-Bedieninterface (Liveview + Ausloeser),
die Gaeste-Galerie mit QR-Code und das Ausliefern der Fotos. Die Kamera-Logik
steckt in camera.py, die Konstanten in config.py.
"""
import io
import ipaddress
import os
import socket
import zipfile
from datetime import datetime

from flask import (Flask, Response, jsonify, render_template, request,
                   send_from_directory, send_file, abort, redirect)
from PIL import Image
import qrcode

import config
import overlay
import wifi
from camera import CameraManager

os.makedirs(config.PHOTO_DIR, exist_ok=True)
os.makedirs(config.THUMB_DIR, exist_ok=True)

app = Flask(__name__)
cam = CameraManager()


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def public_base():
    """Oeffentliche Tunnel-URL, falls vorhanden, sonst die aufrufende Adresse."""
    try:
        with open(config.PUBLIC_URL_FILE) as f:
            url = f.read().strip()
        if url.startswith("http"):
            return url.rstrip("/")
    except Exception:
        pass
    return request.host_url.rstrip("/")


def is_lan_request():
    """True, wenn der Zugriff aus dem lokalen Netz kommt (nicht ueber den Tunnel)."""
    host = request.host.split(":")[0]
    return (host in ("localhost", "127.0.0.1")
            or host.startswith("192.168.")
            or host.startswith("10.")
            or host.startswith("172."))


def list_photos():
    """Alle Fotos, neueste zuerst."""
    files = [f for f in os.listdir(config.PHOTO_DIR)
             if f.lower().endswith(config.ALLOWED_EXT)]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(config.PHOTO_DIR, f)),
               reverse=True)
    return files


def make_thumb(filename):
    """Erzeugt (falls noetig) ein Thumbnail und gibt dessen Pfad zurueck."""
    thumb_path = os.path.join(config.THUMB_DIR, filename)
    src_path = os.path.join(config.PHOTO_DIR, filename)
    if (not os.path.exists(thumb_path)
            or os.path.getmtime(thumb_path) < os.path.getmtime(src_path)):
        try:
            img = Image.open(src_path).convert("RGB")
            img.thumbnail(config.THUMB_SIZE)
            img.save(thumb_path, "JPEG", quality=85)
        except Exception:
            return None
    return thumb_path


def mjpeg_part(frame):
    """Verpackt ein JPEG als ein Teil eines multipart/x-mixed-replace-Streams."""
    return (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")


# --------------------------------------------------------------------------
# Zugriffsschutz: von aussen (Tunnel) nur oeffentliche Pfade
# --------------------------------------------------------------------------
def _captive_redirect():
    """Captive-Portal im eigenen Hotspot.

    Handys/Tablets rufen nach dem Verbinden eine Testseite auf (z.B.
    connectivitycheck.gstatic.com). Der Hotspot-DNS loest alles auf den Pi auf,
    Port 80 wird auf die App umgeleitet - hier landet also jede fremde
    Host-Adresse aus dem Hotspot-Netz und bekommt einen Redirect auf /wlan.
    Das Geraet zeigt daraufhin das "Im Netzwerk anmelden"-Fenster.
    """
    addr = request.remote_addr or ""
    if not addr.startswith(config.AP_SUBNET_PREFIX):
        return None
    host = request.host.split(":")[0].lower()
    try:
        ipaddress.ip_address(host)
        return None          # Zugriff per IP-Adresse: nie umleiten (keine Schleifen)
    except ValueError:
        pass
    me = socket.gethostname().lower()
    if host in ("localhost", me, me + ".local"):
        return None
    return redirect(f"http://{config.AP_IP}:{config.PORT}/wlan", code=302)


@app.before_request
def _guard_public():
    captive = _captive_redirect()
    if captive is not None:
        return captive
    if is_lan_request():
        return
    if any(request.path.startswith(p) for p in config.PUBLIC_PREFIXES):
        return
    abort(403)


# --------------------------------------------------------------------------
# Routen: Steuerung (nur LAN)
# --------------------------------------------------------------------------
@app.route("/")
def control():
    return render_template("control.html")


@app.route("/preview.mjpg")
def preview():
    def gen():
        for frame in cam.frames():
            if frame is not None:
                yield mjpeg_part(frame)
    return Response(gen(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


_ROTATIONS = {90: Image.Transpose.ROTATE_270,    # 90 Grad im Uhrzeigersinn
              180: Image.Transpose.ROTATE_180,
              270: Image.Transpose.ROTATE_90}


def _rotate_file(path, degrees):
    """Dreht die Datei um 90/180/270 Grad im Uhrzeigersinn (verlustfrei bei 90er-Schritten)."""
    op = _ROTATIONS.get(degrees)
    if op is None:
        return
    with Image.open(path) as img:
        fmt, exif = img.format, img.info.get("exif", b"")
        img.transpose(op).save(path, format=fmt, quality=95, exif=exif)


@app.route("/capture", methods=["POST"])
def do_capture():
    try:
        rotation = int(request.form.get("rotation", 0) or 0) % 360
    except ValueError:
        rotation = 0
    try:
        filename = cam.capture()
        path = os.path.join(config.PHOTO_DIR, filename)
        if rotation:
            _rotate_file(path, rotation)
        framed = False
        try:
            # Rahmen/Logo/Text nach der Drehung, damit sie zur Bildlage passen.
            framed = overlay.apply_to_file(path)
        except Exception as e:                   # noqa: BLE001 - Foto ist wichtiger als der Rahmen
            app.logger.warning("Overlay fehlgeschlagen: %s", e)
        view = f"{public_base()}/foto/{filename}"
        return jsonify(ok=True, filename=filename, framed=framed,
                       url=f"/photos/{filename}", view=view)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/status")
def api_status():
    ov = overlay.load_settings()
    frame = ov.get("frame", "") if ov.get("enabled") else ""
    fit = "slice"
    if frame:
        path = os.path.join(config.OVERLAY_DIR, frame)
        fit = overlay.asset_meta(path).get("fit", "slice") if os.path.isfile(path) else "slice"
    return jsonify(camera=cam.is_live(), count=len(list_photos()),
                   overlay=bool(ov.get("enabled")), overlay_frame=frame, overlay_fit=fit)


class _ZipSink:
    """Schreib-Senke fuer zipfile: sammelt Bytes, die der Generator abholt.

    Hat bewusst kein seek()/tell(), damit zipfile den Stream als nicht-seekbar
    behandelt (Data-Descriptors) und nichts zurueckspulen will.
    """
    def __init__(self):
        self._buf = bytearray()

    def write(self, data):
        self._buf += data
        return len(data)

    def flush(self):
        pass

    def drain(self):
        chunk = bytes(self._buf)
        del self._buf[:]
        return chunk


@app.route("/download-all")
def download_all():
    # Nur im LAN erreichbar (nicht in PUBLIC_PREFIXES -> Tunnel bekommt 403).
    photos = list_photos()
    if not photos:
        abort(404)

    def generate():
        sink = _ZipSink()
        # ZIP_STORED: JPEGs sind bereits komprimiert -> keine CPU fuer Deflate.
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as zf:
            for name in photos:
                zf.write(os.path.join(config.PHOTO_DIR, name), arcname=name)
                chunk = sink.drain()      # nach jeder Datei ausliefern -> RAM bleibt klein
                if chunk:
                    yield chunk
        tail = sink.drain()               # zentrales Verzeichnis am Ende
        if tail:
            yield tail

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(generate(), mimetype="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="fotobox_{ts}.zip"'})


@app.route("/delete", methods=["POST"])
def delete_photo():
    # Nur im LAN erreichbar (nicht in PUBLIC_PREFIXES -> Tunnel bekommt 403).
    filename = request.form.get("filename", "")
    # Abgleich mit der echten Fotoliste verhindert Path-Traversal/Fremdzugriff.
    if filename not in list_photos():
        abort(404)
    try:
        os.remove(os.path.join(config.PHOTO_DIR, filename))
    except OSError as e:
        return jsonify(ok=False, error=str(e)), 500
    thumb = os.path.join(config.THUMB_DIR, filename)
    if os.path.exists(thumb):
        try:
            os.remove(thumb)
        except OSError:
            pass        # Thumbnail wird sonst beim naechsten Aufruf neu erzeugt
    return jsonify(ok=True)


@app.route("/rotate", methods=["POST"])
def rotate_photo():
    # Nur im LAN erreichbar (nicht in PUBLIC_PREFIXES -> Tunnel bekommt 403).
    filename = request.form.get("filename", "")
    if filename not in list_photos():
        abort(404)
    path = os.path.join(config.PHOTO_DIR, filename)
    try:
        with Image.open(path) as img:
            fmt = img.format
            # ROTATE_270 = 90 Grad im Uhrzeigersinn; transpose() ist fuer
            # 90-Grad-Schritte exakt (kein Interpolations-Verlust).
            img.transpose(Image.Transpose.ROTATE_270).save(
                path, format=fmt, quality=95)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
    # Thumbnail verwerfen -> wird beim naechsten Abruf in neuer Lage erzeugt.
    thumb = os.path.join(config.THUMB_DIR, filename)
    if os.path.exists(thumb):
        try:
            os.remove(thumb)
        except OSError:
            pass
    make_thumb(filename)
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Routen: Rahmen / Overlay (nur LAN)
# --------------------------------------------------------------------------
@app.route("/rahmen")
def rahmen():
    return render_template("rahmen.html")


@app.route("/overlays/<path:filename>")
def overlay_asset(filename):
    if not filename.lower().endswith(".png"):
        abort(404)
    return send_from_directory(config.OVERLAY_DIR, filename)


@app.route("/api/overlay/settings", methods=["GET", "POST"])
def api_overlay_settings():
    try:
        if request.method == "POST":
            settings = overlay.save_settings(request.form.to_dict())
        else:
            settings = overlay.load_settings()
        return jsonify(ok=True, settings=settings, assets=overlay.list_assets())
    except Exception as e:                       # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/overlay/preview.jpg")
def api_overlay_preview():
    # Vorschau mit den Werten aus der Query (ungespeichert), gerendert auf dem
    # letzten Foto oder einem Platzhalter.
    settings = dict(overlay.DEFAULTS)
    settings.update(overlay.load_settings())
    for k, v in request.args.items():
        if k in overlay.DEFAULTS:
            kind = type(overlay.DEFAULTS[k])
            if kind is bool:
                v = v.lower() in ("1", "true", "on", "yes")
            elif kind is float:
                try:
                    v = float(v)
                except ValueError:
                    continue
            settings[k] = v
    photos = list_photos()
    base = os.path.join(config.PHOTO_DIR, photos[0]) if photos else None
    try:
        img = overlay.preview(settings, base, width=1200)
    except Exception as e:                       # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 500
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    buf.seek(0)
    resp = send_file(buf, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/overlay/upload", methods=["POST"])
def api_overlay_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(ok=False, error="Keine Datei ausgewaehlt."), 400
    try:
        name = overlay.save_upload(f, f.filename, request.form.get("kind", "frame"))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, name=name)


@app.route("/api/overlay/delete", methods=["POST"])
def api_overlay_delete():
    try:
        overlay.delete_asset(request.form.get("name", ""))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 404
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Routen: WLAN-Einstellungen (nur LAN; nicht in PUBLIC_PREFIXES -> Tunnel 403)
# --------------------------------------------------------------------------
@app.route("/wlan")
def wlan():
    return render_template("wlan.html")


def _wifi_call(fn, *args, **kw):
    """Fuehrt eine wifi.py-Funktion aus und verpackt Fehler als JSON."""
    try:
        result = fn(*args, **kw)
    except wifi.WifiError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:                       # noqa: BLE001
        return jsonify(ok=False, error=f"Interner Fehler: {e}"), 500
    if isinstance(result, dict):
        return jsonify(ok=True, **result)
    return jsonify(ok=True)


@app.route("/api/wifi/status")
def api_wifi_status():
    return _wifi_call(wifi.status)


@app.route("/api/wifi/scan")
def api_wifi_scan():
    return _wifi_call(wifi.scan)


@app.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    f = request.form
    return _wifi_call(wifi.connect, f.get("ssid", ""), f.get("psk", ""),
                      hidden=f.get("hidden") in ("1", "true", "on"),
                      security=f.get("security", ""))


@app.route("/api/wifi/forget", methods=["POST"])
def api_wifi_forget():
    return _wifi_call(wifi.forget, request.form.get("ssid", ""))


@app.route("/api/wifi/ap", methods=["POST"])
def api_wifi_ap():
    return _wifi_call(wifi.set_ap, request.form.get("ssid", ""),
                      request.form.get("psk", ""))


@app.route("/api/wifi/autark", methods=["POST"])
def api_wifi_autark():
    enabled = request.form.get("enabled") in ("1", "true", "on")
    return _wifi_call(wifi.set_autark, enabled)


# --------------------------------------------------------------------------
# Routen: oeffentlich (LAN + Tunnel)
# --------------------------------------------------------------------------
@app.route("/galerie")
def galerie():
    # is_lan steuert, ob der Loeschen-Button angezeigt wird (nur Bedien-Tablet,
    # nicht Gaeste ueber den Tunnel).
    return render_template("gallery.html", photos=list_photos(),
                           is_lan=is_lan_request())


@app.route("/foto/<path:filename>")
def foto(filename):
    if filename not in list_photos():
        abort(404)
    return render_template("foto.html", filename=filename)


@app.route("/api/photos")
def api_photos():
    return jsonify(photos=list_photos())


@app.route("/photos/<path:filename>")
def photo(filename):
    return send_from_directory(config.PHOTO_DIR, filename)


@app.route("/thumb/<path:filename>")
def thumb(filename):
    if not filename.lower().endswith(config.ALLOWED_EXT):
        abort(404)
    if make_thumb(filename):
        return send_from_directory(config.THUMB_DIR, filename)
    return send_from_directory(config.PHOTO_DIR, filename)


@app.route("/qr.png")
def qr():
    target = request.args.get("url", public_base() + "/galerie")
    img = qrcode.make(target)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, threaded=True)
