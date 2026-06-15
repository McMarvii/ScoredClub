from __future__ import annotations

import datetime as dt

from scoredclub.authenticity import (
    VERDICT_AUTHENTIC,
    VERDICT_INCONCLUSIVE,
    VERDICT_QUESTIONABLE,
    VERDICT_SUSPICIOUS,
    assess,
    capture_follower_history,
    detect_drops,
    detect_spikes,
    evaluate_history,
    footprint,
    to_dict,
)
from scoredclub.schemas import (
    CommunityInfo,
    EntityProfile,
    EntityType,
    EventsInfo,
    FollowerPoint,
    NetworkingInfo,
    OnlinePresence,
    PressInfo,
    SocialPresence,
)
from tests.conftest import make_top_profile


def _fh(*counts, platform="instagram", start=dt.date(2026, 1, 1)):
    return {platform: [FollowerPoint(date=start + dt.timedelta(days=30 * i), followers=c)
                       for i, c in enumerate(counts)]}


# --- spike detection --------------------------------------------------------

def test_no_spike_on_steady_growth():
    assert detect_spikes(_fh(10000, 10500, 11000, 11500)) == []


def test_spike_detected_on_sudden_jump():
    spikes = detect_spikes(_fh(10000, 10500, 60000, 60500))
    assert len(spikes) == 1
    assert spikes[0]["platform"] == "instagram"
    assert spikes[0]["delta"] == 49500


def test_spike_needs_three_points():
    assert detect_spikes(_fh(1000, 80000)) == []  # only 2 points -> no baseline


def test_spike_ignores_small_absolute_jumps():
    # A relatively large *ratio* but tiny absolute jump is not a spike.
    assert detect_spikes(_fh(100, 110, 400, 410)) == []


# --- footprint --------------------------------------------------------------

def test_footprint_high_for_real_entity():
    assert footprint(make_top_profile()) > 10  # plenty of events/press/bookings


# --- verdicts ---------------------------------------------------------------

def test_inconclusive_without_follower_data():
    result = assess(EntityProfile(name="Nobody", type=EntityType.artist))
    assert result.verdict == VERDICT_INCONCLUSIVE
    assert result.score is None


def test_authentic_for_well_rounded_entity():
    result = assess(make_top_profile())
    assert result.verdict == VERDICT_AUTHENTIC
    assert result.score == 100.0
    assert result.flags == []


def test_reach_without_footprint_is_questionable():
    profile = EntityProfile(
        name="Mystery DJ", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=80000)),
        # no events, press, community, bookings -> footprint ~0
    )
    result = assess(profile)
    assert result.verdict == VERDICT_QUESTIONABLE
    assert any("Hohe Reichweite" in f for f in result.flags)


def test_spike_plus_reach_is_suspicious():
    profile = EntityProfile(
        name="Bought DJ", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=70000)),
        follower_history=_fh(5000, 5200, 70000, 70100),
    )
    result = assess(profile)
    assert result.verdict == VERDICT_SUSPICIOUS
    assert len(result.flags) >= 2


def test_dormant_large_account_flagged():
    profile = EntityProfile(
        name="Ghost Club", type=EntityType.club,
        # enough footprint that the reach-flag does NOT fire, isolating dormancy
        events=EventsInfo(events_last_6_months=6),
        press=PressInfo(major_features=["RA Feature"]),
        networking=NetworkingInfo(booked_djs=["A", "B", "C"]),
        online=OnlinePresence(instagram=SocialPresence(followers=40000, posts_per_month=0.0)),
    )
    result = assess(profile)
    assert any("kaum Aktivität" in f for f in result.flags)
    assert result.verdict == VERDICT_QUESTIONABLE


def test_does_not_touch_scoring():
    # assess() must not import or mutate the scoring engine / breakdown.
    from scoredclub.scoring import score_entity
    from scoredclub.config import ScoringConfig

    profile = EntityProfile(
        name="X", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=80000)),
    )
    before = score_entity(profile, ScoringConfig()).total
    assess(profile)
    after = score_entity(profile, ScoringConfig()).total
    assert before == after


def test_to_dict_shape():
    d = to_dict(assess(make_top_profile()))
    assert d["verdict"] == "authentic"
    assert "signals" in d and d["signals"]["checked"] is True


# --- historical evaluation: drops + history summary -------------------------

def test_detect_drops_on_sudden_loss():
    drops = detect_drops(_fh(60000, 60500, 11000, 11500))
    assert len(drops) == 1
    assert drops[0]["delta"] == -49500


def test_no_drop_on_steady_series():
    assert detect_drops(_fh(10000, 10500, 11000, 11500)) == []


def test_drop_makes_verdict_questionable():
    profile = EntityProfile(
        name="Purged DJ", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=11500)),
        follower_history=_fh(60000, 60500, 11000, 11500),
    )
    result = assess(profile)
    assert any("Follower-Verlust" in f for f in result.flags)
    assert result.verdict == VERDICT_QUESTIONABLE


def test_evaluate_history_summary():
    summary = evaluate_history(_fh(1000, 1500, 2000))
    ig = summary["instagram"]
    assert ig["points"] == 3
    assert ig["start"] == 1000 and ig["end"] == 2000
    assert ig["growth_pct"] == 100.0
    assert "volatility" in ig and "spikes" in ig and "drops" in ig


def test_assess_spikes_drops_match_standalone_detectors():
    # The single-pass optimisation in assess() must produce the same spikes/drops
    # as the standalone detect_spikes/detect_drops helpers.
    profile = EntityProfile(
        name="X", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=20000)),
        follower_history={
            "instagram": _fh(5000, 5200, 70000, 70100)["instagram"],
            "soundcloud": _fh(60000, 60500, 11000, 11500, platform="soundcloud")["soundcloud"],
        },
    )
    sig = assess(profile).signals
    assert sig["spikes"] == detect_spikes(profile.follower_history)
    assert sig["drops"] == detect_drops(profile.follower_history)


def test_assess_signals_include_history():
    profile = EntityProfile(
        name="X", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=2000)),
        follower_history=_fh(1000, 1500, 2000),
    )
    sig = assess(profile).signals
    assert "history" in sig and "instagram" in sig["history"]


# --- history capture (builds the historical record over runs) ---------------

def test_capture_appends_current_followers():
    profile = EntityProfile(
        name="X", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=5000)),
        events=EventsInfo(ra_followers=3000),
    )
    changed = capture_follower_history(profile, today=dt.date(2026, 6, 14))
    assert changed is True
    assert profile.follower_history["instagram"][-1].followers == 5000
    assert profile.follower_history["resident_advisor"][-1].followers == 3000


def test_capture_skips_unchanged_value():
    profile = EntityProfile(
        name="X",
        online=OnlinePresence(instagram=SocialPresence(followers=5000)),
        follower_history=_fh(5000, platform="instagram", start=dt.date(2026, 1, 1)),
    )
    # follower_history last value is already 5000 -> no duplicate.
    assert capture_follower_history(profile, today=dt.date(2026, 6, 14)) is False


def test_pipeline_capture_opt_in(session, settings):
    from scoredclub.db import repo
    from scoredclub.pipeline.run import execute_run

    repo.upsert_profile(session, EntityProfile(
        entity_id="berghain", name="Berghain", type=EntityType.club,
        online=OnlinePresence(instagram=SocialPresence(followers=120000)),
    ))
    session.commit()

    # Off by default -> no history captured.
    execute_run(session, settings, skip_collectors=True, run_date=dt.date(2026, 6, 14))
    assert repo.profile_from_row(repo.get_entity(session, "berghain")).follower_history == {}

    # Enabled -> the run snapshots followers into the history.
    settings.authenticity.capture_history = True
    execute_run(session, settings, skip_collectors=True, run_date=dt.date(2026, 6, 15))
    history = repo.profile_from_row(repo.get_entity(session, "berghain")).follower_history
    assert history["instagram"][-1].followers == 120000


def test_capture_accumulates_over_runs():
    profile = EntityProfile(name="X", online=OnlinePresence(instagram=SocialPresence(followers=1000)))
    capture_follower_history(profile, today=dt.date(2026, 1, 1))
    profile.online.instagram.followers = 1200
    capture_follower_history(profile, today=dt.date(2026, 2, 1))
    profile.online.instagram.followers = 9000
    capture_follower_history(profile, today=dt.date(2026, 3, 1))
    series = profile.follower_history["instagram"]
    assert [p.followers for p in series] == [1000, 1200, 9000]
    # Now there is enough history to flag the jump.
    assert detect_spikes(profile.follower_history)
