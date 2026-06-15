from __future__ import annotations

import httpx
import pytest

from scoredclub.collectors.soundcloud import SoundCloudCollector, _parse_tracks, _released
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import EntityProfile, EntityType, OnlinePresence, SocialPresence


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SOUNDCLOUD_CLIENT_ID", raising=False)


def _track(title: str, plays: int, created: str = "2014/01/05 12:00:00 +0000") -> dict:
    return {
        "title": title,
        "playback_count": plays,
        "permalink_url": f"https://soundcloud.com/dj/{title.lower().replace(' ', '-')}",
        "created_at": created,
    }


def _user(user_id: int = 123, followers: int = 50_000) -> dict:
    return {
        "id": user_id,
        "kind": "user",
        "followers_count": followers,
        "permalink_url": "https://soundcloud.com/marcel-dettmann",
    }


def _artist(handle: str | None = None, url: str | None = None) -> EntityProfile:
    return EntityProfile(
        name="Marcel Dettmann",
        type=EntityType.artist,
        online=OnlinePresence(soundcloud=SocialPresence(handle=handle, url=url)),
    )


def test_released_normalises_formats():
    assert _released("2014/01/05 12:00:00 +0000") == "2014-01-05"
    assert _released("2014-01-05T12:00:00Z") == "2014-01-05"
    assert _released("2014") == "2014"
    assert _released("garbage") is None
    assert _released(None) is None


def test_parse_tracks_maps_and_skips_untitled():
    tracks = [_track("Quicksand", 9000), {"playback_count": 10}]  # no title -> skipped
    parsed = _parse_tracks(tracks)
    assert [t.title for t in parsed] == ["Quicksand"]
    assert parsed[0].plays == 9000
    assert parsed[0].released == "2014-01-05"
    assert parsed[0].source == "soundcloud"


def test_collect_noop_without_client_id(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    result = SoundCloudCollector().collect(Settings(), entities=[_artist(handle="dettmann")])
    assert result.ok and result.profiles == []


def test_collect_noop_without_handle(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    result = SoundCloudCollector().collect(Settings(), entities=[_artist()])
    assert result.ok and result.profiles == []


def test_collect_enriches_with_tracks_and_followers(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        if "resolve" in url:
            return httpx.Response(200, json=_user(), request=httpx.Request("GET", url))
        payload = [_track("Quicksand", 9000), _track("Translation", 5000)]
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SoundCloudCollector()
    collector.request_delay = 0
    result = collector.collect(Settings(), entities=[_artist(handle="dettmann")])

    assert result.ok
    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert [t.title for t in profile.top_tracks] == ["Quicksand", "Translation"]
    assert profile.online.soundcloud.followers == 50_000
    assert profile.online.soundcloud.url == "https://soundcloud.com/marcel-dettmann"
    # Resolve first, then tracks by id.
    assert "resolve" in urls[0]
    assert "/users/123/tracks" in urls[1]


def test_collect_paginated_collection(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")

    def fake_get(url, **kwargs):
        if "resolve" in url:
            return httpx.Response(200, json=_user(), request=httpx.Request("GET", url))
        return httpx.Response(
            200, json={"collection": [_track("Quicksand", 9000)]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SoundCloudCollector()
    collector.request_delay = 0
    result = collector.collect(Settings(), entities=[_artist(handle="dettmann")])
    assert [t.title for t in result.profiles[0].top_tracks] == ["Quicksand"]


def test_collect_user_not_found_is_skipped(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")

    def fake_get(url, **kwargs):
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SoundCloudCollector()
    collector.request_delay = 0
    result = collector.collect(Settings(), entities=[_artist(handle="nobody")])
    # 404 -> skipped, not a hard failure.
    assert result.ok and result.profiles == []


def test_collect_aborts_after_failures(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")

    def boom(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "get", boom)
    collector = SoundCloudCollector()
    collector.request_delay = 0
    entities = [_artist(handle=f"dj{i}") for i in range(6)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_enrichment_merges_into_existing_artist(session, monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")
    seed = EntityProfile(
        entity_id="marcel-dettmann", name="Marcel Dettmann", type=EntityType.artist,
        district="Friedrichshain",
        online=OnlinePresence(soundcloud=SocialPresence(handle="dettmann")),
    )
    repo.upsert_profile(session, seed)

    def fake_get(url, **kwargs):
        if "resolve" in url:
            return httpx.Response(200, json=_user(), request=httpx.Request("GET", url))
        return httpx.Response(200, json=[_track("Quicksand", 9000)], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = SoundCloudCollector()
    collector.request_delay = 0
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    result = collector.collect(Settings(), entities=current)
    for profile in result.profiles:
        _, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
        assert is_new is False
    merged = repo.profile_from_row(repo.get_entity(session, "marcel-dettmann"))
    assert [t.title for t in merged.top_tracks] == ["Quicksand"]
    assert merged.online.soundcloud.followers == 50_000
    assert merged.district == "Friedrichshain"  # existing data preserved
