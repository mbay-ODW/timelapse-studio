"""Inkrementeller Dateiscan (I-1, I-2, I-6).

Vergleicht Pfad+Größe+mtime mit dem Index. Nur neue/geänderte Dateien werden
(ohne sie zu öffnen) eingetragen; Thumbnails/Helligkeit/EXIF macht danach der
Thumb-Worker. Ein Rescan ohne Änderungen ist damit reines `stat()`.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .. import config
from ..db import get_conn, tx
from ..logging_setup import log
from .imageproc import SUPPORTED_EXT
from .sources import thumb_path, proxy_path
from .timestamps import mtime_to_naive_ms, parse_filename, resolve

logger = logging.getLogger("scanner")
BATCH = 2000


def _walk(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    name = e.name
                    if name.startswith(".") or name.startswith("@eaDir"):
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file() and os.path.splitext(name)[1].lower() in SUPPORTED_EXT:
                            st = e.stat()
                            yield os.path.relpath(e.path, root), st.st_size, st.st_mtime_ns
                    except OSError:
                        continue
        except OSError as ex:
            log(logger, logging.WARNING, "Verzeichnis nicht lesbar", path=str(d), error=str(ex))


def provisional_ts(rel_path: str, mtime_ns: int, order: list[str], pattern: str,
                   exif_ms: int | None = None) -> tuple[int, str]:
    """Zeit ohne Datei zu öffnen; EXIF liefert ggf. später der Thumb-Worker (exif_ms)."""
    fn_ms = parse_filename(os.path.basename(rel_path), pattern) if "filename" in order else None
    if fn_ms is None and "filename" in order:
        fn_ms = parse_filename(rel_path, pattern)  # Datum evtl. im Ordnernamen
    m_ms = mtime_to_naive_ms(mtime_ns, config.settings.tz)
    return resolve(order, exif_ms=exif_ms, filename_ms=fn_ms, mtime_ms=m_ms)


def request_scan(source_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO scan(source_id, status, requested_at) VALUES (?, 'queued', ?)"
        " ON CONFLICT(source_id) DO UPDATE SET status='queued', requested_at=excluded.requested_at"
        " WHERE scan.status NOT IN ('queued','scanning')",
        (source_id, int(time.time())),
    )


def scan_source(source_id: int, *, full_ts: bool = False) -> dict:
    """full_ts=True berechnet Zeitstempel aller Bilder neu (nach Änderung von Muster/Reihenfolge)."""
    conn = get_conn()
    src = conn.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
    if src is None:
        raise KeyError(source_id)
    root = Path(src["path"])
    order = json.loads(src["ts_order"])
    pattern = src["filename_pattern"]
    started = time.time()
    conn.execute("UPDATE scan SET status='scanning', started_at=?, finished_at=NULL, found=0, new=0,"
                 " changed=0, removed=0, errors=0, message=NULL WHERE source_id=?",
                 (int(started), source_id))
    if not root.is_dir():
        conn.execute("UPDATE scan SET status='error', finished_at=?, message=? WHERE source_id=?",
                     (int(time.time()), "Ordner nicht vorhanden", source_id))
        return {"error": "missing"}

    known: dict[str, tuple[int, int, int]] = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute("SELECT rel_path, id, size, mtime_ns FROM image WHERE source_id=?", (source_id,))
    }
    seen: set[str] = set()
    stats = {"found": 0, "new": 0, "changed": 0, "removed": 0, "errors": 0}
    inserts: list[tuple] = []
    updates: list[tuple] = []
    last_report = 0.0

    def flush() -> None:
        if not inserts and not updates:
            return
        with tx(conn):
            if inserts:
                conn.executemany(
                    "INSERT INTO image(source_id, rel_path, size, mtime_ns, taken_ms, ts_origin)"
                    " VALUES (?,?,?,?,?,?)", inserts)
            if updates:
                conn.executemany(
                    "UPDATE image SET size=?, mtime_ns=?, taken_ms=?, ts_origin=?, thumb_status=0, error=NULL, exif_ms=NULL,"
                    " width=NULL, height=NULL, brightness=NULL, phash=NULL WHERE id=?", updates)
        inserts.clear()
        updates.clear()

    for rel, size, mtime_ns in _walk(root):
        stats["found"] += 1
        seen.add(rel)
        prev = known.get(rel)
        if prev is None:
            ts, origin = provisional_ts(rel, mtime_ns, order, pattern)
            inserts.append((source_id, rel, size, mtime_ns, ts, origin))
            stats["new"] += 1
        elif prev[1] != size or prev[2] != mtime_ns:
            ts, origin = provisional_ts(rel, mtime_ns, order, pattern)
            updates.append((size, mtime_ns, ts, origin, prev[0]))
            stats["changed"] += 1
        if len(inserts) + len(updates) >= BATCH:
            flush()
        now = time.time()
        if now - last_report > 1.0:
            last_report = now
            conn.execute("UPDATE scan SET found=?, new=?, changed=? WHERE source_id=?",
                         (stats["found"], stats["new"], stats["changed"], source_id))
    flush()

    gone = [(known[rel][0],) for rel in known.keys() - seen]
    if gone:
        with tx(conn):
            conn.executemany("DELETE FROM image WHERE id=?", gone)
            conn.executemany("DELETE FROM manual_mark WHERE image_id=?", gone)
        for (iid,) in gone:
            for p in (thumb_path(source_id, iid), proxy_path(source_id, iid)):
                p.unlink(missing_ok=True)
        stats["removed"] = len(gone)

    if full_ts:
        recompute_timestamps(source_id)

    finished = time.time()
    conn.execute("UPDATE scan SET status='done', finished_at=?, found=?, new=?, changed=?, removed=?,"
                 " errors=(SELECT COUNT(*) FROM image WHERE source_id=? AND thumb_status=2) WHERE source_id=?",
                 (int(finished), stats["found"], stats["new"], stats["changed"], stats["removed"],
                  source_id, source_id))
    conn.execute("UPDATE source SET last_scan_at=? WHERE id=?", (int(finished), source_id))
    log(logger, logging.INFO, "Scan fertig", source_id=source_id, seconds=round(finished - started, 1), **stats)
    return stats


def recompute_timestamps(source_id: int) -> int:
    """Nach Änderung von Muster/Reihenfolge: rein aus DB-Werten, ohne Dateien zu öffnen."""
    conn = get_conn()
    src = conn.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
    order = json.loads(src["ts_order"])
    rows = conn.execute("SELECT id, rel_path, mtime_ns, exif_ms FROM image WHERE source_id=?",
                        (source_id,)).fetchall()
    ups = []
    for r in rows:
        ts, origin = provisional_ts(r["rel_path"], r["mtime_ns"], order, src["filename_pattern"], r["exif_ms"])
        ups.append((ts, origin, r["id"]))
    with tx(conn):
        conn.executemany("UPDATE image SET taken_ms=?, ts_origin=? WHERE id=?", ups)
    return len(ups)
