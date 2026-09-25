import os
import threading
import time
from datetime import datetime, timedelta

from app import db
from app.indexer.scanner import scan_source
from app.indexer.sources import sync_sources, thumb_path
from app.indexer.thumbworker import ThumbWorker
from app.indexer.timestamps import from_naive_ms

from .helpers import make_cc400w_series


def _run_thumbs_until_done(timeout=30):
    w = ThumbWorker(workers=2)
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    conn = db.get_conn()
    end = time.time() + timeout
    while time.time() < end:
        if conn.execute("SELECT COUNT(*) FROM image WHERE thumb_status=0").fetchone()[0] == 0:
            break
        time.sleep(0.2)
    w.stop.set()
    th.join(10)


def test_scan_incremental_and_thumbs(env):
    src = env / "sources" / "cam"
    paths = make_cc400w_series(src, datetime(2026, 6, 3, 6, 0), 20, timedelta(minutes=30),
                               brightness_fn=lambda t: 20 if t.hour < 8 else 200)
    (src / "broken.jpg").write_bytes(b"not a jpeg")
    (src / "notes.txt").write_text("ignore me")
    sync_sources()
    conn = db.get_conn()
    sid = conn.execute("SELECT id FROM source WHERE name='cam'").fetchone()[0]
    conn.execute("INSERT INTO scan(source_id, status) VALUES (?, 'queued')", (sid,))

    stats = scan_source(sid)
    assert stats["found"] == 21 and stats["new"] == 21

    # Zeit aus Dateiname, nicht mtime
    first = conn.execute("SELECT taken_ms, ts_origin FROM image WHERE rel_path=?", (paths[0].name,)).fetchone()
    assert from_naive_ms(first["taken_ms"]).replace(microsecond=0) == datetime(2026, 6, 3, 6, 0)
    assert first["ts_origin"] == "filename"

    _run_thumbs_until_done()
    rows = conn.execute("SELECT id, thumb_status, brightness, width, height FROM image ORDER BY taken_ms").fetchall()
    ok = [r for r in rows if r["thumb_status"] == 1]
    bad = [r for r in rows if r["thumb_status"] == 2]
    assert len(ok) == 20 and len(bad) == 1  # I-6: kaputte Datei markiert, Rest fertig
    assert ok[0]["brightness"] < 40 and ok[-1]["brightness"] > 180
    assert (ok[0]["width"], ok[0]["height"]) == (256, 144)
    assert thumb_path(sid, ok[0]["id"]).exists()

    # Rescan ohne Änderung: nichts neu
    assert scan_source(sid)["new"] == 0
    # Löschen + Ändern erkennen
    paths[1].unlink()
    os.utime(paths[2], ns=(0, 10**18))
    s = scan_source(sid)
    assert s["removed"] == 1 and s["changed"] == 1
    assert conn.execute("SELECT thumb_status FROM image WHERE rel_path=?", (paths[2].name,)).fetchone()[0] == 0
