from __future__ import annotations

from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import ScoreBreakdown, utcnow
from scoredclub.pipeline.run import compute_run_trends
from scoredclub.trending import RunScores, compute_trends
from tests.conftest import make_minimal_profile, make_top_profile


class TestComputeTrends:
    def test_single_run_all_new(self):
        runs = [RunScores(1, {"a": 80.0, "b": 40.0})]
        report = compute_trends(runs)
        assert report.trends["a"].rank == 1
        assert report.trends["b"].rank == 2
        assert report.trends["a"].direction == "new"
        assert report.trends["a"].score_delta is None
        assert report.trends["a"].sparkline == [80.0]
        assert report.risers == [] and report.fallers == []

    def test_two_runs_directions(self):
        runs = [
            RunScores(1, {"a": 70.0, "b": 40.0, "c": 50.0}),
            RunScores(2, {"a": 80.0, "b": 35.0, "c": 50.0}),
        ]
        report = compute_trends(runs, stable_epsilon=1.0)
        assert report.trends["a"].direction == "rising"
        assert report.trends["a"].score_delta == 10.0
        assert report.trends["b"].direction == "falling"
        assert report.trends["b"].score_delta == -5.0
        assert report.trends["c"].direction == "stable"
        assert report.trends["c"].score_delta == 0.0

    def test_rank_delta_on_swap(self):
        runs = [
            RunScores(1, {"x": 60.0, "y": 50.0}),
            RunScores(2, {"x": 40.0, "y": 55.0}),
        ]
        report = compute_trends(runs)
        # y overtakes x.
        assert report.trends["y"].rank == 1
        assert report.trends["y"].rank_delta == 1  # moved up one place
        assert report.trends["x"].rank == 2
        assert report.trends["x"].rank_delta == -1

    def test_movers_sorted(self):
        runs = [
            RunScores(1, {"a": 50.0, "b": 50.0, "c": 50.0, "d": 50.0}),
            RunScores(2, {"a": 70.0, "b": 60.0, "c": 30.0, "d": 45.0}),
        ]
        report = compute_trends(runs, movers_limit=2)
        assert [t.entity_id for t in report.risers] == ["a", "b"]  # +20, +10
        assert [t.entity_id for t in report.fallers] == ["c", "d"]  # -20, -5

    def test_new_entity_flagged(self):
        runs = [RunScores(1, {"a": 50.0}), RunScores(2, {"a": 55.0, "b": 30.0})]
        report = compute_trends(runs)
        assert report.trends["b"].direction == "new"
        assert report.trends["b"].score_delta is None
        assert report.trends["a"].direction == "rising"

    def test_momentum_window_truncates(self):
        # Entity climbs steadily; with window=2 only the last delta counts.
        runs = [
            RunScores(1, {"a": 20.0}),
            RunScores(2, {"a": 40.0}),
            RunScores(3, {"a": 41.0}),
        ]
        report = compute_trends(runs, momentum_window=2, stable_epsilon=1.0)
        # window = last 2 runs -> series [40, 41] -> momentum 1.0 -> not > epsilon
        assert report.trends["a"].sparkline == [40.0, 41.0]
        assert report.trends["a"].momentum == 1.0
        assert report.trends["a"].direction == "stable"

    def test_empty(self):
        report = compute_trends([])
        assert report.trends == {} and report.risers == [] and report.fallers == []


class TestPipelineTrends:
    def _run(self, session, scores: dict[str, float]):
        run = repo.start_run(session)
        for entity_id, total in scores.items():
            entity = repo.get_entity(session, entity_id)
            repo.save_score(session, run, entity, ScoreBreakdown(total=total, tier="MID-TIER"))
        repo.finish_run(session, run, len(scores), 0, None, None, utcnow())
        return run

    def test_persists_and_directions(self, session):
        a = make_top_profile()  # entity_id "testclub"
        b = make_minimal_profile(name="Zweiter Club")
        repo.upsert_profile(session, a)
        repo.upsert_profile(session, b)
        settings = Settings()

        self._run(session, {"testclub": 80.0, "zweiter-club": 40.0})
        compute_run_trends(session, settings)

        run2 = self._run(session, {"testclub": 85.0, "zweiter-club": 28.0})
        report = compute_run_trends(session, settings)

        # Persisted for the latest run.
        persisted = repo.trends_for_run(session, run2.id)
        assert persisted["testclub"].direction == "rising"
        assert persisted["testclub"].score_delta == 5.0
        assert persisted["zweiter-club"].direction == "falling"
        assert persisted["zweiter-club"].score_delta == -12.0

        # Movers from the report.
        assert [t.entity_id for t in report.risers] == ["testclub"]
        assert [t.entity_id for t in report.fallers] == ["zweiter-club"]

        # History accumulates one trend snapshot per run.
        assert len(repo.trend_history(session, "testclub")) == 2
