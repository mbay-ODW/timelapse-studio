"""Hintergrund-Erzeugung von Thumbnails + Helligkeit + dHash + EXIF-Zeit (I-4, I-5).

Priorität: zuerst Bilder, die das Frontend gerade anzeigt (Tabelle thumb_priority),
danach alle offenen in Zeitreihenfolge.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor

from .. import config
from ..db import get_conn, tx
from ..logging_setup import log
from .imageproc import process
from .scanner import provisional_ts
from .sources import thumb_path

logger = logging.getLogger("thumbs")
BATCH = 64


class ThumbWorker:
    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or config.settings.index_workers
        self.stop = threading.Event()
        self.pool: ProcessPoolExecutor | None = None
        self.rate = 0.0  # Bilder/s, geglättet

    def _next_batch(self, conn) -> list:
        rows = conn.execute(
            "SELECT i.id, i.source_id, i.rel_path, i.mtime_ns, s.path FROM thumb_priority p"
            " JOIN image i ON i.id = p.image_id JOIN source s ON s.id = i.source_id"
            " WHERE i.thumb_status = 0 ORDER BY p.requested_at DESC LIMIT ?", (BATCH,)).fetchall()
        conn.execute("DELETE FROM thumb_priority WHERE image_id IN (SELECT p.image_id FROM thumb_priority p"
                     " JOIN image i ON i.id=p.image_id WHERE i.thumb_status != 0)")
        if len(rows) < BATCH:
            ids = {r["id"] for r in rows}
            more = conn.execute(
                "SELECT i.id, i.source_id, i.rel_path, i.mtime_ns, s.path FROM image i"
                " JOIN source s ON s.id = i.source_id"
                " WHERE i.thumb_status = 0 AND s.enabled = 1 AND s.present = 1 LIMIT ?",
                (BATCH * 2,)).fetchall()
            rows += [r for r in more if r["id"] not in ids][: BATCH - len(rows)]
        return rows

    def run(self) -> None:
        conn = get_conn()
        size = config.settings.thumb_size
        self.pool = ProcessPoolExecutor(max_workers=self.workers)
        src_cache: dict[int, tuple[list[str], str]] = {}
        cache_at = 0.0
        try:
            while not self.stop.is_set():
                rows = self._next_batch(conn)
                if not rows:
                    self.rate = 0.0
                    self.stop.wait(2.0)
                    continue
                if time.time() - cache_at > 10:
                    src_cache = {r["id"]: (json.loads(r["ts_order"]), r["filename_pattern"])
                                 for r in conn.execute("SELECT id, ts_order, filename_pattern FROM source")}
                    cache_at = time.time()
                t0 = time.time()
                futures = [
                    self.pool.submit(process, r["id"], f'{r["path"]}/{r["rel_path"]}',
                                     str(thumb_path(r["source_id"], r["id"])), size)
                    for r in rows
                ]
                meta = {r["id"]: r for r in rows}
                ok_rows, err_rows = [], []
                for f in futures:
                    res = f.result()
                    r = meta[res.image_id]
                    if res.ok:
                        order, pattern = src_cache.get(r["source_id"], (["exif", "filename", "mtime"], ""))
                        ts, origin = provisional_ts(r["rel_path"], r["mtime_ns"], order, pattern, res.exif_ms)
                        ok_rows.append((res.width, res.height, res.brightness, res.phash, res.exif_ms,
                                        ts, origin, res.image_id))
                    else:
                        err_rows.append((res.error, res.image_id))
                with tx(conn):
                    conn.executemany(
                        "UPDATE image SET width=?, height=?, brightness=?, phash=?, exif_ms=?, taken_ms=?,"
                        " ts_origin=?, thumb_status=1, error=NULL WHERE id=?", ok_rows)
                    conn.executemany("UPDATE image SET thumb_status=2, error=? WHERE id=?", err_rows)
                for e, iid in err_rows:
                    log(logger, logging.WARNING, "Bild nicht lesbar", image_id=iid, error=e)
                dt = max(time.time() - t0, 1e-3)
                inst = len(rows) / dt
                self.rate = inst if self.rate == 0 else 0.8 * self.rate + 0.2 * inst
        finally:
            self.pool.shutdown(cancel_futures=True)
