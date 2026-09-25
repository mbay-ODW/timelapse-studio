from __future__ import annotations

import json
import os
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn
from ..indexer.scanner import request_scan
from ..indexer.sources import sync_sources
from ..indexer.timestamps import TS_METHODS, PatternError, compile_pattern, from_naive_ms, parse_filename
from .deps import not_found

router = APIRouter(prefix="/api", tags=["sources"])


def _source_dict(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "display_name": r["display_name"], "kind": r["kind"],
        "enabled": bool(r["enabled"]), "present": bool(r["present"]),
        "ts_order": json.loads(r["ts_order"]), "filename_pattern": r["filename_pattern"],
        "last_scan_at": r["last_scan_at"], "image_count": r["image_count"],
        "first_ms": r["first_ms"], "last_ms": r["last_ms"],
    }


@router.get("/sources")
def list_sources():
    sync_sources()
    rows = get_conn().execute(
        "SELECT s.*, (SELECT COUNT(*) FROM image i WHERE i.source_id=s.id) AS image_count,"
        " (SELECT MIN(taken_ms) FROM image i WHERE i.source_id=s.id) AS first_ms,"
        " (SELECT MAX(taken_ms) FROM image i WHERE i.source_id=s.id) AS last_ms"
        " FROM source s ORDER BY s.kind, s.display_name").fetchall()
    return [_source_dict(r) for r in rows]


class SourcePatch(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    ts_order: list[str] | None = None
    filename_pattern: str | None = None


@router.patch("/sources/{source_id}")
def patch_source(source_id: int, body: SourcePatch):
    conn = get_conn()
    if conn.execute("SELECT 1 FROM source WHERE id=?", (source_id,)).fetchone() is None:
        raise not_found("Quelle nicht gefunden")
    ts_changed = False
    if body.display_name is not None:
        conn.execute("UPDATE source SET display_name=? WHERE id=?", (body.display_name.strip()[:100], source_id))
    if body.enabled is not None:
        conn.execute("UPDATE source SET enabled=? WHERE id=?", (int(body.enabled), source_id))
    if body.ts_order is not None:
        order = [m for m in body.ts_order if m in TS_METHODS]
        if not order:
            raise HTTPException(422, "Mindestens eine Zeitstempel-Methode nötig")
        conn.execute("UPDATE source SET ts_order=? WHERE id=?", (json.dumps(order), source_id))
        ts_changed = True
    if body.filename_pattern is not None:
        try:
            compile_pattern(body.filename_pattern)
        except PatternError as e:
            raise HTTPException(422, str(e))
        conn.execute("UPDATE source SET filename_pattern=? WHERE id=?", (body.filename_pattern, source_id))
        ts_changed = True
    if ts_changed:
        conn.execute("INSERT INTO setting(key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value='1'",
                     (f"recompute_ts:{source_id}",))
    return {"ok": True, "recompute": ts_changed}


class PatternTest(BaseModel):
    pattern: str


@router.post("/sources/{source_id}/pattern-test")
def pattern_test(source_id: int, body: PatternTest):
    """Live-Test eines Dateinamenmusters an Beispieldateien der Quelle (I-3)."""
    conn = get_conn()
    try:
        compile_pattern(body.pattern)
    except PatternError as e:
        return {"valid": False, "error": str(e), "samples": []}
    rows = conn.execute("SELECT rel_path FROM image WHERE source_id=? ORDER BY random() LIMIT 8",
                        (source_id,)).fetchall()
    samples = []
    for r in rows:
        ms = parse_filename(os.path.basename(r["rel_path"]), body.pattern)
        samples.append({"file": r["rel_path"],
                        "parsed": from_naive_ms(ms).isoformat(sep=" ", timespec="seconds") if ms else None})
    return {"valid": True, "error": None, "samples": samples}


@router.post("/sources/{source_id}/scan")
def scan(source_id: int):
    if get_conn().execute("SELECT 1 FROM source WHERE id=?", (source_id,)).fetchone() is None:
        raise not_found("Quelle nicht gefunden")
    request_scan(source_id)
    return {"ok": True}


def scan_status() -> dict:
    conn = get_conn()
    scans = [dict(r) for r in conn.execute(
        "SELECT sc.*, s.display_name FROM scan sc JOIN source s ON s.id=sc.source_id")]
    t = conn.execute(
        "SELECT COUNT(*) AS total, SUM(thumb_status=0) AS pending, SUM(thumb_status=1) AS done,"
        " SUM(thumb_status=2) AS errors FROM image i JOIN source s ON s.id=i.source_id"
        " WHERE s.enabled=1").fetchone()
    rate_row = conn.execute("SELECT value FROM setting WHERE key='thumb_rate'").fetchone()
    rate = float(rate_row["value"]) if rate_row else 0.0
    pending = t["pending"] or 0
    return {
        "scans": scans,
        "thumbs": {"total": t["total"] or 0, "pending": pending, "done": t["done"] or 0,
                   "errors": t["errors"] or 0, "rate": round(rate, 1),
                   "eta_s": round(pending / rate) if rate > 0 and pending else None},
        "now": int(time.time()),
    }


@router.get("/scan/status")
def get_scan_status():
    return scan_status()


@router.get("/sources/{source_id}/errors")
def source_errors(source_id: int, limit: int = 200):
    rows = get_conn().execute("SELECT id, rel_path, error FROM image WHERE source_id=? AND thumb_status=2"
                              " LIMIT ?", (source_id, min(limit, 1000))).fetchall()
    return [dict(r) for r in rows]
