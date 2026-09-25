import threading
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from .helpers import make_cc400w_series


@pytest.fixture()
def client(env):
    make_cc400w_series(env / "sources" / "cam", datetime(2026, 6, 1, 0, 0), 144, timedelta(minutes=30),
                       brightness_fn=lambda t: 200 if 8 <= t.hour < 18 else 15)
    import importlib
    from app import main
    importlib.reload(main)
    from app.indexer.scanner import request_scan, scan_source
    from app.indexer.sources import sync_sources
    from app.indexer.thumbworker import ThumbWorker
    from app.db import get_conn
    sync_sources()
    request_scan(1)
    scan_source(1)
    w = ThumbWorker(workers=2)
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    for _ in range(100):
        if get_conn().execute("SELECT COUNT(*) FROM image WHERE thumb_status=0").fetchone()[0] == 0:
            break
        time.sleep(0.1)
    w.stop.set()
    th.join(5)
    return TestClient(main.app)


def test_project_flow(client):
    p = client.post("/api/projects", json={"name": "Garten"}).json()
    pid = p["id"]
    assert p["rules"][0]["type"] == "sources" and p["params"]["fps"] == 30

    ev = client.post(f"/api/projects/{pid}/evaluate").json()
    assert ev["count"] == 144 and ev["total"] == 144 and len(ev["distribution"]) == 3

    rules = [{"type": "time_window", "params": {"from": "07:00", "to": "19:00"}},
             {"type": "nth", "params": {"n": 4}}]
    client.put(f"/api/projects/{pid}/rules", json=rules)
    ev = client.post(f"/api/projects/{pid}/evaluate").json()
    assert ev["count"] == 18 and [s["count"] for s in ev["steps"]] == [72, 18]
    assert ev["video"]["total_s"] == pytest.approx(18 / 30)

    # Helligkeit aus Thumbnails
    client.put(f"/api/projects/{pid}/rules", json=[{"type": "brightness", "params": {"min": 100}}])
    assert client.post(f"/api/projects/{pid}/evaluate").json()["count"] == 60

    # Manuell aus- und einschließen
    fr = client.get(f"/api/projects/{pid}/frames?limit=5").json()["items"]
    client.post(f"/api/projects/{pid}/marks", json={"ids": [fr[0][0]], "mode": "exclude"})
    assert client.post(f"/api/projects/{pid}/evaluate").json()["count"] == 59

    # Ziellänge
    client.put(f"/api/projects/{pid}/rules", json=[])
    client.patch(f"/api/projects/{pid}", json={"params": {"mode": "length", "target_length_s": 2, "fps": 30}})
    v = client.post(f"/api/projects/{pid}/evaluate").json()["video"]
    kinds = {s["kind"] for s in v["suggestions"]}
    assert {"fps", "nth", "limit"} <= kinds

    # Export → Import
    data = client.get(f"/api/projects/{pid}/export").json()
    imp = client.post("/api/projects/import", json=data).json()
    assert imp["name"] == "Garten" and imp["params"]["mode"] == "length"
    assert client.get(f"/api/projects/{imp['id']}/marks").json()["exclude"] == 1

    dup = client.post(f"/api/projects/{pid}/duplicate").json()
    assert dup["name"] == "Garten (Kopie)"
    assert client.delete(f"/api/projects/{dup['id']}").json()["ok"]


def test_presets_seeded(client):
    names = [p["name"] for p in client.get("/api/presets").json()]
    assert "Social 9:16" in names
    client.post("/api/presets", json={"name": "Mein Preset", "params": {"fps": 25, "crop": {"x": 0}}})
    p = next(p for p in client.get("/api/presets").json() if p["name"] == "Mein Preset")
    assert p["params"]["fps"] == 25 and "crop" not in p["params"]


def test_timeline_and_thumbs(client):
    b = client.get("/api/timeline/buckets").json()
    assert [x["count"] for x in b] == [48, 48, 48] and b[0]["day"] == "2026-06-01"
    day = client.get("/api/timeline/day/2026-06-01").json()["items"]
    assert len(day) == 48
    r = client.get(f"/api/images/{day[0][0]}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    h = client.get("/api/stats/histogram?bucket=hour").json()
    assert len(h["items"]) == 72


def test_batch_thumbs(client):
    day = client.get("/api/timeline/day/2026-06-02").json()["items"]
    ids = [d[0] for d in day[:5]] + [999999]
    r = client.get("/api/thumbs?ids=" + ",".join(map(str, ids)))
    body = r.content
    n = int.from_bytes(body[:4], "little")
    import json as _j
    header = _j.loads(body[4:4 + n])
    assert [h[0] for h in header] == ids and header[-1][1] == 0 and all(h[1] > 0 for h in header[:5])
    assert len(body) == 4 + n + sum(h[1] for h in header)
    assert body[4 + n:4 + n + 4] == b"RIFF"  # WebP


def test_chunked_upload_resume_and_zip(client, env):
    import io
    import zipfile as zf
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (10, 20, 30)).save(buf, "JPEG")
    data = buf.getvalue()
    init = client.post("/api/uploads/init", json={"album": "Garten 2026", "filename": "IMG_20260601_120000.jpg",
                                                 "size": len(data)}).json()
    uid = init["upload_id"]
    r = client.put(f"/api/uploads/{uid}?offset=0", content=data[:100])
    assert r.json() == {"offset": 100, "done": False}
    # falscher Offset → 409 mit aktuellem Stand (Resume)
    assert client.put(f"/api/uploads/{uid}?offset=0", content=data[:10]).status_code == 409
    again = client.post("/api/uploads/init", json={"album": "Garten 2026", "filename": "IMG_20260601_120000.jpg",
                                                  "size": len(data)}).json()
    assert again["offset"] == 100
    done = client.put(f"/api/uploads/{uid}?offset=100", content=data[100:]).json()
    assert done["done"] and done["files_added"] == 1
    assert (env / "media" / "uploads" / "Garten 2026" / "IMG_20260601_120000.jpg").exists()

    zbuf = io.BytesIO()
    with zf.ZipFile(zbuf, "w") as z:
        z.writestr("serie/a.jpg", data)
        z.writestr("../../evil.jpg", data)
        z.writestr("__MACOSX/._a.jpg", b"x")
        z.writestr("notes.txt", b"x")
    zd = zbuf.getvalue()
    uid = client.post("/api/uploads/init", json={"album": "Zip", "filename": "x.zip", "size": len(zd)}).json()["upload_id"]
    res = client.put(f"/api/uploads/{uid}?offset=0", content=zd).json()
    assert res["files_added"] == 2
    assert not (env / "media" / "evil.jpg").exists() and not (env / "evil.jpg").exists()
    names = [a["name"] for a in client.get("/api/uploads/albums").json()]
    assert names == ["Garten 2026", "Zip"]
