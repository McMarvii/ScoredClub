"""FastAPI app.

Read endpoints are public (intended for local/Docker use — put a reverse proxy
in front to protect them if exposed). Write/trigger endpoints (ingest, run) are
guarded by an API key: set ``SCOREDCLUB_API_KEY`` in the environment to enable
them; without it they are disabled (503).
"""

from __future__ import annotations

import hmac
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_type
from pathlib import Path
from typing import Iterator

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoredclub import __version__
from scoredclub.config import Settings
from scoredclub.db import get_session, init_db, repo
from scoredclub.db.models import Alert, Run

app = FastAPI(title="ScoredClub API", version=__version__)

_settings = Settings.load()
init_db(_settings.database_url)


def db_session() -> Iterator[Session]:
    session = get_session(_settings.database_url)
    try:
        yield session
    finally:
        session.close()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> bool:
    """Guard write endpoints. Disabled (503) unless SCOREDCLUB_API_KEY is set."""
    configured = os.environ.get("SCOREDCLUB_API_KEY")
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Write API disabled: set SCOREDCLUB_API_KEY to enable.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return True


class RunRequest(BaseModel):
    skip_collectors: bool = True
    date: str | None = None
    research: list | dict | None = None
    run_async: bool = Field(default=False, alias="async")

    model_config = {"populate_by_name": True}


class CompareRequest(BaseModel):
    config_b: dict  # required: a scoring config (the variant)
    config_a: dict | None = None  # baseline; null = active config
    date: str | None = None
    label_a: str = "A"
    label_b: str = "B"


# In-process background job runner (no external broker). Jobs are kept in
# memory; state is lost on restart — documented in the API reference.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scoredclub-job")


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _run_job(job_id, skip_collectors, run_date, research_entries) -> None:
    _set_job(job_id, status="running")
    try:
        from scoredclub.collectors.llm_ingest import ingest_entries
        from scoredclub.db import get_session
        from scoredclub.pipeline.run import execute_run

        with get_session(_settings.database_url) as session:
            if research_entries:
                ingest_entries(session, research_entries)
                session.commit()
            summary = execute_run(
                session, _settings, research_file=None,
                skip_collectors=skip_collectors, run_date=run_date,
            )
        _set_job(
            job_id, status="done",
            result={
                "run_id": summary.run_id,
                "entities_tracked": summary.entities_tracked,
                "new_entities": summary.new_entities,
                "alerts": summary.alerts,
                "report_md": summary.report_md,
                "warnings": summary.warnings,
            },
        )
    except Exception as exc:  # noqa: BLE001 — surface as job error, never crash the worker
        _set_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")


def _entity_summary(entity) -> dict:
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "type": entity.type,
        "status": entity.status,
        "district": entity.district,
        "tier": entity.tier,
        "current_score": entity.current_score,
        "last_event_date": entity.last_event_date.isoformat() if entity.last_event_date else None,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/ingest")
def ingest_endpoint(
    payload: list | dict = Body(...),
    _auth: bool = Depends(require_api_key),
    session: Session = Depends(db_session),
) -> dict:
    """Validate and upsert research entities (array or {entities: [...]})."""
    from scoredclub.collectors.llm_ingest import ingest_entries

    entries = payload.get("entities") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise HTTPException(
            status_code=400, detail="Body must be a JSON array or an object with 'entities'."
        )
    report = ingest_entries(session, entries)
    session.commit()
    return {
        "ok": report.ok,
        "ingested": report.ingested,
        "new_entities": report.new_entities,
        "merged_entities": report.merged_entities,
        "errors": report.errors,
    }


@app.post("/runs")
def trigger_run(
    body: RunRequest = Body(default_factory=RunRequest),
    _auth: bool = Depends(require_api_key),
    session: Session = Depends(db_session),
) -> dict:
    """Trigger a pipeline run. Sync by default; pass ``"async": true`` for a background job."""
    from scoredclub.collectors.llm_ingest import ingest_entries
    from scoredclub.pipeline.run import execute_run

    try:
        run_date = date_type.fromisoformat(body.date) if body.date else None
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be ISO format YYYY-MM-DD.")

    entries = None
    if body.research is not None:
        entries = body.research.get("entities") if isinstance(body.research, dict) else body.research
        if not isinstance(entries, list):
            entries = None

    if body.run_async:
        job_id = uuid.uuid4().hex
        _set_job(job_id, status="queued")
        _executor.submit(_run_job, job_id, body.skip_collectors, run_date, entries)
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": "queued"})

    if entries:
        ingest_entries(session, entries)
        session.commit()
    summary = execute_run(
        session, _settings, research_file=None, skip_collectors=body.skip_collectors, run_date=run_date
    )
    return {
        "run_id": summary.run_id,
        "entities_tracked": summary.entities_tracked,
        "new_entities": summary.new_entities,
        "alerts": summary.alerts,
        "report_md": summary.report_md,
        "warnings": summary.warnings,
    }


@app.post("/compare")
def compare_endpoint(
    body: CompareRequest = Body(...),
    _auth: bool = Depends(require_api_key),
    session: Session = Depends(db_session),
) -> dict:
    """A/B compare two scoring configurations over the current entities (read-only)."""
    from scoredclub.compare import compare_scoring, render_comparison_json
    from scoredclub.config import ScoringConfig

    try:
        run_date = date_type.fromisoformat(body.date) if body.date else None
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be ISO format YYYY-MM-DD.")
    try:
        scoring_a = ScoringConfig.model_validate(body.config_a) if body.config_a else _settings.scoring
        scoring_b = ScoringConfig.model_validate(body.config_b)
    except Exception as exc:  # noqa: BLE001 — invalid config -> 400
        raise HTTPException(status_code=400, detail=f"invalid scoring config: {exc}")

    profiles = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    report = compare_scoring(
        profiles, scoring_a, scoring_b, today=run_date,
        label_a=body.label_a, label_b=body.label_b,
    )
    return render_comparison_json(report)


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
        return {"job_id": job_id, **job}


@app.get("/entities")
def list_entities(
    type: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    session: Session = Depends(db_session),
) -> list[dict]:
    results = []
    for entity in repo.all_entities(session):
        if type and entity.type != type:
            continue
        if tier and (entity.tier or "") != tier:
            continue
        if status and entity.status != status:
            continue
        if min_score is not None and (entity.current_score or 0) < min_score:
            continue
        results.append(_entity_summary(entity))
    return sorted(results, key=lambda e: e["current_score"] or 0, reverse=True)


@app.get("/entities/{entity_id}")
def get_entity(entity_id: str, session: Session = Depends(db_session)) -> dict:
    entity = repo.get_entity(session, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity '{entity_id}' not found")
    history = repo.score_history(session, entity_id)
    from scoredclub.authenticity import assess, to_dict as authenticity_dict
    from scoredclub.followers import growth_to_dict, profile_follower_growth

    profile = repo.profile_from_row(entity)
    return {
        **_entity_summary(entity),
        "profile": entity.profile,
        "latest_breakdown": history[-1].breakdown if history else None,
        "score_history": [
            {"run_id": s.run_id, "score": s.score, "tier": s.tier} for s in history
        ],
        "follower_growth": growth_to_dict(profile_follower_growth(profile)),
        # Informational only — never part of the score.
        "follower_authenticity": authenticity_dict(assess(profile)),
    }


def _trend_dict(t) -> dict:
    return {
        "entity_id": t.entity_id,
        "run_id": t.run_id,
        "score": t.score,
        "rank": t.rank,
        "score_delta": t.score_delta,
        "rank_delta": t.rank_delta,
        "momentum": t.momentum,
        "direction": t.direction,
    }


@app.get("/entities/{entity_id}/trend")
def entity_trend(entity_id: str, session: Session = Depends(db_session)) -> dict:
    entity = repo.get_entity(session, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity '{entity_id}' not found")
    history = repo.trend_history(session, entity_id)
    return {
        "entity_id": entity_id,
        "name": entity.name,
        "sparkline": [t.score for t in history],
        "history": [{**_trend_dict(t)} for t in history],
        "latest": _trend_dict(history[-1]) if history else None,
    }


@app.get("/runs")
def list_runs(session: Session = Depends(db_session)) -> list[dict]:
    runs = session.scalars(select(Run).order_by(Run.id.desc())).all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "entities_tracked": r.entities_tracked,
            "new_entities_found": r.new_entities_found,
            "report_md_path": r.report_md_path,
        }
        for r in runs
    ]


@app.get("/trending")
def trending(session: Session = Depends(db_session)) -> dict:
    """Latest run's trend leaderboard: direction, deltas and rank per entity."""
    run = repo.latest_run(session)
    if run is None:
        return {"run_id": None, "entities": []}
    trends = repo.trends_for_run(session, run.id)
    names = {e.entity_id: e.name for e in repo.all_entities(session)}
    rows = sorted(trends.values(), key=lambda t: t.rank)
    return {
        "run_id": run.id,
        "entities": [{**_trend_dict(t), "name": names.get(t.entity_id, t.entity_id)} for t in rows],
    }


@app.get("/trending/movers")
def trending_movers(
    limit: int = Query(default=5, ge=1, le=50), session: Session = Depends(db_session)
) -> dict:
    """Top risers and fallers in the latest run (by score delta)."""
    run = repo.latest_run(session)
    if run is None:
        return {"run_id": None, "risers": [], "fallers": []}
    trends = repo.trends_for_run(session, run.id)
    names = {e.entity_id: e.name for e in repo.all_entities(session)}
    movers = [t for t in trends.values() if t.score_delta is not None]
    risers = sorted((t for t in movers if t.score_delta > 0), key=lambda t: t.score_delta, reverse=True)[:limit]
    fallers = sorted((t for t in movers if t.score_delta < 0), key=lambda t: t.score_delta)[:limit]
    decorate = lambda t: {**_trend_dict(t), "name": names.get(t.entity_id, t.entity_id)}
    return {"run_id": run.id, "risers": [decorate(t) for t in risers], "fallers": [decorate(t) for t in fallers]}


def _intel_dict(i, name: str) -> dict:
    return {
        "entity_id": i.entity_id,
        "name": name,
        "current_score": i.current_score,
        "percentile": i.percentile,
        "career_phase": i.career_phase,
        "breakout": {"bucket": i.breakout.bucket, "slope": i.breakout.slope, "z_score": i.breakout.z_score},
        "forecast": {
            "projected_score": i.forecast.projected_score,
            "slope": i.forecast.slope,
            "rising_soon": i.forecast.rising_soon,
        },
    }


@app.get("/analytics")
def analytics(session: Session = Depends(db_session)) -> dict:
    """Breakout detection, career phase and short-term forecast per entity."""
    from scoredclub.analytics import BUCKET_INSUFFICIENT, BUCKET_NONE, compute_intelligence

    intel, run_ids = compute_intelligence(session, _settings)
    if not intel:
        return {"runs_considered": 0, "entities": [], "breakouts": []}
    names = {e.entity_id: e.name for e in repo.all_entities(session)}
    rows = sorted(intel.values(), key=lambda i: i.current_score, reverse=True)
    entities = [_intel_dict(i, names.get(i.entity_id, i.entity_id)) for i in rows]
    breakouts = [
        e for e, i in zip(entities, rows)
        if i.breakout.bucket not in (BUCKET_NONE, BUCKET_INSUFFICIENT)
    ]
    return {"runs_considered": len(run_ids), "entities": entities, "breakouts": breakouts}


@app.get("/graph")
def booking_graph(
    include_graph: bool = Query(default=False, description="Include full nodes/edges"),
    top: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(db_session),
) -> dict:
    """Booking/collaboration graph metrics (and optionally the full graph)."""
    from scoredclub.graph import build_graph_from_db, graph_metrics, graph_to_dict

    graph_obj, _ = build_graph_from_db(session)
    payload = {"metrics": graph_metrics(graph_obj, top=top)}
    if include_graph:
        payload["graph"] = graph_to_dict(graph_obj)
    return payload


@app.get("/authenticity")
def authenticity(
    flagged_only: bool = Query(default=False),
    session: Session = Depends(db_session),
) -> dict:
    """Follower-authenticity verdicts per entity (informational; not in the score)."""
    from scoredclub.authenticity import VERDICT_AUTHENTIC, VERDICT_INCONCLUSIVE, assess

    rows = []
    for entity in repo.all_entities(session):
        result = assess(repo.profile_from_row(entity))
        if result.verdict == VERDICT_INCONCLUSIVE:
            continue
        if flagged_only and result.verdict == VERDICT_AUTHENTIC:
            continue
        rows.append({
            "entity_id": entity.entity_id, "name": entity.name, "type": entity.type,
            "verdict": result.verdict, "score": result.score, "flags": result.flags,
        })
    order = {"suspicious": 0, "questionable": 1, "authentic": 2}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -(r["score"] or 0)))
    return {"entities": rows}


@app.get("/funding")
def funding(within_days: int = Query(default=90, ge=1, le=730)) -> dict:
    """Förder-/Policy-Feed: programmes, policy items and upcoming deadlines."""
    from scoredclub.funding import feed_to_dict, load_funding

    feed = load_funding(_settings.sources.funding_feed_path)
    return feed_to_dict(feed, within_days=within_days)


@app.get("/clubsterben")
def clubsterben(session: Session = Depends(db_session)) -> dict:
    """Cultural-ecosystem register: openings/closures, causes, at-risk venues."""
    from scoredclub.clubsterben import build_register_from_db, register_to_dict

    return register_to_dict(build_register_from_db(session))


@app.get("/export.csv", response_class=PlainTextResponse)
def export_csv_endpoint(session: Session = Depends(db_session)) -> PlainTextResponse:
    """All entities as CSV (summary + per-dimension points)."""
    from scoredclub.export import export_csv

    return PlainTextResponse(content=export_csv(session), media_type="text/csv")


@app.get("/feed.xml", response_class=PlainTextResponse)
def feed_endpoint(
    limit: int = Query(default=50, ge=1, le=200), session: Session = Depends(db_session)
) -> PlainTextResponse:
    """RSS 2.0 feed of the most recent alerts."""
    from scoredclub.feeds import build_feed

    return PlainTextResponse(
        content=build_feed(session, limit=limit), media_type="application/rss+xml"
    )


@app.get("/runs/latest/report", response_class=PlainTextResponse)
def latest_report(session: Session = Depends(db_session)) -> str:
    run = session.scalar(
        select(Run).where(Run.report_md_path.is_not(None)).order_by(Run.id.desc()).limit(1)
    )
    if run is None or not run.report_md_path:
        raise HTTPException(status_code=404, detail="no report available yet")
    path = Path(run.report_md_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"report file {path} missing")
    return path.read_text(encoding="utf-8")


@app.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(db_session)) -> dict:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    snapshots = repo.snapshots_for_run(session, run_id)
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "entities_tracked": run.entities_tracked,
        "new_entities_found": run.new_entities_found,
        "scores": {
            entity_id: {"score": s.score, "tier": s.tier} for entity_id, s in snapshots.items()
        },
    }


@app.get("/alerts")
def list_alerts(
    run_id: int | None = Query(default=None), session: Session = Depends(db_session)
) -> list[dict]:
    stmt = select(Alert).order_by(Alert.id.desc())
    if run_id is not None:
        stmt = stmt.where(Alert.run_id == run_id)
    return [
        {
            "id": a.id,
            "run_id": a.run_id,
            "entity_id": a.entity_id,
            "alert_type": a.alert_type,
            "message": a.message,
            "old_value": a.old_value,
            "new_value": a.new_value,
            "delta": a.delta,
            "webhook_delivered": a.webhook_delivered,
        }
        for a in session.scalars(stmt).all()
    ]
