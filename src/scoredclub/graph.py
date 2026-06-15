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
        "top_collaborations": collaboration_pairs(graph, top=top),
        "most_collaborative": most_collaborative(graph, top=top),
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


# --- collaboration / relationship ranking ------------------------------------
# "Who works with / books whom the most." A collaboration between two nodes is
# weighted from three signals: a direct edge (strongest), booking the same DJ,
# or playing the same venue.
WEIGHT_DIRECT = 3
WEIGHT_SHARED_DJ = 2
WEIGHT_SHARED_VENUE = 1


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _collaboration_index(graph: BookingGraph) -> dict[tuple[str, str], dict]:
    """Build, per unordered node pair, the direct/shared-DJ/shared-venue counts."""
    pairs: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"direct": 0, "shared_djs": 0, "shared_venues": 0}
    )

    dj_bookers: dict[str, set[str]] = defaultdict(set)
    venue_artists: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.source != edge.target:
            pairs[_pair_key(edge.source, edge.target)]["direct"] += 1
        if edge.relation == REL_BOOKS:
            dj_bookers[edge.target].add(edge.source)
        elif edge.relation == REL_PLAYED_AT:
            venue_artists[edge.target].add(edge.source)

    for bookers in dj_bookers.values():
        for a, b in combinations(sorted(bookers), 2):
            pairs[_pair_key(a, b)]["shared_djs"] += 1
    for artists in venue_artists.values():
        for a, b in combinations(sorted(artists), 2):
            pairs[_pair_key(a, b)]["shared_venues"] += 1
    return pairs


def _weight(counts: dict) -> int:
    return (
        WEIGHT_DIRECT * counts["direct"]
        + WEIGHT_SHARED_DJ * counts["shared_djs"]
        + WEIGHT_SHARED_VENUE * counts["shared_venues"]
    )


def collaboration_pairs(graph: BookingGraph, top: int = 20) -> list[dict]:
    """Strongest "works-with" node pairs, ranked by weighted collaboration."""
    label = {nid: node.label for nid, node in graph.nodes.items()}
    rows = []
    for (a, b), counts in _collaboration_index(graph).items():
        weight = _weight(counts)
        if weight <= 0:
            continue
        rows.append({
            "a": a, "a_label": label.get(a, a),
            "b": b, "b_label": label.get(b, b),
            "weight": weight,
            "direct": counts["direct"],
            "shared_djs": counts["shared_djs"],
            "shared_venues": counts["shared_venues"],
        })
    rows.sort(key=lambda r: (-r["weight"], r["a"], r["b"]))
    return rows[:top]


def most_collaborative(graph: BookingGraph, top: int = 20) -> list[dict]:
    """Entities ranked by how many partners they work with (and total weight)."""
    label = {nid: node.label for nid, node in graph.nodes.items()}
    by_node: dict[str, dict] = defaultdict(lambda: {"collaborators": 0, "weight": 0})
    for (a, b), counts in _collaboration_index(graph).items():
        weight = _weight(counts)
        if weight <= 0:
            continue
        for node in (a, b):
            by_node[node]["collaborators"] += 1
            by_node[node]["weight"] += weight
    rows = [
        {"id": nid, "label": label.get(nid, nid),
         "collaborators": v["collaborators"], "weight": v["weight"]}
        for nid, v in by_node.items()
    ]
    rows.sort(key=lambda r: (-r["collaborators"], -r["weight"], r["id"]))
    return rows[:top]


def entity_relationships(graph: BookingGraph, entity_id: str) -> dict:
    """Who an entity works with: books / booked-by / collaborates / venues / shared."""
    label = {nid: node.label for nid, node in graph.nodes.items()}

    def lab(nid: str) -> dict:
        return {"id": nid, "label": label.get(nid, nid)}

    books, booked_by, collaborates, cross, played_venues, played_by = ([] for _ in range(6))
    for edge in graph.edges:
        if edge.source == entity_id:
            if edge.relation == REL_BOOKS:
                books.append(lab(edge.target))
            elif edge.relation == REL_PLAYED_AT:
                played_venues.append(lab(edge.target))
            elif edge.relation == REL_COLLABORATES:
                collaborates.append(lab(edge.target))
            elif edge.relation == REL_CROSS_PROMOTES:
                cross.append(lab(edge.target))
        elif edge.target == entity_id:
            if edge.relation == REL_BOOKS:
                booked_by.append(lab(edge.source))
            elif edge.relation == REL_PLAYED_AT:
                played_by.append(lab(edge.source))
            elif edge.relation == REL_COLLABORATES:
                collaborates.append(lab(edge.source))
            elif edge.relation == REL_CROSS_PROMOTES:
                cross.append(lab(edge.source))

    shared = []
    for (a, b), counts in _collaboration_index(graph).items():
        if entity_id in (a, b) and counts["shared_djs"] > 0:
            other = b if a == entity_id else a
            shared.append({**lab(other), "shared_djs": counts["shared_djs"]})
    shared.sort(key=lambda r: (-r["shared_djs"], r["id"]))

    return {
        "entity_id": entity_id,
        "name": label.get(entity_id, entity_id),
        "books": books,
        "booked_by": booked_by,
        "collaborates_with": collaborates,
        "cross_promotes": cross,
        "played_venues": played_venues,
        "played_by": played_by,
        "shared_booking_partners": shared,
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
