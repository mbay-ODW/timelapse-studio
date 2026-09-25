"""Video-Parameter eines Projekts (§7.2) mit Defaults und Normalisierung."""
from __future__ import annotations

import copy

DEFAULT_PARAMS: dict = {
    "mode": "fps",               # fps | length (P-2/P-3)
    "fps": 30,
    "target_length_s": 180,
    "hold_first_s": 0,
    "hold_last_s": 0,
    "resolution": "1080",        # source | 2160 | 1440 | 1080 | 720 | custom
    "custom_w": 1920,
    "custom_h": 1080,
    "aspect": "original",        # original | 16:9 | 9:16 | 1:1 | 4:3
    "crop": None,                # {x,y,w,h} normiert 0..1 bezogen aufs Quellbild
    "rotate": 0,                 # 0 | 90 | 180 | 270
    "flip_h": False,
    "flip_v": False,
    "codec": "h264",             # h264 | h265 | av1
    "quality": "standard",       # small | standard | high | max
    "expert": {"enabled": False, "crf": 20, "preset": "medium", "bitrate_kbps": 0},
    "deflicker": {"enabled": False, "size": 10},
    "blend": {"enabled": False, "frames": 3},
    "overlay": {"enabled": False, "format": "%d.%m.%Y %H:%M", "position": "bl", "size": 3.5, "box": True},
    "title": {"text": "", "duration_s": 3},
    "credits": {"text": "", "duration_s": 3},
    "fade_in_s": 0,
    "fade_out_s": 0,
    "audio": {"file": None, "name": None, "fade_out_s": 3},
}

RES_HEIGHT = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720}
ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def normalize(params: dict | None) -> dict:
    p = _merge(DEFAULT_PARAMS, params or {})
    p["fps"] = min(240.0, max(0.1, float(p["fps"])))
    p["rotate"] = int(p["rotate"]) % 360 if int(p["rotate"]) % 90 == 0 else 0
    for k in ("hold_first_s", "hold_last_s", "fade_in_s", "fade_out_s"):
        p[k] = min(600.0, max(0.0, float(p[k] or 0)))
    if p["codec"] not in ("h264", "h265", "av1"):
        p["codec"] = "h264"
    if p["quality"] not in ("small", "standard", "high", "max"):
        p["quality"] = "standard"
    return p


def extra_seconds(p: dict) -> float:
    """Zusätzliche Dauer außerhalb der Bildsequenz (Halten, Titel, Abspann)."""
    t = p["hold_first_s"] + p["hold_last_s"]
    if (p["title"].get("text") or "").strip():
        t += float(p["title"].get("duration_s") or 0)
    if (p["credits"].get("text") or "").strip():
        t += float(p["credits"].get("duration_s") or 0)
    return t


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def output_geometry(p: dict, src_w: int, src_h: int) -> dict:
    """Crop-Rechteck (Pixel, im Quellbild), Rotation und Ausgabegröße (gerade Zahlen für yuv420p)."""
    cw, ch = src_w, src_h
    cx = cy = 0
    crop = p.get("crop")
    if crop:
        cx = int(round(crop["x"] * src_w))
        cy = int(round(crop["y"] * src_h))
        cw = int(round(crop["w"] * src_w))
        ch = int(round(crop["h"] * src_h))
    elif p["aspect"] in ASPECTS:
        # zentrierter Zuschnitt aufs Seitenverhältnis (nach Rotation gedacht)
        target = ASPECTS[p["aspect"]]
        if p["rotate"] in (90, 270):
            target = 1 / target
        if cw / ch > target:
            nw = int(round(ch * target))
            cx, cw = (cw - nw) // 2, nw
        else:
            nh = int(round(cw / target))
            cy, ch = (ch - nh) // 2, nh
    cw, ch = max(2, min(cw, src_w - cx)), max(2, min(ch, src_h - cy))
    rw, rh = (ch, cw) if p["rotate"] in (90, 270) else (cw, ch)
    res = p["resolution"]
    if res == "custom":
        ow, oh = _even(p["custom_w"]), _even(p["custom_h"])
    elif res in RES_HEIGHT:
        # "1080p" = kürzere Kante 1080 (auch Hochformat), nie hochskalieren
        short = min(RES_HEIGHT[res], min(rw, rh))
        scale = short / min(rw, rh)
        ow, oh = _even(rw * scale), _even(rh * scale)
    else:
        ow, oh = _even(rw), _even(rh)
    return {"crop": {"x": cx, "y": cy, "w": cw, "h": ch}, "rotated": {"w": rw, "h": rh},
            "out": {"w": ow, "h": oh}}
