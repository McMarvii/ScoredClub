"""Configuration loading.

Settings come from ``config/berlin_techno_agent_config.json`` (path
overridable via the ``SCOREDCLUB_CONFIG`` env var) with environment
variables taking precedence for runtime/secret values:

- ``DATABASE_URL``            (default ``sqlite:///data/scoredclub.db``)
- ``SCOREDCLUB_WEBHOOK_URL``  (overrides ``alerts.webhook_url``)
- ``SCOREDCLUB_CONFIG``       (path to the JSON config file)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_PATH = Path("config/berlin_techno_agent_config.json")
DEFAULT_DATABASE_URL = "sqlite:///data/scoredclub.db"


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ScoringWeights(_Base):
    event_activity: float = 0.20
    online_reach: float = 0.20
    press: float = 0.15
    community: float = 0.15
    networking: float = 0.10
    continuity: float = 0.10
    safety: float = 0.10


class TierThresholds(_Base):
    top: float = 75.0
    mid: float = 50.0
    emerging: float = 25.0


class ScoringConfig(_Base):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    bonus_per_item: float = 5.0
    bonus_cap: float = 15.0
    malus_per_incident: float = 5.0
    malus_cap: float = 15.0
    tier_thresholds: TierThresholds = Field(default_factory=TierThresholds)
    inactive_after_days: int = 180


class AlertsConfig(_Base):
    score_change_threshold: float = 10.0
    webhook_url: str | None = None


class SourcesConfig(_Base):
    clubcommission_url: str = "https://www.clubcommission.de/"
    ra_graphql_url: str = "https://ra.co/graphql"
    reddit_search_url: str = "https://www.reddit.com/search.json"
    reddit_enabled: bool = True
    reddit_max_threads: int = 5
    extra_sources: list[str] = Field(default_factory=list)


class RunConfig(_Base):
    next_run_interval_days: int = 30
    output_dir: str = "output"


class Settings(_Base):
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    database_url: str = DEFAULT_DATABASE_URL

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Settings":
        path = Path(config_path or os.environ.get("SCOREDCLUB_CONFIG", DEFAULT_CONFIG_PATH))
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(f"Cannot read config file {path}: {exc}") from exc
        settings = cls.model_validate(data)
        settings.database_url = os.environ.get("DATABASE_URL", settings.database_url)
        webhook_env = os.environ.get("SCOREDCLUB_WEBHOOK_URL")
        if webhook_env:
            settings.alerts.webhook_url = webhook_env
        return settings
