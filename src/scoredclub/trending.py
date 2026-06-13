"""Trend analysis over the score history.

Pure functions (no DB) that turn a chronological sequence of per-run scores
into trend metrics: rank, score/rank deltas, momentum and a direction label,
plus cross-entity "movers" (top risers and fallers). The pipeline persists
the results in ``trend_snapshots`` and the API serves them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIRECTION_NEW = "new"
DIRECTION_RISING = "rising"
DIRECTION_FALLING = "falling"
DIRECTION_STABLE = "stable"


@dataclass
class RunScores:
    """Scores of all entities at a single run, oldest-to-newest order."""

    run_id: int
    scores: dict[str, float] = field(default_factory=dict)  # entity_id -> score


@dataclass
class EntityTrend:
    entity_id: str
    current_score: float
    rank: int
    score_delta: float | None
    rank_delta: int | None
    momentum: float
    direction: str
    sparkline: list[float]  # chronological scores (current run last)
    run_ids: list[int]


@dataclass
class TrendReport:
    trends: dict[str, EntityTrend]
    risers: list[EntityTrend]
    fallers: list[EntityTrend]


def _ranks(scores: dict[str, float]) -> dict[str, int]:
    """1-based rank by descending score (ties keep a stable order by id)."""
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return {entity_id: i + 1 for i, (entity_id, _) in enumerate(ordered)}


def _direction(momentum: float, has_history: bool, epsilon: float) -> str:
    if not has_history:
        return DIRECTION_NEW
    if momentum > epsilon:
        return DIRECTION_RISING
    if momentum < -epsilon:
        return DIRECTION_FALLING
    return DIRECTION_STABLE


def compute_trends(
    runs: list[RunScores],
    momentum_window: int = 4,
    stable_epsilon: float = 1.0,
    movers_limit: int = 5,
) -> TrendReport:
    """Compute trend metrics for the latest run in ``runs``.

    ``runs`` must be ordered oldest-to-newest. Momentum is the mean of the
    consecutive score deltas within the last ``momentum_window`` runs for each
    entity. Entities present only in the latest run are flagged ``new``.
    """
    if not runs:
        return TrendReport(trends={}, risers=[], fallers=[])

    latest = runs[-1]
    rank_now = _ranks(latest.scores)
    rank_prev = _ranks(runs[-2].scores) if len(runs) >= 2 else {}

    window = runs[-momentum_window:] if momentum_window > 0 else runs

    trends: dict[str, EntityTrend] = {}
    for entity_id, score in latest.scores.items():
        # Build this entity's chronological series across the window.
        series: list[float] = []
        series_runs: list[int] = []
        for run in window:
            if entity_id in run.scores:
                series.append(run.scores[entity_id])
                series_runs.append(run.run_id)

        has_history = len(series) >= 2
        deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
        momentum = round(sum(deltas) / len(deltas), 2) if deltas else 0.0
        score_delta = round(deltas[-1], 2) if deltas else None

        prev_rank = rank_prev.get(entity_id)
        rank_delta = (prev_rank - rank_now[entity_id]) if prev_rank is not None else None

        trends[entity_id] = EntityTrend(
            entity_id=entity_id,
            current_score=round(score, 2),
            rank=rank_now[entity_id],
            score_delta=score_delta,
            rank_delta=rank_delta,
            momentum=momentum,
            direction=_direction(momentum, has_history, stable_epsilon),
            sparkline=[round(s, 2) for s in series],
            run_ids=series_runs,
        )

    movers = [t for t in trends.values() if t.score_delta is not None]
    risers = sorted(
        (t for t in movers if t.score_delta > 0), key=lambda t: t.score_delta, reverse=True
    )[:movers_limit]
    fallers = sorted(
        (t for t in movers if t.score_delta < 0), key=lambda t: t.score_delta
    )[:movers_limit]

    return TrendReport(trends=trends, risers=risers, fallers=fallers)
