from __future__ import annotations

import json
from datetime import timedelta

from scoredclub.config import ScoringConfig
from scoredclub.pipeline.diff import RunDiff
from scoredclub.reports.render import (
    ScoredEntity,
    render_entities_json,
    render_markdown,
    render_next_run_json,
    write_reports,
)
from scoredclub.schemas import EntityProfile
from scoredclub.scoring import score_entity
from tests.conftest import TODAY, make_minimal_profile, make_top_profile

CONFIG = ScoringConfig()


def _scored() -> list[ScoredEntity]:
    top = make_top_profile()
    emerging = make_minimal_profile(status="active", active_since="2025")
    emerging.events.events_last_3_months = 4
    emerging.last_event_date = TODAY
    emerging.online.instagram.followers = 2500
    emerging.online.instagram.handle = "emerging"
    return [
        ScoredEntity(profile=top, breakdown=score_entity(top, CONFIG, today=TODAY)),
        ScoredEntity(
            profile=emerging,
            breakdown=score_entity(emerging, CONFIG, today=TODAY),
            is_new=True,
        ),
    ]


def test_markdown_structure(settings):
    md = render_markdown(_scored(), [], TODAY, settings)
    assert "# Berlin Techno Intelligence Report" in md
    assert "## TOP-TIER (Score ≥ 75)" in md
    assert "## EMERGING" in md
    assert "## Zusammenfassung" in md
    assert "### Testclub" in md
    # The top profile is grouped under TOP-TIER before the MID-TIER heading.
    assert md.index("### Testclub") < md.index("## MID-TIER")
    assert "Neu entdeckte Entitäten" in md
    assert "Neues Kollektiv" in md
    assert "Empfehlungen" in md


def test_entities_json_roundtrip(settings):
    data = render_entities_json(_scored(), TODAY, settings)
    assert data["generated_at"] == TODAY.isoformat()
    assert data["next_run"] == (TODAY + timedelta(days=30)).isoformat()
    for entry in data["entities"]:
        EntityProfile.model_validate(entry)  # must round-trip
        assert "score" in entry


def test_next_run_json(settings):
    diff = RunDiff()
    data = render_next_run_json(diff, [], TODAY, 2, settings)
    assert data["last_run"] == TODAY.isoformat()
    assert data["next_run"] == (TODAY + timedelta(days=30)).isoformat()
    assert data["entities_tracked"] == 2


def test_write_reports_files(settings, tmp_path):
    md_path, json_path, next_path = write_reports(_scored(), RunDiff(), [], TODAY, settings)
    assert md_path.exists() and md_path.name == f"berlin_techno_check_{TODAY}.md"
    assert json_path.exists() and json_path.name == f"berlin_techno_entities_{TODAY}.json"
    assert next_path.exists() and next_path.name == "next_run.json"
    json.loads(json_path.read_text(encoding="utf-8"))
    json.loads(next_path.read_text(encoding="utf-8"))
