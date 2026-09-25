import math

from app.video.timelogic import Timing, estimate, suggest_for_length, warnings


def test_timing_fps_fixed():
    t = Timing(frames=5400, fps=30)
    assert t.total_s == 180
    t = Timing(frames=300, fps=30, hold_first_s=1, hold_last_s=2)
    assert t.total_s == 13


def test_warnings():
    assert any("ruckelig" in w for w in warnings(8, 100))
    assert any("60 fps" in w for w in warnings(90, 100))
    assert warnings(30, 100) == []


def test_target_length_suggestions_acceptance4():
    """Abnahme 4: Ziellänge 3:00 bei 30 fps → n vorschlagen; exakte Variante ±1 Frame."""
    frames = 86_040  # z. B. 07–19 Uhr über 6 Monate
    s = {x.kind: x for x in suggest_for_length(frames, 180, 30)}
    assert math.isclose(s["fps"].total_s, 180, abs_tol=0.01)
    nth = s["nth"]
    assert nth.n == 16 and nth.frames == math.ceil(frames / 16)
    assert abs(nth.total_s - 180) < 180 * 0.05       # nah dran
    lim = s["limit"]
    assert lim.frames == 5400 and lim.exact and lim.total_s == 180


def test_target_length_respects_holds_and_too_few():
    s = {x.kind: x for x in suggest_for_length(100, 10, 30, extra_s=2)}
    assert s["fps"].fps == 12.5 and s["fps"].total_s == 10
    assert "Zu wenige" in s["info"].label and "nth" not in s


def test_estimate_monotonic():
    a = estimate(1000, 30, 1920, 1080, 2560, 1440, "h264", "standard")
    b = estimate(1000, 30, 1920, 1080, 2560, 1440, "h264", "high")
    c = estimate(1000, 30, 1920, 1080, 2560, 1440, "h265", "standard")
    assert b["size_bytes"] > a["size_bytes"] > c["size_bytes"] > 0
    assert a["render_s"] > 0
