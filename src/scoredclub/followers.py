"""Cross-platform follower time-series analysis (pure).

Turns an entity's ``follower_history`` (per-platform dated follower counts) into
growth stats: absolute and percentage change plus a least-squares slope per
platform, and a combined view. Complements the single-point follower band used
in the online-reach dimension with a *trajectory*.
"""

from __future__ import annotations

from dataclasses import dataclass

from scoredclub.analytics import linear_slope
from scoredclub.schemas import EntityProfile, FollowerPoint


@dataclass
class GrowthStat:
    start: int
    end: int
    delta: int
    pct: float | None  # None when the starting value is 0
    slope: float  # followers per step (least squares)
    points: int


def compute_growth(history: list[FollowerPoint]) -> GrowthStat | None:
    """Growth over a per-platform follower series (needs ≥ 2 points).

    Returns ``None`` for fewer than two points (no trajectory to measure).
    """
    # Sort chronologically. The ``p.date is None`` part of the key pushes
    # undated points to the end *without* ever comparing ``None`` to a date:
    # tuple comparison checks equality first, so two ``(True, None)`` keys are
    # equal and a date is only ever compared against another date.
    ordered = sorted(history, key=lambda p: (p.date is None, p.date))
    values = [p.followers for p in ordered]
    if len(values) < 2:
        return None
    start, end = values[0], values[-1]
    delta = end - start
    # Percentage change is undefined from a zero base, so report None there.
    pct = round(100.0 * delta / start, 1) if start else None
    # The slope is "followers per step" (least squares over the index, not the
    # calendar gap) — a direction/strength signal, not a calendar-rate forecast.
    return GrowthStat(
        start=start, end=end, delta=delta, pct=pct,
        slope=round(linear_slope([float(v) for v in values]), 2), points=len(values),
    )


def profile_follower_growth(profile: EntityProfile) -> dict[str, GrowthStat]:
    """Per-platform growth stats for an entity (platforms with ≥ 2 points)."""
    out: dict[str, GrowthStat] = {}
    for platform, history in profile.follower_history.items():
        stat = compute_growth(history)
        if stat is not None:
            out[platform] = stat
    return out


def growth_to_dict(growth: dict[str, GrowthStat]) -> dict:
    return {
        platform: {
            "start": s.start, "end": s.end, "delta": s.delta,
            "pct": s.pct, "slope": s.slope, "points": s.points,
        }
        for platform, s in growth.items()
    }
