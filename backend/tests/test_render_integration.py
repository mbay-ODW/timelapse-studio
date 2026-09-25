"""N-7: 10 Testbilder → MP4 mit erwarteter Framezahl und Dauer (per ffprobe)."""
import json
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from .helpers import make_cc400w_series

pytestmark = pytest.mark.skipif(
    not shutil.which("ffprobe")
    or "drawtext" not in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout,
    reason="ffmpeg mit drawtext nötig (im Container ausführen)")


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_read_frames,codec_name:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    return {"w": s["width"], "h": s["height"], "fps": s["r_frame_rate"], "frames": int(s["nb_read_frames"]),
            "codec": s["codec_name"], "duration": float(d["format"]["duration"])}


@pytest.fixture()
def setup(env):
    make_cc400w_series(env / "sources" / "cam", datetime(2026, 6, 1, 8, 0), 60, timedelta(minutes=10),
                       size=(640, 360))
    from app.indexer.scanner import request_scan, scan_source
    from app.indexer.sources import sync_sources
    sync_sources()
    request_scan(1)
    scan_source(1)
    from app.db import get_conn
    conn = get_conn()
    # Größe setzen, ohne Thumb-Worker zu starten
    conn.execute("UPDATE image SET width=640, height=360, thumb_status=1")
    from app.api import projects
    p = projects.create_project(projects.ProjectCreate(name="Integration"))
    return p["id"]


def _run(jid):
    from app.video.queue import JobRunner
    r = JobRunner(jid)
    r.run()
    from app.api.jobs import get_job
    return get_job(jid)


def test_ten_images_to_mp4(setup):
    from app.api import jobs, projects
    pid = setup
    projects.replace_rules(pid, [projects.RuleIn(type="nth", params={"n": 6})])  # 60 → 10 Bilder
    projects.patch_project(pid, projects.ProjectPatch(params={
        "fps": 5, "resolution": "source", "overlay": {"enabled": True}, "deflicker": {"enabled": True, "size": 3}}))
    from app.pipeline import service
    ev = service.evaluate(pid)
    assert len(ev.ids) == 10
    from app.video.params import normalize
    from app.api.projects import _project
    params = normalize(json.loads(_project(pid)["params_json"]))
    jid = jobs.create_job(pid, "render", params, ev.ids.copy(), None, None)
    j = _run(jid)
    assert j["status"] == "done", j["error"]
    info = ffprobe(j and jobs._output(jid))
    assert info["frames"] == 10 and info["fps"] == "5/1"
    assert info["duration"] == pytest.approx(2.0, abs=0.05)
    assert (info["w"], info["h"]) == (640, 360) and info["codec"] == "h264"
    assert j["output_name"].startswith("Integration_") and j["output_name"].endswith("_360p_5fps.mp4")


def test_holds_title_crop_rotate(setup):
    from app.api import jobs
    from app.pipeline import service
    from app.video.params import normalize
    pid = setup
    ev = service.evaluate(pid)
    params = normalize({"fps": 10, "resolution": "source", "hold_first_s": 1, "hold_last_s": 1,
                        "title": {"text": "Titel", "duration_s": 1}, "fade_in_s": 0.5, "fade_out_s": 0.5,
                        "rotate": 90, "aspect": "1:1", "blend": {"enabled": True, "frames": 2}})
    jid = jobs.create_job(pid, "render", params, ev.ids.copy(), None, None)
    j = _run(jid)
    assert j["status"] == "done", j["error"]
    info = ffprobe(jobs._output(jid))
    assert info["frames"] == 60 + 10 + 10 + 10       # Bilder + Halten vorn/hinten + Titel
    assert (info["w"], info["h"]) == (360, 360)


def test_preview_range(setup):
    from app.api import jobs
    from app.pipeline import service
    from app.video.params import normalize
    pid = setup
    ev = service.evaluate(pid)
    jid = jobs.create_job(pid, "preview", normalize({"fps": 30}), ev.ids.copy(), {"start": 10, "end": 40}, None)
    j = _run(jid)
    assert j["status"] == "done", j["error"]
    info = ffprobe(jobs._output(jid))
    assert info["frames"] == 30 and min(info["w"], info["h"]) == 360  # nie hochskaliert


def test_cancel_within_5s_and_cleanup(setup, env):
    from app.api import jobs
    from app.db import get_conn
    from app.pipeline import service
    from app.video.params import normalize
    from app.video.queue import JobRunner
    pid = setup
    ev = service.evaluate(pid)
    ids = np.tile(ev.ids, 200)  # 12.000 Frames → läuft lange genug
    jid = jobs.create_job(pid, "render", normalize({"fps": 30, "resolution": "source", "quality": "max"}),
                          ids, None, None)
    runner = JobRunner(jid)
    th = threading.Thread(target=runner.run)
    th.start()
    for _ in range(100):
        if get_conn().execute("SELECT status FROM job WHERE id=?", (jid,)).fetchone()[0] == "rendering":
            break
        time.sleep(0.1)
    time.sleep(1)
    t0 = time.time()
    jobs.cancel_job(jid)
    th.join(10)
    assert time.time() - t0 < 5
    j = jobs.get_job(jid)
    assert j["status"] == "cancelled"
    renders = env / "media" / "renders"
    assert not list(renders.glob("*.mp4")) and not list(renders.glob("*.part"))
    assert not list((env / "media" / "tmp").iterdir())


def test_recover_after_restart(setup):
    from app.api import jobs
    from app.db import get_conn
    from app.pipeline import service
    from app.video.params import normalize
    from app.video.queue import RenderQueue
    pid = setup
    ev = service.evaluate(pid)
    jid = jobs.create_job(pid, "render", normalize({}), ev.ids.copy(), None, None)
    get_conn().execute("UPDATE job SET status='rendering' WHERE id=?", (jid,))
    RenderQueue(threading.Event()).recover()
    j = jobs.get_job(jid)
    assert j["status"] == "interrupted" and "neu starten" in j["error"]
    new = jobs.rerun_job(jid, type("R", (), {"headers": {}})())
    assert new["status"] == "queued" and new["frames_total"] == 60
