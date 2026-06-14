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
    """Create database tables (quick path; use 'migrate' for Postgres/production)."""
    settings = _settings(config)
    init_db(settings.database_url)
    typer.echo(f"Database initialized ({settings.database_url})")


def _alembic_config(database_url: str):
    """Build an Alembic config pointing at the migrations bundled in the package.

    Works from an installed wheel (no alembic.ini / project checkout needed).
    """
    from alembic.config import Config

    import scoredclub

    migrations_dir = Path(scoredclub.__file__).resolve().parent / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg, migrations_dir


@app.command()
def migrate(
    revision: str = typer.Option("head", help="Target revision"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Apply Alembic migrations — the managed schema path for Postgres/production."""
    from alembic import command

    settings = _settings(config)
    cfg, migrations_dir = _alembic_config(settings.database_url)
    if not migrations_dir.exists():
        typer.secho("Bundled migrations not found in the package.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    command.upgrade(cfg, revision)
    typer.echo(f"Migrated to '{revision}' ({settings.database_url})")


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
            conf_flag = " ⚠low-conf" if breakdown.low_confidence else ""
            typer.echo(
                f"{entity.entity_id:30s} {breakdown.total:6.1f} {breakdown.tier:22s} {points} "
                f"bonus=+{breakdown.bonus:.0f} malus=-{breakdown.malus:.0f} "
                f"conf={breakdown.confidence:.0f}%{conf_flag}"
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
def analytics(
    breakouts_only: bool = typer.Option(False, "--breakouts-only", help="Only entities flagged as a breakout"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Breakout detection, career phase and short-term forecast over the history."""
    from scoredclub.analytics import BUCKET_NONE, BUCKET_INSUFFICIENT, compute_intelligence

    _BUCKET = {"growth": "↑ growth", "strong": "⇈ strong", "explosive": "★ explosive"}
    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        intel, run_ids = compute_intelligence(session, settings)
        if not intel:
            typer.echo("No score history yet. Run 'scoredclub run' first.")
            return
        names = {e.entity_id: e.name for e in repo.all_entities(session)}
        rows = sorted(intel.values(), key=lambda i: i.current_score, reverse=True)
        breakouts = [i for i in rows if i.breakout.bucket not in (BUCKET_NONE, BUCKET_INSUFFICIENT)]
        if breakouts:
            typer.secho(f"Breakouts ({len(breakouts)}):", fg=typer.colors.GREEN)
            for i in breakouts:
                typer.echo(
                    f"  {_BUCKET.get(i.breakout.bucket, i.breakout.bucket):12s} "
                    f"{names.get(i.entity_id, i.entity_id):24s} "
                    f"slope {i.breakout.slope:+.1f}/run  z={i.breakout.z_score:.1f}"
                )
        if breakouts_only:
            return
        typer.echo(f"\nIntelligence (über {len(run_ids)} Läufe):")
        for i in rows:
            soon = " ⤴ rising-soon" if i.forecast.rising_soon else ""
            typer.echo(
                f"  {names.get(i.entity_id, i.entity_id):24s} {i.current_score:6.1f} "
                f"P{i.percentile:5.1f} {i.career_phase:12s} "
                f"→ {i.forecast.projected_score:6.1f}{soon}"
            )


@app.command()
def retention(
    apply: bool = typer.Option(False, "--apply", help="Write changes (default: dry-run)"),
    days: int = typer.Option(None, help="Override retention window in days"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Redact stale community/personal data (GDPR retention)."""
    import json as _json

    from scoredclub.retention import apply_retention

    settings = _settings(config)
    init_db(settings.database_url)
    window = days if days is not None else settings.retention.community_days
    total = 0
    with get_session(settings.database_url) as session:
        for entity in repo.all_entities(session):
            profile = repo.profile_from_row(entity)
            redacted = apply_retention(profile, retention_days=window)
            if redacted:
                total += 1
                typer.echo(f"{entity.entity_id}: {', '.join(redacted)}")
                if apply:
                    entity.profile = _json.loads(profile.model_dump_json())
        if apply:
            session.commit()
    action = "redigiert" if apply else "betroffen (dry-run)"
    typer.echo(f"{total} Entitäten {action} (Fenster: {window} Tage)")


@app.command("export")
def export_cmd(
    output: Path = typer.Option(None, "--output", "-o", help="Write CSV to a file (default: stdout)"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Export all entities as CSV (summary + per-dimension points)."""
    from scoredclub.export import export_csv

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        csv_text = export_csv(session)
    if output:
        output.write_text(csv_text, encoding="utf-8")
        typer.echo(f"CSV exportiert: {output}")
    else:
        typer.echo(csv_text)


@app.command()
def sentiment(
    entity_id: str = typer.Argument(None, help="Analyze one entity (default: all with signal)"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Lexicon sentiment over an entity's community text (Reddit/notes), no write."""
    from scoredclub.sentiment import analyze_texts, texts_for_profile

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        if entity_id:
            entity = repo.get_entity(session, entity_id)
            if entity is None:
                typer.secho(f"Entity '{entity_id}' not found", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            entities = [entity]
        else:
            entities = repo.all_entities(session)
        shown = 0
        for entity in entities:
            profile = repo.profile_from_row(entity)
            texts = texts_for_profile(profile)
            if not texts:
                continue
            res = analyze_texts(texts)
            shown += 1
            current = profile.community.community_sentiment_hint.value
            typer.echo(
                f"{entity.name:28s} {res.hint.value:9s} "
                f"polarity {res.polarity:+.2f} (+{res.positive_hits:.1f}/-{res.negative_hits:.1f}, "
                f"{res.samples} Texte)  [aktuell: {current}]"
            )
        if not shown:
            typer.echo("Keine analysierbaren Texte (Reddit-Threads/Notizen).")


@app.command()
def graph(
    export: Path = typer.Option(None, "--export", help="Write the full graph (nodes/edges) as JSON"),
    top: int = typer.Option(10, help="How many entries per ranking"),
    config: str = typer.Option(None, help="Path to config JSON"),
) -> None:
    """Booking/collaboration graph: top venues, DJs and shared-booking links."""
    import json as _json

    from scoredclub.graph import build_graph_from_db, graph_metrics, graph_to_dict

    settings = _settings(config)
    init_db(settings.database_url)
    with get_session(settings.database_url) as session:
        graph_obj, _ = build_graph_from_db(session)
        if not graph_obj.edges:
            typer.echo("No booking/collaboration edges yet (no networking data).")
            return
        metrics = graph_metrics(graph_obj, top=top)
        typer.echo(
            f"Graph: {metrics['node_count']} Knoten "
            f"({metrics['entity_nodes']} Entitäten, {metrics['external_nodes']} extern), "
            f"{metrics['edge_count']} Kanten, {metrics['components']} Komponenten"
        )
        if metrics["top_venues"]:
            typer.secho("\nTop Venues (nach Anzahl Artists):", fg=typer.colors.GREEN)
            for v in metrics["top_venues"]:
                typer.echo(f"  {v['label']:30s} {v['artist_count']} Artists")
        if metrics["top_djs"]:
            typer.secho("\nMeistgebuchte DJs/Artists:", fg=typer.colors.GREEN)
            for d in metrics["top_djs"]:
                typer.echo(f"  {d['label']:30s} {d['booker_count']} Bucher")
        if metrics["shared_bookings"]:
            typer.secho("\nGeteilte Bookings (gleiche DJs):", fg=typer.colors.CYAN)
            for s in metrics["shared_bookings"]:
                typer.echo(f"  {s['a_label']} ↔ {s['b_label']}: {s['shared_djs']} gemeinsame DJs")
        if export:
            export.write_text(
                _json.dumps(graph_to_dict(graph_obj), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            typer.echo(f"\nGraph exportiert: {export}")


@app.command()
def compare(
    config_b: Path = typer.Option(..., "--config-b", help="Variant config to compare against"),
    config_a: Path = typer.Option(None, "--config-a", help="Baseline config (default: active)"),
    date: str = typer.Option(None, help="Scoring date YYYY-MM-DD (default: today)"),
    write: bool = typer.Option(True, help="Write comparison report to the output dir"),
) -> None:
    """A/B test two scoring configurations on the current entities."""
    import json as _json
    from datetime import date as date_type
    from pathlib import Path as _Path

    from scoredclub.compare import (
        compare_scoring,
        render_comparison_json,
        render_comparison_markdown,
    )

    active = Settings.load()
    init_db(active.database_url)
    scoring_a = Settings.load(config_a).scoring if config_a else active.scoring
    scoring_b = Settings.load(config_b).scoring
    label_a = config_a.stem if config_a else "aktiv"
    label_b = config_b.stem
    run_date = date_type.fromisoformat(date) if date else date_type.today()

    with get_session(active.database_url) as session:
        profiles = [repo.profile_from_row(e) for e in repo.all_entities(session)]

    if not profiles:
        typer.secho("Keine Entitäten in der DB. Erst 'seed'/'run' ausführen.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    report = compare_scoring(
        profiles, scoring_a, scoring_b, today=run_date, label_a=label_a, label_b=label_b
    )

    typer.echo(f"Vergleich: {label_a} vs. {label_b}")
    typer.echo(f"  Rang-Korrelation (Spearman): {report.rank_correlation}")
    typer.echo(f"  Mittlere abs. Score-Differenz: {report.mean_abs_delta}")
    typer.echo(f"  Tier-Wechsel: {len(report.tier_changes)}")
    if report.tier_changes:
        for c in report.tier_changes:
            typer.echo(f"    {c.name}: {c.tier_a} → {c.tier_b}")
    typer.echo("  Größte Rang-Bewegungen:")
    for c in report.biggest_movers:
        if c.rank_delta:
            arrow = "▲" if c.rank_delta > 0 else "▼"
            typer.echo(f"    {arrow} {c.name:24s} Rang {c.rank_a}→{c.rank_b} (Δ score {c.score_delta:+.1f})")

    if write:
        out_dir = _Path(active.run.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"scoring_compare_{label_a}_vs_{label_b}_{run_date.isoformat()}"
        md_path = out_dir / f"{stem}.md"
        json_path = out_dir / f"{stem}.json"
        md_path.write_text(render_comparison_markdown(report), encoding="utf-8")
        json_path.write_text(
            _json.dumps(render_comparison_json(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        typer.echo(f"  Reports: {md_path}, {json_path}")


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
