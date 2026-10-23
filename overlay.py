"""Rahmen / Overlay fuer die Fotobox.

Nach der Aufnahme wird (falls aktiviert) auf das Foto gelegt:
  * ein Rahmen (transparentes PNG aus dem Ordner overlays/, auf Fotogroesse skaliert)
  * ein Logo (PNG aus overlays/, in einer Ecke)
  * ein Text (Veranstaltung) und/oder das Datum

Die Einstellungen liegen in overlay_settings.json (nicht im Repo). Das
unveraenderte Original jeder Aufnahme wird nach photos/originals/ kopiert,
damit nichts verloren geht.

Rahmen-PNGs sind fuer Querformat 3:2 gedacht; bei Hochformat-Fotos wird der
Rahmen um 90 Grad gedreht. Zu jedem Rahmen kann eine gleichnamige .json mit
empfohlenen Text-Einstellungen liegen (z.B. polaroid.json), die die
Einstellungsseite beim Auswaehlen uebernimmt.
"""
import json
import os
import shutil
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

import config

FRAME_EXT = (".png",)
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

DEFAULTS = {
    "enabled": False,
    "frame": "",            # Dateiname in overlays/ oder "" (kein Rahmen)
    "logo": "",             # Dateiname in overlays/ oder ""
    "logo_pos": "tr",       # tl, tr, bl, br
    "logo_scale": 0.18,     # Breite des Logos relativ zur Fotobreite
    "text": "",             # Veranstaltungs-Text, "" = keiner
    "show_date": True,
    "date_format": "%d.%m.%Y",
    "text_pos": "bottom",   # bottom | top
    "text_color": "light",  # light (weiss) | dark (schwarz)
    "text_bg": True,        # halbtransparenter Balken hinter dem Text
    "text_size": 0.045,     # Schrifthoehe relativ zur kurzen Fotoseite
    "text_offset": 0.03,    # Abstand vom Rand relativ zur kurzen Fotoseite
}


# --------------------------------------------------------------------------
# Einstellungen & Dateien
# --------------------------------------------------------------------------
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(config.OVERLAY_SETTINGS) as f:
            data = json.load(f)
        if isinstance(data, dict):
            s.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(new):
    """Uebernimmt nur bekannte Schluessel, wandelt Typen und validiert Dateinamen."""
    s = load_settings()
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        kind = type(DEFAULTS[k])
        if kind is bool:
            v = str(v).lower() in ("1", "true", "on", "yes")
        elif kind is float:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        else:
            v = str(v).strip()
        s[k] = v
    for key in ("frame", "logo"):
        if s[key] and not _safe_asset(s[key]):
            s[key] = ""
    s["logo_scale"] = min(max(s["logo_scale"], 0.05), 0.5)
    s["text_size"] = min(max(s["text_size"], 0.015), 0.15)
    s["text_offset"] = min(max(s["text_offset"], 0.0), 0.3)
    if s["logo_pos"] not in ("tl", "tr", "bl", "br"):
        s["logo_pos"] = "tr"
    if s["text_pos"] not in ("bottom", "top"):
        s["text_pos"] = "bottom"
    if s["text_color"] not in ("light", "dark"):
        s["text_color"] = "light"
    os.makedirs(os.path.dirname(config.OVERLAY_SETTINGS), exist_ok=True)
    tmp = config.OVERLAY_SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config.OVERLAY_SETTINGS)
    return s


def _safe_asset(name):
    """Pfad zu einer PNG-Datei in overlays/, oder None bei ungueltigem Namen."""
    if not name or os.path.basename(name) != name or not name.lower().endswith(FRAME_EXT):
        return None
    path = os.path.join(config.OVERLAY_DIR, name)
    return path if os.path.isfile(path) else None


def asset_meta(path):
    """Metadaten eines Rahmens: aus gleichnamiger .json und/oder PNG-Textfeldern.

    PNG-Textfelder (fotobox_title, fotobox_fit, fotobox_recommend als JSON)
    ueberleben den Upload ueber die Weboberflaeche, eine .json-Datei nicht.
    Erkannte Schluessel: title, kind (frame|logo), fit (slice|cover) und alle
    Einstellungen aus DEFAULTS als Empfehlung.
    """
    meta = {}
    try:
        with Image.open(path) as im:
            info = getattr(im, "text", None) or im.info
            if info.get("fotobox_title"):
                meta["title"] = str(info["fotobox_title"])
            if info.get("fotobox_fit"):
                meta["fit"] = str(info["fotobox_fit"])
            if info.get("fotobox_kind"):
                meta["kind"] = str(info["fotobox_kind"])
            if info.get("fotobox_recommend"):
                rec = json.loads(info["fotobox_recommend"])
                if isinstance(rec, dict):
                    meta.update(rec)
    except Exception:                            # noqa: BLE001 - Metadaten sind optional
        pass
    side = os.path.splitext(path)[0] + ".json"
    try:
        with open(side) as f:
            data = json.load(f)
        if isinstance(data, dict):
            meta.update(data)
    except (OSError, ValueError):
        pass
    return meta


def list_assets():
    """Alle PNGs in overlays/ mit Titel, Art und empfohlenen Einstellungen."""
    os.makedirs(config.OVERLAY_DIR, exist_ok=True)
    items = []
    for name in sorted(os.listdir(config.OVERLAY_DIR)):
        if not name.lower().endswith(FRAME_EXT):
            continue
        meta = asset_meta(os.path.join(config.OVERLAY_DIR, name))
        items.append({"name": name, "title": meta.get("title", os.path.splitext(name)[0]),
                      "kind": meta.get("kind", "frame"), "fit": meta.get("fit", "slice"),
                      "recommend": {k: v for k, v in meta.items() if k in DEFAULTS}})
    return items


def delete_asset(name):
    path = _safe_asset(name)
    if not path:
        raise ValueError("Datei nicht gefunden.")
    os.remove(path)
    side = os.path.splitext(path)[0] + ".json"
    if os.path.exists(side):
        os.remove(side)


def save_upload(fileobj, filename, kind="frame"):
    """Speichert ein hochgeladenes PNG nach overlays/ (Name wird bereinigt)."""
    base = os.path.basename(filename or "")
    stem, ext = os.path.splitext(base)
    if ext.lower() != ".png":
        raise ValueError("Nur PNG-Dateien (mit Transparenz) sind erlaubt.")
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem) or "upload"
    os.makedirs(config.OVERLAY_DIR, exist_ok=True)
    name = stem + ".png"
    path = os.path.join(config.OVERLAY_DIR, name)
    fileobj.save(path)
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        os.remove(path)
        raise ValueError("Datei ist kein gueltiges PNG.")
    if kind == "logo":
        with open(os.path.splitext(path)[0] + ".json", "w") as f:
            json.dump({"kind": "logo", "title": stem}, f)
    return name


# --------------------------------------------------------------------------
# Rendern
# --------------------------------------------------------------------------
def _font(px):
    for cand in FONT_CANDIDATES:
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, px)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=px)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _fit_frame(fr, W, H, inset=0.25, mode="slice"):
    """Skaliert einen Rahmen auf WxH.

    mode "slice" (Standard, fuer Rand-Rahmen): 9-Slice - Ecken bleiben
    proportional (Faktor kurze Seite Foto / kurze Seite Rahmen), Kanten werden
    nur in Laengsrichtung gestreckt. So passt ein 3:2-Rahmen auch auf
    Hochformat, ohne dass Raender verzerrt werden oder ein breiter unterer
    Rand (Polaroid) an die Seite wandert.

    mode "cover" (fuer fotografische Kulissen): Rahmen proportional so
    vergroessern, dass er das Foto ganz bedeckt, und mittig beschneiden.
    """
    fw, fh = fr.size
    if (fw, fh) == (W, H):
        return fr
    if mode == "cover":
        sc = max(W / fw, H / fh)
        nw, nh = max(W, int(round(fw * sc))), max(H, int(round(fh * sc)))
        fr = fr.resize((nw, nh), Image.Resampling.LANCZOS)
        x0, y0 = (nw - W) // 2, (nh - H) // 2
        return fr.crop((x0, y0, x0 + W, y0 + H))
    scale = min(W, H) / min(fw, fh)
    cf = int(min(fw, fh) * inset)              # Ecken-Groesse im Rahmen
    c = max(1, int(cf * scale))                # Ecken-Groesse im Ziel
    c = min(c, W // 2 - 1, H // 2 - 1)
    if c < 2 or fw - 2 * cf < 1 or fh - 2 * cf < 1:
        return fr.resize((W, H), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    R = Image.Resampling.LANCZOS
    xs = [(0, cf, 0, c), (cf, fw - cf, c, W - c), (fw - cf, fw, W - c, W)]
    ys = [(0, cf, 0, c), (cf, fh - cf, c, H - c), (fh - cf, fh, H - c, H)]
    for sy0, sy1, dy0, dy1 in ys:
        for sx0, sx1, dx0, dx1 in xs:
            dw, dh = dx1 - dx0, dy1 - dy0
            if dw <= 0 or dh <= 0:
                continue
            part = fr.crop((sx0, sy0, sx1, sy1)).resize((dw, dh), R)
            out.paste(part, (dx0, dy0))
    return out


def _compose_text(settings):
    parts = []
    if settings.get("text"):
        parts.append(settings["text"])
    if settings.get("show_date"):
        try:
            parts.append(datetime.now().strftime(settings.get("date_format") or "%d.%m.%Y"))
        except ValueError:
            parts.append(datetime.now().strftime("%d.%m.%Y"))
    return "  ·  ".join(parts)


def render(img, settings=None):
    """Legt Rahmen, Logo und Text auf ein PIL-Bild (RGB) und gibt es zurueck."""
    s = settings or load_settings()
    img = img.convert("RGB")
    W, H = img.size
    short = min(W, H)

    frame_path = _safe_asset(s.get("frame"))
    if frame_path:
        fit = asset_meta(frame_path).get("fit", "slice")
        with Image.open(frame_path) as fr:
            fr = _fit_frame(fr.convert("RGBA"), W, H, mode=fit)
            img.paste(fr, (0, 0), fr)

    logo_path = _safe_asset(s.get("logo"))
    if logo_path:
        with Image.open(logo_path) as lg:
            lg = lg.convert("RGBA")
            lw = max(1, int(W * float(s.get("logo_scale", 0.18))))
            lh = max(1, int(lg.height * lw / lg.width))
            lg = lg.resize((lw, lh), Image.Resampling.LANCZOS)
            m = int(short * 0.03)
            pos = s.get("logo_pos", "tr")
            x = m if pos in ("tl", "bl") else W - lw - m
            y = m if pos in ("tl", "tr") else H - lh - m
            img.paste(lg, (x, y), lg)

    text = _compose_text(s)
    if text:
        px = max(12, int(short * float(s.get("text_size", 0.045))))
        font = _font(px)
        draw = ImageDraw.Draw(img, "RGBA")
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        # Zu breiter Text: verkleinern bis er passt
        while tw > W * 0.9 and px > 12:
            px = int(px * 0.9)
            font = _font(px)
            l, t, r, b = draw.textbbox((0, 0), text, font=font)
            tw, th = r - l, b - t
        pad = int(px * 0.5)
        off = int(short * float(s.get("text_offset", 0.03)))
        x = (W - tw) // 2
        y = off if s.get("text_pos") == "top" else H - off - th - 2 * pad
        light = s.get("text_color", "light") == "light"
        if s.get("text_bg", True):
            bg = (0, 0, 0, 120) if light else (255, 255, 255, 150)
            draw.rounded_rectangle((x - pad * 1.5, y, x + tw + pad * 1.5, y + th + 2 * pad),
                                   radius=pad, fill=bg)
        fill = (255, 255, 255, 255) if light else (20, 20, 20, 255)
        draw.text((x - l, y + pad - t), text, font=font, fill=fill)
    return img


def apply_to_file(path, settings=None):
    """Original sichern, Overlay rendern, Datei ueberschreiben. Gibt True zurueck wenn gerendert."""
    s = settings or load_settings()
    if not s.get("enabled"):
        return False
    if not (s.get("frame") or s.get("logo") or _compose_text(s)):
        return False
    orig_dir = os.path.join(os.path.dirname(path), "originals")
    os.makedirs(orig_dir, exist_ok=True)
    orig = os.path.join(orig_dir, os.path.basename(path))
    if not os.path.exists(orig):
        shutil.copy2(path, orig)
    with Image.open(orig) as im:
        exif = im.getexif()
        # Kamera-Orientierung einrechnen, Rahmen auf das aufrechte Bild legen
        # und das Tag auf 1 setzen, sonst dreht der Browser ein zweites Mal.
        out = render(ImageOps.exif_transpose(im), s)
        exif[0x0112] = 1
    out.save(path, "JPEG", quality=92, exif=exif.tobytes())
    return True


def preview(settings, base_path=None, width=1200):
    """Verkleinerte Vorschau: auf dem letzten Foto oder einem neutralen Platzhalter."""
    if base_path and os.path.exists(base_path):
        with Image.open(base_path) as im:
            im = im.convert("RGB")
            im.thumbnail((width, width))
            base = im.copy()
    else:
        w, h = width, int(width * 2 / 3)
        base = Image.new("RGB", (w, h))
        # weicher Farbverlauf als Platzhalter
        px = base.load()
        for yy in range(h):
            for xx in range(0, w, 4):
                c = (90 + yy * 60 // h, 110 + xx * 50 // w, 150)
                for k in range(4):
                    if xx + k < w:
                        px[xx + k, yy] = c
        d = ImageDraw.Draw(base)
        f = _font(int(h * 0.06))
        d.text((w // 2, h // 2), "Vorschau", font=f, fill=(255, 255, 255), anchor="mm")
    return render(base, settings)
