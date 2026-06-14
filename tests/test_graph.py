from __future__ import annotations

from scoredclub.graph import (
    KIND_ENTITY,
    KIND_EXTERNAL,
    REL_BOOKS,
    REL_COLLABORATES,
    REL_PLAYED_AT,
    build_booking_graph,
    build_graph_from_db,
    graph_metrics,
    graph_to_dict,
)
from scoredclub.db import repo
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


def test_artist_collaborations_are_played_at_edges():
    profiles = [
        _club("berghain", "Berghain"),
        _artist("dettmann", "Marcel Dettmann", ["Berghain", "Tresor"]),
    ]
    graph = build_booking_graph(profiles)
    rels = {(e.source, e.target, e.relation) for e in graph.edges}
    # Resolves "Berghain" to the existing entity; "Tresor" becomes external.
    assert ("dettmann", "berghain", REL_PLAYED_AT) in rels
    assert ("dettmann", "ext:tresor", REL_PLAYED_AT) in rels
    assert graph.nodes["berghain"].kind == KIND_ENTITY
    assert graph.nodes["ext:tresor"].kind == KIND_EXTERNAL


def test_org_collaborations_vs_booked_djs():
    profiles = [_club("rso", "RSO.Berlin", booked=["DJ One"], collabs=["Label X"])]
    graph = build_booking_graph(profiles)
    rels = {(e.source, e.target, e.relation) for e in graph.edges}
    assert ("rso", "ext:dj one", REL_BOOKS) in rels
    assert ("rso", "ext:label x", REL_COLLABORATES) in rels


def test_edges_dedup_and_no_self_loops():
    # Same DJ listed twice + a self-reference by name.
    profiles = [_club("club-a", "Club A", booked=["DJ X", "DJ X", "Club A"])]
    graph = build_booking_graph(profiles)
    booked = [e for e in graph.edges if e.relation == REL_BOOKS]
    assert len(booked) == 1  # deduped; self-loop dropped


def test_metrics_top_venues_and_djs_and_shared_bookings():
    profiles = [
        _club("berghain", "Berghain", booked=["Marcel Dettmann", "Ben Klock"]),
        _club("tresor", "Tresor", booked=["Marcel Dettmann"]),
        _artist("dettmann", "Marcel Dettmann", ["Berghain", "Tresor", "Watergate"]),
        _artist("klock", "Ben Klock", ["Berghain"]),
    ]
    graph = build_booking_graph(profiles)
    metrics = graph_metrics(graph)

    # Dettmann is booked by 2 orgs -> top DJ.
    top_dj_ids = {d["id"] for d in metrics["top_djs"]}
    assert "dettmann" in top_dj_ids
    dettmann = next(d for d in metrics["top_djs"] if d["id"] == "dettmann")
    assert dettmann["booker_count"] == 2

    # Berghain played by 2 artists -> top venue.
    venue_ids = {v["id"] for v in metrics["top_venues"]}
    assert "berghain" in venue_ids

    # Berghain & Tresor share Dettmann -> a co-booking link.
    assert metrics["shared_bookings"]
    link = metrics["shared_bookings"][0]
    assert {link["a"], link["b"]} == {"berghain", "tresor"}
    assert link["shared_djs"] == 1


def test_components_count():
    # Two disconnected pairs.
    profiles = [
        _club("a", "A", booked=["DJ A"]),
        _club("b", "B", booked=["DJ B"]),
    ]
    graph = build_booking_graph(profiles)
    metrics = graph_metrics(graph)
    # 4 nodes (2 entities + 2 external DJs), 2 separate components.
    assert metrics["node_count"] == 4
    assert metrics["components"] == 2


def test_empty_graph():
    graph = build_booking_graph([_club("a", "A")])
    metrics = graph_metrics(graph)
    assert metrics["edge_count"] == 0
    assert metrics["top_venues"] == []
    assert graph_to_dict(graph)["edges"] == []


def test_build_graph_from_db(session):
    repo.upsert_profile(session, _club("berghain", "Berghain", booked=["Marcel Dettmann"]))
    repo.upsert_profile(session, _artist("dettmann", "Marcel Dettmann", ["Berghain"]))
    graph, scores = build_graph_from_db(session)
    rels = {(e.source, e.target, e.relation) for e in graph.edges}
    assert ("berghain", "dettmann", REL_BOOKS) in rels
    assert ("dettmann", "berghain", REL_PLAYED_AT) in rels
