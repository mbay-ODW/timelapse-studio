"""Quellen-Erkennung (Q-1) und Pfadauflösung mit Traversal-Schutz (Q-2/N-4)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config
from ..db import get_conn, tx
from .timestamps import DEFAULT_FILENAME_PATTERN

UPLOAD_PREFIX = "uploads/"


def _discover() -> dict[str, tuple[Path, str]]:
    s = config.settings
    found: dict[str, tuple[Path, str]] = {}
    if s.sources_dir.is_dir():
        for d in sorted(s.sources_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                found[d.name] = (d, "mount")
    if s.uploads_dir.is_dir():
        for d in sorted(s.uploads_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                found[UPLOAD_PREFIX + d.name] = (d, "upload")
    return found


def sync_sources() -> None:
    """Neue Ordner anlegen, verschwundene als nicht vorhanden markieren (Daten bleiben)."""
    found = _discover()
    now = int(time.time())
    conn = get_conn()
    existing = {r["name"]: r for r in conn.execute("SELECT id, name, path, present FROM source")}
    with tx(conn):
        for name, (path, kind) in found.items():
            if name not in existing:
                display = name[len(UPLOAD_PREFIX):] if kind == "upload" else name
                order = ["filename", "exif", "mtime"] if kind == "mount" else ["exif", "filename", "mtime"]
                conn.execute(
                    "INSERT INTO source(name, display_name, path, kind, ts_order, filename_pattern, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (name, display, str(path), kind, json.dumps(order), DEFAULT_FILENAME_PATTERN, now),
                )
            elif not existing[name]["present"] or existing[name]["path"] != str(path):
                conn.execute("UPDATE source SET present=1, path=? WHERE name=?", (str(path), name))
        for name, row in existing.items():
            if name not in found and row["present"]:
                conn.execute("UPDATE source SET present=0 WHERE id=?", (row["id"],))


def source_root(source_row) -> Path:
    return Path(source_row["path"])


def safe_join(root: Path, rel_path: str) -> Path:
    p = (root / rel_path).resolve()
    r = root.resolve()
    if p != r and r not in p.parents:
        raise ValueError("Pfad außerhalb der Quelle")
    return p


def thumb_path(source_id: int, image_id: int) -> Path:
    return config.settings.thumbs_dir / str(source_id) / str(image_id // 1000) / f"{image_id}.webp"


def proxy_path(source_id: int, image_id: int) -> Path:
    return config.settings.proxies_dir / str(source_id) / str(image_id // 1000) / f"{image_id}.jpg"
