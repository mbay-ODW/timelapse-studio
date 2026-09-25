"""Kopplung Framezahl ↔ fps ↔ Videolänge (§7.1, P-1 … P-5)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

FPS_MIN_SMOOTH = 10
FPS_MAX_SENSIBLE = 60


@dataclass
class Timing:
    frames: int
    fps: float
    hold_first_s: float = 0.0
    hold_last_s: float = 0.0
    title_s: float = 0.0
    credits_s: float = 0.0

    @property
    def body_s(self) -> float:
        return self.frames / self.fps if self.fps > 0 else 0.0

    @property
    def total_s(self) -> float:
        return self.body_s + self.hold_first_s + self.hold_last_s + self.title_s + self.credits_s

    @property
    def extra_s(self) -> float:
        return self.hold_first_s + self.hold_last_s + self.title_s + self.credits_s


def warnings(fps: float, frames: int) -> list[str]:
    w = []
    if frames == 0:
        w.append("Keine Bilder ausgewählt.")
    elif frames < 2:
        w.append("Mindestens 2 Bilder nötig für ein Video.")
    if fps <= 0:
        w.append("fps muss größer als 0 sein.")
    elif fps < FPS_MIN_SMOOTH:
        w.append(f"Unter {FPS_MIN_SMOOTH} fps wirkt die Bewegung ruckelig.")
    elif fps > FPS_MAX_SENSIBLE:
        w.append(f"Über {FPS_MAX_SENSIBLE} fps: viele Player und Geräte spielen das nicht flüssig ab.")
    return w


@dataclass
class Suggestion:
    kind: str                     # fps | nth | limit | info
    label: str
    fps: float
    frames: int
    total_s: float
    n: int | None = None          # für kind=nth
    limit: int | None = None      # für kind=limit
    exact: bool = False
    notes: list[str] = field(default_factory=list)


def suggest_for_length(frames: int, target_s: float, target_fps: float, *, extra_s: float = 0.0,
                       current_n: int = 1) -> list[Suggestion]:
    """Modus „Ziellänge fix“ (P-3).

    frames:     Framezahl der aktuellen Auswahl OHNE Längen-Anpassungsregel
    current_n:  falls die Auswahl bereits nur jedes n-te Bild enthält, wird n relativ dazu berechnet
    Liefert (a) fps anpassen, (b) n-tes Bild bei Ziel-fps, (c) exakte Framezahl per „auf N begrenzen“.
    """
    body = target_s - extra_s
    out: list[Suggestion] = []
    if frames < 2 or body <= 0 or target_fps <= 0:
        return out
    # (a) fps so wählen, dass die Länge passt
    fps_a = round(frames / body, 3)
    if 0.1 <= fps_a <= 240:  # außerhalb lässt normalize() den Wert nicht zu
        out.append(Suggestion("fps", f"fps auf {fps_a:g} setzen", fps_a, frames, frames / fps_a + extra_s,
                              notes=warnings(fps_a, frames)))
    wanted = max(2, round(target_fps * body))
    # (b) jedes n-te Bild – ganzzahliges n, bestes von floor/ceil
    if frames > wanted:
        base = frames / wanted
        best = None
        for n in {max(1, math.floor(base)), max(1, math.ceil(base))}:
            f = math.ceil(frames / n)
            if best is None or abs(f - wanted) < abs(best[1] - wanted):
                best = (n, f)
        n, f = best
        if n > 1:  # n = 1 wäre keine Änderung – dann hilft nur fps oder exakte Begrenzung
            out.append(Suggestion("nth", f"jedes {n * current_n}. Bild bei {target_fps:g} fps", target_fps, f,
                                  f / target_fps + extra_s, n=n, exact=abs(f - wanted) <= 1))
        # (c) exakt: auf N Bilder begrenzen (gleichmäßig über die Zeit)
        out.append(Suggestion("limit", f"auf {wanted} Bilder begrenzen bei {target_fps:g} fps", target_fps,
                              wanted, wanted / target_fps + extra_s, limit=wanted, exact=True))
    else:
        out.append(Suggestion("info", f"Zu wenige Bilder für {target_fps:g} fps – nur {frames} vorhanden",
                              target_fps, frames, frames / target_fps + extra_s,
                              notes=["Ziellänge wird mit dieser fps nicht erreicht."]))
    return out


# --- Schätzungen (P-31) ------------------------------------------------------------------

# Bits pro Pixel und Frame bei Zeitraffer-Material (hohe Bild-zu-Bild-Änderung); nahe an den
# Obergrenzen aus ffmpeg.CAP_BPP, weil Kamera-Zeitraffer die Deckelung praktisch immer erreicht
BPP = {"small": 0.075, "standard": 0.14, "high": 0.27, "max": 0.9}
CODEC_FACTOR = {"h264": 1.0, "h265": 0.6, "av1": 0.5}
# Encoder-Durchsatz in Megapixel/s (CPU, 5 Threads, i7-8700-Klasse); vaapi deutlich schneller
ENCODE_MPX_S = {("h264", "cpu"): 70, ("h265", "cpu"): 22, ("av1", "cpu"): 12,
                ("h264", "vaapi"): 400, ("h265", "vaapi"): 400, ("av1", "vaapi"): 12}
DECODE_MPX_S = 180  # JPEG-Decode + Skalierung der Quellbilder


def estimate(frames: int, fps: float, width: int, height: int, src_w: int, src_h: int, codec: str,
             quality: str, hw: str = "cpu", bitrate_kbps: int | None = None,
             size_factor: float = 1.0, speed_factor: float = 1.0) -> dict:
    """size_factor/speed_factor: Korrektur aus bisherigen Jobs (tatsächlich / geschätzt)."""
    px = width * height
    if bitrate_kbps:
        size = bitrate_kbps * 1000 / 8 * frames / max(fps, 0.001)
    else:
        size = BPP.get(quality, BPP["standard"]) * CODEC_FACTOR.get(codec, 1.0) * px * frames / 8
        if hw == "vaapi" and codec in ("h264", "h265"):
            size *= 1.5  # GPU-Encoder braucht für gleiche Qualität mehr Bitrate (siehe ffmpeg.VAAPI_BITRATE_FACTOR)
    enc = ENCODE_MPX_S.get((codec, hw), ENCODE_MPX_S[(codec, "cpu")]) * 1e6
    dec = DECODE_MPX_S * 1e6
    per_frame = px / enc + (src_w * src_h) / dec
    return {"size_bytes": int(size * size_factor), "render_s": round(frames * per_frame * speed_factor, 1),
            "render_fps": round(1 / per_frame / speed_factor, 1) if per_frame else None}
