"""Full pipeline orchestration for `scoredclub run`."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from scoredclub.collectors import NETWORK_COLLECTORS
from scoredclub.collectors.llm_ingest import IngestReport, ingest_file
from scoredclub.config import Settings
from scoredclub.db import init_db, repo
from scoredclub.db.models import Entity
from scoredclub.pipeline.alerts import create_alerts, deliver_webhooks
from scoredclub.pipeline.diff import diff_runs
from scoredclub.reports.render import ScoredEntity, write_reports
from scoredclub.schemas import EntityProfile, utcnow
from scoredclub.scoring import score_entity

logger = logging.getLogger(__name__)

SEED_FILE = Path("data/seeds/berlin_seed_entities.json")


@dataclass
class RunSummary:
    run_id: int
    entities_tracked: int = 0
    new_entities: int = 0
    alerts: int = 0
    warnings: list[str] = field(default_factory=list)
    report_md: str | None = None
    report_json: str | None = None
    ingest_report: IngestReport | None = None


def seed_entities(session: Session, seed_file: Path = SEED_FILE) -> int:
    """Load seed entities (idempotent — dedup handles re-seeding)."""
    if not seed_file.exists():
        logger.warning("seed file %s not found, skipping", seed_file)
        return 0
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    count = 0
    for entry in data.get("entities", []):
        profile = EntityProfile.model_validate(entry)
        _, is_new = repo.upsert_profile(session, profile)
        count += int(is_new)
    session.commit()
    return count


def execute_run(
    session: Session,
    settings: Settings,
    research_file: str | Path | None = None,
    skip_collectors: bool = False,
    run_date: date | None = None,
) -> RunSummary:
    run_date = run_date or date.today()

    # Ensure seeds exist on first run.
    if not repo.all_entities(session):
        seeded = seed_entities(session)
        logger.info("seeded %d entities", seeded)

    run = repo.start_run(session)
    summary = RunSummary(run_id=run.id)

    if research_file:
        summary.ingest_report = ingest_file(session, research_file, run_id=run.id)
        summary.warnings.extend(summary.ingest_report.errors)

    if not skip_collectors:
        for collector_cls in NETWORK_COLLECTORS:
            result = collector_cls().collect(settings)
            summary.warnings.extend(result.warnings)
            for profile in result.profiles:
                repo.upsert_profile(session, profile, run_id=run.id)

    entities: list[Entity] = repo.all_entities(session)
    scored: list[ScoredEntity] = []
    for entity in entities:
        profile = repo.profile_from_row(entity)
        breakdown = score_entity(profile, settings.scoring, today=run_date)
        repo.save_score(session, run, entity, breakdown)
        scored.append(ScoredEntity(profile=profile, breakdown=breakdown))

    diff = diff_runs(session, run)
    delta_by_id = {d.entity_id: d for d in diff.deltas}
    for item in scored:
        delta = delta_by_id.get(item.profile.entity_id)
        if delta:
            item.delta = delta.score_delta
            item.is_new = delta.is_new

    alerts = create_alerts(session, run, diff, settings)
    deliver_webhooks(alerts, settings)

    md_path, json_path, _ = write_reports(scored, diff, alerts, run_date, settings)

    repo.finish_run(
        session,
        run,
        entities_tracked=len(scored),
        new_entities_found=len(diff.new_entities),
        report_md_path=str(md_path),
        report_json_path=str(json_path),
        finished_at=utcnow(),
    )
    session.commit()

    summary.entities_tracked = len(scored)
    summary.new_entities = len(diff.new_entities)
    summary.alerts = len(alerts)
    summary.report_md = str(md_path)
    summary.report_json = str(json_path)
    return summary


def prepare_database(settings: Settings) -> None:
    init_db(settings.database_url)
