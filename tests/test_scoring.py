from __future__ import annotations

from datetime import date, timedelta

import pytest

from scoredclub.config import ScoringConfig, ScoringWeights
from scoredclub.schemas import (
    EntityProfile,
    EntityStatus,
    EventsInfo,
    Incident,
    SentimentHint,
)
from scoredclub.scoring import rubric
from scoredclub.scoring.engine import (
    TIER_EMERGING,
    TIER_INACTIVE,
    TIER_MID,
    TIER_TOP,
    score_entity,
)
from tests.conftest import TODAY, make_minimal_profile, make_top_profile

CONFIG = ScoringConfig()


class TestEventActivity:
    @pytest.mark.parametrize(
        ("events_3m", "expected"),
        [(12, 100.0), (14, 100.0), (6, 75.0), (3, 50.0), (1, 30.0)],
    )
    def test_bands(self, events_3m, expected):
        p = make_top_profile(events=EventsInfo(events_last_3_months=events_3m))
        assert rubric.event_activity(p, TODAY) == expected

    def test_only_six_month_activity(self):
        p = make_top_profile(
            events=EventsInfo(events_last_3_months=0, events_last_6_months=4)
        )
        assert rubric.event_activity(p, TODAY) == 15.0

    def test_no_events(self):
        p = make_minimal_profile()
        assert rubric.event_activity(p, TODAY) == 0.0

    def test_stale_data_guard(self):
        p = make_top_profile(
            events=EventsInfo(events_last_3_months=12),
            last_event_date=TODAY - timedelta(days=120),
        )
        assert rubric.event_activity(p, TODAY) == 80.0


class TestOnlineReach:
    def test_max_profile_hits_100(self):
        assert rubric.online_reach(make_top_profile()) == 100.0

    def test_unknown_followers_score_zero_band(self):
        p = make_minimal_profile()
        assert rubric.online_reach(p) == 0.0

    @pytest.mark.parametrize(
        ("followers", "band"),
        [(100_000, 100.0), (50_000, 85.0), (20_000, 70.0), (10_000, 55.0),
         (5_000, 40.0), (1_000, 25.0), (500, 10.0)],
    )
    def test_follower_bands(self, followers, band):
        p = make_minimal_profile()
        p.online.instagram.followers = followers
        p.online.instagram.handle = "x"
        # one active platform => breadth 1/6
        expected = 0.7 * band + 0.3 * (1 / 6 * 100)
        assert rubric.online_reach(p) == pytest.approx(expected)


class TestPressCommunityNetworking:
    def test_press_caps_at_100(self):
        assert rubric.press(make_top_profile()) == 100.0

    def test_press_single_local_mention(self):
        p = make_minimal_profile()
        p.press.local_press_mentions = ["tip Berlin"]
        assert rubric.press(p) == 5.0

    def test_community_sentiment_multiplier(self):
        p = make_top_profile()
        p.community.community_sentiment_hint = SentimentHint.negative
        positive = make_top_profile()
        assert rubric.community(p) < rubric.community(positive)

    def test_networking_caps(self):
        assert rubric.networking(make_top_profile()) == 100.0
        assert rubric.networking(make_minimal_profile()) == 0.0


class TestContinuity:
    @pytest.mark.parametrize(
        ("year", "expected"),
        [("2004", 100.0), ("2015", 80.0), ("2020", 60.0), ("2024", 40.0),
         ("2025", 25.0), ("2026", 10.0)],
    )
    def test_years(self, year, expected):
        p = make_minimal_profile(active_since=year, status=EntityStatus.active)
        assert rubric.continuity(p, TODAY) == expected

    def test_unknown_year(self):
        p = make_minimal_profile(active_since=None)
        assert rubric.continuity(p, TODAY) == 10.0

    def test_closed_is_zero(self):
        p = make_minimal_profile(active_since="2004", status=EntityStatus.closed)
        assert rubric.continuity(p, TODAY) == 0.0


class TestSafety:
    def test_full(self):
        assert rubric.safety(make_top_profile()) == 100.0

    def test_unknown_flags_score_zero(self):
        assert rubric.safety(make_minimal_profile()) == 0.0


class TestEngine:
    def test_weights_applied(self):
        """Subscore 100 in A must yield exactly 20 points (weight 0.20)."""
        breakdown = score_entity(make_top_profile(), CONFIG, today=TODAY)
        assert breakdown.subscores["A_event_activity"] == 100.0
        assert breakdown.points["A_event_activity"] == 20.0

    def test_max_profile_clamps_at_100(self):
        breakdown = score_entity(make_top_profile(), CONFIG, today=TODAY)
        assert breakdown.bonus == 15.0  # all three bonus criteria, capped
        assert breakdown.total == 100.0
        assert breakdown.tier == TIER_TOP

    def test_bonus_cap(self):
        breakdown = score_entity(make_top_profile(), CONFIG, today=TODAY)
        assert len(breakdown.bonus_items) == 3
        assert breakdown.bonus == 15.0

    def test_malus_per_incident(self):
        p = make_top_profile(
            incidents=[Incident(description="Übergriff dokumentiert")]
        )
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.malus == 5.0

    def test_malus_cap(self):
        p = make_top_profile(
            incidents=[Incident(description=f"Vorfall {i}") for i in range(5)]
        )
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.malus == 15.0

    def test_clamp_at_zero(self):
        p = make_minimal_profile(
            incidents=[Incident(description=f"Vorfall {i}") for i in range(5)]
        )
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.total >= 0.0

    def test_custom_weights(self):
        config = ScoringConfig(
            weights=ScoringWeights(
                event_activity=0.5, online_reach=0.5, press=0.0,
                community=0.0, networking=0.0, continuity=0.0, safety=0.0,
            )
        )
        breakdown = score_entity(make_top_profile(), config, today=TODAY)
        assert breakdown.points["A_event_activity"] == 50.0
        assert breakdown.points["C_press_presence"] == 0.0


class TestTiers:
    def test_inactive_override_by_last_event(self):
        """Score may be high, but >180 days without events forces INAKTIV."""
        p = make_top_profile(last_event_date=TODAY - timedelta(days=200))
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.tier == TIER_INACTIVE

    def test_inactive_status_override(self):
        p = make_top_profile(status=EntityStatus.closed)
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.tier == TIER_INACTIVE

    def test_mid_tier(self):
        p = make_minimal_profile(status=EntityStatus.active, active_since="2004")
        p.events.events_last_3_months = 12
        p.last_event_date = TODAY
        p.online.instagram.followers = 60_000
        p.online.instagram.handle = "x"
        p.policy_safety.queer_friendly = True
        p.policy_safety.safer_spaces_communicated = True
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert TIER_MID == breakdown.tier
        assert 50 <= breakdown.total < 75

    def test_emerging_tier(self):
        p = make_minimal_profile(status=EntityStatus.active, active_since="2024")
        p.events.events_last_3_months = 12
        p.last_event_date = TODAY
        p.online.instagram.followers = 6_000
        p.online.instagram.handle = "x"
        breakdown = score_entity(p, CONFIG, today=TODAY)
        assert breakdown.tier == TIER_EMERGING
