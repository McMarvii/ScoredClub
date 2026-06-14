"""Clubsterben register — cultural-ecosystem monitoring for Berlin.

Aggregates the per-entity ``lifecycle_events`` (openings / closures / relocations
with a cause taxonomy) and ``displacement_signals`` into a scene-wide register:
openings vs closures over time, the causes behind closures, and a watchlist of
venues currently at risk. A defensible, Berlin-specific angle on top of the
generic scoring. Pure functions over profiles; the CLI and API surface it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from scoredclub.schemas import (
    EntityProfile,
    EntityStatus,
    LifecycleEventType,
)


@dataclass
class RegisterSummary:
    openings: int = 0
    closures: int = 0
    net_change: int = 0
    closures_by_cause: dict[str, int] = field(default_factory=dict)
    by_year: dict[str, dict[str, int]] = field(default_factory=dict)
    at_risk: list[dict] = field(default_factory=list)
    recent_events: list[dict] = field(default_factory=list)


def _is_at_risk(profile: EntityProfile) -> bool:
    if profile.status in (EntityStatus.closed, EntityStatus.inactive):
        return True
    if profile.displacement_signals:
        return True
    return any(
        e.event_type == LifecycleEventType.threatened for e in profile.lifecycle_events
    )


def build_register(profiles: list[EntityProfile], recent_limit: int = 20) -> RegisterSummary:
    summary = RegisterSummary()
    causes: Counter[str] = Counter()
    by_year: dict[str, dict[str, int]] = defaultdict(lambda: {"openings": 0, "closures": 0})
    events: list[dict] = []

    for profile in profiles:
        for event in profile.lifecycle_events:
            year = event.date.isoformat()[:4] if event.date else "unbekannt"
            if event.event_type in (LifecycleEventType.opening, LifecycleEventType.reopening):
                summary.openings += 1
                by_year[year]["openings"] += 1
            elif event.event_type == LifecycleEventType.closure:
                summary.closures += 1
                by_year[year]["closures"] += 1
                causes[(event.cause.value if event.cause else "unknown")] += 1
            events.append(
                {
                    "entity_id": profile.entity_id,
                    "name": profile.name,
                    "date": event.date.isoformat() if event.date else None,
                    "event_type": event.event_type.value,
                    "cause": event.cause.value if event.cause else None,
                    "description": event.description,
                }
            )

        if _is_at_risk(profile):
            summary.at_risk.append(
                {
                    "entity_id": profile.entity_id,
                    "name": profile.name,
                    "status": profile.status.value,
                    "district": profile.district,
                    "displacement_signals": [
                        s.signal_type.value for s in profile.displacement_signals
                    ],
                }
            )

    summary.net_change = summary.openings - summary.closures
    summary.closures_by_cause = dict(causes.most_common())
    summary.by_year = {y: by_year[y] for y in sorted(by_year)}
    # Most recent events first; undated events sort last.
    events.sort(key=lambda e: e["date"] or "", reverse=True)
    summary.recent_events = events[:recent_limit]
    return summary


def build_register_from_db(session, recent_limit: int = 20) -> RegisterSummary:
    """Load profiles and build the register (lazy ``repo`` import)."""
    from scoredclub.db import repo

    profiles = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    return build_register(profiles, recent_limit=recent_limit)


def register_to_dict(summary: RegisterSummary) -> dict:
    return {
        "openings": summary.openings,
        "closures": summary.closures,
        "net_change": summary.net_change,
        "closures_by_cause": summary.closures_by_cause,
        "by_year": summary.by_year,
        "at_risk": summary.at_risk,
        "recent_events": summary.recent_events,
    }
