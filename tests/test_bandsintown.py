from __future__ import annotations

import datetime as dt

import httpx
import pytest

from scoredclub.collectors.bandsintown import BandsintownCollector, _parse_events
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import EntityProfile, EntityType


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("BANDSINTOWN_APP_ID", raising=False)


TODAY = dt.date(2026, 6, 14)


def _event(days_ago: int, venue: str, city: str = "Berlin") -> dict:
    when = TODAY - dt.timedelta(days=days_ago)
    return {
        "datetime": f"{when.isoformat()}T23:00:00",
        "venue": {"name": venue, "city": city},
    }


def test_parse_events_counts_windows_and_collects_venues():
    events = [
        _event(10, "Berghain"),       # within 3 + 6 months
        _event(80, "Tresor"),         # within 3 + 6 months
        _event(120, "Sisyphos"),      # within 6 months only
        _event(300, "OXI"),           # outside both windows
        _event(-30, "Watergate"),     # future event: counts for no window
    ]
    parsed = _parse_events(events, TODAY)
    assert parsed["events_last_3_months"] == 2
    assert parsed["events_last_6_months"] == 3
    assert parsed["last_event_date"] == TODAY - dt.timedelta(days=10)
    # All venues collected (past and future), most recent first by input order.
    assert parsed["venues"] == [
        "Berghain, Berlin",
        "Tresor, Berlin",
        "Sisyphos, Berlin",
        "OXI, Berlin",
        "Watergate, Berlin",
    ]


def test_parse_events_dedups_venues_and_tolerates_bad_dates():
    events = [
        _event(5, "Berghain"),
        _event(40, "Berghain"),       # same venue -> deduped
        {"datetime": "not-a-date", "venue": {"name": "Else", "city": "Berlin"}},
        {"venue": {"name": "Klunkerkranich"}},  # no city, no date
    ]
    parsed = _parse_events(events, TODAY)
    assert parsed["events_last_3_months"] == 2
    assert parsed["venues"] == ["Berghain, Berlin", "Else, Berlin", "Klunkerkranich"]


def test_collect_noop_without_app_id(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    entities = [EntityProfile(name="Some DJ", type=EntityType.artist)]
    result = BandsintownCollector().collect(Settings(), entities=entities)
    assert result.ok
    assert result.profiles == []


def test_collect_noop_without_artist_entities(monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    entities = [EntityProfile(name="Berghain", type=EntityType.club)]
    result = BandsintownCollector().collect(Settings(), entities=entities)
    assert result.ok
    assert result.profiles == []


def test_collect_enriches_artist(monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        events = [_event(15, "Berghain"), _event(150, "Tresor")]
        return httpx.Response(200, json=events, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = BandsintownCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name="Marcel Dettmann", type=EntityType.artist)]
    result = collector.collect(Settings(), entities=entities)

    assert result.ok
    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert profile.type == EntityType.artist
    assert profile.events.events_last_3_months == 1
    assert profile.events.events_last_6_months == 2
    assert profile.events.ticketing_platforms == ["Bandsintown"]
    assert profile.networking.collaborations == ["Berghain, Berlin", "Tresor, Berlin"]
    # The artist name is URL-encoded into the path; app_id passed as a param.
    assert "Marcel%20Dettmann/events" in captured["url"]
    assert captured["params"]["app_id"] == "app123"


def test_collect_error_object_yields_no_events(monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")

    def fake_get(url, **kwargs):
        # Bandsintown returns an error object (dict) for unknown artists.
        return httpx.Response(200, json={"errorMessage": "[NOT FOUND]"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = BandsintownCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name="Nobody", type=EntityType.artist)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok
    assert len(result.profiles) == 1
    assert result.profiles[0].events.events_last_3_months == 0
    assert result.profiles[0].networking.collaborations == []


def test_collect_aborts_after_failures(monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")

    def boom(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "get", boom)
    collector = BandsintownCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name=f"DJ {i}", type=EntityType.artist) for i in range(6)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_collect_respects_max_artists(monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    settings = Settings()
    settings.sources.bandsintown_max_artists = 2
    collector = BandsintownCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name=f"DJ {i}", type=EntityType.artist) for i in range(5)]
    result = collector.collect(settings, entities=entities)
    assert result.ok
    assert calls["n"] == 2


def test_enrichment_merges_into_existing_artist(session, monkeypatch):
    monkeypatch.setenv("BANDSINTOWN_APP_ID", "app123")
    seed = EntityProfile(
        entity_id="marcel-dettmann",
        name="Marcel Dettmann",
        type=EntityType.artist,
        district="Friedrichshain",
    )
    repo.upsert_profile(session, seed)

    def fake_get(url, **kwargs):
        events = [_event(20, "Berghain")]
        return httpx.Response(200, json=events, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = BandsintownCollector()
    collector.request_delay = 0
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    result = collector.collect(Settings(), entities=current)

    for profile in result.profiles:
        _, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
        assert is_new is False
    merged = repo.profile_from_row(repo.get_entity(session, "marcel-dettmann"))
    assert merged.networking.collaborations == ["Berghain, Berlin"]
    assert merged.events.ticketing_platforms == ["Bandsintown"]
    # Existing data preserved.
    assert merged.district == "Friedrichshain"
    assert merged.type == EntityType.artist
