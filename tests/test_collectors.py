from __future__ import annotations

import httpx

from scoredclub.collectors.clubcommission import ClubcommissionCollector, _name_from_slug
from scoredclub.collectors.reddit import RedditCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import EntityProfile

MEMBERS_HTML = """
<html><body>
<header><a href="/join/">Join</a></header>
<section class="members">
  <ul>
    <li><a href="https://www.clubcommission.de/members/tresor/"><img src="tresor.png"></a></li>
    <li><a href="https://www.clubcommission.de/members/silent-green/"><img src="sg.png"></a></li>
    <li><a href="https://www.clubcommission.de/members/panke-e-v/">Panke e.V.</a></li>
    <li><a href="https://www.clubcommission.de/members/tresor/"><img src="dup.png"></a></li>
    <li><a href="https://www.clubcommission.de/members/all/">show all Members</a></li>
  </ul>
</section>
<footer><a href="/impressum/">Impressum</a></footer>
</body></html>
"""


def test_name_from_slug():
    assert _name_from_slug("silent-green") == "Silent Green"
    assert _name_from_slug("panke-e-v") == "Panke e.V."
    assert _name_from_slug("about-blank") == "About Blank"


def test_parse_extracts_member_links_dedup_and_blocklist():
    pairs = ClubcommissionCollector._parse(MEMBERS_HTML)
    names = [n for n, _ in pairs]
    # 'all' is blocklisted, the duplicate tresor link is collapsed.
    assert names == ["Tresor", "Silent Green", "Panke e.V."]
    # Visible link text wins when present (Panke e.V.), else slug-derived.
    assert pairs[0][1].endswith("/members/tresor/")


def test_collector_returns_membership_flagged_profiles(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=MEMBERS_HTML)

    transport = httpx.MockTransport(handler)

    real_get = httpx.get

    def fake_get(url, **kwargs):
        kwargs.pop("follow_redirects", None)
        with httpx.Client(transport=transport) as client:
            return client.get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = ClubcommissionCollector().collect(Settings())
    assert result.ok
    assert len(result.profiles) == 3
    assert all(p.cultural_recognition.clubcommission_member for p in result.profiles)
    assert result.profiles[0].sources[0].url.endswith("/members/tresor/")


def test_collector_network_failure_is_nonfatal(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", boom)
    result = ClubcommissionCollector().collect(Settings())
    assert result.ok is False
    assert result.profiles == []
    assert any("fetch failed" in w for w in result.warnings)


def test_ra_collector_blocked_is_nonfatal(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.HTTPStatusError("403", request=None, response=None)

    monkeypatch.setattr(httpx, "post", boom)
    result = ResidentAdvisorCollector().collect(Settings())
    assert result.ok is False
    assert result.profiles == []
    assert result.warnings


def _reddit_payload(*entries):
    return {"data": {"children": [{"data": d} for d in entries]}}


def test_reddit_collector_enriches_and_filters_subreddits(monkeypatch):
    payload = _reddit_payload(
        {"subreddit": "berlin", "permalink": "/r/berlin/comments/a/berghain_door/"},
        {"subreddit": "techno", "permalink": "/r/techno/comments/b/berghain_set/"},
        {"subreddit": "random", "permalink": "/r/random/comments/c/unrelated/"},
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    collector = RedditCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name="Berghain", type="club")]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok
    assert len(result.profiles) == 1
    threads = result.profiles[0].community.reddit_threads
    # The /r/random thread is filtered out; the two relevant subs are kept.
    assert threads == [
        "https://www.reddit.com/r/berlin/comments/a/berghain_door/",
        "https://www.reddit.com/r/techno/comments/b/berghain_set/",
    ]


def test_reddit_collector_disabled(monkeypatch):
    settings = Settings()
    settings.sources.reddit_enabled = False
    # Should not even touch the network.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    result = RedditCollector().collect(settings, entities=[EntityProfile(name="X")])
    assert result.ok
    assert result.profiles == []


def test_reddit_collector_aborts_after_failures(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "get", boom)
    collector = RedditCollector()
    collector.request_delay = 0
    entities = [EntityProfile(name=f"Club {i}") for i in range(6)]
    result = collector.collect(Settings(), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert any("unreachable" in w for w in result.warnings)


def test_reddit_enrichment_merges_into_existing_entity(session, monkeypatch):
    seed = EntityProfile(entity_id="berghain", name="Berghain", type="club", district="Friedrichshain")
    repo.upsert_profile(session, seed)

    payload = _reddit_payload(
        {"subreddit": "berlin", "permalink": "/r/berlin/comments/a/berghain/"},
    )
    monkeypatch.setattr(
        httpx, "get", lambda url, **k: httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    )
    collector = RedditCollector()
    collector.request_delay = 0
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    result = collector.collect(Settings(), entities=current)

    for profile in result.profiles:
        entity, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
        assert is_new is False
    merged = repo.profile_from_row(repo.get_entity(session, "berghain"))
    assert merged.community.reddit_threads == ["https://www.reddit.com/r/berlin/comments/a/berghain/"]
    # Existing data preserved.
    assert merged.district == "Friedrichshain"


def test_upsert_create_if_missing_false_skips_unmatched(session):
    profile = EntityProfile(name="Totally Unknown Venue")
    entity, is_new = repo.upsert_profile(session, profile, create_if_missing=False)
    assert entity is None
    assert is_new is False
    assert repo.all_entities(session) == []
