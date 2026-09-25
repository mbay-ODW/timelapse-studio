"""Zeitstempel-Ermittlung (I-3).

Alle Zeitpunkte werden als *lokale* Wandzeit in "naiver Epoch-ms" gespeichert:
datetime(2026,6,3,15,17,2) → ms seit 1970-01-01 00:00 so, als wäre die Lokalzeit UTC.
Damit sind Tageszeit, Wochentag und Tagesgruppierung reine Integer-Arithmetik
(Pipeline S-3/S-4, Timeline B-1) und unabhängig von Sommerzeitwechseln.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

TS_METHODS = ("exif", "filename", "mtime")

# Greift z. B. bei "CC400W-001-20260603-1517024995-Cam-2-Type-0.jpg"
# (YYYYMMDD-HHMMSS + 4 Stellen Sekundenbruchteil), "IMG_20260603_151702.jpg",
# "2026-06-03 15.17.02.jpg", "snapshot_2026-06-03T15-17-02.png".
DEFAULT_FILENAME_PATTERN = (
    r"(?P<Y>(?:19|20)\d{2})[-_.]?(?P<m>[01]\d)[-_.]?(?P<d>[0-3]\d)"
    r"[-_T ]?(?P<H>[0-2]\d)[-_.:h]?(?P<M>[0-5]\d)[-_.:m]?(?P<S>[0-5]\d)(?P<f>\d{1,6})?"
)

_STRFTIME_MAP = {
    "%Y": r"(?P<Y>\d{4})", "%y": r"(?P<y>\d{2})", "%m": r"(?P<m>\d{2})", "%d": r"(?P<d>\d{2})",
    "%H": r"(?P<H>\d{2})", "%M": r"(?P<M>\d{2})", "%S": r"(?P<S>\d{2})", "%f": r"(?P<f>\d{1,6})",
    "%%": "%",
}


class PatternError(ValueError):
    pass


@lru_cache(maxsize=64)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Regex mit benannten Gruppen (Y/y, m, d, H, M, S, f) oder strftime-Muster (enthält '%')."""
    p = pattern.strip() or DEFAULT_FILENAME_PATTERN
    if "%" in p and "(?P<" not in p:
        out, i = [], 0
        while i < len(p):
            tok = p[i:i + 2]
            if tok in _STRFTIME_MAP:
                out.append(_STRFTIME_MAP[tok])
                i += 2
            elif p[i] == "*":
                out.append(".*?")
                i += 1
            else:
                out.append(re.escape(p[i]))
                i += 1
        p = "".join(out)
    try:
        rx = re.compile(p)
    except re.error as e:
        raise PatternError(f"Ungültiges Muster: {e}") from e
    groups = set(rx.groupindex)
    if not ({"Y", "y"} & groups) or not {"m", "d"} <= groups:
        raise PatternError("Muster braucht mindestens Jahr (Y oder y), Monat (m) und Tag (d)")
    return rx


def naive_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def from_naive_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def parse_filename(name: str, pattern: str = "") -> int | None:
    rx = compile_pattern(pattern)
    m = rx.search(name)
    if not m:
        return None
    g = m.groupdict()
    try:
        year = int(g["Y"]) if g.get("Y") else 2000 + int(g["y"])
        frac = g.get("f") or ""
        micro = int((frac + "000000")[:6]) if frac else 0
        dt = datetime(year, int(g["m"]), int(g["d"]), int(g.get("H") or 0),
                      int(g.get("M") or 0), int(g.get("S") or 0), micro)
    except (ValueError, TypeError):
        return None
    return naive_ms(dt)


def parse_exif_datetime(value: str | bytes | None, subsec: str | bytes | None = None) -> int | None:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    value = value.strip().rstrip("\x00")
    try:
        dt = datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if subsec:
        if isinstance(subsec, bytes):
            subsec = subsec.decode("ascii", "ignore")
        digits = "".join(ch for ch in str(subsec) if ch.isdigit())
        if digits:
            dt = dt.replace(microsecond=int((digits + "000000")[:6]))
    return naive_ms(dt)


@lru_cache(maxsize=8)
def _zone(tz: str) -> ZoneInfo:
    return ZoneInfo(tz)


def mtime_to_naive_ms(mtime_ns: int, tz: str) -> int:
    dt = datetime.fromtimestamp(mtime_ns / 1e9, tz=_zone(tz)).replace(tzinfo=None)
    return naive_ms(dt)


def resolve(order: list[str], *, exif_ms: int | None, filename_ms: int | None,
            mtime_ms: int) -> tuple[int, str]:
    """Erster verfügbarer Wert gemäß Reihenfolge der Quelle; mtime ist immer die letzte Rettung."""
    candidates = {"exif": exif_ms, "filename": filename_ms, "mtime": mtime_ms}
    for method in order:
        v = candidates.get(method)
        if v is not None:
            return v, method
    return mtime_ms, "mtime"
