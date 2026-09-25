"""Brücke DB ↔ Engine mit Caches: Bestand (Universe) und Auswertung pro Projekt."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass

import numpy as np

from ..db import get_conn
from .engine import Marks, Result, Universe, day_distribution, run

_lock = threading.Lock()
_universe: tuple[tuple, Universe] | None = None
_evals: dict[int, tuple[str, "Evaluation"]] = {}


@dataclass
class Evaluation:
    U: Universe
    result: Result
    key: str

    @property
    def ids(self) -> np.ndarray:
        return self.U.ids[self.result.sel]

    @property
    def times(self) -> np.ndarray:
        return self.U.t[self.result.sel]


def _fingerprint(conn) -> tuple:
    src = conn.execute("SELECT group_concat(id) FROM (SELECT id FROM source WHERE enabled=1 AND present=1"
                       " ORDER BY id)").fetchone()[0] or ""
    # thumb_status/taken_ms-Summen erfassen Helligkeits- und Zeitänderungen ohne Versionszähler
    f = conn.execute("SELECT COUNT(*), MAX(id), SUM(thumb_status), TOTAL(taken_ms) FROM image"
                     " WHERE source_id IN (SELECT id FROM source WHERE enabled=1 AND present=1)").fetchone()
    return (src, *tuple(f))


def universe() -> Universe:
    global _universe
    conn = get_conn()
    fp = _fingerprint(conn)
    with _lock:
        if _universe and _universe[0] == fp:
            return _universe[1]
    rows = conn.execute(
        "SELECT id, source_id, taken_ms, brightness, phash FROM image"
        " WHERE taken_ms IS NOT NULL AND source_id IN (SELECT id FROM source WHERE enabled=1 AND present=1)"
    ).fetchall()
    U = Universe.from_rows(rows)
    with _lock:
        _universe = (fp, U)
    return U


def load_rules(project_id: int) -> list[dict]:
    rows = get_conn().execute("SELECT id, type, enabled, params_json FROM rule WHERE project_id=?"
                              " ORDER BY position, id", (project_id,)).fetchall()
    return [{"id": r["id"], "type": r["type"], "enabled": bool(r["enabled"]),
             "params": json.loads(r["params_json"])} for r in rows]


def load_marks(project_id: int) -> Marks:
    m = Marks()
    for r in get_conn().execute("SELECT image_id, mode FROM manual_mark WHERE project_id=?", (project_id,)):
        (m.include if r["mode"] == "include" else m.exclude).add(r["image_id"])
    return m


def evaluate(project_id: int, rules: list[dict] | None = None, *, skip_auto: bool = False) -> Evaluation:
    """rules=None → aus der DB. skip_auto lässt automatisch ergänzte Längen-Regeln weg (P-3)."""
    U = universe()
    if rules is None:
        rules = load_rules(project_id)
    if skip_auto:
        rules = [r for r in rules if not r.get("params", {}).get("auto")]
    marks = load_marks(project_id)
    key = hashlib.sha1(json.dumps([id(U), rules, sorted(marks.include), sorted(marks.exclude)],
                                  sort_keys=True, default=str).encode()).hexdigest()
    cache_key = project_id if not skip_auto else -project_id
    with _lock:
        hit = _evals.get(cache_key)
        if hit and hit[0] == key:
            return hit[1]
    ev = Evaluation(U=U, result=run(U, rules, marks), key=key)
    with _lock:
        _evals[cache_key] = (key, ev)
    return ev


def summary(ev: Evaluation) -> dict:
    sel = ev.result.sel
    t = ev.U.t[sel]
    return {
        "count": int(len(sel)),
        "total": int(len(ev.U)),
        "steps": ev.result.steps,
        "first_ms": int(t.min()) if len(t) else None,
        "last_ms": int(t.max()) if len(t) else None,
        "days": len(np.unique(t // 86_400_000)) if len(t) else 0,
        "distribution": day_distribution(ev.U, sel),
        "key": ev.key[:12],
    }


def dominant_size(ev: Evaluation) -> tuple[int, int]:
    """Häufigste Bildgröße der Auswahl (Stichprobe) – Basis für Ausgabegeometrie."""
    ids = ev.ids
    if len(ids) == 0:
        return 1920, 1080
    sample = ids[np.linspace(0, len(ids) - 1, min(200, len(ids))).astype(int)].tolist()
    rows = get_conn().execute(
        f"SELECT width, height, COUNT(*) c FROM image WHERE id IN ({','.join('?' * len(sample))})"
        " AND width IS NOT NULL GROUP BY width, height ORDER BY c DESC LIMIT 1", sample).fetchone()
    return (rows["width"], rows["height"]) if rows else (1920, 1080)
