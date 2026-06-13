"""Repository helpers: upsert with dedup, queries, snapshots and alerts."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from scoredclub.db.models import Alert, Entity, EntityAlias, Run, ScoreSnapshot
from scoredclub.normalize import find_match, merge_profiles, normalize_name
from scoredclub.schemas import EntityProfile, ScoreBreakdown


def _profile_to_json(profile: EntityProfile) -> dict:
    return json.loads(profile.model_dump_json())


def profile_from_row(entity: Entity) -> EntityProfile:
    return EntityProfile.model_validate(entity.profile)


def all_entities(session: Session) -> list[Entity]:
    return list(session.scalars(select(Entity).order_by(Entity.entity_id)))


def get_entity(session: Session, entity_id: str) -> Entity | None:
    return session.get(Entity, entity_id)


def _sync_aliases(session: Session, entity: Entity, profile: EntityProfile) -> None:
    wanted = {normalize_name(a) for a in [profile.name, *profile.aliases] if a}
    existing = {a.alias_normalized for a in entity.aliases}
    for alias in wanted - existing:
        clash = session.scalar(
            select(EntityAlias).where(EntityAlias.alias_normalized == alias)
        )
        if clash is None:
            session.add(EntityAlias(entity_id=entity.entity_id, alias_normalized=alias))


def upsert_profile(
    session: Session,
    profile: EntityProfile,
    run_id: int | None = None,
    create_if_missing: bool = True,
) -> tuple[Entity | None, bool]:
    """Insert or merge a profile. Returns (entity, is_new).

    When ``create_if_missing`` is False and no existing entity matches, the
    profile is skipped and ``(None, False)`` is returned — used by enrichment
    collectors that must never introduce new entities.
    """
    existing_profiles = [profile_from_row(e) for e in all_entities(session)]
    match = find_match(profile, existing_profiles)

    if match is None and not create_if_missing:
        return None, False

    if match is not None:
        entity = session.get(Entity, match.entity_id)
        assert entity is not None
        merged = merge_profiles(match, profile)
        entity.profile = _profile_to_json(merged)
        entity.name = merged.name
        entity.name_normalized = normalize_name(merged.name)
        entity.type = merged.type.value
        entity.status = merged.status.value
        entity.district = merged.district
        entity.last_event_date = merged.last_event_date
        _sync_aliases(session, entity, merged)
        session.flush()
        return entity, False

    entity = Entity(
        entity_id=profile.entity_id,
        name=profile.name,
        name_normalized=normalize_name(profile.name),
        type=profile.type.value,
        status=profile.status.value,
        district=profile.district,
        last_event_date=profile.last_event_date,
        profile=_profile_to_json(profile),
        first_seen_run_id=run_id,
    )
    session.add(entity)
    session.flush()
    _sync_aliases(session, entity, profile)
    session.flush()
    return entity, True


def save_score(
    session: Session,
    run: Run,
    entity: Entity,
    breakdown: ScoreBreakdown,
) -> ScoreSnapshot:
    entity.current_score = breakdown.total
    entity.tier = breakdown.tier
    snapshot = ScoreSnapshot(
        run_id=run.id,
        entity_id=entity.entity_id,
        score=breakdown.total,
        tier=breakdown.tier,
        status=entity.status,
        breakdown=json.loads(breakdown.model_dump_json()),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def previous_run(session: Session, current_run_id: int) -> Run | None:
    return session.scalar(
        select(Run)
        .where(Run.id != current_run_id, Run.finished_at.is_not(None))
        .order_by(Run.id.desc())
        .limit(1)
    )


def snapshots_for_run(session: Session, run_id: int) -> dict[str, ScoreSnapshot]:
    rows = session.scalars(select(ScoreSnapshot).where(ScoreSnapshot.run_id == run_id))
    return {s.entity_id: s for s in rows}


def score_history(session: Session, entity_id: str) -> list[ScoreSnapshot]:
    return list(
        session.scalars(
            select(ScoreSnapshot)
            .where(ScoreSnapshot.entity_id == entity_id)
            .order_by(ScoreSnapshot.run_id)
        )
    )


def start_run(session: Session) -> Run:
    run = Run()
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    run: Run,
    entities_tracked: int,
    new_entities_found: int,
    report_md_path: str | None,
    report_json_path: str | None,
    finished_at: datetime,
) -> None:
    run.entities_tracked = entities_tracked
    run.new_entities_found = new_entities_found
    run.report_md_path = report_md_path
    run.report_json_path = report_json_path
    run.finished_at = finished_at
    session.flush()


def add_alert(
    session: Session,
    run: Run,
    entity_id: str,
    alert_type: str,
    message: str,
    old_value: str | None = None,
    new_value: str | None = None,
    delta: float | None = None,
) -> Alert:
    alert = Alert(
        run_id=run.id,
        entity_id=entity_id,
        alert_type=alert_type,
        message=message,
        old_value=old_value,
        new_value=new_value,
        delta=delta,
    )
    session.add(alert)
    session.flush()
    return alert
