from __future__ import annotations

import datetime as dt

import httpx

from scoredclub.collectors.mixcloud import MixcloudCollector, _parse_cloudcasts
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import EntityProfile, EntityType, OnlinePresence, SocialPresence


def _cloudcast(name: str, plays: int, when: str = "2024-06-01T10:00:00Z", length: int = 3600) -> dict:
    return {
        "name": name,
        "play_count": plays,
        "created_time": when,
        "url": f"https://www.mixcloud.com/dj/{name.lower().replace(' ', '-')}/",
        "audio_length": length,
    }


def _enabled_settings() -> Settings:
    s = Settings()
    s.sources.mixcloud_enabled = True
    return s


def _artist(handle: str | None = None, url: str | None = None) -> EntityProfile:
    return EntityProfile(
        name="Marcel Dettmann",
        type=EntityType.artist,
        online=OnlinePresence(mixcloud=SocialPresence(handle=handle, url=url)),
    )


def test_parse_cloudcasts_maps_sets_and_tolerates_bad_data():
    cloudcasts = [
        _cloudcast("Mix One", 5000),
        _cloudcast("Mix Two", 9000, when="not-a-date", length=0),
        {"play_count": 10},  # no name -> skipped
    ]
    sets = _parse_cloudcasts(cloudcasts)
    assert [s.title for s in sets] == ["Mix One", "Mix Two"]
    assert sets[0].plays == 5000
    assert sets[0].date == dt.date(2024, 6, 1)
    assert sets[0].duration_min == 60
    assert sets[0].source == "mixcloud"
    # Bad date / zero length degrade to None, not an error.
    assert sets[1].date is None and sets[1].duration_min is None


def test_collect_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    result = MixcloudCollector().collect(Settings(), entities=[_artist(handle="dettmann")])
    assert result.ok and result.profiles == []


def test_collect_noop_without_handle(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    result = MixcloudCollector().collect(_enabled_settings(), entities=[_artist()])
    assert result.ok and result.profiles == []


def test_collect_enriches_with_sets_and_followers(monkeypatch):
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        if "cloudcasts" in url:
            payload = {"data": [_cloudcast("Berghain Mix", 9000), _cloudcast("Tresor Mix", 5000)]}
        else:
            payload = {"follower_count": 12345}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = MixcloudCollector()
    collector.request_delay = 0
    result = collector.collect(_enabled_settings(), entities=[_artist(handle="dettmann")])

    assert result.ok
    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert [s.title for s in profile.top_sets] == ["Berghain Mix", "Tresor Mix"]
    assert profile.online.mixcloud.followers == 12345
    assert profile.online.mixcloud.url == "https://www.mixcloud.com/dettmann/"
    # Cloudcasts fetched before the profile (followers).
    assert "cloudcasts" in urls[0] and "cloudcasts" not in urls[1]


def test_collect_resolves_username_from_url(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.setdefault("first", url)
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = MixcloudCollector()
    collector.request_delay = 0
    entity = _artist(url="https://www.mixcloud.com/spreadyhour/")
    collector.collect(_enabled_settings(), entities=[entity])
    assert "/spreadyhour/cloudcasts/" in captured["first"]


def test_collect_respects_max_entities(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    settings = _enabled_settings()
    settings.sources.mixcloud_max_entities = 2
    collector = MixcloudCollector()
    collector.request_delay = 0
    entities = [_artist(handle=f"dj{i}") for i in range(5)]
    collector.collect(settings, entities=entities)
    # 2 entities * (cloudcasts + followers) requests = 4.
    assert calls["n"] == 4


def test_collect_aborts_after_failures(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "get", boom)
    collector = MixcloudCollector()
    collector.request_delay = 0
    entities = [_artist(handle=f"dj{i}") for i in range(6)]
    result = collector.collect(_enabled_settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_enrichment_merges_and_refetch_updates_plays(session, monkeypatch):
    seed = EntityProfile(
        entity_id="marcel-dettmann", name="Marcel Dettmann", type=EntityType.artist,
        district="Friedrichshain",
        online=OnlinePresence(mixcloud=SocialPresence(handle="dettmann")),
    )
    repo.upsert_profile(session, seed)

    plays = {"value": 5000}

    def fake_get(url, **kwargs):
        if "cloudcasts" in url:
            return httpx.Response(
                200, json={"data": [_cloudcast("Berghain Mix", plays["value"])]},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, json={"follower_count": 12345}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = MixcloudCollector()
    collector.request_delay = 0

    for run_plays in (5000, 7000):  # two runs: the second re-fetches with new plays
        plays["value"] = run_plays
        current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
        result = collector.collect(_enabled_settings(), entities=current)
        for profile in result.profiles:
            _, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
            assert is_new is False

    merged = repo.profile_from_row(repo.get_entity(session, "marcel-dettmann"))
    # Re-fetch updates in place: one set, with the latest play count.
    assert len(merged.top_sets) == 1
    assert merged.top_sets[0].plays == 7000
    assert merged.district == "Friedrichshain"  # existing data preserved
