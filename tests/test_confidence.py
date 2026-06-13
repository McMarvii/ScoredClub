from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scoredclub.config import ConfidenceConfig, ScoringConfig
from scoredclub.scoring import confidence as conf
from scoredclub.scoring.engine import score_entity
from tests.conftest import TODAY, make_minimal_profile, make_top_profile

CFG = ConfidenceConfig()
DIMS = [
    "A_event_activity", "B_online_reach", "C_press_presence", "D_community_resonance",
    "E_scene_networking", "F_continuity", "G_safety_inclusivity",
]


class TestPresence:
    def test_full_profile_high_presence(self):
        presence = conf.dimension_presence(make_top_profile())
        assert set(presence) == set(DIMS)
        assert presence["B_online_reach"] == 100.0
        assert presence["G_safety_inclusivity"] == 100.0

    def test_minimal_profile_mostly_absent(self):
        presence = conf.dimension_presence(make_minimal_profile())
        assert presence["B_online_reach"] == 0.0
        assert presence["C_press_presence"] == 0.0
        # active_since is set on the minimal profile -> F present.
        assert presence["F_continuity"] == 100.0


class TestFreshness:
    def test_recent_is_full(self):
        p = make_top_profile()
        p.last_verification = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc)
        assert conf.freshness(p, CFG, TODAY) == 100.0

    def test_missing_verification(self):
        p = make_minimal_profile()
        assert conf.freshness(p, CFG, TODAY) == CFG.unknown_verification_confidence

    def test_old_decays_to_floor(self):
        p = make_top_profile()
        old = TODAY - timedelta(days=CFG.freshness_full_days * 4)
        p.last_verification = datetime.combine(old, datetime.min.time(), tzinfo=timezone.utc)
        assert conf.freshness(p, CFG, TODAY) == CFG.freshness_floor


class TestOverall:
    def test_blend(self):
        c = conf.overall_confidence(80.0, 40.0, CFG)
        assert c == round(80.0 * 0.7 + 40.0 * 0.3, 1)


class TestEngineIntegration:
    def test_full_profile_high_confidence(self):
        b = score_entity(make_top_profile(), ScoringConfig(), today=TODAY)
        assert b.confidence >= 90
        assert b.low_confidence is False
        assert set(b.dimension_confidence) == set(DIMS)

    def test_missing_dimension_not_counted_as_low_relevance(self):
        # Strip all online-reach data (the "Berghain looked low" case).
        p = make_top_profile()
        for plat in p.online.platforms().values():
            plat.url = None
            plat.handle = None
            plat.followers = None
        p.events.ra_followers = None
        b = score_entity(p, ScoringConfig(), today=TODAY)
        assert b.dimension_confidence["B_online_reach"] == 0.0
        # Raw total is dragged down by B=0, but the confidence-adjusted score
        # (over known dimensions) is not.
        assert b.confidence_adjusted_total > b.total

    def test_thin_profile_flagged_low_confidence(self):
        b = score_entity(make_minimal_profile(), ScoringConfig(), today=TODAY)
        assert b.low_confidence is True
        assert b.confidence < 50

    def test_total_and_tier_unchanged_by_confidence(self):
        # Confidence is additive — the headline numbers must be identical.
        b = score_entity(make_top_profile(), ScoringConfig(), today=TODAY)
        assert b.total == 100.0
        assert b.tier == "TOP-TIER"
        assert b.points["A_event_activity"] == 20.0

    def test_no_data_adjusted_falls_back_to_total(self):
        p = make_minimal_profile(active_since=None, status="unknown")
        b = score_entity(p, ScoringConfig(), today=TODAY)
        # With essentially no present dimensions, adjusted == total (no crash).
        assert b.confidence_adjusted_total == b.total
