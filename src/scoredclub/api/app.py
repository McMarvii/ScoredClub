"""Read-only FastAPI app (no auth in V1 — intended for local/Docker use)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
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
    return {
        **_entity_summary(entity),
        "profile": entity.profile,
        "latest_breakdown": history[-1].breakdown if history else None,
        "score_history": [
            {"run_id": s.run_id, "score": s.score, "tier": s.tier} for s in history
        ],
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
