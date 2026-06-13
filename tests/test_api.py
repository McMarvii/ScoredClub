from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from scoredclub.db import repo
from scoredclub.schemas import ScoreBreakdown, utcnow
from tests.conftest import make_minimal_profile, make_top_profile


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # The app binds its engine at import time — reload with the test DB.
    import scoredclub.db.session as session_module

    session_module._engine = None
    session_module._session_factory = None
    import scoredclub.api.app as app_module

    importlib.reload(app_module)

    from scoredclub.db import get_session

    from scoredclub.config import Settings
    from scoredclub.pipeline.run import compute_run_trends

    with get_session(f"sqlite:///{db_path}") as session:
        top = make_top_profile()
        emerging = make_minimal_profile(name="API Kollektiv")
        repo.upsert_profile(session, top)
        repo.upsert_profile(session, emerging)
        run = repo.start_run(session)
        repo.save_score(
            session, run, repo.get_entity(session, top.entity_id),
            ScoreBreakdown(total=88.0, tier="TOP-TIER"),
        )
        repo.save_score(
            session, run, repo.get_entity(session, emerging.entity_id),
            ScoreBreakdown(total=30.0, tier="EMERGING"),
        )
        repo.finish_run(session, run, 2, 0, None, None, utcnow())
        compute_run_trends(session, Settings())
        session.commit()

    return TestClient(app_module.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_entities_and_filters(client):
    everything = client.get("/entities").json()
    assert len(everything) == 2
    clubs = client.get("/entities", params={"type": "club"}).json()
    assert [e["entity_id"] for e in clubs] == ["testclub"]
    scored = client.get("/entities", params={"min_score": 50}).json()
    assert [e["entity_id"] for e in scored] == ["testclub"]


def test_get_entity_detail(client):
    detail = client.get("/entities/testclub").json()
    assert detail["name"] == "Testclub"
    assert detail["score_history"] == [{"run_id": 1, "score": 88.0, "tier": "TOP-TIER"}]
    assert detail["profile"]["district"] == "Friedrichshain"


def test_unknown_entity_404(client):
    assert client.get("/entities/nope").status_code == 404


def test_runs(client):
    runs = client.get("/runs").json()
    assert len(runs) == 1
    assert runs[0]["entities_tracked"] == 2
    detail = client.get("/runs/1").json()
    assert detail["scores"]["testclub"]["score"] == 88.0


def test_latest_report_404_without_report(client):
    assert client.get("/runs/latest/report").status_code == 404


def test_alerts_empty(client):
    assert client.get("/alerts").json() == []


def test_trending_leaderboard(client):
    data = client.get("/trending").json()
    assert data["run_id"] == 1
    ids = [e["entity_id"] for e in data["entities"]]
    assert ids == ["testclub", "api-kollektiv"]  # ordered by rank
    assert data["entities"][0]["rank"] == 1
    # First run -> everything is "new", no deltas yet.
    assert data["entities"][0]["direction"] == "new"
    assert data["entities"][0]["name"] == "Testclub"


def test_trending_movers_empty_on_first_run(client):
    data = client.get("/trending/movers").json()
    assert data["risers"] == [] and data["fallers"] == []


def test_entity_trend(client):
    data = client.get("/entities/testclub/trend").json()
    assert data["entity_id"] == "testclub"
    assert data["sparkline"] == [88.0]
    assert data["latest"]["rank"] == 1
    assert data["latest"]["direction"] == "new"


def test_entity_trend_404(client):
    assert client.get("/entities/nope/trend").status_code == 404
