"""ffmpeg-Kommandos für Render- und Proxy-Jobs (§7.2, R-7, V-3).

Eingabe ist eine concat-Liste (ffconcat) mit einem Eintrag pro Frame und dem formatierten
Zeitstempel als Paket-Metadatum → `drawtext=%{metadata:ts}` zeigt pro Frame die richtige Zeit.
`setpts=N/(fps*TB)` + `-fps_mode cfr` erzwingt exakt einen Ausgabeframe je Eingabebild.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from ..indexer.timestamps import from_naive_ms
from .params import output_geometry

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Qualitätsstufen → (crf/qp, preset) je Encoder (P-14)
QUALITY = {
    "libx264": {"small": (26, "medium"), "standard": (21, "medium"), "high": (18, "slow"), "max": (15, "slow")},
    "libx265": {"small": (29, "medium"), "standard": (25, "medium"), "high": (21, "slow"), "max": (18, "slow")},
    "libsvtav1": {"small": (42, "8"), "standard": (35, "7"), "high": (30, "6"), "max": (24, "5")},
    "h264_vaapi": {"small": (28, None), "standard": (24, None), "high": (21, None), "max": (18, None)},
    "hevc_vaapi": {"small": (30, None), "standard": (26, None), "high": (23, None), "max": (20, None)},
}
# Bitraten-Obergrenze je Stufe (Bits pro Pixel und Frame) – "capped CRF": Zeitraffer-Material ändert sich
# von Bild zu Bild stark, reines CRF erzeugt sonst 50+ Mbit/s bei 1080p.
CAP_BPP = {"small": 0.08, "standard": 0.15, "high": 0.30, "max": None}

POSITIONS = {
    "tl": ("pad", "pad"), "tc": ("(w-text_w)/2", "pad"), "tr": ("w-text_w-pad", "pad"),
    "bl": ("pad", "h-text_h-pad"), "bc": ("(w-text_w)/2", "h-text_h-pad"), "br": ("w-text_w-pad", "h-text_h-pad"),
}


@lru_cache(maxsize=1)
def available_encoders() -> frozenset[str]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return frozenset()
    out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return frozenset(line.split()[1] for line in out.splitlines() if line.startswith(" V") and len(line.split()) > 1)


def pick_encoder(codec: str, hwaccel: str) -> str:
    enc = available_encoders()
    if hwaccel in ("vaapi", "qsv"):
        hw = {"h264": "h264_vaapi", "h265": "hevc_vaapi"}.get(codec)
        if hw and (not enc or hw in enc):
            return hw
    cpu = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}[codec]
    if enc and cpu not in enc and codec == "av1" and "libaom-av1" in enc:
        return "libaom-av1"
    return cpu


def _esc_concat(path: str) -> str:
    return path.replace("'", "'\\''")


def _esc_meta(text: str) -> str:
    # Wert steht in '…' in der ffconcat-Datei; drawtext expandiert %{metadata} ohne weitere Auswertung
    return text.replace("\\", "\\\\").replace("'", "'\\''")


def _esc_filter(v: str) -> str:
    """Wert für eine Filteroption (in '…')."""
    return v.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def write_concat(path: Path, frames: list[tuple[str, int]], ts_format: str | None) -> None:
    """frames: [(absoluter Pfad, taken_ms)]."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("ffconcat version 1.0\n")
        for p, ms in frames:
            f.write(f"file '{_esc_concat(p)}'\n")
            if ts_format:
                try:
                    txt = from_naive_ms(ms).strftime(ts_format)
                except ValueError:
                    txt = ""
                f.write(f"file_packet_meta ts '{_esc_meta(txt)}'\n")


@dataclass
class RenderPlan:
    cmd: list[str]
    total_frames: int
    duration_s: float
    out_w: int
    out_h: int
    encoder: str
    text_files: list[Path] = field(default_factory=list)


def rate(fps: float) -> Fraction:
    """fps als exakter Bruch (29.97 → 30000/1001)."""
    return Fraction(fps).limit_denominator(1001)


def build(params: dict, *, concat_file: Path, n_frames: int, src_w: int, src_h: int, output: Path,
          tmp_dir: Path, hwaccel: str = "none", vaapi_device: str = "/dev/dri/renderD128",
          threads: int = 4, preview: bool = False, mixed_sizes: bool = False,
          audio_file: Path | None = None) -> RenderPlan:
    p = params
    fps = float(p["fps"])
    fr = rate(fps)
    fr_s = f"{fr.numerator}/{fr.denominator}"
    geo = output_geometry(p, src_w, src_h)
    ow, oh = geo["out"]["w"], geo["out"]["h"]
    if preview:  # V-3: 480p-Proxy (kürzere Kante 480)
        s = 480 / min(ow, oh)
        if s < 1:
            ow, oh = max(2, int(round(ow * s / 2)) * 2), max(2, int(round(oh * s / 2)) * 2)
    encoder = "libx264" if preview else pick_encoder(p["codec"], hwaccel)
    use_vaapi = encoder.endswith("_vaapi")

    chain: list[str] = []
    if mixed_sizes:  # unterschiedliche Bildgrößen auf ein Raster bringen (scale passt sich pro Frame an)
        chain.append(f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
                     f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    # Exakt ein Frame je Bild: ganzzahlige Zeitbasis 1/fps + pts=N (N/(fps*TB) mit µs-Zeitbasis rundet
    # und ließ bei 2.023 Bildern 5 Frames fallen). fps= setzt die Link-Framerate für tpad/fade.
    chain.append(f"settb={fr.denominator}/{fr.numerator},setpts=N,fps={fr_s}")
    c = geo["crop"]
    if (c["w"], c["h"]) != (src_w, src_h):
        chain.append(f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}")
    rot = int(p["rotate"])
    if rot == 90:
        chain.append("transpose=1")
    elif rot == 270:
        chain.append("transpose=2")
    elif rot == 180:
        chain.append("hflip,vflip")
    if p["flip_h"]:
        chain.append("hflip")
    if p["flip_v"]:
        chain.append("vflip")
    chain.append(f"scale={ow}:{oh}:flags={'bilinear' if preview else 'lanczos'},setsar=1")
    if p["deflicker"]["enabled"]:
        size = max(2, min(129, int(p["deflicker"]["size"])))
        chain.append(f"deflicker=size={size}:mode=am")
    if p["blend"]["enabled"] and int(p["blend"]["frames"]) > 1:
        chain.append(f"tmix=frames={min(10, int(p['blend']['frames']))}")
    ov = p["overlay"]
    if ov["enabled"]:
        fs = max(8, int(oh * float(ov["size"]) / 100))
        pad = max(4, fs // 2)
        x, y = POSITIONS.get(ov["position"], POSITIONS["bl"])
        x, y = x.replace("pad", str(pad)), y.replace("pad", str(pad))
        box = f":box=1:boxcolor=black@0.45:boxborderw={max(2, fs // 4)}" if ov["box"] else ":shadowx=2:shadowy=2"
        chain.append(f"drawtext=fontfile={FONT}:text='%{{metadata\\:ts}}':fontsize={fs}:fontcolor=white"
                     f"{box}:x={x}:y={y}")
    # Halten erstes/letztes Bild (P-5) frame-basiert: hinter concat+setpts ist die Link-Framerate unbekannt
    hold_a, hold_b = round(float(p["hold_first_s"]) * fps), round(float(p["hold_last_s"]) * fps)
    if hold_a > 0 or hold_b > 0:
        chain.append(f"tpad=start={hold_a}:stop={hold_b}:start_mode=clone:stop_mode=clone")
    chain.append("format=yuv420p")

    body_frames = n_frames + hold_a + hold_b
    graph = [f"[0:v]{','.join(chain)}[body]"]
    segments = ["[body]"]
    text_files: list[Path] = []
    total_frames = body_frames

    def card(label: str, text: str, dur: float) -> str:
        nonlocal total_frames
        tf = tmp_dir / f"{label}.txt"
        tf.write_text(text, encoding="utf-8")
        text_files.append(tf)
        fs = max(12, int(oh * 0.06))
        total_frames += round(dur * fps)
        graph.append(
            f"color=c=black:s={ow}x{oh}:r={fr_s}:d={dur},drawtext=fontfile={FONT_BOLD}:"
            f"textfile='{_esc_filter(str(tf))}':fontsize={fs}:fontcolor=white:line_spacing={fs // 3}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p,setsar=1[{label}]")
        return f"[{label}]"

    title, credits = p["title"], p["credits"]
    if (title.get("text") or "").strip() and float(title.get("duration_s") or 0) > 0:
        segments.insert(0, card("title", title["text"].strip(), float(title["duration_s"])))
    if (credits.get("text") or "").strip() and float(credits.get("duration_s") or 0) > 0:
        segments.append(card("credits", credits["text"].strip(), float(credits["duration_s"])))
    last = "[body]"
    if len(segments) > 1:
        graph.append(f"{''.join(segments)}concat=n={len(segments)}:v=1:a=0[joined]")
        last = "[joined]"
    duration = total_frames / fps
    fades = []
    if float(p["fade_in_s"]) > 0:
        fades.append(f"fade=t=in:st=0:d={min(float(p['fade_in_s']), duration)}")
    if float(p["fade_out_s"]) > 0:
        d = min(float(p["fade_out_s"]), duration)
        fades.append(f"fade=t=out:st={max(0.0, duration - d):.3f}:d={d}")
    tail = list(fades)
    if use_vaapi:
        tail += ["format=nv12", "hwupload"]
    if tail:
        graph.append(f"{last}{','.join(tail)}[vout]")
        last = "[vout]"

    # kein -nostdin: Abbruch erfolgt sauber per "q" auf stdin (R-2)
    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "warning",
           "-progress", "pipe:1", "-nostats"]
    if use_vaapi:
        cmd += ["-init_hw_device", f"vaapi=va:{vaapi_device}", "-filter_hw_device", "va"]
    # -reinit_filter 0: bei Bildern anderer Größe (z. B. vereinzelte 1280×720-Snapshots) den Filtergraphen
    # NICHT neu aufbauen – sonst beginnt setpts=N wieder bei 0 und ffmpeg verwirft Frames.
    cmd += ["-reinit_filter", "0", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
    has_audio = audio_file is not None and not preview
    if has_audio:
        cmd += ["-i", str(audio_file)]
    cmd += ["-filter_complex", ";".join(graph), "-map", last]
    if has_audio:
        fo = float(p["audio"].get("fade_out_s") or 0)
        af = f"afade=t=out:st={max(0.0, duration - fo):.3f}:d={fo}" if fo > 0 else "anull"
        cmd += ["-map", "1:a:0", "-af", af, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-fps_mode", "cfr", "-r", fr_s, "-frames:v", str(total_frames)]
    cmd += ["-filter_complex_threads", str(threads)]

    ex = p["expert"]
    q_level = "small" if preview else p["quality"]
    q, preset = QUALITY.get(encoder, QUALITY["libx264"])[q_level]
    if preview:
        preset = "ultrafast"
    elif ex["enabled"]:
        q = int(ex.get("crf") or q)
        preset = ex.get("preset") or preset
    bitrate = int(ex.get("bitrate_kbps") or 0) if ex["enabled"] and not preview else 0
    cmd += ["-c:v", encoder]
    cap = CAP_BPP.get(q_level) if not (ex["enabled"] and not preview) else None
    cap_kbps = int(cap * ow * oh * fps / 1000) if cap else 0
    if encoder in ("libx264", "libx265"):
        cmd += ["-preset", str(preset), "-threads", str(threads)]
        if bitrate:
            cmd += ["-b:v", f"{bitrate}k", "-maxrate", f"{int(bitrate * 1.5)}k", "-bufsize", f"{bitrate * 2}k"]
        else:
            cmd += ["-crf", str(q)]
            if cap_kbps:
                cmd += ["-maxrate", f"{cap_kbps}k", "-bufsize", f"{cap_kbps * 2}k"]
        if encoder == "libx265":
            cmd += ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
        cmd += ["-pix_fmt", "yuv420p"]
    elif encoder == "libsvtav1":
        cmd += ["-preset", str(preset)] + (["-b:v", f"{bitrate}k"] if bitrate else ["-crf", str(q)])
        if cap_kbps and not bitrate:
            cmd += ["-maxrate", f"{cap_kbps}k"]
        cmd += ["-pix_fmt", "yuv420p"]
    elif encoder == "libaom-av1":
        cmd += ["-cpu-used", "6", "-row-mt", "1"] + (["-b:v", f"{bitrate}k"] if bitrate else ["-crf", str(q), "-b:v", "0"])
    elif use_vaapi:
        if bitrate or cap_kbps:  # VAAPI: gedeckelte VBR statt CQP, sonst explodiert die Dateigröße
            br = bitrate or int(cap_kbps * 0.7)
            cmd += ["-rc_mode", "VBR", "-b:v", f"{br}k", "-maxrate", f"{bitrate * 1.5 if bitrate else cap_kbps:.0f}k"]
        else:
            cmd += ["-rc_mode", "CQP", "-qp", str(q)]
        if encoder == "hevc_vaapi":
            cmd += ["-tag:v", "hvc1"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", str(output)]
    return RenderPlan(cmd=cmd, total_frames=total_frames, duration_s=duration, out_w=ow, out_h=oh,
                      encoder=encoder, text_files=text_files)


def res_label(w: int, h: int) -> str:
    return f"{min(w, h)}p"
