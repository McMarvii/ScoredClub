"""Run-vs-run comparison."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from scoredclub.db import repo
from scoredclub.db.models import Run


@dataclass
class EntityDelta:
    entity_id: str
    name: str
    old_score: float | None
    new_score: float
    old_status: str | None
    new_status: str
    is_new: bool

    @property
    def score_delta(self) -> float | None:
        if self.old_score is None:
            return None
        return round(self.new_score - self.old_score, 2)


@dataclass
class RunDiff:
    deltas: list[EntityDelta] = field(default_factory=list)

    @property
    def new_entities(self) -> list[EntityDelta]:
        return [d for d in self.deltas if d.is_new]

    def score_changes(self, threshold: float) -> list[EntityDelta]:
        return [
            d
            for d in self.deltas
            if d.score_delta is not None and abs(d.score_delta) > threshold
        ]

    @property
    def status_changes(self) -> list[EntityDelta]:
        return [
            d
            for d in self.deltas
            if d.old_status is not None and d.old_status != d.new_status
        ]


def diff_runs(session: Session, current_run: Run) -> RunDiff:
    previous = repo.previous_run(session, current_run.id)
    old_snapshots = repo.snapshots_for_run(session, previous.id) if previous else {}
    current_snapshots = repo.snapshots_for_run(session, current_run.id)

    diff = RunDiff()
    for entity_id, snapshot in sorted(current_snapshots.items()):
        entity = repo.get_entity(session, entity_id)
        old = old_snapshots.get(entity_id)
        diff.deltas.append(
            EntityDelta(
                entity_id=entity_id,
                name=entity.name if entity else entity_id,
                old_score=old.score if old else None,
                new_score=snapshot.score,
                old_status=old.status if old else None,
                new_status=snapshot.status,
                is_new=old is None and previous is not None,
            )
        )
    return diff
