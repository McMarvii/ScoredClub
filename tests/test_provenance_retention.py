from __future__ import annotations

import datetime as dt
import json
from datetime import datetime, timezone

from scoredclub.normalize import merge_profiles
from scoredclub.reports.render import ScoredEntity, render_entities_json
from scoredclub.config import Settings
from scoredclub.retention import apply_retention
from scoredclub.schemas import (
    CommunityInfo,
    EntityProfile,
    FieldProvenance,
    ScoreBreakdown,
)


# --- Provenance schema + merge ---------------------------------------------

def test_provenance_defaults_empty():
    profile = EntityProfile(name="X")
    assert profile.provenance == {}


def test_provenance_validates():
    profile = EntityProfile(
        name="X",
        provenance={
            "events.ra_followers": {"source": "https://ra.co/clubs/1", "confidence": 80},
        },
    )
    fp = profile.provenance["events.ra_followers"]
    assert isinstance(fp, FieldProvenance)
    assert fp.source == "https://ra.co/clubs/1"
    assert fp.confidence == 80


def test_merge_unions_provenance_newer_wins():
    older = EntityProfile(
        name="X",
        provenance={"events.ra_followers": {"source": "old", "confidence": 50}},
        last_verification=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = EntityProfile(
        name="X",
        provenance={
            "events.ra_followers": {"source": "new", "confidence": 90},
            "press.major_features": {"source": "mixmag"},
        },
        last_verification=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    merged = merge_profiles(older, newer)
    assert merged.provenance["events.ra_followers"].source == "new"  # newer wins
    assert "press.major_features" in merged.provenance  # new key added


def test_merge_keeps_existing_when_incoming_older():
    newer_existing = EntityProfile(
        name="X",
        provenance={"a.b": {"source": "keep"}},
        last_verification=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    older_incoming = EntityProfile(
        name="X",
        provenance={"a.b": {"source": "stale"}, "c.d": {"source": "fill"}},
        last_verification=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    merged = merge_profiles(newer_existing, older_incoming)
    assert merged.provenance["a.b"].source == "keep"  # not overwritten by older
    assert merged.provenance["c.d"].source == "fill"  # gap still filled


def test_render_omits_empty_provenance():
    scored = [ScoredEntity(profile=EntityProfile(name="X"), breakdown=ScoreBreakdown(total=10.0, tier="EMERGING"))]
    payload = render_entities_json(scored, dt.date(2026, 6, 14), Settings())
    assert "provenance" not in payload["entities"][0]


def test_render_includes_nonempty_provenance():
    profile = EntityProfile(name="X", provenance={"a.b": {"source": "s"}})
    scored = [ScoredEntity(profile=profile, breakdown=ScoreBreakdown(total=10.0, tier="EMERGING"))]
    payload = render_entities_json(scored, dt.date(2026, 6, 14), Settings())
    assert payload["entities"][0]["provenance"]["a.b"]["source"] == "s"


# --- Retention --------------------------------------------------------------

def _profile_with_community(verified: datetime | None) -> EntityProfile:
    return EntityProfile(
        name="X",
        community=CommunityInfo(
            reddit_threads=["https://reddit.com/r/berlin/a/x/"],
            twitter_handles=["@x"],
        ),
        last_verification=verified,
    )


def test_retention_redacts_stale_community_data():
    profile = _profile_with_community(datetime(2024, 1, 1, tzinfo=timezone.utc))
    redacted = apply_retention(profile, retention_days=365, today=dt.date(2026, 6, 14))
    assert set(redacted) == {"community.reddit_threads", "community.twitter_handles"}
    assert profile.community.reddit_threads == []
    assert profile.community.twitter_handles == []


def test_retention_keeps_fresh_data():
    profile = _profile_with_community(datetime(2026, 6, 1, tzinfo=timezone.utc))
    redacted = apply_retention(profile, retention_days=365, today=dt.date(2026, 6, 14))
    assert redacted == []
    assert profile.community.reddit_threads


def test_retention_without_verification_is_noop():
    profile = _profile_with_community(None)
    assert apply_retention(profile, retention_days=1, today=dt.date(2026, 6, 14)) == []
    assert profile.community.reddit_threads  # untouched


def test_retention_config_default_off():
    assert Settings().retention.enabled is False
    assert Settings().retention.community_days == 365
