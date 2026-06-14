"""Booking / collaboration graph (Venue ↔ Artist ↔ Kollektiv).

Turns the per-entity ``networking`` data into an actual graph so the networking
dimension becomes queryable rather than just a count. Edges come from:

* ``booked_djs``      → entity *books* DJ          (club/collective → artist)
* ``collaborations``  → for an ``artist`` entity these are the venues played
  (artist *played_at* venue); for an organisation they are collaborator orgs
  (entity *collaborates* with org)
* ``cross_promotions``→ entity *cross_promotes* with another org

Referenced names are resolved to existing entities where possible (via the
normalize matching) and otherwise kept as lightweight "external" nodes, so the
Bandsintown venues an artist played link up with the seeded clubs.

Pure module: callers pass in profiles (+ optional scores); no DB, no I/O. The
metrics (degree, top venues/DJs, co-booking links, components) are derived from
the built graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from scoredclub.normalize import SEED_ALIASES, normalize_name
from scoredclub.schemas import EntityProfile, EntityType

REL_BOOKS = "books"
REL_PLAYED_AT = "played_at"
REL_COLLABORATES = "collaborates"
REL_CROSS_PROMOTES = "cross_promotes"

KIND_ENTITY = "entity"
KIND_EXTERNAL = "external"


@dataclass
class GraphNode:
    id: str  # entity_id, or "ext:<normalized>" for unresolved names
    label: str
    kind: str  # entity | external
    entity_type: str | None = None
    score: float | None = None


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str


@dataclass
class BookingGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)


class _Resolver:
    """Resolve a referenced name to an existing entity id, if one matches."""

    def __init__(self, profiles: list[EntityProfile]):
        self._index: dict[str, str] = {}
        for profile in profiles:
            self._index[normalize_name(profile.name)] = profile.entity_id
            for alias in profile.aliases:
                self._index.setdefault(normalize_name(alias), profile.entity_id)

    def resolve(self, name: str) -> str | None:
        norm = normalize_name(name)
        if norm in self._index:
            return self._index[norm]
        target = SEED_ALIASES.get(norm)
        if target and target in self._index.values():
            return target
        return None


def build_booking_graph(
    profiles: list[EntityProfile], scores: dict[str, float] | None = None
) -> BookingGraph:
    scores = scores or {}
    resolver = _Resolver(profiles)
    graph = BookingGraph()

    for profile in profiles:
        graph.nodes[profile.entity_id] = GraphNode(
            id=profile.entity_id,
            label=profile.name,
            kind=KIND_ENTITY,
            entity_type=profile.type.value,
            score=scores.get(profile.entity_id),
        )

    def node_for(name: str) -> str | None:
        clean = name.strip()
        if not clean:
            return None
        resolved = resolver.resolve(clean)
        if resolved:
            return resolved
        node_id = f"ext:{normalize_name(clean)}"
        if node_id not in graph.nodes:
            graph.nodes[node_id] = GraphNode(id=node_id, label=clean, kind=KIND_EXTERNAL)
        return node_id

    seen: set[tuple[str, str, str]] = set()

    def add_edge(source: str, name: str, relation: str) -> None:
        target = node_for(name)
        if target is None or target == source:
            return
        key = (source, target, relation)
        if key in seen:
            return
        seen.add(key)
        graph.edges.append(GraphEdge(source=source, target=target, relation=relation))

    for profile in profiles:
        src = profile.entity_id
        net = profile.networking
        for dj in net.booked_djs:
            add_edge(src, dj, REL_BOOKS)
        if profile.type == EntityType.artist:
            for venue in net.collaborations:
                add_edge(src, venue, REL_PLAYED_AT)
        else:
            for collab in net.collaborations:
                add_edge(src, collab, REL_COLLABORATES)
        for promo in net.cross_promotions:
            add_edge(src, promo, REL_CROSS_PROMOTES)

    return graph


def _undirected_components(graph: BookingGraph) -> int:
    """Number of connected components over the undirected edge set."""
    parent: dict[str, str] = {n: n for n in graph.nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in graph.edges:
        ra, rb = find(edge.source), find(edge.target)
        if ra != rb:
            parent[ra] = rb
    return len({find(n) for n in graph.nodes}) if graph.nodes else 0


def graph_metrics(graph: BookingGraph, top: int = 10) -> dict:
    """Degree, top venues/DJs and co-booking links derived from the graph."""
    label = {nid: node.label for nid, node in graph.nodes.items()}

    degree: Counter[str] = Counter()
    venue_artists: dict[str, set[str]] = defaultdict(set)
    dj_bookers: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1
        if edge.relation == REL_PLAYED_AT:
            venue_artists[edge.target].add(edge.source)
        elif edge.relation == REL_BOOKS:
            dj_bookers[edge.target].add(edge.source)

    # Co-booking: organisation pairs that book the same DJ (shared-talent links).
    co_booking: Counter[tuple[str, str]] = Counter()
    for bookers in dj_bookers.values():
        for a, b in combinations(sorted(bookers), 2):
            co_booking[(a, b)] += 1

    top_venues = [
        {"id": vid, "label": label.get(vid, vid), "artist_count": len(artists)}
        for vid, artists in sorted(
            venue_artists.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )[:top]
    ]
    top_djs = [
        {"id": did, "label": label.get(did, did), "booker_count": len(bookers)}
        for did, bookers in sorted(
            dj_bookers.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )[:top]
    ]
    top_connected = [
        {"id": nid, "label": label.get(nid, nid), "degree": deg}
        for nid, deg in degree.most_common(top)
    ]
    shared = [
        {
            "a": a, "a_label": label.get(a, a),
            "b": b, "b_label": label.get(b, b),
            "shared_djs": count,
        }
        for (a, b), count in sorted(
            co_booking.items(), key=lambda kv: (-kv[1], kv[0])
        )[:top]
    ]

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "entity_nodes": sum(1 for n in graph.nodes.values() if n.kind == KIND_ENTITY),
        "external_nodes": sum(1 for n in graph.nodes.values() if n.kind == KIND_EXTERNAL),
        "components": _undirected_components(graph),
        "top_connected": top_connected,
        "top_venues": top_venues,
        "top_djs": top_djs,
        "shared_bookings": shared,
    }


def graph_to_dict(graph: BookingGraph) -> dict:
    return {
        "nodes": [
            {
                "id": n.id, "label": n.label, "kind": n.kind,
                "entity_type": n.entity_type, "score": n.score,
            }
            for n in graph.nodes.values()
        ],
        "edges": [
            {"source": e.source, "target": e.target, "relation": e.relation}
            for e in graph.edges
        ],
    }


def build_graph_from_db(session) -> tuple[BookingGraph, dict[str, float]]:
    """Load profiles + current scores from the DB and build the graph.

    Lazy ``repo`` import keeps this module otherwise pure/DB-free.
    """
    from scoredclub.db import repo

    entities = repo.all_entities(session)
    profiles = [repo.profile_from_row(e) for e in entities]
    scores = {e.entity_id: e.current_score for e in entities if e.current_score is not None}
    return build_booking_graph(profiles, scores), scores
