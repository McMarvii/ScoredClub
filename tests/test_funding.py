from __future__ import annotations

import datetime as dt
import json

from scoredclub.funding import (
    FundingFeed,
    feed_to_dict,
    load_funding,
    upcoming_deadlines,
)

TODAY = dt.date(2026, 6, 14)


def _feed():
    return FundingFeed.model_validate({
        "programs": [
            {"name": "Soon", "deadline": (TODAY + dt.timedelta(days=10)).isoformat(), "provider": "X"},
            {"name": "Later", "deadline": (TODAY + dt.timedelta(days=200)).isoformat()},
            {"name": "Past", "deadline": (TODAY - dt.timedelta(days=5)).isoformat()},
            {"name": "Rolling", "deadline": None, "status": "rolling"},
        ],
        "policies": [{"title": "UNESCO-ICH", "source": "UNESCO"}],
    })


def test_upcoming_deadlines_window_and_order():
    upcoming = upcoming_deadlines(_feed(), today=TODAY, within_days=90)
    # Only "Soon" is within 90 days and not past; null/past/far excluded.
    assert [p.name for p in upcoming] == ["Soon"]
    wide = upcoming_deadlines(_feed(), today=TODAY, within_days=365)
    assert [p.name for p in wide] == ["Soon", "Later"]  # sorted soonest first


def test_load_funding_missing_file_is_empty(tmp_path):
    feed = load_funding(tmp_path / "nope.json")
    assert feed.programs == [] and feed.policies == []


def test_load_funding_invalid_file_is_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_funding(bad).programs == []


def test_load_funding_roundtrip(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({
        "programs": [{"name": "Musicboard", "provider": "Musicboard Berlin", "status": "rolling"}],
        "policies": [{"title": "ICH", "url": "https://unesco.de"}],
    }), encoding="utf-8")
    feed = load_funding(path)
    assert feed.programs[0].name == "Musicboard"
    assert feed.policies[0].title == "ICH"


def test_feed_to_dict_shape():
    payload = feed_to_dict(_feed(), today=TODAY, within_days=90)
    assert {"programs", "policies", "upcoming_deadlines"} <= payload.keys()
    assert len(payload["programs"]) == 4
    assert [p["name"] for p in payload["upcoming_deadlines"]] == ["Soon"]


def test_shipped_feed_file_is_valid():
    feed = load_funding("data/funding/berlin_funding.json")
    assert feed.programs  # the committed seed feed loads and validates
    assert any("Musicboard" in p.name for p in feed.programs)
