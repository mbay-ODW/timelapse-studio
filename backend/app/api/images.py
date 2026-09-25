from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from concurrent.futures import ThreadPoolExecutor

from fastapi.responses import FileResponse, Response

from .. import config
from ..db import get_conn
from ..indexer.imageproc import make_proxy, process
from ..indexer.scanner import provisional_ts
from ..indexer.sources import proxy_path, safe_join, thumb_path
from ..indexer.timestamps import from_naive_ms
from .deps import not_found

router = APIRouter(prefix="/api", tags=["images"])
DAY_MS = 86_400_000
_gen_lock = threading.Semaphore(4)  # parallele On-Demand-Erzeugungen begrenzen


def parse_ids(s: str | None) -> list[int] | None:
    if not s:
        return None
    try:
        return [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "Ungültige ID-Liste")


def source_filter(sources: list[int] | None, alias: str = "i") -> tuple[str, list]:
    """Nur aktivierte, vorhandene Quellen; optional eingeschränkt auf eine Liste."""
    sql = f"{alias}.source_id IN (SELECT id FROM source WHERE enabled=1 AND present=1"
    params: list = []
    if sources:
        sql += f" AND id IN ({','.join('?' * len(sources))})"
        params += sources
    return sql + ")", params


def day_str(day_idx: int) -> str:
    return from_naive_ms(day_idx * DAY_MS).strftime("%Y-%m-%d")


@router.get("/timeline/buckets")
def buckets(sources: str | None = None):
    """Anzahl Bilder pro Tag – Grundlage für Grid-Höhe und Scrubber (B-1, B-2)."""
    where, params = source_filter(parse_ids(sources))
    rows = get_conn().execute(
        f"SELECT taken_ms / {DAY_MS} AS d, COUNT(*) AS n FROM image i WHERE {where}"
        " AND taken_ms IS NOT NULL GROUP BY d ORDER BY d", params).fetchall()
    return [{"day": day_str(r["d"]), "count": r["n"]} for r in rows]


@router.get("/timeline/day/{day}")
def day_images(day: str, sources: str | None = None):
    """Alle Bilder eines Tages kompakt: [id, taken_ms, width, height, brightness, thumb_status]."""
    try:
        d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, "Datum im Format YYYY-MM-DD")
    start = int(d.timestamp() * 1000)
    where, params = source_filter(parse_ids(sources))
    rows = get_conn().execute(
        f"SELECT id, taken_ms, width, height, brightness, thumb_status FROM image i WHERE {where}"
        " AND taken_ms >= ? AND taken_ms < ? ORDER BY taken_ms, id",
        params + [start, start + DAY_MS]).fetchall()
    return {"day": day, "items": [list(r) for r in rows]}


@router.get("/stats/histogram")
def histogram(bucket: str = Query("day", pattern="^(day|hour)$"), sources: str | None = None,
              from_ms: int | None = Query(None, alias="from"), to_ms: int | None = Query(None, alias="to")):
    """Aktivitäts-Histogramm (B-5): Bilder pro Tag bzw. pro Stunde."""
    size = DAY_MS if bucket == "day" else 3_600_000
    where, params = source_filter(parse_ids(sources))
    if from_ms is not None:
        where += " AND taken_ms >= ?"
        params.append(from_ms)
    if to_ms is not None:
        where += " AND taken_ms < ?"
        params.append(to_ms)
    rows = get_conn().execute(
        f"SELECT taken_ms / {size} AS b, COUNT(*) AS n FROM image i WHERE {where}"
        " AND taken_ms IS NOT NULL GROUP BY b ORDER BY b", params).fetchall()
    return {"bucket": bucket, "size_ms": size, "items": [[r["b"] * size, r["n"]] for r in rows]}


def _row(image_id: int):
    r = get_conn().execute(
        "SELECT i.*, s.path AS src_path, s.display_name AS source_name, s.ts_order, s.filename_pattern"
        " FROM image i JOIN source s ON s.id=i.source_id WHERE i.id=?", (image_id,)).fetchone()
    if r is None:
        raise not_found("Bild nicht gefunden")
    return r


def _abs(r) -> Path:
    return safe_join(Path(r["src_path"]), r["rel_path"])


@router.get("/images/{image_id}")
def image_meta(image_id: int):
    r = _row(image_id)
    return {
        "id": r["id"], "source_id": r["source_id"], "source": r["source_name"], "path": r["rel_path"],
        "taken_ms": r["taken_ms"], "ts_origin": r["ts_origin"], "width": r["width"], "height": r["height"],
        "size": r["size"], "brightness": r["brightness"], "thumb_status": r["thumb_status"], "error": r["error"],
    }


CACHE = {"Cache-Control": "private, max-age=604800"}


@router.get("/images/{image_id}/thumb")
def image_thumb(image_id: int):
    """Liefert das Thumbnail; fehlt es noch, wird es sofort erzeugt (Priorität sichtbarer Bilder, I-5)."""
    r = _row(image_id)
    tp = thumb_path(r["source_id"], image_id)
    if not tp.exists():
        if r["thumb_status"] == 2:
            raise not_found("Bild nicht lesbar")
        with _gen_lock:
            res = process(image_id, str(_abs(r)), str(tp), config.settings.thumb_size)
        conn = get_conn()
        if res.ok:
            ts, origin = provisional_ts(r["rel_path"], r["mtime_ns"], json.loads(r["ts_order"]),
                                        r["filename_pattern"], res.exif_ms)
            conn.execute("UPDATE image SET width=?, height=?, brightness=?, phash=?, exif_ms=?, taken_ms=?,"
                         " ts_origin=?, thumb_status=1, error=NULL WHERE id=?",
                         (res.width, res.height, res.brightness, res.phash, res.exif_ms, ts, origin, image_id))
        else:
            conn.execute("UPDATE image SET thumb_status=2, error=? WHERE id=?", (res.error, image_id))
            raise not_found("Bild nicht lesbar")
    return FileResponse(tp, media_type="image/webp", headers=CACHE)


@router.get("/images/{image_id}/preview")
def image_preview(image_id: int):
    """Mittelgroßer Proxy (~960 px JPEG) für Lightbox und Canvas-Player (V-1)."""
    r = _row(image_id)
    pp = proxy_path(r["source_id"], image_id)
    if not pp.exists():
        try:
            with _gen_lock:
                make_proxy(str(_abs(r)), str(pp), config.settings.proxy_size)
        except Exception:
            raise not_found("Bild nicht lesbar")
    return FileResponse(pp, media_type="image/jpeg", headers=CACHE)


@router.get("/images/{image_id}/original")
def image_original(image_id: int):
    r = _row(image_id)
    p = _abs(r)
    if not p.exists():
        raise not_found("Datei fehlt")
    return FileResponse(p, filename=p.name, headers=CACHE)


_batch_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="batch")
MAX_BATCH = 200


def _thumb_bytes(image_id: int) -> bytes:
    try:
        r = image_thumb(image_id)
        return open(r.path, "rb").read()
    except Exception:
        return b""


def _preview_bytes(image_id: int) -> bytes:
    try:
        r = image_preview(image_id)
        return open(r.path, "rb").read()
    except Exception:
        return b""


def _pack(ids: list[int], blobs: list[bytes]) -> Response:
    """Binärformat: 4 Byte Header-Länge (LE) | JSON [[id, länge], …] | Daten hintereinander.

    Ein Request für viele Bilder – schont Traefik-Ratelimit (geteilter LAN-Bucket) und Authelia.
    """
    header = json.dumps([[i, len(b)] for i, b in zip(ids, blobs)]).encode()
    body = len(header).to_bytes(4, "little") + header + b"".join(blobs)
    return Response(body, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


def _batch(ids: str, fn) -> Response:
    lst = parse_ids(ids) or []
    if len(lst) > MAX_BATCH:
        raise HTTPException(422, f"Maximal {MAX_BATCH} IDs pro Anfrage")
    return _pack(lst, list(_batch_pool.map(fn, lst)))


@router.get("/thumbs")
def thumbs_batch(ids: str):
    return _batch(ids, _thumb_bytes)


@router.get("/previews")
def previews_batch(ids: str):
    return _batch(ids, _preview_bytes)
