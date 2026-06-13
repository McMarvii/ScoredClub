"""Full pipeline orchestration for `scoredclub run`."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from scoredclub.collectors import DISCOVERY_COLLECTORS, ENRICHMENT_COLLECTORS
from scoredclub.collectors.llm_ingest import IngestReport, ingest_file
from scoredclub.config import Settings
from scoredclub.db import init_db, repo
from scoredclub.db.models import Entity
from scoredclub.pipeline.alerts import create_alerts, deliver_webhooks
from scoredclub.pipeline.diff import diff_runs
from scoredclub.reports.render import ScoredEntity, write_reports
from scoredclub.schemas import EntityProfile, utcnow
from scoredclub.scoring import score_entity
from scoredclub.trending import RunScores, TrendReport, compute_trends

logger = logging.getLogger(__name__)

SEED_FILE = Path("data/seeds/berlin_seed_entities.json")


def compute_run_trends(session: Session, settings: Settings) -> TrendReport:
    """Compute trends from the recent score history and persist them.

    Loads the last ``momentum_window`` runs (including the current one, whose
    score snapshots have already been saved), computes per-entity trends and
    cross-entity movers, and stores a trend snapshot per entity for the latest
    run.
    """
    cfg = settings.trending
    runs = repo.recent_runs(session, cfg.momentum_window)
    if not runs:
        return TrendReport(trends={}, risers=[], fallers=[])
    run_ids = [r.id for r in runs]
    series = repo.run_score_series(session, run_ids)
    ordered = [RunScores(run_id=rid, scores=series.get(rid, {})) for rid in run_ids]
    report = compute_trends(
        ordered,
        momentum_window=cfg.momentum_window,
        stable_epsilon=cfg.stable_epsilon,
        movers_limit=cfg.movers_limit,
    )
    latest_run_id = run_ids[-1]
    for trend in report.trends.values():
        repo.save_trend(session, latest_run_id, trend)
    session.flush()
    return report


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


def seed_entity_ids(seed_file: Path = SEED_FILE) -> set[str]:
    """The entity_ids of the seed/start list (used to flag off-seed finds)."""
    if not seed_file.exists():
        return set()
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    return {
        EntityProfile.model_validate(entry).entity_id
        for entry in data.get("entities", [])
    }


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
        # Discovery collectors may introduce new entities.
        for collector_cls in DISCOVERY_COLLECTORS:
            result = collector_cls().collect(settings)
            summary.warnings.extend(result.warnings)
            for profile in result.profiles:
                repo.upsert_profile(session, profile, run_id=run.id)
        # Enrichment collectors augment the current entities only.
        current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
        for collector_cls in ENRICHMENT_COLLECTORS:
            result = collector_cls().collect(settings, entities=current)
            summary.warnings.extend(result.warnings)
            for profile in result.profiles:
                repo.upsert_profile(
                    session, profile, run_id=run.id, create_if_missing=False
                )

    # District-based geocoding: fill empty geo from the entity's district.
    if settings.run.geocode_districts:
        from scoredclub.geocode import apply_geocoding

        for entity in repo.all_entities(session):
            profile = repo.profile_from_row(entity)
            if apply_geocoding(profile):
                entity.profile = json.loads(profile.model_dump_json())
        session.flush()

    seed_ids = seed_entity_ids()
    entities: list[Entity] = repo.all_entities(session)
    scored: list[ScoredEntity] = []
    for entity in entities:
        profile = repo.profile_from_row(entity)
        breakdown = score_entity(profile, settings.scoring, today=run_date)
        repo.save_score(session, run, entity, breakdown)
        scored.append(
            ScoredEntity(
                profile=profile,
                breakdown=breakdown,
                discovered=entity.entity_id not in seed_ids,
            )
        )

    diff = diff_runs(session, run)
    delta_by_id = {d.entity_id: d for d in diff.deltas}
    for item in scored:
        delta = delta_by_id.get(item.profile.entity_id)
        if delta:
            item.delta = delta.score_delta
            item.is_new = delta.is_new

    alerts = create_alerts(session, run, diff, settings)
    deliver_webhooks(alerts, settings)

    # Compute and persist trends from the score history (incl. this run).
    trend_report = compute_run_trends(session, settings)
    trend_by_id = trend_report.trends
    for item in scored:
        trend = trend_by_id.get(item.profile.entity_id)
        if trend:
            item.trend = {
                "direction": trend.direction,
                "score_delta": trend.score_delta,
                "rank": trend.rank,
                "rank_delta": trend.rank_delta,
                "momentum": trend.momentum,
                "sparkline": trend.sparkline,
            }

    md_path, json_path, _ = write_reports(
        scored, diff, alerts, run_date, settings, trend_report=trend_report
    )

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
