from __future__ import annotations

import httpx

from scoredclub.db import repo
from scoredclub.pipeline.alerts import (
    ALERT_NEW_ENTITY,
    ALERT_SCORE_CHANGE,
    ALERT_STATUS_CHANGE,
    create_alerts,
    deliver_webhooks,
)
from scoredclub.pipeline.diff import diff_runs
from scoredclub.schemas import ScoreBreakdown, utcnow
from tests.conftest import make_minimal_profile, make_top_profile


def _snapshot(session, run, entity_id, score, status="active"):
    entity = repo.get_entity(session, entity_id)
    entity.status = status
    breakdown = ScoreBreakdown(total=score, tier="MID-TIER")
    repo.save_score(session, run, entity, breakdown)


def _two_runs(session, second_scores: dict[str, float], second_status: dict[str, str] | None = None,
              new_in_second: list = None):
    second_status = second_status or {}
    a = make_top_profile()
    b = make_minimal_profile(name="Zweiter Club")
    repo.upsert_profile(session, a)
    repo.upsert_profile(session, b)

    run1 = repo.start_run(session)
    _snapshot(session, run1, a.entity_id, 80.0)
    _snapshot(session, run1, b.entity_id, 40.0)
    repo.finish_run(session, run1, 2, 0, None, None, utcnow())

    run2 = repo.start_run(session)
    for profile in new_in_second or []:
        repo.upsert_profile(session, profile, run_id=run2.id)
    for entity_id, score in second_scores.items():
        _snapshot(session, run2, entity_id, score, status=second_status.get(entity_id, "active"))
    return run2


def test_score_change_above_threshold_fires(session, settings):
    run2 = _two_runs(session, {"testclub": 65.0, "zweiter-club": 40.0})
    diff = diff_runs(session, run2)
    alerts = create_alerts(session, run2, diff, settings)
    score_alerts = [a for a in alerts if a.alert_type == ALERT_SCORE_CHANGE]
    assert len(score_alerts) == 1
    assert score_alerts[0].entity_id == "testclub"
    assert score_alerts[0].delta == -15.0


def test_change_at_or_below_threshold_does_not_fire(session, settings):
    run2 = _two_runs(session, {"testclub": 70.0, "zweiter-club": 45.0})
    diff = diff_runs(session, run2)
    alerts = create_alerts(session, run2, diff, settings)
    assert [a for a in alerts if a.alert_type == ALERT_SCORE_CHANGE] == []


def test_status_change_fires(session, settings):
    run2 = _two_runs(
        session,
        {"testclub": 80.0, "zweiter-club": 40.0},
        second_status={"zweiter-club": "inactive"},
    )
    diff = diff_runs(session, run2)
    alerts = create_alerts(session, run2, diff, settings)
    status_alerts = [a for a in alerts if a.alert_type == ALERT_STATUS_CHANGE]
    assert len(status_alerts) == 1
    assert status_alerts[0].new_value == "inactive"


def test_new_entity_fires(session, settings):
    newcomer = make_minimal_profile(name="Neuer Spot")
    run2 = _two_runs(
        session,
        {"testclub": 80.0, "zweiter-club": 40.0, "neuer-spot": 30.0},
        new_in_second=[newcomer],
    )
    diff = diff_runs(session, run2)
    alerts = create_alerts(session, run2, diff, settings)
    new_alerts = [a for a in alerts if a.alert_type == ALERT_NEW_ENTITY]
    assert [a.entity_id for a in new_alerts] == ["neuer-spot"]


def test_first_run_produces_no_alerts(session, settings):
    profile = make_top_profile()
    repo.upsert_profile(session, profile)
    run1 = repo.start_run(session)
    _snapshot(session, run1, profile.entity_id, 80.0)
    diff = diff_runs(session, run1)
    assert create_alerts(session, run1, diff, settings) == []


def test_webhook_delivery_and_failure_nonfatal(session, settings):
    run2 = _two_runs(session, {"testclub": 50.0, "zweiter-club": 40.0})
    diff = diff_runs(session, run2)
    alerts = create_alerts(session, run2, diff, settings)
    assert alerts

    received = []

    def ok_handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    settings.alerts.webhook_url = "https://hooks.example/x"
    client = httpx.Client(transport=httpx.MockTransport(ok_handler))
    deliver_webhooks(alerts, settings, client=client)
    assert len(received) == len(alerts)
    assert all(a.webhook_delivered for a in alerts)

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(fail_handler))
    deliver_webhooks(alerts, settings, client=client)  # must not raise
    assert all(not a.webhook_delivered for a in alerts)
