"""Tests for residency detection in the booking graph.

A residency is when an artist appears at the same venue at least
``min_appearances`` times in their parties/gigography. The detection is
purely derived from ``profile.parties``; the result surfaces as a
``REL_RESIDENT`` edge in the booking graph, a ``residencies``/``residents``
key in ``entity_relationships``, and ``top_residencies`` in ``graph_metrics``.
"""

from __future__ import annotations

import datetime as dt

from scoredclub.graph import (
    REL_PLAYED_AT,
    REL_RESIDENT,
    build_booking_graph,
    detect_residencies,
    entity_relationships,
    graph_metrics,
)
from scoredclub.schemas import (
    EntityProfile,
    EntityType,
    NetworkingInfo,
    PartyAppearance,
)


def _artist(entity_id: str, name: str, parties: list[PartyAppearance], venues: list[str] | None = None) -> EntityProfile:
    return EntityProfile(
        entity_id=entity_id, name=name, type=EntityType.artist,
        parties=parties,
        networking=NetworkingInfo(collaborations=venues or []),
    )


def _club(entity_id: str, name: str) -> EntityProfile:
    return EntityProfile(entity_id=entity_id, name=name, type=EntityType.club)


def _party(venue: str, year: int = 2024) -> PartyAppearance:
    return PartyAppearance(name="Klubnacht", venue=venue, date=dt.date(year, 1, 1))


# ---------------------------------------------------------------------------
# detect_residencies — unit tests on the pure function
# ---------------------------------------------------------------------------

def test_detects_residency_above_threshold():
    profile = _artist("dettmann", "Marcel Dettmann", parties=[
        _party("Berghain"),
        _party("Berghain"),
        _party("Berghain"),  # 3 → residency
        _party("Tresor"),    # 1 → no residency
    ])
    result = detect_residencies([profile], min_appearances=3)
    assert result == {"dettmann": ["Berghain"]}


def test_no_residency_below_threshold():
    profile = _artist("dettmann", "Marcel Dettmann", parties=[
        _party("Berghain"),
        _party("Berghain"),  # only 2 < 3
    ])
    assert detect_residencies([profile], min_appearances=3) == {}


def test_threshold_configurable():
    profile = _artist("x", "X", parties=[_party("Berghain"), _party("Berghain")])
    assert detect_residencies([profile], min_appearances=2) == {"x": ["Berghain"]}
    assert detect_residencies([profile], min_appearances=3) == {}


def test_venue_dedup_case_insensitive():
    # "berghain" and "Berghain" normalize to the same venue.
    profile = _artist("dettmann", "Marcel Dettmann", parties=[
        PartyAppearance(name="A", venue="Berghain"),
        PartyAppearance(name="B", venue="berghain"),
        PartyAppearance(name="C", venue="BERGHAIN"),
    ])
    result = detect_residencies([profile], min_appearances=3)
    assert "dettmann" in result
    assert len(result["dettmann"]) == 1  # deduped to one venue


def test_parties_without_venue_ignored():
    profile = _artist("x", "X", parties=[
        PartyAppearance(name="A"),              # no venue
        PartyAppearance(name="B", venue=""),    # empty venue
        PartyAppearance(name="C", venue="  "),  # whitespace
    ])
    assert detect_residencies([profile]) == {}


def test_non_artist_entities_skipped():
    club = EntityProfile(
        entity_id="berghain", name="Berghain", type=EntityType.club,
        parties=[_party("Berghain")] * 5,
    )
    assert detect_residencies([club]) == {}


def test_multiple_artists_multiple_venues():
    a = _artist("a", "A", parties=[_party("V1")] * 3 + [_party("V2")] * 3)
    b = _artist("b", "B", parties=[_party("V1")] * 4 + [_party("V3")])
    result = detect_residencies([a, b], min_appearances=3)
    assert set(result["a"]) == {"V1", "V2"}
    assert result["b"] == ["V1"]


# ---------------------------------------------------------------------------
# REL_RESIDENT edges in the booking graph
# ---------------------------------------------------------------------------

def test_residency_edges_added_to_graph():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Berghain")] * 3),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rels = {(e.source, e.target, e.relation) for e in graph.edges}
    assert ("dettmann", "berghain", REL_RESIDENT) in rels


def test_residency_resolves_to_external_when_no_entity():
    profiles = [
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Tresor")] * 3),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rels = {(e.source, e.target, e.relation) for e in graph.edges}
    assert ("dettmann", "ext:tresor", REL_RESIDENT) in rels


def test_residency_edge_distinct_from_played_at():
    # played_at comes from networking.collaborations; resident comes from parties.
    # Both edges can coexist for the same artist↔venue pair.
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann",
                parties=[_party("Berghain")] * 3,
                venues=["Berghain"]),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rels = [(e.source, e.target, e.relation) for e in graph.edges
            if e.source == "dettmann" and e.target == "berghain"]
    relations = {r[2] for r in rels}
    assert REL_PLAYED_AT in relations
    assert REL_RESIDENT in relations


def test_no_residency_edges_below_threshold():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Berghain")] * 2),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    resident_edges = [e for e in graph.edges if e.relation == REL_RESIDENT]
    assert resident_edges == []


# ---------------------------------------------------------------------------
# entity_relationships — residencies / residents keys
# ---------------------------------------------------------------------------

def test_entity_relationships_residencies_for_artist():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Berghain")] * 3),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rel = entity_relationships(graph, "dettmann")
    assert any(r["id"] == "berghain" for r in rel["residencies"])
    assert rel["residents"] == []  # artist, not a venue


def test_entity_relationships_residents_for_venue():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Berghain")] * 3),
        _artist("klock", "Ben Klock", parties=[_party("Berghain")] * 5),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rel = entity_relationships(graph, "berghain")
    resident_ids = {r["id"] for r in rel["residents"]}
    assert resident_ids == {"dettmann", "klock"}
    assert rel["residencies"] == []  # venue, not an artist


def test_entity_relationships_no_residencies_when_below_threshold():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", parties=[_party("Berghain")] * 2),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    rel = entity_relationships(graph, "dettmann")
    assert rel["residencies"] == []


# ---------------------------------------------------------------------------
# graph_metrics — top_residencies
# ---------------------------------------------------------------------------

def test_graph_metrics_top_residencies():
    profiles = [
        _club("berghain", "Berghain"),
        _club("tresor", "Tresor"),
        _artist("a", "DJ A", parties=[_party("Berghain")] * 3 + [_party("Tresor")] * 3),
        _artist("b", "DJ B", parties=[_party("Berghain")] * 4),
    ]
    graph = build_booking_graph(profiles, min_appearances=3)
    metrics = graph_metrics(graph)
    residencies = metrics["top_residencies"]
    assert residencies, "expected at least one residency in metrics"
    top = residencies[0]
    assert top["id"] == "berghain"  # Berghain has 2 residents, Tresor only 1
    assert top["resident_count"] == 2


def test_graph_metrics_empty_residencies():
    profiles = [_club("berghain", "Berghain")]
    graph = build_booking_graph(profiles)
    assert graph_metrics(graph)["top_residencies"] == []
