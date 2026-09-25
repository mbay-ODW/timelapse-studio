"""Bildverarbeitung für Index-Worker: Thumbnail (WebP), Helligkeit, dHash, EXIF-Zeit.

Läuft in einem ProcessPool – nur reine Funktionen, keine DB-Zugriffe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from .timestamps import parse_exif_datetime

try:  # HEIC optional (Q-4)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover
    pass

Image.MAX_IMAGE_PIXELS = 200_000_000

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}


@dataclass
class ProcResult:
    image_id: int
    ok: bool
    width: int | None = None
    height: int | None = None
    brightness: float | None = None
    phash: int | None = None
    exif_ms: int | None = None
    error: str | None = None


def _exif_ms(im: Image.Image) -> int | None:
    try:
        exif = im.getexif()
        sub = exif.get_ifd(0x8769)  # Exif-IFD
        return parse_exif_datetime(sub.get(0x9003) or exif.get(0x0132), sub.get(0x9291))
    except Exception:
        return None


def dhash(gray: Image.Image) -> int:
    """64-bit Difference-Hash als vorzeichenbehafteter int64 (SQLite-kompatibel)."""
    small = gray.resize((9, 8), Image.Resampling.BILINEAR)
    px = small.tobytes()
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (px[base + col] > px[base + col + 1])
    return bits - (1 << 64) if bits >= (1 << 63) else bits


def open_oriented(path: str | os.PathLike, max_edge: int | None = None) -> Image.Image:
    im = Image.open(path)
    if max_edge and im.format == "JPEG":
        im.draft("RGB", (max_edge, max_edge))  # DCT-Skalierung: 4–8× schneller
    im = ImageOps.exif_transpose(im)
    return im


def process(image_id: int, src: str, thumb_path: str, thumb_size: int) -> ProcResult:
    try:
        with Image.open(src) as raw:
            exif_ms = _exif_ms(raw)
            w, h = raw.size
            orientation = raw.getexif().get(0x0112, 1) if hasattr(raw, "getexif") else 1
            if orientation in (5, 6, 7, 8):
                w, h = h, w
            if raw.format == "JPEG":
                # Zielgröße seitenrichtig anfordern → DCT-Skalierung bis 1/8 (z. B. 2560×1440 → 320×180)
                rw, rh = raw.size
                scale = thumb_size / max(rw, rh)
                raw.draft("RGB", (max(1, int(rw * scale)), max(1, int(rh * scale))))
            im = ImageOps.exif_transpose(raw)
            im = im.convert("RGB")
            im.thumbnail((thumb_size, thumb_size), Image.Resampling.BILINEAR, reducing_gap=2.0)
        gray = im.convert("L")
        brightness = round(ImageStat.Stat(gray).mean[0], 2)
        ph = dhash(gray)
        Path(thumb_path).parent.mkdir(parents=True, exist_ok=True)
        tmp = thumb_path + ".tmp"
        im.save(tmp, "WEBP", quality=72, method=2)
        os.replace(tmp, thumb_path)
        return ProcResult(image_id, True, w, h, brightness, ph, exif_ms)
    except Exception as e:  # I-6: markieren, weitermachen
        return ProcResult(image_id, False, error=f"{type(e).__name__}: {e}"[:500])


def make_proxy(src: str, dst: str, size: int) -> None:
    with Image.open(src) as raw:
        if raw.format == "JPEG":
            raw.draft("RGB", (size, size))
        im = ImageOps.exif_transpose(raw).convert("RGB")
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    tmp = dst + ".tmp"
    im.save(tmp, "JPEG", quality=82, optimize=False, progressive=False)
    os.replace(tmp, dst)
