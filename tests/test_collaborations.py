from __future__ import annotations

from scoredclub.graph import (
    build_booking_graph,
    collaboration_pairs,
    entity_relationships,
    most_collaborative,
)
from scoredclub.schemas import EntityProfile, EntityType, NetworkingInfo


def _club(entity_id, name, booked=None, collabs=None, cross=None):
    return EntityProfile(
        entity_id=entity_id, name=name, type=EntityType.club,
        networking=NetworkingInfo(
            booked_djs=booked or [], collaborations=collabs or [], cross_promotions=cross or [],
        ),
    )


def _artist(entity_id, name, venues):
    return EntityProfile(
        entity_id=entity_id, name=name, type=EntityType.artist,
        networking=NetworkingInfo(collaborations=venues),
    )


def test_shared_dj_creates_collaboration_pair():
    # Berghain and Tresor both book Marcel Dettmann -> they "work together".
    profiles = [
        _club("berghain", "Berghain", booked=["Marcel Dettmann"]),
        _club("tresor", "Tresor", booked=["Marcel Dettmann"]),
        _artist("dettmann", "Marcel Dettmann", []),
    ]
    pairs = collaboration_pairs(build_booking_graph(profiles))
    link = next(p for p in pairs if {p["a"], p["b"]} == {"berghain", "tresor"})
    assert link["shared_djs"] == 1
    assert link["direct"] == 0
    assert link["weight"] == 2  # WEIGHT_SHARED_DJ


def test_direct_edge_outweighs_shared():
    # A direct edge (weight 3) ranks above a pair that only shares a DJ (weight 2).
    profiles = [
        _club("a", "A", collabs=["B"]),       # A -collaborates-> B (direct edge)
        _club("b", "B"),
        _club("c", "C", booked=["DJ X"]),     # C & D only share a booked DJ
        _club("d", "D", booked=["DJ X"]),
    ]
    pairs = collaboration_pairs(build_booking_graph(profiles))
    assert {pairs[0]["a"], pairs[0]["b"]} == {"a", "b"}  # direct edge wins
    assert pairs[0]["direct"] >= 1
    # The shared-only C↔D pair has the lower weight.
    cd = next(p for p in pairs if {p["a"], p["b"]} == {"c", "d"})
    assert cd["weight"] == 2 < pairs[0]["weight"]


def test_most_collaborative_ranks_by_partner_count():
    profiles = [
        _club("hub", "Hub", booked=["DJ A", "DJ B"]),
        _club("x", "X", booked=["DJ A"]),
        _club("y", "Y", booked=["DJ B"]),
    ]
    # Hub works with both DJs (direct) and shares each with X / Y -> the most partners.
    ranking = most_collaborative(build_booking_graph(profiles))
    assert ranking[0]["id"] == "hub"
    assert ranking[0]["collaborators"] == 4  # ext DJ A, ext DJ B, X, Y
    assert ranking[0]["collaborators"] > ranking[1]["collaborators"]


def test_entity_relationships_directions():
    profiles = [
        _club("berghain", "Berghain", booked=["Marcel Dettmann"], cross=["Tresor"]),
        _artist("dettmann", "Marcel Dettmann", ["Berghain"]),
        _club("tresor", "Tresor", booked=["Marcel Dettmann"]),
    ]
    graph = build_booking_graph(profiles)

    berghain = entity_relationships(graph, "berghain")
    assert [r["id"] for r in berghain["books"]] == ["dettmann"]
    assert any(r["id"] == "tresor" for r in berghain["cross_promotes"])
    # Berghain & Tresor share Dettmann.
    assert any(r["id"] == "tresor" for r in berghain["shared_booking_partners"])

    dettmann = entity_relationships(graph, "dettmann")
    booked_by = {r["id"] for r in dettmann["booked_by"]}
    assert booked_by == {"berghain", "tresor"}  # both orgs book the artist
    assert any(r["id"] == "berghain" for r in dettmann["played_venues"])


def test_no_collaborations_empty():
    assert collaboration_pairs(build_booking_graph([_club("solo", "Solo")])) == []
    assert most_collaborative(build_booking_graph([_club("solo", "Solo")])) == []
