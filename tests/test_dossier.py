from __future__ import annotations

import datetime as dt

from scoredclub.dossier import build_dossier, build_dossier_from_db
from scoredclub.db import repo
from scoredclub.schemas import (
    DJSet,
    EntityProfile,
    EntityType,
    NetworkingInfo,
    PartyAppearance,
    Track,
)


def _artist_with_content():
    return EntityProfile(
        entity_id="dettmann", name="Marcel Dettmann", type=EntityType.artist,
        top_tracks=[
            Track(title="Track A", plays=5000),
            Track(title="Best", rank=1, plays=100),     # explicit rank wins
            Track(title="Track B", plays=9000),
        ] + [Track(title=f"Filler {i}", plays=i) for i in range(15)],
        top_sets=[
            DJSet(title="Set Low", plays=100),
            DJSet(title="Set High", plays=9000, venue="Berghain"),
        ] + [DJSet(title=f"Set {i}", plays=i) for i in range(10)],
        parties=[
            PartyAppearance(name="Old", date=dt.date(2023, 1, 1)),
            PartyAppearance(name="Recent", date=dt.date(2026, 5, 1), venue="Tresor", role="headliner"),
            PartyAppearance(name="Undated"),
        ] + [PartyAppearance(name=f"P{i}", date=dt.date(2024, 1, 1) + dt.timedelta(days=i)) for i in range(30)],
        networking=NetworkingInfo(collaborations=["Ben Klock"]),
    )


def test_top_tracks_capped_and_ranked():
    d = build_dossier(_artist_with_content())
    assert len(d["top_tracks"]) == 10               # capped
    assert d["top_tracks"][0]["title"] == "Best"     # explicit rank=1 first
    # Then by plays desc among the unranked.
    assert d["top_tracks"][1]["title"] == "Track B"
    assert d["counts"]["tracks"] == 18


def test_top_sets_capped_to_five_by_plays():
    d = build_dossier(_artist_with_content())
    assert len(d["top_sets"]) == 5
    assert d["top_sets"][0]["title"] == "Set High"


def test_parties_capped_to_twenty_recent_first():
    d = build_dossier(_artist_with_content())
    assert len(d["parties"]) == 20                    # capped
    assert d["parties"][0]["name"] == "Recent"        # most recent first
    assert d["parties"][0]["role"] == "headliner"
    # The undated party is pushed to the end, so it falls outside the top 20 here.
    assert all(p["name"] != "Undated" for p in d["parties"]) or d["parties"][-1]["date"] is None


def test_dossier_includes_authenticity_and_relationships():
    d = build_dossier(_artist_with_content(), score=72.0, tier="MID-TIER",
                      relationships={"books": [{"id": "x", "label": "X"}]})
    assert d["score"] == 72.0
    assert d["follower_authenticity"]["verdict"] in {"authentic", "questionable", "suspicious", "inconclusive"}
    assert d["relationships"]["books"][0]["label"] == "X"


def test_empty_dossier():
    d = build_dossier(EntityProfile(name="Nobody", type=EntityType.artist))
    assert d["top_tracks"] == [] and d["top_sets"] == [] and d["parties"] == []
    assert d["counts"] == {"tracks": 0, "sets": 0, "parties": 0}


def test_build_dossier_from_db(session):
    repo.upsert_profile(session, _artist_with_content())
    repo.upsert_profile(session, EntityProfile(
        entity_id="berghain", name="Berghain", type=EntityType.club,
        networking=NetworkingInfo(booked_djs=["Marcel Dettmann"])))
    d = build_dossier_from_db(session, "dettmann")
    assert d["name"] == "Marcel Dettmann"
    # Relationship graph resolved: Berghain books this artist.
    assert any(r["id"] == "berghain" for r in d["relationships"]["booked_by"])
    assert build_dossier_from_db(session, "nope") is None
