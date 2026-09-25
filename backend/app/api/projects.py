"""Projekte, Regeln, manuelle Markierungen, Auswertung, Presets (§6, §7, §10)."""
from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..db import get_conn, tx
from ..pipeline import service
from ..pipeline.engine import RULES
from ..video import timelogic
from ..video.params import DEFAULT_PARAMS, extra_seconds, normalize, output_geometry
from .deps import not_found

router = APIRouter(prefix="/api", tags=["projects"])
EXPORT_VERSION = 1


def _project(pid: int):
    r = get_conn().execute("SELECT * FROM project WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise not_found("Projekt nicht gefunden")
    return r


def _touch(pid: int) -> None:
    get_conn().execute("UPDATE project SET updated_at=? WHERE id=?", (int(time.time()), pid))


def _project_dict(r, with_rules: bool = True) -> dict:
    d = {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "updated_at": r["updated_at"],
         "params": normalize(json.loads(r["params_json"]))}
    if with_rules:
        d["rules"] = service.load_rules(r["id"])
    return d


def default_rules() -> list[dict]:
    return [{"type": "sources", "enabled": True, "params": {"source_ids": []}}]


def _insert_rules(conn, pid: int, rules: list[dict]) -> None:
    for pos, rule in enumerate(rules):
        if rule["type"] not in RULES:
            raise HTTPException(422, f"Unbekannter Regeltyp: {rule['type']}")
        conn.execute("INSERT INTO rule(project_id, position, type, enabled, params_json) VALUES (?,?,?,?,?)",
                     (pid, pos, rule["type"], int(rule.get("enabled", True)), json.dumps(rule.get("params") or {})))


def _create(name: str, params: dict | None, rules: list[dict], marks: list[tuple[int, str]] = ()) -> int:
    now = int(time.time())
    conn = get_conn()
    with tx(conn):
        cur = conn.execute("INSERT INTO project(name, created_at, updated_at, params_json) VALUES (?,?,?,?)",
                           (name.strip()[:120] or "Neues Projekt", now, now, json.dumps(normalize(params))))
        pid = cur.lastrowid
        _insert_rules(conn, pid, rules)
        conn.executemany("INSERT OR IGNORE INTO manual_mark(project_id, image_id, mode) VALUES (?,?,?)",
                         [(pid, i, m) for i, m in marks])
    return pid


# ----------------------------------------------------------------------------- Projekte

@router.get("/projects")
def list_projects():
    rows = get_conn().execute(
        "SELECT p.*, (SELECT COUNT(*) FROM job j WHERE j.project_id=p.id AND j.kind='render') AS renders"
        " FROM project p ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        d = _project_dict(r, with_rules=False)
        d["renders"] = r["renders"]
        out.append(d)
    return out


class ProjectCreate(BaseModel):
    name: str = "Neues Projekt"
    params: dict | None = None
    rules: list[dict] | None = None


@router.post("/projects")
def create_project(body: ProjectCreate):
    pid = _create(body.name, body.params, body.rules if body.rules is not None else default_rules())
    return _project_dict(_project(pid))


@router.get("/projects/{pid}")
def get_project(pid: int):
    return _project_dict(_project(pid))


class ProjectPatch(BaseModel):
    name: str | None = None
    params: dict | None = None      # vollständig oder teilweise (wird gemerged)


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch):
    r = _project(pid)
    conn = get_conn()
    if body.name is not None:
        conn.execute("UPDATE project SET name=? WHERE id=?", (body.name.strip()[:120] or r["name"], pid))
    if body.params is not None:
        merged = normalize({**json.loads(r["params_json"]), **body.params})
        conn.execute("UPDATE project SET params_json=? WHERE id=?", (json.dumps(merged), pid))
    _touch(pid)
    return _project_dict(_project(pid))


@router.delete("/projects/{pid}")
def delete_project(pid: int, delete_renders: bool = False):
    """Löscht nur App-Daten (J-2); Renders optional, Quellbilder nie."""
    _project(pid)
    from ..video.jobfiles import delete_job_files
    conn = get_conn()
    jobs = conn.execute("SELECT id FROM job WHERE project_id=? AND status NOT IN"
                        " ('queued','preparing','rendering')", (pid,)).fetchall()
    if conn.execute("SELECT 1 FROM job WHERE project_id=? AND status IN ('queued','preparing','rendering')",
                    (pid,)).fetchone():
        raise HTTPException(409, "Projekt hat laufende oder wartende Jobs")
    if delete_renders:
        for j in jobs:
            delete_job_files(j["id"])
        conn.execute("DELETE FROM job WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM project WHERE id=?", (pid,))
    return {"ok": True}


@router.post("/projects/{pid}/duplicate")
def duplicate_project(pid: int):
    r = _project(pid)
    rules = service.load_rules(pid)
    marks = [(m["image_id"], m["mode"]) for m in
             get_conn().execute("SELECT image_id, mode FROM manual_mark WHERE project_id=?", (pid,))]
    new = _create(f"{r['name']} (Kopie)", json.loads(r["params_json"]), rules, marks)
    return _project_dict(_project(new))


@router.get("/projects/{pid}/export")
def export_project(pid: int):
    """J-4: Regeln + Parameter als JSON (ohne Bilder). Manuelle Markierungen als Pfade (portabel)."""
    r = _project(pid)
    marks = get_conn().execute(
        "SELECT m.mode, s.name AS source, i.rel_path FROM manual_mark m JOIN image i ON i.id=m.image_id"
        " JOIN source s ON s.id=i.source_id WHERE m.project_id=?", (pid,)).fetchall()
    srcs = {row["id"]: row["name"] for row in get_conn().execute("SELECT id, name FROM source")}
    rules = service.load_rules(pid)
    for rule in rules:
        rule.pop("id", None)
        if rule["type"] == "sources":
            rule["params"]["source_names"] = [srcs.get(i) for i in rule["params"].get("source_ids", [])]
    data = {"timelapse_studio_project": EXPORT_VERSION, "name": r["name"],
            "params": normalize(json.loads(r["params_json"])), "rules": rules,
            "manual_marks": [dict(m) for m in marks]}
    fname = "".join(c if c.isalnum() or c in "-_" else "_" for c in r["name"])[:60] or "projekt"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{fname}.json"'})


@router.post("/projects/import")
def import_project(data: dict[str, Any]):
    if data.get("timelapse_studio_project") != EXPORT_VERSION:
        raise HTTPException(422, "Keine gültige Timelapse-Studio-Projektdatei")
    conn = get_conn()
    by_name = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM source")}
    rules = []
    for rule in data.get("rules", []):
        rule = {"type": rule["type"], "enabled": rule.get("enabled", True), "params": rule.get("params") or {}}
        if rule["type"] == "sources" and "source_names" in rule["params"]:
            rule["params"]["source_ids"] = [by_name[n] for n in rule["params"].pop("source_names") if n in by_name]
        rules.append(rule)
    marks = []
    for m in data.get("manual_marks", []):
        sid = by_name.get(m.get("source"))
        if sid is None:
            continue
        row = conn.execute("SELECT id FROM image WHERE source_id=? AND rel_path=?", (sid, m["rel_path"])).fetchone()
        if row:
            marks.append((row["id"], m["mode"]))
    pid = _create(data.get("name", "Import"), data.get("params"), rules, marks)
    return _project_dict(_project(pid))


# ----------------------------------------------------------------------------- Regeln

class RuleIn(BaseModel):
    id: int | None = None
    type: str
    enabled: bool = True
    params: dict = Field(default_factory=dict)


@router.put("/projects/{pid}/rules")
def replace_rules(pid: int, rules: list[RuleIn]):
    """Komplette, geordnete Regelliste speichern (Autosave, Umsortieren)."""
    _project(pid)
    conn = get_conn()
    with tx(conn):
        conn.execute("DELETE FROM rule WHERE project_id=?", (pid,))
        _insert_rules(conn, pid, [r.model_dump() for r in rules])
    _touch(pid)
    return service.load_rules(pid)


@router.post("/projects/{pid}/rules")
def add_rule(pid: int, rule: RuleIn):
    rules = service.load_rules(pid) + [rule.model_dump()]
    return replace_rules(pid, [RuleIn(**r) for r in rules])


@router.patch("/projects/{pid}/rules/{rid}")
def patch_rule(pid: int, rid: int, rule: RuleIn):
    rules = service.load_rules(pid)
    if not any(r["id"] == rid for r in rules):
        raise not_found("Regel nicht gefunden")
    rules = [rule.model_dump() if r["id"] == rid else r for r in rules]
    return replace_rules(pid, [RuleIn(**r) for r in rules])


@router.delete("/projects/{pid}/rules/{rid}")
def delete_rule(pid: int, rid: int):
    rules = [r for r in service.load_rules(pid) if r["id"] != rid]
    return replace_rules(pid, [RuleIn(**r) for r in rules])


# ----------------------------------------------------------------------------- Markierungen (B-6, S-10)

class MarksIn(BaseModel):
    ids: list[int]
    mode: str  # include | exclude | clear


@router.post("/projects/{pid}/marks")
def set_marks(pid: int, body: MarksIn):
    _project(pid)
    if body.mode not in ("include", "exclude", "clear"):
        raise HTTPException(422, "mode muss include, exclude oder clear sein")
    conn = get_conn()
    with tx(conn):
        if body.mode == "clear":
            conn.executemany("DELETE FROM manual_mark WHERE project_id=? AND image_id=?", [(pid, i) for i in body.ids])
        else:
            conn.executemany("INSERT INTO manual_mark(project_id, image_id, mode) VALUES (?,?,?)"
                             " ON CONFLICT(project_id, image_id) DO UPDATE SET mode=excluded.mode",
                             [(pid, i, body.mode) for i in body.ids])
    _touch(pid)
    return marks_summary(pid)


@router.get("/projects/{pid}/marks")
def marks_summary(pid: int):
    rows = get_conn().execute("SELECT mode, COUNT(*) n FROM manual_mark WHERE project_id=? GROUP BY mode",
                              (pid,)).fetchall()
    d = {r["mode"]: r["n"] for r in rows}
    return {"include": d.get("include", 0), "exclude": d.get("exclude", 0)}


@router.delete("/projects/{pid}/marks")
def clear_all_marks(pid: int):
    get_conn().execute("DELETE FROM manual_mark WHERE project_id=?", (pid,))
    _touch(pid)
    return {"include": 0, "exclude": 0}


# ----------------------------------------------------------------------------- Auswertung

def _size_speed_factors(codec: str) -> tuple[float, float]:
    """Korrektur der Schätzung aus fertigen Jobs (P-31)."""
    rows = get_conn().execute(
        "SELECT params_json, output_size, started_at, finished_at, frames_total FROM job"
        " WHERE status='done' AND kind='render' ORDER BY finished_at DESC LIMIT 10").fetchall()
    sf, vf = [], []
    for r in rows:
        p = json.loads(r["params_json"])
        est = p.get("_estimate") or {}
        if p.get("codec") != codec or not est:
            continue
        if est.get("size_bytes") and r["output_size"]:
            sf.append(r["output_size"] / est["size_bytes"])
        if est.get("render_s") and r["finished_at"] and r["started_at"]:
            vf.append((r["finished_at"] - r["started_at"]) / max(est["render_s"], 1))
    def robust(v: list[float]) -> float:  # Ausreißer (z. B. alte Jobs mit anderer Kodierung) begrenzen
        return float(np.clip(np.median(v), 0.33, 3.0)) if v else 1.0
    return robust(sf), robust(vf)


def video_info(pid: int, params: dict, count: int, ev) -> dict:
    fps = params["fps"]
    extra = extra_seconds(params)
    src_w, src_h = service.dominant_size(ev)
    geo = output_geometry(params, src_w, src_h)
    from .. import config
    hw = "vaapi" if config.settings.hwaccel in ("vaapi", "qsv") else "cpu"
    sf, vf = _size_speed_factors(params["codec"])
    br = params["expert"]["bitrate_kbps"] if params["expert"]["enabled"] else None
    est = timelogic.estimate(count, fps, geo["out"]["w"], geo["out"]["h"], src_w, src_h, params["codec"],
                             params["quality"], hw, br or None, sf, vf)
    body_s = count / fps if fps > 0 else 0
    info = {
        "frames": count, "fps": fps, "body_s": round(body_s, 3), "extra_s": extra,
        "total_s": round(body_s + extra, 3), "warnings": timelogic.warnings(fps, count),
        "source_size": {"w": src_w, "h": src_h}, "geometry": geo, "estimate": est, "suggestions": [],
    }
    if params["mode"] == "length":
        base = service.evaluate(pid, skip_auto=True)
        base_n = len(base.result.sel)
        sugg = timelogic.suggest_for_length(base_n, params["target_length_s"], fps, extra_s=extra)
        info["suggestions"] = [s.__dict__ for s in sugg]
        info["base_frames"] = base_n
    return info


@router.post("/projects/{pid}/evaluate")
def evaluate(pid: int):
    """Framezahl, Verteilung, Zwischenstände je Regel und Video-Kennzahlen (S-20, P-1 … P-31)."""
    r = _project(pid)
    t0 = time.perf_counter()
    ev = service.evaluate(pid)
    out = service.summary(ev)
    out["marks"] = marks_summary(pid)
    out["video"] = video_info(pid, normalize(json.loads(r["params_json"])), out["count"], ev)
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


@router.get("/projects/{pid}/frames")
def frames(pid: int, offset: int = 0, limit: int = Query(1000, le=20000)):
    """Frame-Liste der Auswahl, paginiert: [[id, taken_ms], …] (Player, Render)."""
    _project(pid)
    ev = service.evaluate(pid)
    ids = ev.ids[offset:offset + limit]
    ts = ev.times[offset:offset + limit]
    return {"total": int(len(ev.result.sel)), "offset": offset,
            "items": [[int(a), int(b)] for a, b in zip(ids, ts)]}


@router.get("/projects/{pid}/selection")
def selection_in_range(pid: int, from_ms: int = Query(..., alias="from"), to_ms: int = Query(..., alias="to")):
    """IDs der ausgewählten Bilder in einem Zeitraum (Grid-Markierung B-7) + manuelle Marken."""
    _project(pid)
    ev = service.evaluate(pid)
    t = ev.times
    m = (t >= from_ms) & (t < to_ms)
    marks = get_conn().execute(
        "SELECT m.image_id, m.mode FROM manual_mark m JOIN image i ON i.id=m.image_id"
        " WHERE m.project_id=? AND i.taken_ms >= ? AND i.taken_ms < ?", (pid, from_ms, to_ms)).fetchall()
    return {"ids": ev.ids[m].tolist(), "include": [r["image_id"] for r in marks if r["mode"] == "include"],
            "exclude": [r["image_id"] for r in marks if r["mode"] == "exclude"]}


@router.get("/projects/{pid}/sample-image")
def sample_image(pid: int, position: float = 0.5):
    """Beispielbild für Crop-Editor (P-11): Bild an relativer Position der Auswahl."""
    ev = service.evaluate(pid)
    if len(ev.result.sel) == 0:
        raise not_found("Keine Bilder ausgewählt")
    i = int(round(min(max(position, 0), 1) * (len(ev.result.sel) - 1)))
    return {"id": int(ev.ids[i]), "taken_ms": int(ev.times[i])}


# ----------------------------------------------------------------------------- Presets (P-30)

@router.get("/presets")
def list_presets():
    return [{"id": r["id"], "name": r["name"], "params": json.loads(r["params_json"])}
            for r in get_conn().execute("SELECT * FROM preset ORDER BY name")]


class PresetIn(BaseModel):
    name: str
    params: dict


PRESET_KEYS = [k for k in DEFAULT_PARAMS if k not in ("crop",)]


@router.post("/presets")
def save_preset(body: PresetIn):
    """Speichert nur Video-Parameter (keine Crop-Koordinaten); gleicher Name überschreibt."""
    name = body.name.strip()[:80]
    if not name:
        raise HTTPException(422, "Name fehlt")
    p = normalize(body.params)
    params = {k: p[k] for k in PRESET_KEYS}
    get_conn().execute("INSERT INTO preset(name, params_json, created_at) VALUES (?,?,?)"
                       " ON CONFLICT(name) DO UPDATE SET params_json=excluded.params_json",
                       (name, json.dumps(params), int(time.time())))
    return list_presets()


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int):
    get_conn().execute("DELETE FROM preset WHERE id=?", (preset_id,))
    return list_presets()


def seed_presets() -> None:
    """Beispiel-Presets beim ersten Start (P-30)."""
    conn = get_conn()
    if conn.execute("SELECT 1 FROM preset LIMIT 1").fetchone():
        return
    seeds = {
        "Baustelle 1080p 30fps Deflicker": {"resolution": "1080", "fps": 30, "deflicker": {"enabled": True, "size": 10},
                                            "overlay": {"enabled": True}},
        "Social 9:16": {"resolution": "1080", "aspect": "9:16", "fps": 30, "quality": "high"},
        "Archiv 1440p hoch": {"resolution": "1440", "fps": 30, "quality": "high", "codec": "h265"},
    }
    for name, p in seeds.items():
        full = normalize(p)
        conn.execute("INSERT OR IGNORE INTO preset(name, params_json, created_at) VALUES (?,?,?)",
                     (name, json.dumps({k: full[k] for k in PRESET_KEYS}), int(time.time())))
