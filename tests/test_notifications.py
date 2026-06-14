from __future__ import annotations

import httpx

from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.pipeline.alerts import (
    create_alerts,
    deliver_email,
    deliver_notifications,
    deliver_slack,
    format_digest,
)
from scoredclub.pipeline.diff import diff_runs
from scoredclub.schemas import ScoreBreakdown, utcnow
from tests.conftest import make_minimal_profile, make_top_profile


def _alerts_two_runs(session, settings):
    a = make_top_profile()
    b = make_minimal_profile(name="Zweiter Club")
    repo.upsert_profile(session, a)
    repo.upsert_profile(session, b)
    run1 = repo.start_run(session)
    repo.save_score(session, run1, repo.get_entity(session, a.entity_id), ScoreBreakdown(total=80.0, tier="TOP-TIER"))
    repo.save_score(session, run1, repo.get_entity(session, b.entity_id), ScoreBreakdown(total=40.0, tier="EMERGING"))
    repo.finish_run(session, run1, 2, 0, None, None, utcnow())
    run2 = repo.start_run(session)
    repo.save_score(session, run2, repo.get_entity(session, a.entity_id), ScoreBreakdown(total=50.0, tier="MID-TIER"))
    repo.save_score(session, run2, repo.get_entity(session, b.entity_id), ScoreBreakdown(total=40.0, tier="EMERGING"))
    diff = diff_runs(session, run2)
    return create_alerts(session, run2, diff, settings)


def test_format_digest(session):
    settings = Settings()
    alerts = _alerts_two_runs(session, settings)
    digest = format_digest(alerts)
    assert digest.startswith(f"ScoredClub: {len(alerts)} neue Alerts")
    assert "[score_change]" in digest


def test_slack_disabled_by_default(session):
    settings = Settings()
    alerts = _alerts_two_runs(session, settings)
    called = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200)))
    assert deliver_slack(alerts, settings, client=client) is False
    assert called == []  # no URL -> not even attempted


def test_slack_posts_single_digest_when_configured(session):
    settings = Settings()
    settings.alerts.slack_webhook_url = "https://hooks.slack.example/x"
    alerts = _alerts_two_runs(session, settings)
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert deliver_slack(alerts, settings, client=client) is True
    assert len(payloads) == 1  # one digest, not one-per-alert
    assert "ScoredClub" in payloads[0]["text"]


def test_slack_failure_is_nonfatal(session):
    settings = Settings()
    settings.alerts.slack_webhook_url = "https://hooks.slack.example/x"
    alerts = _alerts_two_runs(session, settings)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert deliver_slack(alerts, settings, client=client) is False  # retried, never raised


class _FakeSMTP:
    """Minimal SMTP context-manager double recording the calls."""

    instances: list = []

    def __init__(self):
        self.tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent = message


def test_email_disabled_by_default(session):
    settings = Settings()
    alerts = _alerts_two_runs(session, settings)
    _FakeSMTP.instances.clear()
    assert deliver_email(alerts, settings, smtp_factory=_FakeSMTP) is False
    assert _FakeSMTP.instances == []


def test_email_sends_digest_when_enabled(session, monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_SMTP_PASSWORD", "secret")
    settings = Settings()
    settings.alerts.email.enabled = True
    settings.alerts.email.username = "user@example.com"
    settings.alerts.email.to_addrs = ["ops@example.com"]
    alerts = _alerts_two_runs(session, settings)
    _FakeSMTP.instances.clear()

    assert deliver_email(alerts, settings, smtp_factory=_FakeSMTP) is True
    smtp = _FakeSMTP.instances[0]
    assert smtp.tls is True
    assert smtp.logged_in == ("user@example.com", "secret")
    assert smtp.sent["To"] == "ops@example.com"
    assert "ScoredClub" in smtp.sent.get_content()


def test_email_requires_recipients(session):
    settings = Settings()
    settings.alerts.email.enabled = True  # but no to_addrs
    alerts = _alerts_two_runs(session, settings)
    _FakeSMTP.instances.clear()
    assert deliver_email(alerts, settings, smtp_factory=_FakeSMTP) is False


def test_deliver_notifications_combines_channels(session):
    settings = Settings()
    settings.alerts.webhook_url = "https://hooks.example/wh"
    settings.alerts.slack_webhook_url = "https://hooks.slack.example/sl"
    alerts = _alerts_two_runs(session, settings)
    hits = {"wh": 0, "sl": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "slack" in request.url.host:
            hits["sl"] += 1
        else:
            hits["wh"] += 1
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    deliver_notifications(alerts, settings, http_client=client)
    assert hits["wh"] == len(alerts)  # one webhook per alert
    assert hits["sl"] == 1  # one slack digest


def test_slack_env_override(monkeypatch):
    monkeypatch.setenv("SCOREDCLUB_SLACK_WEBHOOK_URL", "https://hooks.slack.example/env")
    settings = Settings.load("does-not-exist.json")
    assert settings.alerts.slack_webhook_url == "https://hooks.slack.example/env"
