"""Advanced trend intelligence over the score history (pure functions).

Builds on the raw per-run score series (the same data trending uses) to derive
three signals the basic trending module does not:

* **Breakout / anomaly detection.** Classifies an entity's recent momentum
  against *its own* historical volatility — a dynamic baseline rather than a
  fixed score-delta threshold. A steady or noisy climb is judged relative to
  how much the entity normally moves run-to-run, so the same +5 means different
  things for a stable entity and a jumpy one.
* **Career-phase classification.** Maps an entity's percentile rank within the
  current cohort to a phase label (developing → emerging → established → elite),
  a coarser, more stable view than the score tiers.
* **Short-term forecast.** A least-squares slope projection of the next score
  with a "rising soon" flag.

No database, no I/O — callers feed in a chronological score series. The CLI and
API compute these on demand from the stored history.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# Breakout buckets, weakest to strongest (plus two non-classifications).
BUCKET_NONE = "none"
BUCKET_GROWTH = "growth"
BUCKET_STRONG = "strong"
BUCKET_EXPLOSIVE = "explosive"
BUCKET_INSUFFICIENT = "insufficient_data"

# Career phases, weakest to strongest.
PHASE_DEVELOPING = "developing"
PHASE_EMERGING = "emerging"
PHASE_ESTABLISHED = "established"
PHASE_ELITE = "elite"


@dataclass
class Breakout:
    bucket: str
    slope: float  # least-squares score change per run over the window
    z_score: float  # slope normalized by the entity's own volatility


@dataclass
class Forecast:
    projected_score: float  # clamped 0..100
    slope: float
    rising_soon: bool


@dataclass
class EntityIntelligence:
    entity_id: str
    current_score: float
    percentile: float  # 0..100 within the cohort
    career_phase: str
    breakout: Breakout
    forecast: Forecast


def linear_slope(series: list[float]) -> float:
    """Least-squares slope (score change per step) of a series.

    Returns 0.0 for fewer than two points. The x-axis is the index 0..n-1, so
    the slope is "points per run".
    """
    n = len(series)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(series) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom == 0:
        return 0.0
    num = sum((i - mean_x) * (series[i] - mean_y) for i in range(n))
    return num / denom


def detect_breakout(
    series: list[float],
    *,
    min_points: int = 3,
    baseline_floor: float = 1.0,
    growth_z: float = 1.0,
    strong_z: float = 2.0,
    explosive_z: float = 3.0,
) -> Breakout:
    """Classify upward momentum against the entity's own run-to-run volatility.

    The baseline is the standard deviation of the consecutive deltas (how much
    the entity usually moves), floored at ``baseline_floor`` so a perfectly
    steady climb still registers. ``z = slope / baseline``; only positive slopes
    can break out.
    """
    if len(series) < min_points:
        return Breakout(BUCKET_INSUFFICIENT, 0.0, 0.0)
    deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
    volatility = statistics.pstdev(deltas) if len(deltas) >= 2 else abs(deltas[0])
    baseline = max(volatility, baseline_floor)
    slope = linear_slope(series)
    z = slope / baseline if baseline else 0.0
    if slope <= 0:
        bucket = BUCKET_NONE
    elif z >= explosive_z:
        bucket = BUCKET_EXPLOSIVE
    elif z >= strong_z:
        bucket = BUCKET_STRONG
    elif z >= growth_z:
        bucket = BUCKET_GROWTH
    else:
        bucket = BUCKET_NONE
    return Breakout(bucket, round(slope, 2), round(z, 2))


def percentiles(scores: dict[str, float]) -> dict[str, float]:
    """Percentile rank (0..100) of each entity within the cohort.

    Uses the share of entities scoring strictly lower, so the lowest scorer is
    near 0 and the top scorer near 100. Ties share the same percentile.
    """
    if not scores:
        return {}
    if len(scores) == 1:
        return {next(iter(scores)): 100.0}
    n = len(scores)
    values = list(scores.values())
    result: dict[str, float] = {}
    for entity_id, score in scores.items():
        below = sum(1 for v in values if v < score)
        result[entity_id] = round(100.0 * below / (n - 1), 1)
    return result


def career_phase(
    percentile: float,
    *,
    elite: float = 90.0,
    established: float = 70.0,
    emerging: float = 40.0,
) -> str:
    if percentile >= elite:
        return PHASE_ELITE
    if percentile >= established:
        return PHASE_ESTABLISHED
    if percentile >= emerging:
        return PHASE_EMERGING
    return PHASE_DEVELOPING


def forecast(series: list[float], *, epsilon: float = 0.5) -> Forecast:
    """Project the next score from the least-squares slope (clamped 0..100)."""
    if not series:
        return Forecast(0.0, 0.0, False)
    slope = linear_slope(series)
    projected = max(0.0, min(100.0, series[-1] + slope))
    return Forecast(round(projected, 1), round(slope, 2), slope > epsilon)


def analyze_series(
    entity_id: str,
    series: list[float],
    percentile: float,
    *,
    baseline_floor: float = 1.0,
    growth_z: float = 1.0,
    strong_z: float = 2.0,
    explosive_z: float = 3.0,
    forecast_epsilon: float = 0.5,
    elite_percentile: float = 90.0,
    established_percentile: float = 70.0,
    emerging_percentile: float = 40.0,
) -> EntityIntelligence:
    return EntityIntelligence(
        entity_id=entity_id,
        current_score=round(series[-1], 2) if series else 0.0,
        percentile=percentile,
        career_phase=career_phase(
            percentile,
            elite=elite_percentile,
            established=established_percentile,
            emerging=emerging_percentile,
        ),
        breakout=detect_breakout(
            series,
            baseline_floor=baseline_floor,
            growth_z=growth_z,
            strong_z=strong_z,
            explosive_z=explosive_z,
        ),
        forecast=forecast(series, epsilon=forecast_epsilon),
    )


def series_from_runs(ordered_runs: list[dict[str, float]]) -> dict[str, list[float]]:
    """Build per-entity chronological score series from oldest→newest run maps.

    Each element of ``ordered_runs`` is a ``{entity_id: score}`` map for one run.
    Entities absent from a run are simply skipped for that run (their series
    stays contiguous), matching the trending module's behaviour.
    """
    out: dict[str, list[float]] = {}
    for scores in ordered_runs:
        for entity_id, score in scores.items():
            out.setdefault(entity_id, []).append(score)
    return out


def analyze_cohort(
    series_by_entity: dict[str, list[float]],
    current_scores: dict[str, float],
    **kwargs,
) -> dict[str, EntityIntelligence]:
    """Analyze every entity. ``series_by_entity`` maps id -> chronological scores."""
    pct = percentiles(current_scores)
    out: dict[str, EntityIntelligence] = {}
    for entity_id, series in series_by_entity.items():
        out[entity_id] = analyze_series(
            entity_id, series, pct.get(entity_id, 0.0), **kwargs
        )
    return out


def compute_intelligence(session, settings) -> tuple[dict[str, EntityIntelligence], list[int]]:
    """Load the recent score history and compute per-entity intelligence.

    Thin DB orchestrator shared by the CLI and API (lazy ``repo`` import keeps
    this module otherwise pure/DB-free). Returns the analysis plus the run ids
    considered, oldest→newest.
    """
    from scoredclub.db import repo

    cfg = settings.analytics
    limit = cfg.history_window if cfg.history_window > 0 else 10_000
    runs = repo.recent_runs(session, limit)
    run_ids = [r.id for r in runs]
    series_map = repo.run_score_series(session, run_ids)
    ordered = [series_map.get(rid, {}) for rid in run_ids]
    intel = analyze_cohort(
        series_from_runs(ordered),
        ordered[-1] if ordered else {},
        baseline_floor=cfg.breakout_baseline_floor,
        growth_z=cfg.growth_z,
        strong_z=cfg.strong_z,
        explosive_z=cfg.explosive_z,
        forecast_epsilon=cfg.forecast_epsilon,
        elite_percentile=cfg.elite_percentile,
        established_percentile=cfg.established_percentile,
        emerging_percentile=cfg.emerging_percentile,
    )
    return intel, run_ids
