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
    # Write endpoints are guarded by SCOREDCLUB_API_KEY — off unless a test sets it.
    monkeypatch.delenv("SCOREDCLUB_API_KEY", raising=False)
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
    # Follower-growth view present (empty without follower history).
    assert detail["follower_growth"] == {}


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


def test_authenticity_in_entity_detail(client):
    detail = client.get("/entities/testclub").json()
    auth = detail["follower_authenticity"]
    # Well-rounded fixture entity -> authentic, no flags; never affects the score.
    assert auth["verdict"] == "authentic"
    assert auth["flags"] == []


def test_authenticity_list_endpoint(client):
    data = client.get("/authenticity").json()
    assert "entities" in data
    # The minimal collective has no follower data -> inconclusive -> excluded.
    ids = {r["entity_id"] for r in data["entities"]}
    assert "api-kollektiv" not in ids


def test_funding_endpoint(client):
    data = client.get("/funding").json()
    assert {"programs", "policies", "upcoming_deadlines"} <= data.keys()
    # Serves the committed seed feed.
    assert any("Musicboard" in p["name"] for p in data["programs"])


def test_clubsterben_endpoint(client):
    data = client.get("/clubsterben").json()
    # Seeded test entities carry no lifecycle events -> zeroed register, valid shape.
    assert data["openings"] == 0
    assert data["closures"] == 0
    assert data["net_change"] == 0
    assert "by_year" in data and "at_risk" in data


def test_export_csv_endpoint(client):
    response = client.get("/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("entity_id,name,type")
    assert any(line.startswith("testclub,") for line in lines)


def test_feed_endpoint(client):
    response = client.get("/feed.xml")
    assert response.status_code == 200
    assert "rss" in response.headers["content-type"] or response.text.startswith("<?xml")
    import xml.etree.ElementTree as ET

    root = ET.fromstring(response.text)
    assert root.tag == "rss"  # valid even with no alerts


def test_dossier_endpoint(client):
    d = client.get("/entities/testclub/dossier").json()
    assert d["name"] == "Testclub"
    assert "top_tracks" in d and "top_sets" in d and "parties" in d
    assert "relationships" in d and "follower_authenticity" in d
    assert client.get("/entities/nope/dossier").status_code == 404


def test_collaborations_endpoint(client):
    data = client.get("/collaborations").json()
    assert "top_collaborations" in data
    assert "most_collaborative" in data


def test_entity_relationships_endpoint(client):
    rel = client.get("/entities/testclub/relationships").json()
    assert rel["entity_id"] == "testclub"
    # The top fixture profile books several DJs.
    assert isinstance(rel["books"], list)
    assert client.get("/entities/nope/relationships").status_code == 404


def test_graph_endpoint(client):
    data = client.get("/graph").json()
    metrics = data["metrics"]
    # The top profile has booked_djs + collaborations + cross_promotions.
    assert metrics["edge_count"] > 0
    assert metrics["entity_nodes"] == 2
    assert "graph" not in data  # full graph omitted unless requested
    full = client.get("/graph", params={"include_graph": True}).json()
    assert "graph" in full
    assert any(n["id"] == "testclub" for n in full["graph"]["nodes"])


def test_analytics_endpoint(client):
    data = client.get("/analytics").json()
    assert data["runs_considered"] == 1
    ids = [e["entity_id"] for e in data["entities"]]
    assert ids == ["testclub", "api-kollektiv"]  # ordered by score desc
    top = data["entities"][0]
    assert top["percentile"] == 100.0
    assert top["career_phase"] == "elite"
    # Single run -> not enough history to break out.
    assert top["breakout"]["bucket"] == "insufficient_data"
    assert data["breakouts"] == []


def test_entity_trend_404(client):
    assert client.get("/entities/nope/trend").status_code == 404


# ---- write/trigger endpoints (auth) ----

_RESEARCH = [{"name": "Neuer Club", "type": "club", "status": "active"}]


def test_writes_disabled_without_api_key(client):
    # No SCOREDCLUB_API_KEY configured -> write endpoints are 503.
    assert client.post("/ingest", json=_RESEARCH).status_code == 503
    assert client.post("/runs", json={}).status_code == 503


def test_ingest_requires_valid_key(client, monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    assert client.post("/ingest", json=_RESEARCH).status_code == 401  # missing header
    assert client.post("/ingest", json=_RESEARCH, headers={"X-API-Key": "wrong"}).status_code == 401

    resp = client.post("/ingest", json=_RESEARCH, headers={"X-API-Key": "s3cret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "neuer-club" in body["new_entities"]
    # Entity is now queryable via the read API.
    assert client.get("/entities/neuer-club").status_code == 200


def test_ingest_bad_body(client, monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    resp = client.post("/ingest", json={"not_entities": 1}, headers={"X-API-Key": "s3cret"})
    assert resp.status_code == 400


def test_trigger_run(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    import scoredclub.api.app as app_module

    app_module._settings.run.output_dir = str(tmp_path / "out")
    resp = client.post(
        "/runs", json={"skip_collectors": True}, headers={"X-API-Key": "s3cret"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] >= 2  # the fixture already created run #1
    assert body["entities_tracked"] == 2
    # A new run is now visible.
    assert len(client.get("/runs").json()) >= 2


def test_async_run_job(client, monkeypatch, tmp_path):
    import time

    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    import scoredclub.api.app as app_module

    app_module._settings.run.output_dir = str(tmp_path / "out")
    resp = client.post(
        "/runs", json={"async": True, "skip_collectors": True}, headers={"X-API-Key": "s3cret"}
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    status = {}
    for _ in range(100):  # poll up to ~10s
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert status["status"] == "done", status
    assert status["result"]["entities_tracked"] == 2


def test_job_unknown_404(client):
    assert client.get("/jobs/doesnotexist").status_code == 404


# ---- A/B compare endpoint ----

_REACH_HEAVY = {
    "weights": {
        "event_activity": 0.2, "online_reach": 0.5, "press": 0.0, "community": 0.0,
        "networking": 0.0, "continuity": 0.2, "safety": 0.1,
    }
}


def test_compare_requires_key(client, monkeypatch):
    # No key configured -> 503.
    assert client.post("/compare", json={"config_b": _REACH_HEAVY}).status_code == 503
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    assert client.post("/compare", json={"config_b": _REACH_HEAVY}).status_code == 401


def test_compare_returns_comparison(client, monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    resp = client.post(
        "/compare",
        json={"config_b": _REACH_HEAVY, "label_a": "aktiv", "label_b": "reach"},
        headers={"X-API-Key": "s3cret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label_a"] == "aktiv" and body["label_b"] == "reach"
    assert "rank_correlation" in body
    assert len(body["entities"]) == 2
    assert {"score_a", "score_b", "score_delta", "rank_a", "rank_b"} <= set(body["entities"][0])


def test_compare_invalid_config(client, monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_API_KEY", "s3cret")
    resp = client.post(
        "/compare",
        json={"config_b": {"weights": {"event_activity": "not-a-number"}}},
        headers={"X-API-Key": "s3cret"},
    )
    assert resp.status_code == 400
