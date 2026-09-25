"""Hintergrund-Prozess: Quellen-Scan, Thumbnails, Render-Queue."""
from __future__ import annotations

import logging
import os
import signal
import threading
import time

from . import config
from .db import get_conn, migrate
from .indexer.scanner import recompute_timestamps, request_scan, scan_source
from .indexer.sources import sync_sources
from .indexer.thumbworker import ThumbWorker
from .logging_setup import log, setup_logging

logger = logging.getLogger("worker")
SCAN_INTERVAL_MIN = int(os.environ.get("SCAN_INTERVAL_MIN", "60"))


def _set(conn, key: str, value) -> None:
    conn.execute("INSERT INTO setting(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))


class Worker:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.thumbs = ThumbWorker()
        self.threads: list[threading.Thread] = []
        self.render = None

    def request_all_scans(self) -> None:
        sync_sources()
        for r in get_conn().execute("SELECT id FROM source WHERE enabled=1 AND present=1"):
            request_scan(r["id"])

    def scan_loop(self) -> None:
        conn = get_conn()
        # Scans, die beim letzten Stopp liefen, neu einreihen
        conn.execute("UPDATE scan SET status='queued' WHERE status='scanning'")
        self.request_all_scans()
        next_auto = time.time() + SCAN_INTERVAL_MIN * 60 if SCAN_INTERVAL_MIN > 0 else None
        while not self.stop.is_set():
            for r in conn.execute("SELECT key FROM setting WHERE key LIKE 'recompute_ts:%'").fetchall():
                sid = int(r["key"].split(":")[1])
                conn.execute("DELETE FROM setting WHERE key=?", (r["key"],))
                n = recompute_timestamps(sid)
                log(logger, logging.INFO, "Zeitstempel neu berechnet", source_id=sid, images=n)
            row = conn.execute("SELECT source_id FROM scan WHERE status='queued' ORDER BY requested_at LIMIT 1").fetchone()
            if row:
                try:
                    scan_source(row["source_id"])
                except Exception as e:
                    logger.exception("Scan fehlgeschlagen")
                    conn.execute("UPDATE scan SET status='error', message=? WHERE source_id=?",
                                 (str(e)[:300], row["source_id"]))
                continue
            if next_auto and time.time() > next_auto:
                next_auto = time.time() + SCAN_INTERVAL_MIN * 60
                self.request_all_scans()
                continue
            self.stop.wait(2.0)

    def heartbeat_loop(self) -> None:
        conn = get_conn()
        while not self.stop.is_set():
            _set(conn, "worker_heartbeat", int(time.time()))
            _set(conn, "thumb_rate", round(self.thumbs.rate, 2))
            self.stop.wait(2.0)

    def start(self) -> None:
        targets = [self.scan_loop, self.thumbs.run, self.heartbeat_loop]
        try:
            from .video.queue import RenderQueue  # ab Phase 6
            self.render = RenderQueue(self.stop)
            targets.append(self.render.run)
        except ImportError:
            pass
        for t in targets:
            th = threading.Thread(target=t, name=t.__qualname__, daemon=True)
            th.start()
            self.threads.append(th)

    def shutdown(self, *_):
        log(logger, logging.INFO, "Worker stoppt")
        self.stop.set()
        self.thumbs.stop.set()
        if self.render:
            self.render.shutdown()


def main() -> None:
    s = config.settings
    setup_logging(s.log_level)
    s.ensure_dirs()
    migrate()
    w = Worker()
    signal.signal(signal.SIGTERM, w.shutdown)
    signal.signal(signal.SIGINT, w.shutdown)
    w.start()
    log(logger, logging.INFO, "Worker gestartet", index_workers=s.index_workers,
        max_parallel_renders=s.max_parallel_renders, hwaccel=s.hwaccel)
    while not w.stop.is_set():
        w.stop.wait(1.0)
    for th in w.threads:
        th.join(timeout=10)


if __name__ == "__main__":
    main()
