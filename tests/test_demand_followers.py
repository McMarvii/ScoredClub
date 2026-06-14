from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone

from scoredclub.config import ScoringConfig
from scoredclub.followers import compute_growth, growth_to_dict, profile_follower_growth
from scoredclub.normalize import merge_profiles
from scoredclub.reports.render import ScoredEntity, render_entities_json
from scoredclub.config import Settings
from scoredclub.schemas import (
    DemandInfo,
    EntityProfile,
    FollowerPoint,
    ScoreBreakdown,
)
from scoredclub.scoring import score_entity
from scoredclub.scoring.rubric import bonus_items
from tests.conftest import make_top_profile


# --- Demand signals ---------------------------------------------------------

def test_demand_coerces_yes_no():
    d = DemandInfo(sold_out="yes", waitlist="no", going_count=800)
    assert d.sold_out is True
    assert d.waitlist is False


def test_demand_adds_bonus_item():
    base = make_top_profile(demand=None)
    assert not any("Nachfrage" in b for b in bonus_items(base))
    sold = make_top_profile(demand=DemandInfo(sold_out=True))
    assert any("Nachfrage" in b for b in bonus_items(sold))
    going = make_top_profile(demand=DemandInfo(going_count=600))
    assert any("Nachfrage" in b for b in bonus_items(going))
    low = make_top_profile(demand=DemandInfo(going_count=100))
    assert not any("Nachfrage" in b for b in bonus_items(low))


def test_demand_none_does_not_change_score():
    profile = make_top_profile(demand=None)
    breakdown = score_entity(profile, ScoringConfig())
    assert not any("Nachfrage" in b for b in breakdown.bonus_items)


# --- Follower time-series ---------------------------------------------------

def test_compute_growth():
    assert compute_growth([FollowerPoint(followers=100)]) is None  # needs >=2
    stat = compute_growth([
        FollowerPoint(date=dt.date(2026, 1, 1), followers=1000),
        FollowerPoint(date=dt.date(2026, 3, 1), followers=1500),
        FollowerPoint(date=dt.date(2026, 6, 1), followers=2000),
    ])
    assert stat.start == 1000 and stat.end == 2000
    assert stat.delta == 1000
    assert stat.pct == 100.0
    assert stat.slope == 500.0


def test_compute_growth_from_zero_start():
    stat = compute_growth([FollowerPoint(followers=0), FollowerPoint(followers=50)])
    assert stat.pct is None  # undefined from a zero base
    assert stat.delta == 50


def test_profile_follower_growth_per_platform():
    profile = EntityProfile(
        name="X",
        follower_history={
            "instagram": [FollowerPoint(date=dt.date(2026, 1, 1), followers=1000),
                          FollowerPoint(date=dt.date(2026, 6, 1), followers=1400)],
            "soundcloud": [FollowerPoint(followers=500)],  # single point -> skipped
        },
    )
    growth = profile_follower_growth(profile)
    assert set(growth) == {"instagram"}
    assert growth["instagram"].delta == 400
    assert "instagram" in growth_to_dict(growth)


# --- Merge + render omission ------------------------------------------------

def test_merge_demand_and_follower_history():
    existing = EntityProfile(
        name="X",
        follower_history={"instagram": [FollowerPoint(date=dt.date(2026, 1, 1), followers=1000)]},
        last_verification=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    incoming = EntityProfile(
        name="X",
        demand=DemandInfo(sold_out=True),
        follower_history={"instagram": [FollowerPoint(date=dt.date(2026, 6, 1), followers=1500)]},
        last_verification=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    merged = merge_profiles(existing, incoming)
    assert merged.demand.sold_out is True
    # New dated point appended to the same platform series.
    assert len(merged.follower_history["instagram"]) == 2


def test_render_omits_empty_demand_and_history():
    scored = [ScoredEntity(profile=EntityProfile(name="X"), breakdown=ScoreBreakdown(total=10.0, tier="EMERGING"))]
    entity = render_entities_json(scored, dt.date(2026, 6, 14), Settings())["entities"][0]
    assert "demand" not in entity
    assert "follower_history" not in entity


def test_render_includes_demand_when_present():
    profile = EntityProfile(name="X", demand=DemandInfo(sold_out=True))
    scored = [ScoredEntity(profile=profile, breakdown=ScoreBreakdown(total=10.0, tier="EMERGING"))]
    entity = render_entities_json(scored, dt.date(2026, 6, 14), Settings())["entities"][0]
    assert entity["demand"]["sold_out"] is True
