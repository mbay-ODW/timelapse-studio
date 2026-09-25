"""SQLite-Zugriff (WAL) und automatische Migrationen beim Start (N-6)."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

# Jede Migration ist genau ein Schritt; user_version = Anzahl angewandter Schritte.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE source (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,              -- Ordnername bzw. 'uploads/<album>'
        display_name TEXT NOT NULL,
        path TEXT NOT NULL,                     -- absoluter Pfad im Container
        kind TEXT NOT NULL DEFAULT 'mount',     -- mount | upload
        enabled INTEGER NOT NULL DEFAULT 1,
        present INTEGER NOT NULL DEFAULT 1,     -- Ordner existiert aktuell
        ts_order TEXT NOT NULL DEFAULT '["exif","filename","mtime"]',
        filename_pattern TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        last_scan_at INTEGER
    );
    CREATE TABLE image (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
        rel_path TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        taken_ms INTEGER,                       -- Lokalzeit als "naive Epoch" in ms
        ts_origin TEXT,                         -- exif | filename | mtime
        exif_ms INTEGER,                        -- EXIF DateTimeOriginal (vom Thumb-Worker)
        width INTEGER,
        height INTEGER,
        brightness REAL,
        phash INTEGER,
        thumb_status INTEGER NOT NULL DEFAULT 0, -- 0 offen, 1 ok, 2 Fehler
        error TEXT,
        UNIQUE (source_id, rel_path)
    );
    CREATE INDEX image_source_taken ON image(source_id, taken_ms, id);
    CREATE INDEX image_taken ON image(taken_ms, id);
    CREATE INDEX image_brightness ON image(brightness);
    CREATE INDEX image_thumb_pending ON image(thumb_status) WHERE thumb_status = 0;
    CREATE TABLE thumb_priority (
        image_id INTEGER PRIMARY KEY,
        requested_at INTEGER NOT NULL
    );
    CREATE TABLE scan (
        source_id INTEGER PRIMARY KEY REFERENCES source(id) ON DELETE CASCADE,
        status TEXT NOT NULL,                   -- queued | scanning | done | error
        requested_at INTEGER,
        started_at INTEGER,
        finished_at INTEGER,
        found INTEGER NOT NULL DEFAULT 0,
        new INTEGER NOT NULL DEFAULT 0,
        changed INTEGER NOT NULL DEFAULT 0,
        removed INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        message TEXT
    );
    CREATE TABLE project (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        params_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE rule (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        type TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        params_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX rule_project ON rule(project_id, position);
    CREATE TABLE manual_mark (
        project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        image_id INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('include','exclude')),
        PRIMARY KEY (project_id, image_id)
    );
    CREATE TABLE preset (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        params_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE job (
        id INTEGER PRIMARY KEY,
        project_id INTEGER REFERENCES project(id) ON DELETE SET NULL,
        project_name TEXT NOT NULL,
        kind TEXT NOT NULL,                     -- render | preview
        status TEXT NOT NULL,                   -- queued|preparing|rendering|done|failed|cancelled|interrupted
        priority INTEGER NOT NULL DEFAULT 0,
        queue_pos REAL NOT NULL,
        params_json TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        phase TEXT,
        frames_total INTEGER NOT NULL DEFAULT 0,
        frames_done INTEGER NOT NULL DEFAULT 0,
        fps_current REAL,
        speed REAL,
        created_at INTEGER NOT NULL,
        started_at INTEGER,
        finished_at INTEGER,
        eta_s REAL,
        output_path TEXT,
        output_size INTEGER,
        log_path TEXT,
        error TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        worker_pid INTEGER,
        heartbeat_at INTEGER,
        remote_user TEXT
    );
    CREATE INDEX job_status ON job(status, priority DESC, queue_pos);
    CREATE TABLE setting (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]

_local = threading.local()


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or config.settings.db_path
    conn = sqlite3.connect(p, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def get_conn() -> sqlite3.Connection:
    """Eine Verbindung pro Thread (FastAPI-Threadpool, Worker-Threads)."""
    conn = getattr(_local, "conn", None)
    db_path = str(config.settings.db_path)
    if conn is None or getattr(_local, "path", None) != db_path:
        conn = connect()
        _local.conn = conn
        _local.path = db_path
    return conn


@contextmanager
def tx(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    c = conn or get_conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    else:
        c.execute("COMMIT")


def migrate(conn: sqlite3.Connection | None = None) -> int:
    c = conn or get_conn()
    version = c.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        c.executescript("BEGIN;" + script + f"PRAGMA user_version={i};COMMIT;")
    return len(MIGRATIONS)
