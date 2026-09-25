from datetime import datetime

import pytest

from app.indexer.timestamps import (PatternError, compile_pattern, from_naive_ms, mtime_to_naive_ms,
                                    parse_exif_datetime, parse_filename, resolve)


def dt(ms):
    return from_naive_ms(ms)


def test_cc400w_default_pattern():
    ms = parse_filename("CC400W-001-20260603-1517024995-Cam-2-Type-0.jpg")
    assert dt(ms) == datetime(2026, 6, 3, 15, 17, 2, 499000)  # ms-Auflösung


@pytest.mark.parametrize("name,expected", [
    ("IMG_20260603_151702.jpg", datetime(2026, 6, 3, 15, 17, 2)),
    ("2026-06-03 15.17.02.jpg", datetime(2026, 6, 3, 15, 17, 2)),
    ("snap_2026-06-03T15-17-02.png", datetime(2026, 6, 3, 15, 17, 2)),
])
def test_default_pattern_variants(name, expected):
    assert dt(parse_filename(name)) == expected


def test_strftime_pattern():
    ms = parse_filename("cam_03.06.26_1517.jpg", "cam_%d.%m.%y_%H%M*")
    assert dt(ms) == datetime(2026, 6, 3, 15, 17)


def test_pattern_needs_date_parts():
    with pytest.raises(PatternError):
        compile_pattern(r"(?P<H>\d\d)")


def test_no_match_and_invalid_date():
    assert parse_filename("holiday.jpg") is None
    assert parse_filename("x-20261399-120000.jpg") is None


def test_exif():
    assert dt(parse_exif_datetime("2026:06:03 15:17:02", "45")) == datetime(2026, 6, 3, 15, 17, 2, 450000)
    assert parse_exif_datetime("0000:00:00 00:00:00") is None


def test_mtime_is_local_wallclock():
    # 2026-06-03 13:17:02 UTC == 15:17:02 in Berlin (Sommerzeit)
    import calendar
    ns = calendar.timegm((2026, 6, 3, 13, 17, 2)) * 10**9
    assert dt(mtime_to_naive_ms(ns, "Europe/Berlin")) == datetime(2026, 6, 3, 15, 17, 2)


def test_resolve_order():
    assert resolve(["exif", "filename", "mtime"], exif_ms=None, filename_ms=5, mtime_ms=9) == (5, "filename")
    assert resolve(["mtime", "exif"], exif_ms=1, filename_ms=5, mtime_ms=9) == (9, "mtime")
