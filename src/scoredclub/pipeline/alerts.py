"""Alert creation and optional webhook delivery."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.db.models import Alert, Run
from scoredclub.pipeline.diff import RunDiff

logger = logging.getLogger(__name__)

ALERT_SCORE_CHANGE = "score_change"
ALERT_STATUS_CHANGE = "status_change"
ALERT_NEW_ENTITY = "new_entity"


def create_alerts(session: Session, run: Run, diff: RunDiff, settings: Settings) -> list[Alert]:
    threshold = settings.alerts.score_change_threshold
    alerts: list[Alert] = []

    for delta in diff.score_changes(threshold):
        alerts.append(
            repo.add_alert(
                session,
                run,
                delta.entity_id,
                ALERT_SCORE_CHANGE,
                message=(
                    f"{delta.name}: Score {delta.old_score} -> {delta.new_score} "
                    f"(Δ {delta.score_delta:+.1f})"
                ),
                old_value=str(delta.old_score),
                new_value=str(delta.new_score),
                delta=delta.score_delta,
            )
        )
    for delta in diff.status_changes:
        alerts.append(
            repo.add_alert(
                session,
                run,
                delta.entity_id,
                ALERT_STATUS_CHANGE,
                message=f"{delta.name}: Status {delta.old_status} -> {delta.new_status}",
                old_value=delta.old_status,
                new_value=delta.new_status,
            )
        )
    for delta in diff.new_entities:
        alerts.append(
            repo.add_alert(
                session,
                run,
                delta.entity_id,
                ALERT_NEW_ENTITY,
                message=f"Neue Entität entdeckt: {delta.name} (Score {delta.new_score})",
                new_value=str(delta.new_score),
            )
        )
    return alerts


def deliver_webhooks(
    alerts: list[Alert],
    settings: Settings,
    client: httpx.Client | None = None,
) -> None:
    """POST one JSON payload per alert. Failures are logged, never fatal."""
    url = settings.alerts.webhook_url
    if not url or not alerts:
        return
    own_client = client is None
    client = client or httpx.Client(timeout=5.0)
    try:
        for alert in alerts:
            payload = {
                "entity_id": alert.entity_id,
                "alert_type": alert.alert_type,
                "message": alert.message,
                "old_value": alert.old_value,
                "new_value": alert.new_value,
                "delta": alert.delta,
                "run_id": alert.run_id,
            }
            delivered = False
            for attempt in range(2):  # one retry
                try:
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    delivered = True
                    break
                except Exception as exc:  # noqa: BLE001 — never fatal
                    logger.warning(
                        "webhook delivery attempt %d failed for %s: %s",
                        attempt + 1,
                        alert.entity_id,
                        exc,
                    )
            alert.webhook_delivered = delivered
    finally:
        if own_client:
            client.close()
