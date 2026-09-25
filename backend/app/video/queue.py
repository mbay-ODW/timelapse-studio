"""Persistente Render-Queue im Worker-Prozess (§9, R-1 … R-8).

Die Queue ist die Tabelle `job`. Der Worker nimmt wartende Jobs nach Priorität und Position,
startet ffmpeg, schreibt Fortschritt in die DB (API streamt ihn per SSE) und reagiert auf
`cancel_requested`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import config
from ..db import get_conn
from ..logging_setup import log
from . import ffmpeg
from .jobfiles import frames_file, job_tmp_dir, log_file

logger = logging.getLogger("render")
ACTIVE = ("preparing", "rendering")


def in_window(window: str, now: datetime | None = None) -> bool:
    """RENDER_WINDOW "22:00-06:00" (über Mitternacht erlaubt); leer = immer."""
    if not window:
        return True
    try:
        a, b = window.split("-")
        ah, am = map(int, a.split(":"))
        bh, bm = map(int, b.split(":"))
    except ValueError:
        return True
    now = now or datetime.now()
    m, lo, hi = now.hour * 60 + now.minute, ah * 60 + am, bh * 60 + bm
    return lo <= m < hi if lo < hi else (m >= lo or m < hi)


def notify(title: str, message: str, tags: str = "") -> None:
    s = config.settings
    if not (s.ntfy_url and s.ntfy_topic):
        return
    req = urllib.request.Request(f"{s.ntfy_url}/{s.ntfy_topic}", data=message.encode(), method="POST",
                                 headers={"Title": title.encode("utf-8").decode("latin-1", "ignore"),
                                          "Tags": tags})
    if s.ntfy_token:
        req.add_header("Authorization", f"Bearer {s.ntfy_token}")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # Benachrichtigung darf den Job nie scheitern lassen
        log(logger, logging.WARNING, "ntfy fehlgeschlagen", error=str(e))


class JobRunner:
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self.interrupted = False   # Worker fährt herunter (Container-Stopp)
        self.is_preview = False

    # ------------------------------------------------------------------ Hilfen
    def _upd(self, conn, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE job SET {cols}, heartbeat_at=? WHERE id=?",
                     (*fields.values(), int(time.time()), self.job_id))

    def _cancel_requested(self, conn) -> bool:
        r = conn.execute("SELECT cancel_requested FROM job WHERE id=?", (self.job_id,)).fetchone()
        return bool(r and r[0])

    def stop_process(self) -> None:
        """Sauber beenden: 'q' → SIGTERM (2 s) → SIGKILL (2 s) → spätestens nach ~4,5 s weg."""
        p = self.proc
        if p is None or p.poll() is not None:
            return
        try:
            if p.stdin:
                p.stdin.write(b"q")
                p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        for sig, wait in ((None, 0.5), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            if sig is not None and p.poll() is None:
                p.send_signal(sig)
            try:
                p.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue

    # ------------------------------------------------------------------ Ablauf
    def run(self) -> None:
        conn = get_conn()
        s = config.settings
        job = conn.execute("SELECT * FROM job WHERE id=?", (self.job_id,)).fetchone()
        params = json.loads(job["params_json"])
        preview = job["kind"] == "preview"
        tmp = job_tmp_dir(self.job_id)
        tmp.mkdir(parents=True, exist_ok=True)
        logf = log_file(self.job_id)
        logf.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        self._upd(conn, status="preparing", phase="Frameliste erstellen", started_at=int(started),
                  worker_pid=os.getpid(), frames_done=0, error=None, log_path=str(logf))
        out_final = Path(job["output_path"])
        out_part = out_final.with_name(out_final.name + ".part")
        try:
            ids = np.load(frames_file(self.job_id))
            rng = params.get("_range") or {}
            if rng:
                a, b = int(rng.get("start", 0)), rng.get("end")
                ids = ids[a:(int(b) if b is not None else None)]
            if len(ids) < 1:
                raise RuntimeError("Keine Bilder in der Auswahl")
            frames, sizes = self._frame_paths(conn, ids)
            if len(frames) < len(ids):
                log(logger, logging.WARNING, "Bilder fehlen", job_id=self.job_id, missing=len(ids) - len(frames))
            if not frames:
                raise RuntimeError("Keine der ausgewählten Dateien ist lesbar")
            (src_w, src_h), mixed = sizes
            concat = tmp / "frames.ffconcat"
            ov = params["overlay"]
            ffmpeg.write_concat(concat, frames, ov["format"] if ov["enabled"] else None)
            audio = None
            if not preview and params.get("audio", {}).get("file"):
                ap = s.uploads_dir / ".audio" / params["audio"]["file"]
                audio = ap if ap.exists() else None
            plan = ffmpeg.build(params, concat_file=concat, n_frames=len(frames), src_w=src_w, src_h=src_h,
                                output=out_part, tmp_dir=tmp, hwaccel=s.hwaccel, vaapi_device=s.vaapi_device,
                                threads=s.ffmpeg_threads, preview=preview, mixed_sizes=mixed, audio_file=audio)
            self._upd(conn, status="rendering", phase="Rendern", frames_total=plan.total_frames)
            with open(logf, "w", encoding="utf-8") as lf:
                lf.write("$ " + " ".join(plan.cmd) + "\n\n")
            self._run_ffmpeg(conn, plan, logf)
            if self.interrupted:
                raise ConnectionAbortedError
            if self.cancelled:
                raise InterruptedError
            if self.proc.returncode != 0:
                raise RuntimeError(f"ffmpeg beendet mit Code {self.proc.returncode}")
            self._upd(conn, phase="Abschließen")
            os.replace(out_part, out_final)
            size = out_final.stat().st_size
            finished = time.time()
            self._upd(conn, status="done", phase=None, finished_at=int(finished), output_size=size, eta_s=0,
                      frames_done=plan.total_frames)
            log(logger, logging.INFO, "Job fertig", job_id=self.job_id, seconds=round(finished - started, 1),
                size=size, encoder=plan.encoder)
            if not preview:
                notify(f"Zeitraffer fertig: {job['project_name']}",
                       f"{out_final.name} · {size / 1e6:.0f} MB · {int(finished - started)} s", "white_check_mark")
        except ConnectionAbortedError:
            out_part.unlink(missing_ok=True)
            self._upd(conn, status="interrupted", phase=None, finished_at=int(time.time()), eta_s=None,
                      error="Abgebrochen durch Neustart – neu starten?")
        except InterruptedError:
            out_part.unlink(missing_ok=True)
            self._upd(conn, status="cancelled", phase=None, finished_at=int(time.time()), eta_s=None,
                      error="Vom Benutzer abgebrochen")
            log(logger, logging.INFO, "Job abgebrochen", job_id=self.job_id)
        except Exception as e:
            out_part.unlink(missing_ok=True)
            self._upd(conn, status="failed", phase=None, finished_at=int(time.time()), eta_s=None,
                      error=str(e)[:1000])
            log(logger, logging.ERROR, "Job fehlgeschlagen", job_id=self.job_id, error=str(e))
            if not preview:
                notify(f"Zeitraffer fehlgeschlagen: {job['project_name']}", str(e)[:300], "x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # R-7

    def _frame_paths(self, conn, ids: np.ndarray):
        """Pfade + Zeit in Frame-Reihenfolge; ermittelt dominante Größe und ob Größen gemischt sind."""
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS jf(pos INTEGER PRIMARY KEY, image_id INTEGER)")
        conn.execute("DELETE FROM jf")
        conn.executemany("INSERT INTO jf(pos, image_id) VALUES (?,?)", enumerate(ids.tolist()))
        rows = conn.execute(
            "SELECT s.path || '/' || i.rel_path AS p, i.taken_ms, i.width, i.height FROM jf"
            " JOIN image i ON i.id = jf.image_id JOIN source s ON s.id = i.source_id ORDER BY jf.pos").fetchall()
        conn.execute("DELETE FROM jf")
        frames = [(r["p"], r["taken_ms"]) for r in rows if os.path.exists(r["p"])]
        counts: dict[tuple[int, int], int] = {}
        for r in rows:
            if r["width"]:
                counts[(r["width"], r["height"])] = counts.get((r["width"], r["height"]), 0) + 1
        dominant = max(counts, key=counts.get) if counts else (1920, 1080)
        return frames, (dominant, len(counts) > 1)

    def _run_ffmpeg(self, conn, plan: ffmpeg.RenderPlan, logf: Path) -> None:
        stderr_f = open(logf, "a", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(plan.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=stderr_f, preexec_fn=lambda: os.nice(5))
        state: dict[str, str] = {}
        t0 = time.time()
        last_db = 0.0
        speeds: deque[tuple[float, int]] = deque(maxlen=20)
        stop_poll = threading.Event()

        def poll_cancel():
            c = get_conn()
            while not stop_poll.wait(0.5):
                if self._cancel_requested(c):
                    self.cancelled = True
                    self.stop_process()
                    return

        watcher = threading.Thread(target=poll_cancel, daemon=True)
        watcher.start()
        try:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                state[k] = v
                if k != "progress":
                    continue
                now = time.time()
                done = int(state.get("frame", "0") or 0)
                speeds.append((now, done))
                if now - last_db >= 0.5 or v == "end":
                    last_db = now
                    fps_cur = None
                    if len(speeds) >= 2 and speeds[-1][0] > speeds[0][0]:
                        fps_cur = (speeds[-1][1] - speeds[0][1]) / (speeds[-1][0] - speeds[0][0])
                    elapsed = now - t0
                    remaining = max(0, plan.total_frames - done)
                    eta = None
                    if fps_cur and fps_cur > 0:
                        eta = remaining / fps_cur
                    elif done > 0:
                        eta = elapsed * remaining / done
                    speed = state.get("speed", "").rstrip("x").strip()
                    self._upd(conn, frames_done=min(done, plan.total_frames),
                              fps_current=round(fps_cur, 2) if fps_cur else None,
                              speed=float(speed) if speed not in ("", "N/A") else None,
                              eta_s=round(eta, 1) if eta is not None else None)
            self.proc.wait()
        finally:
            stop_poll.set()
            stderr_f.close()


class RenderQueue:
    def __init__(self, stop: threading.Event) -> None:
        self.stop = stop
        self.running: dict[int, tuple[threading.Thread, JobRunner]] = {}
        self.last_cleanup = 0.0

    def recover(self) -> None:
        """R-1/Abnahme 9: nach Neustart laufende Jobs als unterbrochen markieren."""
        conn = get_conn()
        rows = conn.execute("SELECT id, output_path FROM job WHERE status IN ('preparing','rendering')").fetchall()
        for r in rows:
            if r["output_path"]:
                Path(r["output_path"] + ".part").unlink(missing_ok=True)
            shutil.rmtree(job_tmp_dir(r["id"]), ignore_errors=True)
            conn.execute("UPDATE job SET status='interrupted', phase=NULL, eta_s=NULL, finished_at=?,"
                         " error='Abgebrochen durch Neustart – neu starten?' WHERE id=?", (int(time.time()), r["id"]))
            log(logger, logging.WARNING, "Job nach Neustart als unterbrochen markiert", job_id=r["id"])

    def _next(self, conn):
        render_ok = in_window(config.settings.render_window)
        rows = conn.execute("SELECT id, kind FROM job WHERE status='queued' AND cancel_requested=0"
                            " ORDER BY priority DESC, queue_pos, id").fetchall()
        for r in rows:
            if r["kind"] == "preview" or render_ok:
                return r["id"]
        return None

    def cleanup(self, conn) -> None:
        days = config.settings.renders_retention_days
        if days <= 0 or time.time() - self.last_cleanup < 3600:
            return
        self.last_cleanup = time.time()
        from .jobfiles import delete_job_files
        cutoff = int(time.time()) - days * 86400
        for r in conn.execute("SELECT id FROM job WHERE status IN ('done','failed','cancelled','interrupted')"
                              " AND finished_at < ?", (cutoff,)).fetchall():
            delete_job_files(r["id"])
            conn.execute("DELETE FROM job WHERE id=?", (r["id"],))
            log(logger, logging.INFO, "Render automatisch gelöscht", job_id=r["id"])

    def run(self) -> None:
        self.recover()
        conn = get_conn()
        limit = max(1, config.settings.max_parallel_renders)
        while not self.stop.is_set():
            for jid in [j for j, (t, _) in self.running.items() if not t.is_alive()]:
                del self.running[jid]
            # Abbruch wartender Jobs direkt erledigen
            conn.execute("UPDATE job SET status='cancelled', finished_at=?, error='Vom Benutzer abgebrochen'"
                         " WHERE status='queued' AND cancel_requested=1", (int(time.time()),))
            # Vorschau-Jobs dürfen einen zusätzlichen Slot nutzen (V-3: höhere Priorität, kurze Laufzeit)
            while True:
                n_render = sum(1 for _, (_, r) in self.running.items() if not r.is_preview)
                nxt = self._next(conn)
                if nxt is None:
                    break
                kind = conn.execute("SELECT kind FROM job WHERE id=?", (nxt,)).fetchone()["kind"]
                n_prev = len(self.running) - n_render
                if kind == "render" and n_render >= limit:
                    break
                if kind == "preview" and n_prev >= 1:
                    break
                runner = JobRunner(nxt)
                runner.is_preview = kind == "preview"
                th = threading.Thread(target=runner.run, name=f"job-{nxt}", daemon=True)
                conn.execute("UPDATE job SET status='preparing' WHERE id=? AND status='queued'", (nxt,))
                self.running[nxt] = (th, runner)
                th.start()
            self.cleanup(conn)
            self.stop.wait(1.0)

    def shutdown(self) -> None:
        for _, (th, runner) in list(self.running.items()):
            runner.interrupted = True
            runner.stop_process()
        for _, (th, _) in list(self.running.items()):
            th.join(timeout=8)
