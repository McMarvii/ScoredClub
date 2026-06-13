"""LLM research ingest — the primary data path.

A research agent (e.g. Claude with web search) produces a JSON file of
entity profiles conforming to :class:`~scoredclub.schemas.EntityProfile`.
This module validates each entry individually (partial ingest: valid
entries are ingested, invalid ones reported with their index) and upserts
them with dedup/merge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from scoredclub.db import repo
from scoredclub.schemas import EntityProfile


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    new_entities: list[str] = field(default_factory=list)
    merged_entities: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_research_file(path: str | Path) -> list[dict]:
    """Accepts a bare JSON array or ``{"entities": [...]}``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        entities = data.get("entities")
        if not isinstance(entities, list):
            raise ValueError("JSON object must contain an 'entities' array")
        return entities
    if isinstance(data, list):
        return data
    raise ValueError("Research file must be a JSON array or an object with 'entities'")


def validate_entries(entries: list[dict]) -> tuple[list[EntityProfile], list[str]]:
    profiles: list[EntityProfile] = []
    errors: list[str] = []
    for index, entry in enumerate(entries):
        try:
            profiles.append(EntityProfile.model_validate(entry))
        except ValidationError as exc:
            name = entry.get("name", "<unnamed>") if isinstance(entry, dict) else "<invalid>"
            first = exc.errors()[0]
            errors.append(
                f"entity[{index}] '{name}': {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
            )
    return profiles, errors


def ingest_entries(
    session: Session, entries: list[dict], run_id: int | None = None, dry_run: bool = False
) -> IngestReport:
    """Validate and upsert already-parsed entries (e.g. from an API body)."""
    report = IngestReport()
    profiles, errors = validate_entries(entries)
    report.errors.extend(errors)
    if dry_run:
        report.ingested = [p.entity_id for p in profiles]
        return report

    for profile in profiles:
        entity, is_new = repo.upsert_profile(session, profile, run_id=run_id)
        report.ingested.append(entity.entity_id)
        (report.new_entities if is_new else report.merged_entities).append(entity.entity_id)
    return report


def ingest_file(
    session: Session, path: str | Path, run_id: int | None = None, dry_run: bool = False
) -> IngestReport:
    report = IngestReport()
    try:
        entries = load_research_file(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.errors.append(f"cannot read {path}: {exc}")
        return report
    return ingest_entries(session, entries, run_id=run_id, dry_run=dry_run)
