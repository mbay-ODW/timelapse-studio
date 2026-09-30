#!/usr/bin/env python3
"""Erzeugt eine synthetische Kamera-Bildserie zum Ausprobieren von Timelapse Studio.

Szene: Ein Haus entsteht über zwei Wochen – mit Tag/Nacht-Zyklus, Sonnenbahn, ziehenden Wolken,
Regentagen, Baukran und beleuchteten Fenstern. Dateinamen tragen den Zeitstempel wie bei
Überwachungskameras (``DEMO-CAM-YYYYMMDD-HHMMSS.jpg``).

    python3 scripts/make-demo-data.py data/sources/demo-baustelle --days 14 --step 10
"""
from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 960, 540
HORIZON = 330


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sky_colors(hour: float, rain: bool) -> tuple[tuple, tuple, float]:
    """Himmelsfarbe oben/unten und Tageslicht 0..1 für eine Uhrzeit."""
    day = max(0.0, math.sin((hour - 6) / 14 * math.pi)) if 6 <= hour <= 20 else 0.0
    dusk = max(0.0, 1 - abs(hour - 6.3) / 1.2) + max(0.0, 1 - abs(hour - 19.7) / 1.2)
    top = lerp((8, 12, 32), (70, 130, 210), day)
    bottom = lerp((20, 26, 55), (170, 205, 240), day)
    if dusk > 0:
        bottom = lerp(bottom, (250, 150, 90), min(1, dusk) * 0.8)
    if rain:
        grey = lerp((25, 28, 35), (140, 145, 155), day)
        top, bottom = lerp(top, grey, 0.8), lerp(bottom, grey, 0.8)
    return top, bottom, day


def draw_frame(t: datetime, start: datetime, days: int, rng: random.Random, rain_days: set[int]) -> Image.Image:
    hour = t.hour + t.minute / 60
    d = (t - start).total_seconds() / 86400          # Projekt-Tag als Kommazahl
    rain = int(d) in rain_days
    top, bottom, light = sky_colors(hour, rain)

    img = Image.new("RGB", (W, H))
    px = np.zeros((H, W, 3), np.float32)
    grad = np.linspace(0, 1, HORIZON)[:, None]
    px[:HORIZON] = np.array(top) * (1 - grad[..., None]) + np.array(bottom) * grad[..., None]
    ground = lerp((20, 30, 18), (92, 138, 64), light)
    px[HORIZON:] = ground
    img = Image.fromarray(px.clip(0, 255).astype(np.uint8))
    g = ImageDraw.Draw(img)

    # Sonne / Mond
    if 6 <= hour <= 20 and not rain:
        a = (hour - 6) / 14 * math.pi
        sx, sy = int(80 + (W - 160) * (hour - 6) / 14), int(HORIZON - math.sin(a) * 250)
        g.ellipse((sx - 26, sy - 26, sx + 26, sy + 26), fill=(255, 236, 170))
    elif not rain:
        g.ellipse((W - 150, 60, W - 118, 92), fill=(220, 225, 240))

    # Wolken ziehen über den Tag
    cloud_col = lerp((40, 44, 60), (245, 247, 252), light)
    for k in range(6 if not rain else 11):
        cx = (k * 173 + (t.timestamp() / 60) * (1.3 + k * 0.2)) % (W + 300) - 150
        cy = 50 + (k * 37) % 140
        for j in range(4):
            g.ellipse((cx + j * 34, cy - (j % 2) * 14, cx + j * 34 + 70, cy + 34), fill=cloud_col)

    # Hügel und Bäume im Hintergrund
    hill = lerp((16, 26, 16), (70, 112, 58), light)
    g.polygon([(0, HORIZON), (180, HORIZON - 60), (420, HORIZON - 20), (700, HORIZON - 75), (W, HORIZON - 30), (W, HORIZON)], fill=hill)
    tree = lerp((10, 20, 12), (40, 92, 44), light)
    for x in (60, 120, 830, 890):
        g.rectangle((x - 5, HORIZON - 10, x + 5, HORIZON + 30), fill=lerp((20, 14, 8), (90, 64, 40), light))
        g.ellipse((x - 38, HORIZON - 95, x + 38, HORIZON + 5), fill=tree)

    # Baufortschritt 0..1 über die Tage (nachts und bei Regen ruht die Baustelle)
    work = 0.0
    for day_i in range(days):
        for hh in range(7, 17):
            tt = start + timedelta(days=day_i, hours=hh)
            if tt <= t and day_i not in rain_days and tt.weekday() < 6:
                work += 1
    progress = min(1.0, work / (days * 10 * 0.62))

    bx, bw, by = 360, 260, HORIZON + 120
    wall = lerp((40, 30, 26), (196, 170, 140), light)
    concrete = lerp((30, 30, 32), (150, 150, 155), light)
    g.rectangle((bx - 20, by, bx + bw + 20, by + 18), fill=concrete)                 # Bodenplatte
    wall_h = int(170 * min(1, progress / 0.6))
    if wall_h:
        g.rectangle((bx, by - wall_h, bx + bw, by), fill=wall)
    if progress > 0.6:                                                               # Dach
        r = min(1, (progress - 0.6) / 0.25)
        roof = lerp((40, 18, 16), (170, 70, 52), light)
        peak = by - 170 - int(90 * r)
        g.polygon([(bx - 25, by - 170), (bx + bw // 2, peak), (bx + bw + 25, by - 170)], fill=roof)
    if progress > 0.85:                                                              # Fenster (nachts beleuchtet)
        lit = (255, 214, 120) if light < 0.25 and rng.random() < 0.8 else lerp((30, 40, 60), (150, 190, 220), light)
        for wx in (bx + 30, bx + 110, bx + 190):
            g.rectangle((wx, by - 130, wx + 40, by - 80), fill=lit)
        g.rectangle((bx + 115, by - 60, bx + 150, by), fill=lerp((20, 14, 10), (110, 70, 40), light))

    # Kran, solange gebaut wird
    if 0.05 < progress < 0.95:
        crane = lerp((60, 45, 10), (235, 180, 40), light)
        cx = bx + bw + 90
        g.rectangle((cx, by - 280, cx + 10, by + 10), fill=crane)
        arm = math.sin(t.timestamp() / 3000) * 0.4
        ex, ey = cx + 5 - int(math.cos(arm) * 240), by - 280 + int(math.sin(arm) * 20)
        g.line((cx + 5, by - 280, ex, ey), fill=crane, width=6)
        if 7 <= hour <= 17 and not rain:
            g.line((ex, ey, ex, by - 190), fill=(40, 40, 40), width=2)
            g.rectangle((ex - 14, by - 190, ex + 14, by - 175), fill=concrete)

    # Arbeiter / Auto tagsüber
    if 7 <= hour <= 16.5 and not rain and t.weekday() < 6 and 0 < progress < 1:
        for k in range(3):
            wx = bx - 60 + int((t.timestamp() / 90 + k * 97) % 380)
            g.rectangle((wx, by - 26, wx + 8, by), fill=(230, 110, 30))
            g.ellipse((wx - 1, by - 36, wx + 9, by - 26), fill=(240, 220, 60))

    # Regenstreifen
    if rain:
        rg = ImageDraw.Draw(img)
        for _ in range(260):
            x, y = rng.randrange(W), rng.randrange(H)
            rg.line((x, y, x - 4, y + 14), fill=(190, 200, 215), width=1)

    img = img.filter(ImageFilter.GaussianBlur(0.6))
    noise = np.random.default_rng(int(t.timestamp())).normal(0, 3 + (1 - light) * 5, (H, W, 1))
    out = (np.asarray(img, np.float32) + noise).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(out)
    ImageDraw.Draw(img).text((10, 8), t.strftime("%Y-%m-%d %H:%M:%S"), fill=(235, 235, 235))
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="Zielordner (wird eine Quelle, z. B. data/sources/demo-baustelle)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step", type=int, default=10, help="Minuten zwischen zwei Bildern")
    ap.add_argument("--start", default="2026-05-04")
    args = ap.parse_args()

    rng = random.Random(42)
    start = datetime.strptime(args.start, "%Y-%m-%d")
    rain_days = {3, 9}
    args.target.mkdir(parents=True, exist_ok=True)
    n = args.days * 24 * 60 // args.step
    for i in range(n):
        t = start + timedelta(minutes=i * args.step, seconds=rng.randrange(0, 20))
        draw_frame(t, start, args.days, rng, rain_days).save(
            args.target / f"DEMO-CAM-{t:%Y%m%d-%H%M%S}.jpg", "JPEG", quality=82)
        if i % 200 == 0:
            print(f"{i}/{n}")
    print(f"{n} Bilder in {args.target}")


if __name__ == "__main__":
    main()
