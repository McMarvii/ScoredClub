from __future__ import annotations

from scoredclub.analytics import (
    BUCKET_EXPLOSIVE,
    BUCKET_GROWTH,
    BUCKET_INSUFFICIENT,
    BUCKET_NONE,
    BUCKET_STRONG,
    PHASE_DEVELOPING,
    PHASE_ELITE,
    PHASE_EMERGING,
    PHASE_ESTABLISHED,
    analyze_cohort,
    career_phase,
    compute_intelligence,
    detect_breakout,
    forecast,
    linear_slope,
    percentiles,
    series_from_runs,
)
from scoredclub.config import Settings
from scoredclub.db.models import Run, ScoreSnapshot


def test_linear_slope():
    assert linear_slope([]) == 0.0
    assert linear_slope([5.0]) == 0.0
    assert linear_slope([1.0, 2.0, 3.0, 4.0]) == 1.0
    assert linear_slope([4.0, 3.0, 2.0, 1.0]) == -1.0
    assert linear_slope([5.0, 5.0, 5.0]) == 0.0


def test_detect_breakout_insufficient_and_flat():
    assert detect_breakout([10.0, 12.0]).bucket == BUCKET_INSUFFICIENT
    assert detect_breakout([50.0, 50.0, 50.0]).bucket == BUCKET_NONE
    # A decline never breaks out.
    assert detect_breakout([60.0, 55.0, 50.0, 45.0]).bucket == BUCKET_NONE


def test_detect_breakout_steady_climb_is_explosive():
    # Zero volatility (steady +5/run), baseline floored to 1.0 -> z = 5 -> explosive.
    b = detect_breakout([50.0, 55.0, 60.0, 65.0])
    assert b.bucket == BUCKET_EXPLOSIVE
    assert b.slope == 5.0
    assert b.z_score == 5.0


def test_detect_breakout_dynamic_baseline_dampens_noisy_series():
    # Same net climb but high run-to-run volatility -> lower z -> milder bucket.
    steady = detect_breakout([50.0, 52.0, 54.0, 56.0])  # slope 2, vol 0 -> z=2 strong
    noisy = detect_breakout([50.0, 60.0, 48.0, 56.0])  # similar end, high vol -> weaker
    assert steady.bucket == BUCKET_STRONG
    assert noisy.z_score < steady.z_score


def test_detect_breakout_growth_bucket():
    # slope 1.5, baseline floor 1.0 -> z=1.5 -> growth
    b = detect_breakout([50.0, 51.5, 53.0, 54.5], baseline_floor=1.0)
    assert b.bucket == BUCKET_GROWTH


def test_percentiles():
    assert percentiles({}) == {}
    assert percentiles({"a": 42.0}) == {"a": 100.0}
    pct = percentiles({"a": 10.0, "b": 20.0, "c": 30.0})
    assert pct["c"] == 100.0
    assert pct["a"] == 0.0
    assert pct["b"] == 50.0
    # Ties share a percentile.
    tied = percentiles({"a": 10.0, "b": 10.0, "c": 30.0})
    assert tied["a"] == tied["b"] == 0.0


def test_career_phase():
    assert career_phase(95.0) == PHASE_ELITE
    assert career_phase(75.0) == PHASE_ESTABLISHED
    assert career_phase(50.0) == PHASE_EMERGING
    assert career_phase(10.0) == PHASE_DEVELOPING


def test_forecast():
    assert forecast([]).projected_score == 0.0
    f = forecast([50.0, 52.0, 54.0, 56.0])
    assert f.slope == 2.0
    assert f.projected_score == 58.0
    assert f.rising_soon is True
    # Flat -> no rise; projection clamped within 0..100.
    assert forecast([50.0, 50.0, 50.0]).rising_soon is False
    assert forecast([99.0, 100.0, 100.0]).projected_score <= 100.0


def test_series_from_runs_keeps_series_contiguous():
    runs = [{"a": 10.0, "b": 5.0}, {"a": 12.0}, {"a": 14.0, "b": 9.0}]
    sbe = series_from_runs(runs)
    assert sbe["a"] == [10.0, 12.0, 14.0]
    # 'b' missing from the middle run -> contiguous two-point series.
    assert sbe["b"] == [5.0, 9.0]


def test_analyze_cohort():
    sbe = {
        "rising": [40.0, 45.0, 50.0, 55.0],
        "flat": [80.0, 80.0, 80.0, 80.0],
    }
    current = {"rising": 55.0, "flat": 80.0}
    out = analyze_cohort(sbe, current)
    assert out["rising"].breakout.bucket == BUCKET_EXPLOSIVE
    assert out["rising"].forecast.rising_soon is True
    assert out["flat"].breakout.bucket == BUCKET_NONE
    # 'flat' has the higher score -> top percentile -> elite.
    assert out["flat"].percentile == 100.0
    assert out["flat"].career_phase == PHASE_ELITE


def _add_run(session, scores: dict[str, float]) -> Run:
    run = Run()
    session.add(run)
    session.flush()
    for entity_id, score in scores.items():
        session.add(
            ScoreSnapshot(
                run_id=run.id, entity_id=entity_id, score=score,
                tier="MID-TIER", status="active", breakdown={},
            )
        )
    session.flush()
    return run


def test_compute_intelligence_over_db_history(session):
    _add_run(session, {"climber": 40.0, "steady": 70.0})
    _add_run(session, {"climber": 50.0, "steady": 70.0})
    _add_run(session, {"climber": 60.0, "steady": 70.0})
    settings = Settings()

    intel, run_ids = compute_intelligence(session, settings)
    assert len(run_ids) == 3
    assert intel["climber"].breakout.bucket == BUCKET_EXPLOSIVE
    assert intel["climber"].forecast.rising_soon is True
    assert intel["steady"].breakout.bucket == BUCKET_NONE
    # Latest-run scores drive the percentile (steady=70 > climber=60).
    assert intel["steady"].percentile == 100.0


def test_compute_intelligence_empty(session):
    intel, run_ids = compute_intelligence(session, Settings())
    assert intel == {}
    assert run_ids == []


def test_history_window_limits_runs(session):
    for score in (10.0, 20.0, 30.0, 40.0, 50.0):
        _add_run(session, {"x": score})
    settings = Settings()
    settings.analytics.history_window = 3
    intel, run_ids = compute_intelligence(session, settings)
    # Only the last 3 runs (30,40,50) are considered.
    assert len(run_ids) == 3
    assert intel["x"].current_score == 50.0
