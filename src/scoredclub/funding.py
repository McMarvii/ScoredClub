"""Förder-/Policy-Feed — funding programmes and cultural-policy items.

A lightweight, ingestable feed of Berlin music/club funding programmes and
relevant policy/status items (Clubcommission/Senat, UNESCO-ICH). It is read from
a JSON file (``sources.funding_feed_path``) — the same offline, file-driven
pattern as the research ingest — so the data flows without a DB table or a
live scraper. ``upcoming_deadlines`` surfaces programmes whose application
deadline falls within a window, the "eligibility/deadline hints" the roadmap
asks for. A live collector for German sources can later write this same file.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FundingProgram(_Base):
    name: str
    provider: str | None = None
    url: str | None = None
    deadline: dt.date | None = None
    eligibility: str | None = None
    amount: str | None = None
    status: str | None = None  # e.g. "open" | "closed" | "rolling"
    notes: str | None = None


class PolicyItem(_Base):
    title: str
    source: str | None = None
    url: str | None = None
    date: dt.date | None = None
    summary: str | None = None


class FundingFeed(_Base):
    programs: list[FundingProgram] = Field(default_factory=list)
    policies: list[PolicyItem] = Field(default_factory=list)


def load_funding(path: str | Path) -> FundingFeed:
    """Load the feed from a JSON file. Missing/invalid file -> empty feed."""
    path = Path(path)
    if not path.exists():
        return FundingFeed()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return FundingFeed()
    return FundingFeed.model_validate(data)


def upcoming_deadlines(
    feed: FundingFeed, *, today: dt.date | None = None, within_days: int = 90
) -> list[FundingProgram]:
    """Programmes with a deadline from ``today`` up to ``within_days`` ahead.

    Sorted by deadline (soonest first). Programmes without a deadline are
    excluded (no deadline to remind about).
    """
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=within_days)
    due = [
        p for p in feed.programs
        if p.deadline is not None and today <= p.deadline <= horizon
    ]
    return sorted(due, key=lambda p: p.deadline)


def feed_to_dict(feed: FundingFeed, today: dt.date | None = None, within_days: int = 90) -> dict:
    return {
        "programs": [json.loads(p.model_dump_json()) for p in feed.programs],
        "policies": [json.loads(p.model_dump_json()) for p in feed.policies],
        "upcoming_deadlines": [
            json.loads(p.model_dump_json())
            for p in upcoming_deadlines(feed, today=today, within_days=within_days)
        ],
    }
