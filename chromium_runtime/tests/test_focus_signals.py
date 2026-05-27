import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_focus_observer_script_tracks_interaction_counters():
    from app.runtime import build_focus_observer_script

    script = build_focus_observer_script()

    assert "__parFocusSignals" in script
    assert "scroll" in script
    assert "click" in script
    assert "input" in script
    assert "copy" in script


def test_compute_focus_score_combines_duration_and_interactions():
    from app.runtime import compute_focus_score

    score = compute_focus_score(
        duration_seconds=180,
        signals={"scroll": 3, "click": 2, "input": 1, "copy": 1},
    )

    assert 0.7 <= score <= 1.0


def test_compute_focus_score_stays_lower_for_idle_page():
    from app.runtime import compute_focus_score

    active = compute_focus_score(180, {"scroll": 3, "click": 2, "input": 1, "copy": 1})
    idle = compute_focus_score(180, {"scroll": 0, "click": 0, "input": 0, "copy": 0})

    assert idle < active
    assert idle >= 0.3
