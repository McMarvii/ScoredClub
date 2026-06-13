"""Typer CLI — entrypoint `scoredclub`."""

from __future__ import annotations

import json
import logging
from datetime import date as date_type
from pathlib import Path

import typer

from scoredclub import __version__
from scoredclub.config import Settings
from scoredclub.db import get_session, init_db, repo
from scoredclub.scoring import score_entity

app = typer.Typer(
    name="scoredclub",
    help="Berlin Techno Collective & Club Intelligence System",
    no_args_is_help=True,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _settings(config: str | None = None) -> Settings:
    return Settings.load(config)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"scoredclub {__version__}")


@app.command("init-db")
def init_db_cmd(config: str = typer.Option(None, help="Path to config JSON")) -> None:
    """Create database tables."""
    settings = _settings(config)
    init_db(settings.database_url)
    typer.echo(f"Database initialized ({settings.database_url})")


@app.command()
def seed(config: str = typer.Option(None, help="Path to config JSON")) -> None:
    """Load the Berlin seed entities."""
    from scoredclub.pipeline.run import seed_entities

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        count = seed_entities(session)
    typer.echo(f"Seeded {count} new entities")


@app.command()
def ingest(
    file: Path = typer.Argument(..., help="Research JSON (array or {entities: [...]})"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only, do not write"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Validate and ingest an LLM research file."""
    from scoredclub.collectors.llm_ingest import ingest_file

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        report = ingest_file(session, file, dry_run=dry_run)
        if not dry_run:
            session.commit()

    action = "validated" if dry_run else "ingested"
    typer.echo(f"{len(report.ingested)} entities {action}")
    if report.new_entities:
        typer.echo(f"  new: {', '.join(report.new_entities)}")
    if report.merged_entities:
        typer.echo(f"  merged: {', '.join(report.merged_entities)}")
    for error in report.errors:
        typer.secho(f"  ERROR {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def score(
    entity_id: str = typer.Argument(None, help="Score a single entity (default: all)"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """(Re)score entities and print breakdowns — no run, no report."""
    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        entities = (
            [repo.get_entity(session, entity_id)] if entity_id else repo.all_entities(session)
        )
        if entity_id and entities[0] is None:
            typer.secho(f"Entity '{entity_id}' not found", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        for entity in entities:
            profile = repo.profile_from_row(entity)
            breakdown = score_entity(profile, settings.scoring)
            entity.current_score = breakdown.total
            entity.tier = breakdown.tier
            points = " ".join(f"{k.split('_')[0]}={v}" for k, v in breakdown.points.items())
            typer.echo(
                f"{entity.entity_id:30s} {breakdown.total:6.1f} {breakdown.tier:22s} {points} "
                f"bonus=+{breakdown.bonus:.0f} malus=-{breakdown.malus:.0f}"
            )
        session.commit()


@app.command()
def run(
    research: Path = typer.Option(None, help="LLM research JSON to ingest"),
    skip_collectors: bool = typer.Option(False, help="Skip network collectors"),
    date: str = typer.Option(None, help="Run date YYYY-MM-DD (default: today)"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Full pipeline: ingest -> collect -> score -> diff -> alerts -> reports."""
    from scoredclub.pipeline.run import execute_run

    settings = _settings(config)
    init_db(settings.database_url)
    run_date = date_type.fromisoformat(date) if date else None
    with get_session(settings.database_url) as session:
        summary = execute_run(
            session,
            settings,
            research_file=research,
            skip_collectors=skip_collectors,
            run_date=run_date,
        )
    typer.echo(f"Run #{summary.run_id} finished")
    typer.echo(f"  entities tracked: {summary.entities_tracked}")
    typer.echo(f"  new entities:     {summary.new_entities}")
    typer.echo(f"  alerts:           {summary.alerts}")
    typer.echo(f"  report:           {summary.report_md}")
    typer.echo(f"  entities json:    {summary.report_json}")
    for warning in summary.warnings:
        typer.secho(f"  WARN {warning}", fg=typer.colors.YELLOW)


@app.command()
def report(
    run_id: int = typer.Option(None, help="Run to re-render (default: latest)"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Re-render reports for an existing run."""
    from scoredclub.pipeline.diff import diff_runs
    from scoredclub.reports.render import ScoredEntity, write_reports
    from scoredclub.schemas import ScoreBreakdown
    from sqlalchemy import select

    from scoredclub.db.models import Alert, Run

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        if run_id is None:
            run_row = session.scalar(select(Run).order_by(Run.id.desc()).limit(1))
        else:
            run_row = session.get(Run, run_id)
        if run_row is None:
            typer.secho("No run found", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        snapshots = repo.snapshots_for_run(session, run_row.id)
        scored = []
        for entity_id, snapshot in snapshots.items():
            entity = repo.get_entity(session, entity_id)
            scored.append(
                ScoredEntity(
                    profile=repo.profile_from_row(entity),
                    breakdown=ScoreBreakdown.model_validate(snapshot.breakdown),
                )
            )
        diff = diff_runs(session, run_row)
        alerts = list(session.scalars(select(Alert).where(Alert.run_id == run_row.id)))
        run_date = run_row.started_at.date()
        md_path, json_path, next_path = write_reports(scored, diff, alerts, run_date, settings)
    typer.echo(f"Re-rendered: {md_path}, {json_path}, {next_path}")


@app.command("list")
def list_cmd(
    type: str = typer.Option(None, help="Filter by type (club|collective|label|series)"),
    tier: str = typer.Option(None, help="Filter by tier"),
    status: str = typer.Option(None, help="Filter by status"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """List tracked entities."""
    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        entities = repo.all_entities(session)
        for entity in entities:
            if type and entity.type != type:
                continue
            if tier and (entity.tier or "") != tier:
                continue
            if status and entity.status != status:
                continue
            score_str = f"{entity.current_score:6.1f}" if entity.current_score is not None else "     -"
            typer.echo(
                f"{entity.entity_id:30s} {entity.type:10s} {score_str} "
                f"{entity.tier or '-':22s} {entity.status}"
            )


@app.command()
def show(
    entity_id: str = typer.Argument(...),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Show full profile, latest breakdown and score history."""
    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        entity = repo.get_entity(session, entity_id)
        if entity is None:
            typer.secho(f"Entity '{entity_id}' not found", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        typer.echo(json.dumps(entity.profile, indent=2, ensure_ascii=False))
        history = repo.score_history(session, entity_id)
        if history:
            typer.echo("\nScore-Historie:")
            for snapshot in history:
                typer.echo(f"  run {snapshot.run_id}: {snapshot.score:6.1f} ({snapshot.tier})")


@app.command()
def trending(
    movers: int = typer.Option(5, help="How many risers/fallers to show"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Show the latest run's trends: risers, fallers and the leaderboard."""
    _ARROWS = {"rising": "▲", "falling": "▼", "stable": "→", "new": "✦"}
    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        run = repo.latest_run(session)
        if run is None:
            typer.echo("No runs yet. Run 'scoredclub run' first.")
            return
        trends = repo.trends_for_run(session, run.id)
        if not trends:
            typer.echo("No trend data for the latest run.")
            return
        names = {e.entity_id: e.name for e in repo.all_entities(session)}
        rows = [t for t in trends.values() if t.score_delta is not None]
        risers = sorted((t for t in rows if t.score_delta > 0), key=lambda t: t.score_delta, reverse=True)[:movers]
        fallers = sorted((t for t in rows if t.score_delta < 0), key=lambda t: t.score_delta)[:movers]

        if risers:
            typer.secho("Aufsteiger:", fg=typer.colors.GREEN)
            for t in risers:
                typer.echo(f"  ▲ {names.get(t.entity_id, t.entity_id):24s} {t.score:6.1f}  (Δ {t.score_delta:+.1f})")
        if fallers:
            typer.secho("Absteiger:", fg=typer.colors.RED)
            for t in fallers:
                typer.echo(f"  ▼ {names.get(t.entity_id, t.entity_id):24s} {t.score:6.1f}  (Δ {t.score_delta:+.1f})")
        typer.echo("\nLeaderboard:")
        for t in sorted(trends.values(), key=lambda t: t.rank):
            arrow = _ARROWS.get(t.direction, "·")
            rank_delta = f"({t.rank_delta:+d})" if t.rank_delta else "    "
            typer.echo(f"  {t.rank:2d}. {arrow} {names.get(t.entity_id, t.entity_id):24s} {t.score:6.1f} {rank_delta}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    """Start the FastAPI read API."""
    import uvicorn

    uvicorn.run("scoredclub.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
