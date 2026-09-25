"""Dateiablage der Jobs (R-7, R-8)."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from .. import config
from ..db import get_conn


def jobs_meta_dir() -> Path:
    return config.settings.renders_dir / ".jobs"


def frames_file(job_id: int) -> Path:
    return jobs_meta_dir() / f"{job_id}.frames.npy"


def log_file(job_id: int) -> Path:
    return jobs_meta_dir() / f"{job_id}.log"


def job_tmp_dir(job_id: int) -> Path:
    return config.settings.tmp_dir / f"job-{job_id}"


def safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return (s or "projekt")[:60]


def output_name(project: str, res_label: str, fps: float, preview: bool, job_id: int) -> str:
    """R-8: <projekt>_<YYYYMMDD-HHMM>_<auflösung>_<fps>fps.mp4 (Proxy mit Präfix)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fps_s = f"{fps:g}".replace(".", "_")
    base = f"{safe_name(project)}_{stamp}_{res_label}_{fps_s}fps"
    if preview:
        base = f"preview_{base}_{job_id}"
    out = config.settings.renders_dir / f"{base}.mp4"
    i = 2
    while out.exists():
        out = config.settings.renders_dir / f"{base}-{i}.mp4"
        i += 1
    return str(out)


def delete_job_files(job_id: int) -> None:
    r = get_conn().execute("SELECT output_path FROM job WHERE id=?", (job_id,)).fetchone()
    if r and r["output_path"]:
        p = Path(r["output_path"])
        # nur innerhalb des Render-Verzeichnisses löschen
        if config.settings.renders_dir.resolve() in p.resolve().parents:
            p.unlink(missing_ok=True)
            p.with_name(p.name + ".part").unlink(missing_ok=True)
    frames_file(job_id).unlink(missing_ok=True)
    log_file(job_id).unlink(missing_ok=True)
    shutil.rmtree(job_tmp_dir(job_id), ignore_errors=True)
