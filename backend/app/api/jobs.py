"""Render-Jobs: anlegen, Queue steuern, Fortschritt, Download, Log (§9, V-3/V-4)."""
from __future__ import annotations

import json
import os
import shutil
import time
from collections import deque
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import config
from ..db import get_conn, tx
from ..pipeline import service
from ..video import ffmpeg, timelogic
from ..video.jobfiles import delete_job_files, frames_file, log_file, output_name
from ..video.params import normalize, output_geometry
from ..video.queue import in_window
from . import events
from .deps import not_found, remote_user

router = APIRouter(prefix="/api", tags=["jobs"])
ACTIVE = ("preparing", "rendering")
OPEN = ("queued", "preparing", "rendering")


def _job(jid: int):
    r = get_conn().execute("SELECT * FROM job WHERE id=?", (jid,)).fetchone()
    if r is None:
        raise not_found("Job nicht gefunden")
    return r


def job_dict(r, now: float | None = None) -> dict:
    now = now or time.time()
    p = json.loads(r["params_json"])
    started, finished = r["started_at"], r["finished_at"]
    elapsed = (finished or now) - started if started else None
    pct = 100.0 * r["frames_done"] / r["frames_total"] if r["frames_total"] else 0.0
    out = r["output_path"]
    return {
        "id": r["id"], "project_id": r["project_id"], "project_name": r["project_name"], "kind": r["kind"],
        "status": r["status"], "phase": r["phase"], "priority": r["priority"], "summary": r["summary"],
        "frames_total": r["frames_total"], "frames_done": r["frames_done"], "percent": round(min(pct, 100), 1),
        "fps_current": r["fps_current"], "speed": r["speed"], "eta_s": r["eta_s"], "elapsed_s": elapsed,
        "created_at": r["created_at"], "started_at": started, "finished_at": finished,
        "output_name": Path(out).name if out else None, "output_size": r["output_size"],
        "output_exists": bool(out) and r["status"] == "done" and os.path.exists(out),
        "error": r["error"], "cancel_requested": bool(r["cancel_requested"]), "remote_user": r["remote_user"],
        "estimate": p.get("_estimate"), "range": p.get("_range"),
        "out_w": p.get("_out_w"), "out_h": p.get("_out_h"), "fps": p.get("fps"), "codec": p.get("codec"),
    }


def snapshot() -> dict:
    """Für SSE: aktive/wartende Jobs + die letzten 30 abgeschlossenen."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM job WHERE status IN ('queued','preparing','rendering')"
        " UNION ALL SELECT * FROM (SELECT * FROM job WHERE status NOT IN ('queued','preparing','rendering')"
        " ORDER BY COALESCE(finished_at, created_at) DESC LIMIT 30)").fetchall()
    now = time.time()
    jobs = [job_dict(r, now) for r in rows]
    active = [j for j in jobs if j["status"] in OPEN]
    # elapsed ändert sich jede Sekunde nur bei aktiven Jobs – gewollt (Live-Dauer)
    return {"active": len(active), "jobs": jobs,
            "render_window": config.settings.render_window,
            "window_open": in_window(config.settings.render_window)}


events.register_job_snapshot(snapshot)


class JobIn(BaseModel):
    project_id: int
    kind: str = "render"           # render | preview
    start: int | None = None       # Frame-Ausschnitt [start, end) für Proxy-Render (V-3)
    end: int | None = None
    seconds: float | None = None   # alternativ: erste N Sekunden


def _summary(p: dict, w: int, h: int, n: int) -> str:
    bits = [f"{ffmpeg.res_label(w, h)}", f"{p['fps']:g} fps", p["codec"].upper(), f"{n:,} Frames".replace(",", ".")]
    if p["deflicker"]["enabled"]:
        bits.append("Deflicker")
    if p["blend"]["enabled"]:
        bits.append(f"Blend {p['blend']['frames']}")
    if p["overlay"]["enabled"]:
        bits.append("Zeitstempel")
    return " · ".join(bits)


def create_job(project_id: int, kind: str, params: dict, ids: np.ndarray, rng: dict | None,
               user: str | None) -> int:
    conn = get_conn()
    proj = conn.execute("SELECT name FROM project WHERE id=?", (project_id,)).fetchone()
    if proj is None:
        raise not_found("Projekt nicht gefunden")
    n = len(ids)
    if rng:
        n = len(ids[rng.get("start", 0):rng.get("end")])
    if n < 1:
        raise HTTPException(422, "Keine Bilder in der Auswahl")
    # dominante Größe grob aus Stichprobe (exakt ermittelt der Worker)
    sample = ids[np.linspace(0, len(ids) - 1, min(200, len(ids))).astype(int)].tolist()
    row = conn.execute(f"SELECT width, height, COUNT(*) c FROM image WHERE id IN ({','.join('?' * len(sample))})"
                       " AND width IS NOT NULL GROUP BY width, height ORDER BY c DESC LIMIT 1", sample).fetchone()
    src_w, src_h = (row["width"], row["height"]) if row else (1920, 1080)
    geo = output_geometry(params, src_w, src_h)
    ow, oh = geo["out"]["w"], geo["out"]["h"]
    preview = kind == "preview"
    if preview:
        s = 480 / min(ow, oh)
        if s < 1:
            ow, oh = int(round(ow * s / 2)) * 2, int(round(oh * s / 2)) * 2
    hw = "vaapi" if config.settings.hwaccel in ("vaapi", "qsv") else "cpu"
    est = timelogic.estimate(n, params["fps"], ow, oh, src_w, src_h, "h264" if preview else params["codec"],
                             "small" if preview else params["quality"], hw)
    stored = {**params, "_estimate": est, "_range": rng, "_out_w": ow, "_out_h": oh}
    now = int(time.time())
    with tx(conn):
        pos = conn.execute("SELECT COALESCE(MAX(queue_pos), 0) + 1 FROM job").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO job(project_id, project_name, kind, status, priority, queue_pos, params_json, summary,"
            " frames_total, created_at, remote_user) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, proj["name"], kind, "queued", 10 if preview else 0, pos, json.dumps(stored),
             _summary(params, ow, oh, n), n, now, user))
        jid = cur.lastrowid
        conn.execute("UPDATE job SET output_path=? WHERE id=?",
                     (output_name(proj["name"], ffmpeg.res_label(ow, oh), params["fps"], preview, jid), jid))
    frames_file(jid).parent.mkdir(parents=True, exist_ok=True)
    np.save(frames_file(jid), ids.astype(np.int64))
    return jid


@router.post("/jobs")
def post_job(body: JobIn, request: Request):
    if body.kind not in ("render", "preview"):
        raise HTTPException(422, "kind muss render oder preview sein")
    conn = get_conn()
    proj = conn.execute("SELECT params_json FROM project WHERE id=?", (body.project_id,)).fetchone()
    if proj is None:
        raise not_found("Projekt nicht gefunden")
    params = normalize(json.loads(proj["params_json"]))
    ev = service.evaluate(body.project_id)
    ids = ev.ids.copy()
    if len(ids) < 2 and body.kind == "render":
        raise HTTPException(422, "Mindestens 2 Bilder nötig")
    rng = None
    if body.kind == "preview":
        start = max(0, body.start or 0)
        end = body.end
        if body.seconds:
            end = start + int(round(body.seconds * params["fps"]))
        if end is not None:
            end = min(end, len(ids))
        if start or end is not None:
            rng = {"start": start, "end": end}
    return job_dict(_job(create_job(body.project_id, body.kind, params, ids, rng, remote_user(request))))


@router.get("/jobs")
def list_jobs(project_id: int | None = None, limit: int = 200):
    sql, args = "SELECT * FROM job", []
    if project_id is not None:
        sql += " WHERE project_id=?"
        args.append(project_id)
    sql += " ORDER BY CASE WHEN status IN ('queued','preparing','rendering') THEN 0 ELSE 1 END," \
           " CASE WHEN status='queued' THEN queue_pos END, COALESCE(finished_at, created_at) DESC LIMIT ?"
    now = time.time()
    return [job_dict(r, now) for r in get_conn().execute(sql, (*args, min(limit, 1000)))]


@router.get("/jobs/{jid}")
def get_job(jid: int):
    return job_dict(_job(jid))


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int):
    r = _job(jid)
    if r["status"] not in OPEN:
        raise HTTPException(409, "Job läuft nicht")
    get_conn().execute("UPDATE job SET cancel_requested=1 WHERE id=?", (jid,))
    return job_dict(_job(jid))


@router.delete("/jobs/{jid}")
def delete_job(jid: int):
    r = _job(jid)
    if r["status"] in OPEN:
        raise HTTPException(409, "Laufende oder wartende Jobs erst abbrechen")
    delete_job_files(jid)
    get_conn().execute("DELETE FROM job WHERE id=?", (jid,))
    return {"ok": True}


@router.post("/jobs/{jid}/rerun")
def rerun_job(jid: int, request: Request):
    """„Mit gleichen Parametern neu rendern“ / „neu starten“ nach Unterbrechung (R-1, R-2)."""
    r = _job(jid)
    if r["project_id"] is None:
        raise HTTPException(409, "Projekt existiert nicht mehr")
    p = json.loads(r["params_json"])
    rng = p.pop("_range", None)
    for k in [k for k in p if k.startswith("_")]:
        p.pop(k)
    if not frames_file(jid).exists():
        raise HTTPException(409, "Frameliste des Jobs fehlt")
    ids = np.load(frames_file(jid))
    return job_dict(_job(create_job(r["project_id"], r["kind"], normalize(p), ids, rng, remote_user(request))))


class MoveIn(BaseModel):
    direction: str  # up | down | top


@router.post("/jobs/{jid}/move")
def move_job(jid: int, body: MoveIn):
    """R-4: Reihenfolge wartender Jobs ändern."""
    conn = get_conn()
    r = _job(jid)
    if r["status"] != "queued":
        raise HTTPException(409, "Nur wartende Jobs lassen sich verschieben")
    q = conn.execute("SELECT id, queue_pos FROM job WHERE status='queued' AND priority=? ORDER BY queue_pos, id",
                     (r["priority"],)).fetchall()
    ids = [x["id"] for x in q]
    i = ids.index(jid)
    if body.direction == "top":
        ids.insert(0, ids.pop(i))
    elif body.direction == "up" and i > 0:
        ids[i - 1], ids[i] = ids[i], ids[i - 1]
    elif body.direction == "down" and i < len(ids) - 1:
        ids[i + 1], ids[i] = ids[i], ids[i + 1]
    base = min(x["queue_pos"] for x in q)
    with tx(conn):
        for k, x in enumerate(ids):
            conn.execute("UPDATE job SET queue_pos=? WHERE id=?", (base + k, x))
    return list_jobs()


def _output(jid: int) -> Path:
    r = _job(jid)
    if r["status"] != "done" or not r["output_path"] or not os.path.exists(r["output_path"]):
        raise not_found("Video nicht vorhanden")
    return Path(r["output_path"])


@router.get("/jobs/{jid}/download")
def download(jid: int):
    p = _output(jid)
    return FileResponse(p, media_type="video/mp4", filename=p.name)


@router.get("/jobs/{jid}/video")
def video(jid: int):
    """Inline-Wiedergabe (V-4); FileResponse unterstützt Range-Requests."""
    return FileResponse(_output(jid), media_type="video/mp4")


@router.get("/jobs/{jid}/log")
def job_log(jid: int, full: bool = False):
    _job(jid)
    lf = log_file(jid)
    if not lf.exists():
        return PlainTextResponse("")
    if full:
        return FileResponse(lf, media_type="text/plain", filename=f"job-{jid}.log")
    with open(lf, encoding="utf-8", errors="replace") as f:
        return PlainTextResponse("".join(deque(f, maxlen=200)))


@router.get("/storage")
def storage():
    s = config.settings
    du = shutil.disk_usage(s.media_dir)
    used = get_conn().execute("SELECT COALESCE(SUM(output_size),0) FROM job WHERE status='done'").fetchone()[0]
    return {"renders_bytes": used, "free_bytes": du.free, "total_bytes": du.total}
