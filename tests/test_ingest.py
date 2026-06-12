from __future__ import annotations

import json
from pathlib import Path

from scoredclub.collectors.llm_ingest import ingest_file
from scoredclub.db import repo
from scoredclub.pipeline.run import seed_entities

FIXTURE = Path(__file__).parent / "fixtures" / "sample_research.json"
SEED_FILE = Path(__file__).parent.parent / "data" / "seeds" / "berlin_seed_entities.json"


def test_partial_ingest_reports_invalid_entry(session):
    report = ingest_file(session, FIXTURE)
    assert not report.ok
    assert len(report.errors) == 1
    assert "entity[2]" in report.errors[0]
    assert "Kaputtes Objekt" in report.errors[0]
    # The two valid entities were still ingested.
    assert len(report.ingested) == 2


def test_ingest_merges_into_seeds(session):
    seed_entities(session, SEED_FILE)
    report = ingest_file(session, FIXTURE)
    assert "berghain" in report.merged_entities
    assert report.new_entities == ["frische-crew"]

    berghain = repo.get_entity(session, "berghain")
    profile = repo.profile_from_row(berghain)
    assert profile.online.instagram.followers == 250000
    # Seed data preserved.
    assert profile.district == "Friedrichshain"
    assert profile.address is not None


def test_reingest_is_idempotent(session):
    seed_entities(session, SEED_FILE)
    ingest_file(session, FIXTURE)
    count_before = len(repo.all_entities(session))
    report = ingest_file(session, FIXTURE)
    assert len(repo.all_entities(session)) == count_before
    assert report.new_entities == []


def test_dry_run_writes_nothing(session, tmp_path):
    file = tmp_path / "research.json"
    file.write_text(json.dumps([{"name": "Dry Club", "type": "club"}]))
    report = ingest_file(session, file, dry_run=True)
    assert report.ok
    assert repo.all_entities(session) == []


def test_bare_array_accepted(session, tmp_path):
    file = tmp_path / "research.json"
    file.write_text(json.dumps([{"name": "Array Club", "type": "club"}]))
    report = ingest_file(session, file)
    assert report.ok
    assert report.new_entities == ["array-club"]
