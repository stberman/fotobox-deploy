#!/usr/bin/env python3
"""Erzeugt die mitgelieferten Standard-Rahmen in overlays/ (3:2 Querformat, 3000x2000).

Aufruf:  python tools/make_frames.py
Eigene Rahmen: einfach transparente PNGs nach overlays/ legen (oder ueber die
Seite /rahmen hochladen). Optional eine gleichnamige .json mit "title" und
empfohlenen Text-Einstellungen (siehe DEFAULTS in overlay.py).
"""
import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 3000, 2000
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overlays")
os.makedirs(OUT, exist_ok=True)


def save(img, name, **meta):
    img.save(os.path.join(OUT, name + ".png"), "PNG", optimize=True)
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("->", name)


def border(width, color, radius=0, bottom=None):
    """Rahmen mit (optional) groesserem unteren Rand und abgerundeter Innenkante."""
    img = Image.new("RGBA", (W, H), color)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((width, width, W - width, H - (bottom or width)), radius=radius, fill=255)
    cut = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(cut, (0, 0), mask)
    return img


# 1) Schlichter weisser Rahmen, innen abgerundet
save(border(70, (255, 255, 255, 255), radius=60), "weiss",
     title="Weiß schlicht", text_color="light", text_pos="bottom", text_bg=True)

# 2) Polaroid: breiter weisser Rand unten fuer Text
save(border(90, (255, 255, 255, 255), radius=20, bottom=330), "polaroid",
     title="Polaroid", text_color="dark", text_pos="bottom", text_bg=False,
     text_offset=0.045, text_size=0.055)

# 3) Schwarz elegant: duenner Rand + dunkler Verlauf unten fuer Text
img = border(40, (15, 15, 15, 255), radius=30)
grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gp = grad.load()
for y in range(int(H * 0.72), H):
    a = int(200 * ((y - H * 0.72) / (H * 0.28)) ** 1.6)
    for x in range(W):
        gp[x, y] = (0, 0, 0, a)
img = Image.alpha_composite(grad, img)
save(img, "schwarz", title="Schwarz elegant", text_color="light", text_pos="bottom", text_bg=False,
     text_size=0.05, text_offset=0.035)

# 4) Gold: doppelte goldene Linie
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
gold = (212, 175, 55, 255)
d.rectangle((50, 50, W - 50, H - 50), outline=gold, width=18)
d.rectangle((95, 95, W - 95, H - 95), outline=gold, width=6)
for cx, cy in ((50, 50), (W - 50, 50), (50, H - 50), (W - 50, H - 50)):
    d.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=gold)
save(img, "gold", title="Gold", text_color="light", text_pos="bottom", text_bg=True)

# 5) Party: Konfetti entlang der Raender
random.seed(7)
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
colors = [(255, 82, 82), (255, 193, 7), (76, 175, 80), (33, 150, 243), (233, 30, 99), (255, 255, 255)]
for _ in range(900):
    # Position: in einem Band von ~12% Breite am Rand, dichter zur Kante hin
    side = random.random()
    band = (random.random() ** 2) * 0.12
    if side < 0.5:   # oben/unten
        x = random.uniform(0, W)
        y = band * H if random.random() < 0.5 else H - band * H
    else:            # links/rechts
        y = random.uniform(0, H)
        x = band * W if random.random() < 0.5 else W - band * W
    r = random.uniform(10, 34)
    col = random.choice(colors) + (random.randint(170, 255),)
    shape = random.random()
    if shape < 0.5:
        d.ellipse((x - r, y - r, x + r, y + r), fill=col)
    elif shape < 0.8:
        ang = random.uniform(0, math.pi)
        pts = [(x + r * 1.6 * math.cos(ang), y + r * 1.6 * math.sin(ang)),
               (x - r * 1.6 * math.cos(ang), y - r * 1.6 * math.sin(ang))]
        d.line(pts, fill=col, width=int(r * 0.7))
    else:
        pts = [(x + r * math.cos(a), y + r * math.sin(a))
               for a in (random.uniform(0, 2) + k * 2.094 for k in range(3))]
        d.polygon(pts, fill=col)
img = img.filter(ImageFilter.GaussianBlur(1.2))
save(img, "party", title="Party-Konfetti", text_color="light", text_pos="bottom", text_bg=True)
