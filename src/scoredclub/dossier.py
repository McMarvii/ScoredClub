"""Steckbrief / dossier — a condensed profile sheet per DJ, venue or collective.

Pulls together the highlights of an entity: identity + key stats, the **top 10
songs**, **top 5 sets**, the **max. top 20 played/hosted parties**, the follower-
authenticity verdict, and the most important relationships (who they work with /
book / are booked by). Pure assembly over an :class:`EntityProfile`; the CLI and
API add the score and the booking-graph relationships.

Ranking is *source-based*, never black-box taste: tracks by an explicit
editorial rank then by plays, sets by plays then recency, parties by recency.
"""

from __future__ import annotations

import datetime as dt

from scoredclub.schemas import EntityProfile

TOP_TRACKS = 10
TOP_SETS = 5
TOP_PARTIES = 20


def _date_ordinal_desc(d: dt.date | None) -> int:
    # Undated items get 0 so they sort last under descending order.
    return d.toordinal() if d else 0


def _rank_tracks(tracks: list) -> list[dict]:
    # Explicitly ranked tracks first (by rank asc), then the rest by plays desc.
    ordered = sorted(
        tracks,
        key=lambda t: (t.rank if t.rank is not None else 10**9, -(t.plays or 0), t.title),
    )
    return [
        {"title": t.title, "artist": t.artist, "label": t.label, "url": t.url,
         "plays": t.plays, "released": t.released, "rank": t.rank, "source": t.source}
        for t in ordered[:TOP_TRACKS]
    ]


def _rank_sets(sets: list) -> list[dict]:
    ordered = sorted(sets, key=lambda s: (-(s.plays or 0), -_date_ordinal_desc(s.date), s.title))
    return [
        {"title": s.title, "venue": s.venue,
         "date": s.date.isoformat() if s.date else None,
         "url": s.url, "plays": s.plays, "duration_min": s.duration_min, "source": s.source}
        for s in ordered[:TOP_SETS]
    ]


def _rank_parties(parties: list) -> list[dict]:
    ordered = sorted(parties, key=lambda p: (-_date_ordinal_desc(p.date), p.name))
    return [
        {"name": p.name, "venue": p.venue,
         "date": p.date.isoformat() if p.date else None,
         "role": p.role, "url": p.url, "source": p.source}
        for p in ordered[:TOP_PARTIES]
    ]


def build_dossier(
    profile: EntityProfile,
    *,
    score: float | None = None,
    tier: str | None = None,
    relationships: dict | None = None,
) -> dict:
    """Assemble an entity's dossier. ``relationships`` comes from the booking graph."""
    from scoredclub.authenticity import assess, to_dict as authenticity_dict

    return {
        "entity_id": profile.entity_id,
        "name": profile.name,
        "type": profile.type.value,
        "district": profile.district,
        "status": profile.status.value,
        "active_since": profile.active_since,
        "score": score,
        "tier": tier,
        "follower_authenticity": authenticity_dict(assess(profile)),
        "top_tracks": _rank_tracks(profile.top_tracks),
        "top_sets": _rank_sets(profile.top_sets),
        "parties": _rank_parties(profile.parties),
        "counts": {
            "tracks": len(profile.top_tracks),
            "sets": len(profile.top_sets),
            "parties": len(profile.parties),
        },
        "relationships": relationships,
    }


def build_dossier_from_db(session, entity_id: str) -> dict | None:
    """Load an entity + its score + booking-graph relationships into a dossier."""
    from scoredclub.db import repo
    from scoredclub.graph import build_graph_from_db, entity_relationships

    entity = repo.get_entity(session, entity_id)
    if entity is None:
        return None
    profile = repo.profile_from_row(entity)
    graph, _ = build_graph_from_db(session)
    return build_dossier(
        profile,
        score=entity.current_score,
        tier=entity.tier,
        relationships=entity_relationships(graph, entity_id),
    )
