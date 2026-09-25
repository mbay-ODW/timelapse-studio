import time
from datetime import datetime, timezone

import numpy as np
import pytest

from app.pipeline.engine import (DAY_MS, Marks, Universe, day_distribution, parse_date, run, weekday)


def ms(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


def make(times, bright=None, src=None, ph=None):
    n = len(times)
    rows = [(i + 1, (src[i] if src else 1), t, (bright[i] if bright else 100.0), (ph[i] if ph else None))
            for i, t in enumerate(times)]
    return Universe.from_rows(rows)


def ids(U, res):
    return U.ids[res.sel].tolist()


# Serie: 3 Tage (Mo 01.06.2026 – Mi 03.06.2026), alle 30 min → 144 Bilder
START = ms(2026, 6, 1)
SERIES = [START + i * 30 * 60_000 for i in range(144)]


def test_weekday_monday():
    assert weekday(np.array([START]))[0] == 0  # 01.06.2026 ist Montag


def test_time_window_day_and_midnight():
    U = make(SERIES)
    r = run(U, [{"type": "time_window", "params": {"from": "07:00", "to": "19:00"}}])
    assert len(r.sel) == 3 * 24  # 07:00 … 18:30 → 24 pro Tag
    assert all(7 <= (U.t[i] % DAY_MS) / 3_600_000 < 19 for i in r.sel)
    r = run(U, [{"type": "time_window", "params": {"from": "22:00", "to": "02:00"}}])
    assert len(r.sel) == 3 * 8  # 22:00–23:30 (4) + 00:00–01:30 (4)


def test_date_range_inclusive_end():
    U = make(SERIES)
    r = run(U, [{"type": "date_range", "params": {"from": "2026-06-02", "to": "2026-06-02"}}])
    assert len(r.sel) == 48


def test_weekdays():
    U = make(SERIES)
    r = run(U, [{"type": "weekdays", "params": {"days": [0, 2]}}])  # Mo + Mi
    assert len(r.sel) == 96


def test_nth_with_offset_after_window():
    U = make(SERIES)
    rules = [{"type": "time_window", "params": {"from": "07:00", "to": "19:00"}},
             {"type": "nth", "params": {"n": 20, "offset": 0}}]
    r = run(U, rules)
    assert len(r.sel) == 4  # 72 Bilder → Index 0,20,40,60
    r = run(U, [{"type": "nth", "params": {"n": 10, "offset": 3}}])
    assert ids(U, r)[:2] == [4, 14]


def test_interval_first_nearest_brightest_median():
    bright = [float(i % 48) for i in range(144)]  # pro Tag 0..47 → hellstes = 23:30
    U = make(SERIES, bright=bright)
    first = run(U, [{"type": "interval", "params": {"interval_s": 86400, "strategy": "first"}}])
    assert [U.t[i] % DAY_MS for i in first.sel] == [0, 0, 0]
    near = run(U, [{"type": "interval", "params": {"interval_s": 86400, "strategy": "nearest", "at": "12:10"}}])
    assert [(U.t[i] % DAY_MS) // 60000 for i in near.sel] == [12 * 60] * 3
    br = run(U, [{"type": "interval", "params": {"interval_s": 86400, "strategy": "brightest"}}])
    assert [U.b[i] for i in br.sel] == [47.0] * 3
    med = run(U, [{"type": "interval", "params": {"interval_s": 86400, "strategy": "median"}}])
    assert [U.b[i] for i in med.sel] == [23.0] * 3
    hourly = run(U, [{"type": "interval", "params": {"interval_s": 3600, "strategy": "first"}}])
    assert len(hourly.sel) == 72


def test_limit_even_and_exact():
    U = make(SERIES)
    r = run(U, [{"type": "limit", "params": {"n": 10}}])
    assert len(r.sel) == 10
    assert U.t[r.sel[0]] == SERIES[0] and U.t[r.sel[-1]] == SERIES[-1]
    # Clustered: 100 Bilder in 1 min + 2 Ausreißer → trotzdem exakt N
    times = [START + i * 100 for i in range(100)] + [START + DAY_MS, START + 2 * DAY_MS]
    U2 = make(times)
    assert len(run(U2, [{"type": "limit", "params": {"n": 20}}]).sel) == 20


def test_brightness_keeps_unknown():
    bright = [10.0, 50.0, None, 200.0]
    U = make(SERIES[:4], bright=bright)
    r = run(U, [{"type": "brightness", "params": {"min": 30, "max": 150}}])
    assert ids(U, r) == [2, 3]


def test_dedupe_consecutive():
    ph = [0b1111, 0b1111, 0b1110, 0xFF00FF00, None]
    U = make(SERIES[:5], ph=ph)
    r = run(U, [{"type": "dedupe", "params": {"threshold": 1}}])
    assert ids(U, r) == [1, 4, 5]


def test_manual_marks_and_sources():
    U = make(SERIES[:6], src=[1, 1, 2, 2, 1, 2])
    marks = Marks(include={3}, exclude={1})
    r = run(U, [{"type": "sources", "params": {"source_ids": [1]}}], marks)
    assert ids(U, r) == [2, 3, 5]  # 1 ausgeschlossen, 3 manuell rein (andere Quelle)


def test_order_desc_and_disabled_and_error():
    U = make(SERIES[:5])
    r = run(U, [{"type": "nth", "enabled": False, "params": {"n": 2}},
                {"type": "nth", "params": {"n": 0}},
                {"type": "order", "params": {"direction": "desc"}}])
    assert ids(U, r) == [5, 4, 3, 2, 1]
    assert r.steps[0]["count"] is None and r.steps[1]["error"]


def test_day_distribution():
    U = make(SERIES)
    dist = day_distribution(U, np.arange(len(U)))
    assert [c for _, c in dist] == [48, 48, 48]


def test_parse_date_formats():
    assert parse_date("2026-06-01") == START
    assert parse_date("2026-06-01T12:00") == START + 12 * 3_600_000


def test_performance_344k():
    """S-21: Neuberechnung bei 344k Bildern < 1 s (reine Engine, ohne DB)."""
    rng = np.random.default_rng(1)
    n = 344_000
    t = np.sort(rng.integers(ms(2026, 3, 1), ms(2026, 9, 1), n))
    U = Universe(ids=np.arange(1, n + 1), src=np.ones(n, np.int32), t=t,
                 b=rng.uniform(0, 255, n).astype(np.float32), ph=rng.integers(1, 2**63, n).astype(np.uint64))
    rules = [{"type": "time_window", "params": {"from": "07:00", "to": "19:00"}},
             {"type": "brightness", "params": {"min": 40}},
             {"type": "interval", "params": {"interval_s": 600, "strategy": "brightest"}},
             {"type": "nth", "params": {"n": 20}}]
    t0 = time.perf_counter()
    r = run(U, rules, Marks(exclude=set(range(1, 5000))))
    day_distribution(U, r.sel)
    assert time.perf_counter() - t0 < 1.0
