from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from scoredclub.db import repo
from scoredclub.db.models import Alert, Run
from scoredclub.export import build_entity_rows, export_csv, rows_to_csv
from scoredclub.feeds import FeedItem, alerts_to_items, build_feed, render_rss
from scoredclub.schemas import ScoreBreakdown, utcnow
from tests.conftest import make_minimal_profile, make_top_profile


# --- CSV export -------------------------------------------------------------

def test_rows_to_csv_columns_and_order():
    rows = [
        {"entity_id": "a", "name": "A", "type": "club", "status": "active",
         "district": "X", "tier": "MID", "current_score": 50.0, "confidence": 80,
         "last_event_date": "", "A_event_activity": 10.0},
        {"entity_id": "b", "name": "B", "type": "club", "status": "active",
         "district": "", "tier": "TOP", "current_score": 90.0, "confidence": 95,
         "last_event_date": "", "A_event_activity": 18.0},
    ]
    text = rows_to_csv(rows)
    reader = list(csv.reader(io.StringIO(text)))
    header = reader[0]
    assert header[:7] == ["entity_id", "name", "type", "status", "district", "tier", "current_score"]
    assert "A_event_activity" in header  # dimension columns appended
    # Sorted by score desc -> B before A.
    assert reader[1][0] == "b"
    assert reader[2][0] == "a"


def test_export_csv_from_db(session):
    repo.upsert_profile(session, make_top_profile())
    repo.upsert_profile(session, make_minimal_profile(name="CSV Kollektiv"))
    run = repo.start_run(session)
    repo.save_score(
        session, run, repo.get_entity(session, "testclub"),
        ScoreBreakdown(total=88.0, tier="TOP-TIER", confidence=90.0,
                       points={"A_event_activity": 18.0, "G_safety": 8.0}),
    )
    session.commit()
    text = export_csv(session)
    rows = list(csv.DictReader(io.StringIO(text)))
    top = next(r for r in rows if r["entity_id"] == "testclub")
    assert top["tier"] == "TOP-TIER"
    assert top["current_score"] == "88.0"
    assert top["A_event_activity"] == "18.0"


def test_build_entity_rows_without_history(session):
    repo.upsert_profile(session, make_top_profile())
    rows = build_entity_rows(session)
    assert rows[0]["entity_id"] == "testclub"
    assert rows[0]["current_score"] == ""  # no score yet


# --- RSS feed ---------------------------------------------------------------

def test_render_rss_is_wellformed_and_escapes():
    items = [
        FeedItem(
            title="Score & rise", description="<b>up> 10",
            guid="g1", pub_date=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
        )
    ]
    xml = render_rss(items, now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc))
    # Parses as XML and escapes special chars.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    assert root.tag == "rss"
    item = root.find("./channel/item")
    assert item.findtext("title") == "Score & rise"
    assert item.findtext("description") == "<b>up> 10"
    assert "Sun, 14 Jun 2026 12:00:00 +0000" in xml


def test_alerts_to_items():
    class _A:
        id = 7
        alert_type = "score_change"
        entity_id = "berghain"
        message = "Score gestiegen"
        old_value = "70"
        new_value = "85"
        created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)

    items = alerts_to_items([_A()])
    assert items[0].guid == "scoredclub-alert-7"
    assert "70 → 85" in items[0].description


def test_build_feed_from_db(session):
    run = Run()
    session.add(run)
    session.flush()
    session.add(
        Alert(run_id=run.id, entity_id="berghain", alert_type="status_change",
              message="aktiv → geschlossen", old_value="active", new_value="closed")
    )
    session.commit()
    xml = build_feed(session)
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    titles = [i.findtext("title") for i in root.findall("./channel/item")]
    assert any("berghain" in t for t in titles)
