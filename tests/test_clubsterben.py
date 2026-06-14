from __future__ import annotations

import datetime as dt

from scoredclub.clubsterben import build_register, build_register_from_db, register_to_dict
from scoredclub.db import repo
from scoredclub.normalize import merge_profiles
from scoredclub.schemas import (
    DisplacementSignal,
    EntityProfile,
    EntityStatus,
    EntityType,
    LifecycleEvent,
    LifecycleEventType,
)


def _profile(entity_id, name, *, status=EntityStatus.active, events=None, signals=None):
    return EntityProfile(
        entity_id=entity_id, name=name, type=EntityType.club, status=status,
        lifecycle_events=events or [], displacement_signals=signals or [],
    )


def test_counts_openings_closures_and_net():
    profiles = [
        _profile("a", "A", events=[
            LifecycleEvent(date=dt.date(2024, 5, 1), event_type=LifecycleEventType.opening),
        ]),
        _profile("b", "B", status=EntityStatus.closed, events=[
            LifecycleEvent(date=dt.date(2025, 3, 1), event_type=LifecycleEventType.closure, cause="rent"),
        ]),
        _profile("c", "C", status=EntityStatus.closed, events=[
            LifecycleEvent(date=dt.date(2025, 7, 1), event_type=LifecycleEventType.closure, cause="redevelopment"),
        ]),
    ]
    reg = build_register(profiles)
    assert reg.openings == 1
    assert reg.closures == 2
    assert reg.net_change == -1
    assert reg.closures_by_cause == {"rent": 1, "redevelopment": 1}


def test_by_year_breakdown():
    profiles = [
        _profile("a", "A", events=[
            LifecycleEvent(date=dt.date(2024, 1, 1), event_type=LifecycleEventType.opening),
            LifecycleEvent(date=dt.date(2025, 1, 1), event_type=LifecycleEventType.closure, cause="noise"),
        ]),
    ]
    reg = build_register(profiles)
    assert reg.by_year["2024"]["openings"] == 1
    assert reg.by_year["2025"]["closures"] == 1


def test_at_risk_from_status_signal_and_threat():
    profiles = [
        _profile("closed", "Closed", status=EntityStatus.closed),
        _profile("signal", "Signal", signals=[
            DisplacementSignal(signal_type="rent_increase", description="+30%"),
        ]),
        _profile("threatened", "Threatened", events=[
            LifecycleEvent(event_type=LifecycleEventType.threatened, description="Abriss geplant"),
        ]),
        _profile("safe", "Safe"),
    ]
    reg = build_register(profiles)
    at_risk_ids = {item["entity_id"] for item in reg.at_risk}
    assert at_risk_ids == {"closed", "signal", "threatened"}
    signal = next(i for i in reg.at_risk if i["entity_id"] == "signal")
    assert signal["displacement_signals"] == ["rent_increase"]


def test_recent_events_sorted_desc():
    profiles = [
        _profile("a", "A", events=[
            LifecycleEvent(date=dt.date(2023, 1, 1), event_type=LifecycleEventType.opening),
            LifecycleEvent(date=dt.date(2025, 1, 1), event_type=LifecycleEventType.closure, cause="rent"),
        ]),
    ]
    reg = build_register(profiles)
    assert [e["date"] for e in reg.recent_events] == ["2025-01-01", "2023-01-01"]


def test_empty_register():
    reg = build_register([_profile("a", "A")])
    assert reg.openings == 0 and reg.closures == 0 and reg.at_risk == []
    assert register_to_dict(reg)["net_change"] == 0


def test_merge_unions_lifecycle_and_displacement():
    existing = _profile("a", "A", events=[
        LifecycleEvent(date=dt.date(2024, 1, 1), event_type=LifecycleEventType.opening),
    ])
    incoming = EntityProfile(
        entity_id="a", name="A",
        lifecycle_events=[LifecycleEvent(date=dt.date(2025, 1, 1), event_type=LifecycleEventType.closure, cause="rent")],
        displacement_signals=[DisplacementSignal(signal_type="property_sale")],
    )
    merged = merge_profiles(existing, incoming)
    assert len(merged.lifecycle_events) == 2
    assert len(merged.displacement_signals) == 1


def test_build_register_from_db(session):
    repo.upsert_profile(session, _profile("b", "B", status=EntityStatus.closed, events=[
        LifecycleEvent(date=dt.date(2025, 3, 1), event_type=LifecycleEventType.closure, cause="rent"),
    ]))
    reg = build_register_from_db(session)
    assert reg.closures == 1
    assert reg.closures_by_cause == {"rent": 1}
