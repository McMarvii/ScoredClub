from __future__ import annotations

import datetime as dt

import httpx
import pytest

from scoredclub.collectors.songkick import SongkickCollector, _parse_events
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import EntityProfile, EntityType


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SONGKICK_API_KEY", raising=False)


TODAY = dt.date(2026, 6, 14)


def _event(days_ago: int, venue: str, city: str = "Berlin") -> dict:
    when = TODAY - dt.timedelta(days=days_ago)
    return {
        "start": {"date": when.isoformat()},
        "venue": {"displayName": venue, "metroArea": {"displayName": city}},
    }


def _search_payload(artist_id):
    artists = [{"id": artist_id}] if artist_id is not None else []
    return {"resultsPage": {"results": {"artist": artists}}}


def _gig_payload(events):
    return {"resultsPage": {"results": {"event": events}}}


def test_parse_events_windows_and_venues():
    events = [
        _event(10, "Berghain"),
        _event(80, "Tresor"),
        _event(150, "Sisyphos"),
        _event(300, "OXI"),
    ]
    parsed = _parse_events(events, TODAY)
    assert parsed["events_last_3_months"] == 2
    assert parsed["events_last_6_months"] == 3
    assert parsed["last_event_date"] == TODAY - dt.timedelta(days=10)
    assert parsed["venues"] == ["Berghain, Berlin", "Tresor, Berlin", "Sisyphos, Berlin", "OXI, Berlin"]


def test_parse_events_tolerates_bad_dates_and_missing_city():
    events = [
        {"start": {"date": "not-a-date"}, "venue": {"displayName": "Else"}},
        {"venue": {"displayName": "Klunkerkranich", "metroArea": {"displayName": "Berlin"}}},
    ]
    parsed = _parse_events(events, TODAY)
    assert parsed["events_last_3_months"] == 0
    assert parsed["venues"] == ["Else", "Klunkerkranich, Berlin"]


def test_collect_noop_without_api_key(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    entities = [EntityProfile(name="Some DJ", type=EntityType.artist)]
    result = SongkickCollector().collect(Settings(), entities=entities)
    assert result.ok and result.profiles == []


def test_collect_noop_without_artists(monkeypatch):
    monkeypatch.setenv("SONGKICK_API_KEY", "key")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    entities = [EntityProfile(name="Berghain", type=EntityType.club)]
    result = SongkickCollector().collect(Settings(), entities=entities)
    assert result.ok and result.profiles == []


def test_collect_enriches_artist(monkeypatch):
    monkeypatch.setenv("SONGKICK_API_KEY", "key")
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        if "search/artists" in url:
            return httpx.Response(200, json=_search_payload(123), request=httpx.Request("GET", url))
        return httpx.Response(
            200, json=_gig_payload([_event(15, "Berghain"), _event(150, "Tresor")]),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SongkickCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name="Marcel Dettmann", type=EntityType.artist)]
    result = collector.collect(Settings(), entities=entities)

    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert profile.events.events_last_3_months == 1
    assert profile.events.events_last_6_months == 2
    assert profile.events.ticketing_platforms == ["Songkick"]
    assert profile.networking.collaborations == ["Berghain, Berlin", "Tresor, Berlin"]
    # Search first, then gigography by id.
    assert "search/artists.json" in urls[0]
    assert "/artists/123/gigography.json" in urls[1]


def test_collect_artist_not_found(monkeypatch):
    monkeypatch.setenv("SONGKICK_API_KEY", "key")

    def fake_get(url, **kwargs):
        return httpx.Response(200, json=_search_payload(None), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SongkickCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name="Nobody", type=EntityType.artist)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok and result.profiles == []  # not found -> nothing added


def test_collect_aborts_after_failures(monkeypatch):
    monkeypatch.setenv("SONGKICK_API_KEY", "key")

    def boom(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "get", boom)
    collector = SongkickCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name=f"DJ {i}", type=EntityType.artist) for i in range(6)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_enrichment_merges_into_existing_artist(session, monkeypatch):
    monkeypatch.setenv("SONGKICK_API_KEY", "key")
    seed = EntityProfile(
        entity_id="marcel-dettmann", name="Marcel Dettmann",
        type=EntityType.artist, district="Friedrichshain",
    )
    repo.upsert_profile(session, seed)

    def fake_get(url, **kwargs):
        if "search/artists" in url:
            return httpx.Response(200, json=_search_payload(123), request=httpx.Request("GET", url))
        return httpx.Response(200, json=_gig_payload([_event(20, "Berghain")]), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SongkickCollector()
    collector.request_delay = 0
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    result = collector.collect(Settings(), entities=current)
    for profile in result.profiles:
        _, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
        assert is_new is False
    merged = repo.profile_from_row(repo.get_entity(session, "marcel-dettmann"))
    assert merged.networking.collaborations == ["Berghain, Berlin"]
    assert merged.events.ticketing_platforms == ["Songkick"]
    assert merged.district == "Friedrichshain"
