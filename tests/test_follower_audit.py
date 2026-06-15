from __future__ import annotations

import httpx
import pytest

from scoredclub.authenticity import VERDICT_QUESTIONABLE, VERDICT_SUSPICIOUS, assess
from scoredclub.collectors.follower_audit import (
    FollowerAuditCollector,
    _instagram_handle,
    _parse_audit,
)
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import (
    EntityProfile,
    EntityType,
    FollowerAudit,
    OnlinePresence,
    SocialPresence,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("FOLLOWER_AUDIT_API_KEY", raising=False)


# --- helpers ----------------------------------------------------------------

def test_instagram_handle_from_handle_and_url():
    assert _instagram_handle(EntityProfile(
        name="X", online=OnlinePresence(instagram=SocialPresence(handle="@berghain")))) == "berghain"
    assert _instagram_handle(EntityProfile(
        name="X", online=OnlinePresence(instagram=SocialPresence(url="https://instagram.com/tresorberlin/")))) == "tresorberlin"
    assert _instagram_handle(EntityProfile(name="X")) is None


def test_parse_audit_maps_fields_and_history():
    audit, history = _parse_audit({
        "fake_follower_pct": 42.0, "engagement_rate": 0.4, "quality_score": 35,
        "source": "provider-x", "checked_at": "2026-06-15",
        "history": [{"date": "2026-01-01", "followers": 5000},
                    {"date": "2026-06-01", "followers": 6000},
                    {"bad": "row"}],
    })
    assert audit.fake_follower_pct == 42.0
    assert audit.engagement_rate == 0.4
    assert audit.source == "provider-x"
    assert audit.checked_at.isoformat() == "2026-06-15"
    assert [p.followers for p in history] == [5000, 6000]  # invalid row skipped


# --- collector --------------------------------------------------------------

def test_collect_noop_without_key(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    e = EntityProfile(name="X", online=OnlinePresence(instagram=SocialPresence(handle="x")))
    assert FollowerAuditCollector().collect(Settings(), entities=[e]).profiles == []


def test_collect_noop_without_handle(monkeypatch):
    monkeypatch.setenv("FOLLOWER_AUDIT_API_KEY", "key")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    e = EntityProfile(name="X")  # no instagram handle
    assert FollowerAuditCollector().collect(Settings(), entities=[e]).profiles == []


def test_collect_pulls_external_audit_and_history(monkeypatch):
    monkeypatch.setenv("FOLLOWER_AUDIT_API_KEY", "key")
    captured = {}

    def fake_get(url, **kwargs):
        captured["params"] = kwargs.get("params")
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(200, json={
            "fake_follower_pct": 55.0, "engagement_rate": 0.3, "source": "audit-x",
            "history": [{"date": "2026-01-01", "followers": 9000}],
        }, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = FollowerAuditCollector()
    collector.request_delay = 0
    e = EntityProfile(name="Berghain", type=EntityType.club,
                      online=OnlinePresence(instagram=SocialPresence(handle="berghain")))
    result = collector.collect(Settings(), entities=[e])

    assert len(result.profiles) == 1
    p = result.profiles[0]
    assert p.follower_audit.fake_follower_pct == 55.0
    assert p.follower_history["instagram"][0].followers == 9000
    assert captured["params"]["handle"] == "berghain"
    assert captured["headers"]["Authorization"] == "Bearer key"


def test_collect_aborts_after_failures(monkeypatch):
    monkeypatch.setenv("FOLLOWER_AUDIT_API_KEY", "key")
    monkeypatch.setattr(httpx, "get", lambda url, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    collector = FollowerAuditCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name=f"C{i}", online=OnlinePresence(instagram=SocialPresence(handle=f"c{i}")))
                for i in range(6)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_audit_merges_into_entity(session, monkeypatch):
    monkeypatch.setenv("FOLLOWER_AUDIT_API_KEY", "key")
    repo.upsert_profile(session, EntityProfile(
        entity_id="berghain", name="Berghain", type=EntityType.club,
        online=OnlinePresence(instagram=SocialPresence(handle="berghain")),
    ))

    def fake_get(url, **kwargs):
        return httpx.Response(200, json={"fake_follower_pct": 40.0, "source": "audit-x"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = FollowerAuditCollector()
    collector.request_delay = 0
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    for profile in collector.collect(Settings(), entities=current).profiles:
        repo.upsert_profile(session, profile, create_if_missing=False)
    merged = repo.profile_from_row(repo.get_entity(session, "berghain"))
    assert merged.follower_audit.fake_follower_pct == 40.0


# --- assessment uses the external dataset (not just internal comparison) -----

def test_severe_fake_pct_makes_suspicious():
    profile = EntityProfile(
        name="Bought", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=80000)),
        follower_audit=FollowerAudit(fake_follower_pct=60.0, source="audit-x"),
    )
    result = assess(profile)
    assert result.verdict == VERDICT_SUSPICIOUS
    assert any("unechte Follower" in f for f in result.flags)
    assert result.signals["audit"]["fake_follower_pct"] == 60.0


def test_moderate_fake_pct_is_questionable():
    profile = EntityProfile(
        name="Some DJ", type=EntityType.artist,
        online=OnlinePresence(instagram=SocialPresence(followers=10000)),
        follower_audit=FollowerAudit(fake_follower_pct=35.0),
    )
    assert assess(profile).verdict == VERDICT_QUESTIONABLE


def test_low_engagement_flag():
    profile = EntityProfile(
        name="Ghost", type=EntityType.club,
        online=OnlinePresence(instagram=SocialPresence(followers=50000)),
        follower_audit=FollowerAudit(engagement_rate=0.1, fake_follower_pct=5.0),
    )
    result = assess(profile)
    assert any("Engagement-Rate" in f for f in result.flags)


def test_clean_audit_keeps_authentic():
    from tests.conftest import make_top_profile
    profile = make_top_profile(follower_audit=FollowerAudit(fake_follower_pct=3.0, engagement_rate=4.5))
    result = assess(profile)
    assert result.verdict == "authentic"
    assert result.signals["audit"]["source"] is None
