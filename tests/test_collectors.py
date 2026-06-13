from __future__ import annotations

import httpx

from scoredclub.collectors.clubcommission import ClubcommissionCollector, _name_from_slug
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector
from scoredclub.config import Settings

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
