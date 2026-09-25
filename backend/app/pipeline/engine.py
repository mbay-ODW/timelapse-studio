"""Nicht-destruktive Auswahl-Pipeline (§6, S-1 … S-11).

Arbeitet vektorisiert auf numpy-Arrays des gesamten Bildbestands. Zeiten sind "naive
Epoch-ms" (Lokalzeit als UTC kodiert, siehe indexer.timestamps), dadurch sind
Tageszeit/Wochentag reine Integer-Arithmetik.

Jede Regel bekommt die aktuelle, zeitlich sortierte Auswahl (Index-Array in den Bestand)
und liefert eine neue. Die Reihenfolge der Regeln ist bedeutsam (z. B. erst Tageszeit,
dann jedes n-te Bild).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

DAY_MS = 86_400_000
MIN_MS = 60_000


@dataclass
class Universe:
    """Alle Bilder aller aktiven Quellen, sortiert nach (Zeit, id)."""
    ids: np.ndarray          # int64
    src: np.ndarray          # int32
    t: np.ndarray            # int64 (naive ms)
    b: np.ndarray            # float32, NaN = noch unbekannt
    ph: np.ndarray           # uint64 dHash (0 = unbekannt)

    @classmethod
    def from_rows(cls, rows) -> "Universe":
        """rows: (id, source_id, taken_ms, brightness|None, phash|None)."""
        if not rows:
            e = np.empty(0)
            return cls(e.astype(np.int64), e.astype(np.int32), e.astype(np.int64), e.astype(np.float32),
                       e.astype(np.uint64))
        ids, src, t, b, ph = zip(*rows)
        ids = np.array(ids, np.int64)
        src = np.array(src, np.int32)
        t = np.array(t, np.int64)
        b = np.array(b, np.float64).astype(np.float32)  # None → NaN
        ph = np.array([0 if p is None else p for p in ph], np.int64).view(np.uint64)
        order = np.lexsort((ids, t))
        return cls(ids[order], src[order], t[order], b[order], ph[order])

    def __len__(self) -> int:
        return len(self.ids)


@dataclass
class Marks:
    include: set[int] = field(default_factory=set)
    exclude: set[int] = field(default_factory=set)


class RuleError(ValueError):
    pass


# ----------------------------------------------------------------------------- Hilfen

def parse_hhmm(v: str | None, default: int = 0) -> int:
    """'07:30' → ms seit Mitternacht; '24:00' erlaubt."""
    if v in (None, ""):
        return default
    try:
        h, m = str(v).split(":")[:2]
        h, m = int(h), int(m)
    except ValueError:
        raise RuleError(f"Ungültige Uhrzeit: {v}")
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise RuleError(f"Ungültige Uhrzeit: {v}")
    return (h * 60 + m) * MIN_MS


def parse_date(v: str | None) -> int | None:
    """'2026-06-03' oder '2026-06-03T12:00' → naive ms."""
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(v, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    raise RuleError(f"Ungültiges Datum: {v}")


def weekday(t: np.ndarray) -> np.ndarray:
    """0 = Montag … 6 = Sonntag (1970-01-01 war ein Donnerstag)."""
    return ((t // DAY_MS) + 3) % 7


def _first_per_group(groups: np.ndarray, sort_key: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Pro Gruppe das Element mit kleinstem sort_key (stabil nach Zeit)."""
    if len(idx) == 0:
        return idx
    order = np.lexsort((np.arange(len(idx)), sort_key, groups))
    g_sorted = groups[order]
    first = np.ones(len(order), bool)
    first[1:] = g_sorted[1:] != g_sorted[:-1]
    chosen = idx[order[first]]
    return np.sort(chosen)  # Index in Universe == zeitliche Reihenfolge


# ----------------------------------------------------------------------------- Regeln
# Signatur: (U, sel, params, marks) -> sel ; sel = aufsteigend sortierte Indizes in U

def r_sources(U, sel, p, _m):
    ids = p.get("source_ids") or []
    if not ids:
        return sel
    return sel[np.isin(U.src[sel], np.asarray(ids, np.int32))]


def r_date_range(U, sel, p, _m):
    lo = parse_date(p.get("from"))
    hi = parse_date(p.get("to"))
    if hi is not None and len(p.get("to", "")) == 10:
        hi += DAY_MS  # Enddatum inklusive
    t = U.t[sel]
    mask = np.ones(len(sel), bool)
    if lo is not None:
        mask &= t >= lo
    if hi is not None:
        mask &= t < hi
    return sel[mask]


def r_time_window(U, sel, p, _m):
    """[von, bis) – über Mitternacht, wenn von > bis (z. B. 22:00–06:00)."""
    lo = parse_hhmm(p.get("from"), 0)
    hi = parse_hhmm(p.get("to"), DAY_MS)
    tod = U.t[sel] % DAY_MS
    if lo == hi:
        return sel
    mask = (tod >= lo) & (tod < hi) if lo < hi else (tod >= lo) | (tod < hi)
    return sel[mask]


def r_weekdays(U, sel, p, _m):
    days = p.get("days")
    if days is None or len(days) == 7:
        return sel
    return sel[np.isin(weekday(U.t[sel]), np.asarray(days, np.int64))]


def r_nth(U, sel, p, _m):
    n = int(p.get("n", 1))
    off = int(p.get("offset") or 0)
    if n < 1:
        raise RuleError("n muss ≥ 1 sein")
    if off < 0:
        raise RuleError("Offset muss ≥ 0 sein")
    return sel[off::n]


def r_interval(U, sel, p, _m):
    """Ein Bild pro Intervall; Strategien first | nearest (zu Uhrzeit) | brightest | median."""
    iv = int(p.get("interval_s") or 0) * 1000
    if iv <= 0:
        raise RuleError("Intervall muss > 0 sein")
    strategy = p.get("strategy", "first")
    t = U.t[sel]
    groups = t // iv  # an lokaler Mitternacht ausgerichtet (für Teiler eines Tages)
    if strategy == "first":
        key = t
    elif strategy == "nearest":
        anchor = parse_hhmm(p.get("at"), 12 * 60 * MIN_MS) % iv
        key = np.abs(t - (groups * iv + anchor))
    elif strategy == "brightest":
        b = U.b[sel]
        key = -np.where(np.isnan(b), -np.inf, b)
    elif strategy == "median":
        b = U.b[sel].astype(np.float64)
        b = np.where(np.isnan(b), np.inf, b)
        # Abstand zur Median-Helligkeit der eigenen Gruppe
        order = np.lexsort((b, groups))
        g_s, b_s = groups[order], b[order]
        starts = np.flatnonzero(np.r_[True, g_s[1:] != g_s[:-1]])
        counts = np.diff(np.r_[starts, len(g_s)])
        med = b_s[starts + (counts - 1) // 2]
        med_full = np.repeat(med, counts)
        dist = np.empty_like(b)
        dist[order] = np.abs(b_s - med_full)
        key = dist
    else:
        raise RuleError(f"Unbekannte Strategie: {strategy}")
    return _first_per_group(groups, key, sel)


def r_limit(U, sel, p, _m):
    """Auf N Bilder begrenzen, gleichmäßig über die Zeit verteilt."""
    n = int(p.get("n") or 0)
    if n <= 0:
        raise RuleError("N muss > 0 sein")
    if len(sel) <= n:
        return sel
    t = U.t[sel]
    targets = np.linspace(t[0], t[-1], n)
    pos = np.searchsorted(t, targets).clip(1, len(t) - 1)
    left_closer = (targets - t[pos - 1]) <= (t[pos] - targets)
    pick = np.unique(np.where(left_closer, pos - 1, pos))
    if len(pick) < n:  # Lücken in der Zeitachse → mit gleichmäßig verteilten Resten auffüllen
        rest = np.setdiff1d(np.arange(len(sel)), pick, assume_unique=True)
        need = n - len(pick)
        extra = rest[np.linspace(0, len(rest) - 1, need).round().astype(int)]
        pick = np.union1d(pick, extra)
    return sel[pick]


def r_brightness(U, sel, p, _m):
    """Unbekannte Helligkeit (Thumbnail noch nicht erzeugt) bleibt erhalten."""
    lo = p.get("min")
    hi = p.get("max")
    b = U.b[sel]
    mask = np.ones(len(sel), bool)
    if lo is not None:
        mask &= ~(b < float(lo))
    if hi is not None:
        mask &= ~(b > float(hi))
    return sel[mask]


def r_dedupe(U, sel, p, _m):
    """Standbilder überspringen: Bild fällt weg, wenn dHash-Abstand zum vorherigen ≤ Schwelle."""
    thr = int(p.get("threshold", 4))
    if len(sel) < 2:
        return sel
    ph = U.ph[sel]
    dist = np.bitwise_count(ph[1:] ^ ph[:-1])
    known = (ph[1:] != 0) & (ph[:-1] != 0)
    keep = np.r_[True, ~(known & (dist <= thr))]
    return sel[keep]


def r_manual(U, sel, _p, marks: Marks):
    if marks.exclude:
        sel = sel[~np.isin(U.ids[sel], np.fromiter(marks.exclude, np.int64))]
    if marks.include:
        inc = np.flatnonzero(np.isin(U.ids, np.fromiter(marks.include, np.int64)))
        sel = np.union1d(sel, inc)
    return sel


def r_order(_U, sel, p, _m):
    return sel[::-1] if p.get("direction") == "desc" else sel


RULES = {
    "sources": r_sources,          # S-1
    "date_range": r_date_range,    # S-2
    "time_window": r_time_window,  # S-3
    "weekdays": r_weekdays,        # S-4
    "nth": r_nth,                  # S-5
    "interval": r_interval,        # S-6
    "limit": r_limit,              # S-7
    "brightness": r_brightness,    # S-8
    "dedupe": r_dedupe,            # S-9
    "manual": r_manual,            # S-10
    "order": r_order,              # S-11
}


@dataclass
class Result:
    sel: np.ndarray                 # Indizes in U, in Ausgabereihenfolge
    steps: list[dict]               # je Regel: {rule_id, type, count, error}
    reversed: bool = False


def run(U: Universe, rules: list[dict], marks: Marks | None = None) -> Result:
    """rules: [{id, type, enabled, params}] in Reihenfolge. Fehlerhafte Regeln werden übersprungen."""
    marks = marks or Marks()
    sel = np.arange(len(U), dtype=np.int64)
    steps = []
    reverse = False
    manual_applied = False
    for r in rules:
        if not r.get("enabled", True):
            steps.append({"rule_id": r.get("id"), "type": r["type"], "count": None, "error": None})
            continue
        fn = RULES.get(r["type"])
        err = None
        if fn is None:
            err = "Unbekannter Regeltyp"
        elif r["type"] == "order":
            reverse = r.get("params", {}).get("direction") == "desc"
        else:
            try:
                sel = fn(U, sel, r.get("params") or {}, marks)
                manual_applied |= r["type"] == "manual"
            except RuleError as e:
                err = str(e)
        steps.append({"rule_id": r.get("id"), "type": r["type"], "count": int(len(sel)), "error": err})
    # Manuelle Markierungen gelten immer – ohne eigene Regel am Ende
    if not manual_applied and (marks.include or marks.exclude):
        sel = r_manual(U, sel, {}, marks)
    if reverse:
        sel = sel[::-1]
    return Result(sel=sel, steps=steps, reversed=reverse)


def day_distribution(U: Universe, sel: np.ndarray) -> list[tuple[int, int]]:
    """[(Tag-Start-ms, Anzahl)] – für Mini-Chart (S-20)."""
    if len(sel) == 0:
        return []
    days, counts = np.unique(U.t[np.sort(sel)] // DAY_MS, return_counts=True)
    return [(int(d) * DAY_MS, int(c)) for d, c in zip(days, counts)]
