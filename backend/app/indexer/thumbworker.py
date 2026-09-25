"""Hintergrund-Erzeugung von Thumbnails + Helligkeit + dHash + EXIF-Zeit (I-4, I-5).

Der Prozesspool wird kontinuierlich gefüttert (kein Warten auf ganze Batches), Ergebnisse
werden gesammelt geschrieben. Sichtbare Bilder ohne Thumbnail erzeugt die API sofort selbst
(On-Demand in /api/images/{id}/thumb) – das ist die Priorisierung aus I-5.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait

from .. import config
from ..db import get_conn, tx
from ..logging_setup import log
from .imageproc import process
from .scanner import provisional_ts
from .sources import thumb_path

logger = logging.getLogger("thumbs")


def _init_proc() -> None:
    # Index-Arbeit ist Hintergrundlast: anderen Stacks den Vortritt lassen
    try:
        os.nice(10)
    except OSError:
        pass
FETCH = 256
FLUSH_EVERY = 200


class ThumbWorker:
    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or config.settings.index_workers
        self.stop = threading.Event()
        self.rate = 0.0  # Bilder/s, geglättet

    def run(self) -> None:
        conn = get_conn()
        size = config.settings.thumb_size
        max_in_flight = self.workers * 3
        src_cache: dict[int, tuple[list[str], str]] = {}
        cache_at = 0.0
        cursor: tuple[int, str] = (0, "")  # (source_id, rel_path) ≈ Schreibreihenfolge auf der Platte
        queue: list = []
        in_flight: dict[Future, object] = {}
        done_rows: list[tuple] = []
        err_rows: list[tuple] = []
        last_flush = time.time()
        window_start, window_count = time.time(), 0

        def flush() -> None:
            nonlocal last_flush
            if done_rows or err_rows:
                with tx(conn):
                    conn.executemany(
                        "UPDATE image SET width=?, height=?, brightness=?, phash=?, exif_ms=?, taken_ms=?,"
                        " ts_origin=?, thumb_status=1, error=NULL WHERE id=?", done_rows)
                    conn.executemany("UPDATE image SET thumb_status=2, error=? WHERE id=?", err_rows)
                for e, iid in err_rows:
                    log(logger, logging.WARNING, "Bild nicht lesbar", image_id=iid, error=e)
                done_rows.clear()
                err_rows.clear()
            last_flush = time.time()

        with ProcessPoolExecutor(max_workers=self.workers, initializer=_init_proc) as pool:
            while not self.stop.is_set():
                if time.time() - cache_at > 10:
                    src_cache = {r["id"]: (json.loads(r["ts_order"]), r["filename_pattern"])
                                 for r in conn.execute("SELECT id, ts_order, filename_pattern FROM source")}
                    cache_at = time.time()
                if not queue:
                    queue = conn.execute(
                        "SELECT i.id, i.source_id, i.rel_path, i.mtime_ns, s.path FROM image i"
                        " JOIN source s ON s.id = i.source_id"
                        " WHERE i.thumb_status = 0 AND (i.source_id, i.rel_path) > (?, ?)"
                        " AND s.enabled = 1 AND s.present = 1"
                        " ORDER BY i.source_id, i.rel_path LIMIT ?", (*cursor, FETCH)).fetchall()
                    if queue:
                        cursor = (queue[-1]["source_id"], queue[-1]["rel_path"])
                while queue and len(in_flight) < max_in_flight:
                    r = queue.pop(0)
                    f = pool.submit(process, r["id"], f'{r["path"]}/{r["rel_path"]}',
                                    str(thumb_path(r["source_id"], r["id"])), size)
                    in_flight[f] = r
                if not in_flight:
                    flush()
                    cursor = (0, "")  # alles abgearbeitet → nächste Runde von vorn (neue/zurückgesetzte Bilder)
                    self.rate = 0.0
                    self.stop.wait(2.0)
                    continue
                finished, _ = wait(list(in_flight), timeout=1.0, return_when=FIRST_COMPLETED)
                for f in finished:
                    r = in_flight.pop(f)
                    res = f.result()
                    if res.ok:
                        order, pattern = src_cache.get(r["source_id"], (["exif", "filename", "mtime"], ""))
                        ts, origin = provisional_ts(r["rel_path"], r["mtime_ns"], order, pattern, res.exif_ms)
                        done_rows.append((res.width, res.height, res.brightness, res.phash, res.exif_ms,
                                          ts, origin, res.image_id))
                    else:
                        err_rows.append((res.error, res.image_id))
                window_count += len(finished)
                now = time.time()
                if now - window_start >= 5:
                    inst = window_count / (now - window_start)
                    self.rate = inst if self.rate == 0 else 0.7 * self.rate + 0.3 * inst
                    window_start, window_count = now, 0
                if len(done_rows) + len(err_rows) >= FLUSH_EVERY or now - last_flush > 2:
                    flush()
            for f in list(in_flight):
                f.cancel()
            flush()
