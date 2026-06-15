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


class ConfidenceConfig(_Base):
    """How much we trust an entity's score, given data completeness + freshness."""

    # Below this overall confidence (0-100) an entity is flagged low-confidence.
    low_confidence_threshold: float = 50.0
    # Verified within this many days -> full freshness.
    freshness_full_days: int = 45
    # Freshness never drops below this floor as data ages.
    freshness_floor: float = 20.0
    # Freshness assigned when last_verification is missing entirely.
    unknown_verification_confidence: float = 30.0
    # Blend of data completeness vs. freshness in the overall confidence.
    completeness_weight: float = 0.7
    freshness_weight: float = 0.3


class ScoringConfig(_Base):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    bonus_per_item: float = 5.0
    bonus_cap: float = 15.0
    malus_per_incident: float = 5.0
    malus_cap: float = 15.0
    tier_thresholds: TierThresholds = Field(default_factory=TierThresholds)
    inactive_after_days: int = 180
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)


class EmailConfig(_Base):
    """SMTP digest e-mails (off by default). Password via SCOREDCLUB_SMTP_PASSWORD."""

    enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    use_tls: bool = True
    username: str | None = None
    from_addr: str = "scoredclub@localhost"
    to_addrs: list[str] = Field(default_factory=list)
    subject_prefix: str = "[ScoredClub]"


class AlertsConfig(_Base):
    score_change_threshold: float = 10.0
    webhook_url: str | None = None
    # Optional Slack incoming-webhook URL (off unless set). One digest message
    # per run. Overridable via SCOREDCLUB_SLACK_WEBHOOK_URL.
    slack_webhook_url: str | None = None
    email: EmailConfig = Field(default_factory=EmailConfig)


class SourcesConfig(_Base):
    clubcommission_url: str = "https://www.clubcommission.de/"
    ra_graphql_url: str = "https://ra.co/graphql"
    reddit_search_url: str = "https://www.reddit.com/search.json"
    # OAuth endpoints used when REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET are set in
    # the environment (reliable, rate-limited access). Falls back to the public
    # search endpoint above when no credentials are configured.
    reddit_oauth_token_url: str = "https://www.reddit.com/api/v1/access_token"
    reddit_oauth_search_url: str = "https://oauth.reddit.com/search"
    reddit_enabled: bool = True
    reddit_max_threads: int = 5
    # Bandsintown is the sanctioned event source for artist-type entities.
    # The collector is a no-op unless BANDSINTOWN_APP_ID is set in the
    # environment and at least one artist entity is present.
    bandsintown_url: str = "https://rest.bandsintown.com/artists"
    bandsintown_max_artists: int = 25
    # Songkick is a second sanctioned event source for artists (needs
    # SONGKICK_API_KEY); no-op without the key or without artist entities.
    songkick_url: str = "https://api.songkick.com/api/3.0"
    songkick_max_artists: int = 25
    # Deterministic lexicon sentiment analysis (no network). Off by default so
    # the canonical run is unaffected; when on it fills only *unknown* hints and
    # never overrides a researcher-supplied sentiment.
    sentiment_enabled: bool = False
    # Förder-/Policy-Feed (JSON file; ingestable like research, no live scraper).
    funding_feed_path: str = "data/funding/berlin_funding.json"
    # External follower-audit provider (fake-follower %, engagement, history).
    # No-op unless FOLLOWER_AUDIT_API_KEY is set; provider-agnostic — point the
    # URL at an adapter that returns the normalised shape (see docs).
    follower_audit_url: str = "https://api.follower-audit.example/v1/audit"
    follower_audit_max_entities: int = 25
    extra_sources: list[str] = Field(default_factory=list)


class RunConfig(_Base):
    next_run_interval_days: int = 30
    output_dir: str = "output"
    # Fill empty geo coordinates from the entity's Berlin district (static
    # centroids; no external geocoding service).
    geocode_districts: bool = True


class TrendingConfig(_Base):
    # Number of most recent runs used to compute momentum/direction.
    momentum_window: int = 4
    # |momentum| below this counts as "stable" rather than rising/falling.
    stable_epsilon: float = 1.0
    # How many entities to list as top risers / fallers.
    movers_limit: int = 5


class RetentionConfig(_Base):
    """GDPR retention for community/personal data (applied via ``scoredclub retention``)."""

    enabled: bool = False
    # Redact community/personal data older than this many days (by last_verification).
    community_days: int = 365


class AuthenticityConfig(_Base):
    """Follower-authenticity module (informational; never affects scoring)."""

    # Append current follower counts to follower_history on every run, so the
    # historical trajectory the check evaluates builds up over time. Off by
    # default to keep the canonical run reproducible.
    capture_history: bool = False


class AnalyticsConfig(_Base):
    """Breakout/anomaly detection, career-phase and forecast tuning (pure)."""

    # Runs considered for breakout/forecast (0 = full history).
    history_window: int = 12
    # Dynamic baseline never drops below this (points/run) so a steady climb
    # still registers as a breakout.
    breakout_baseline_floor: float = 1.0
    # Slope-to-volatility z thresholds for the breakout buckets.
    growth_z: float = 1.0
    strong_z: float = 2.0
    explosive_z: float = 3.0
    # Minimum projected slope (points/run) to flag "rising soon".
    forecast_epsilon: float = 0.5
    # Percentile cut-offs for the career phases.
    elite_percentile: float = 90.0
    established_percentile: float = 70.0
    emerging_percentile: float = 40.0


class LLMResearchConfig(_Base):
    """Agentic LLM research collector (optional, off by default).

    Requires the optional ``anthropic`` dependency and an ``ANTHROPIC_API_KEY``
    in the environment. When disabled (the default) the collector is a no-op.
    """

    enabled: bool = False
    model: str = "claude-opus-4-8"
    # Max entities researched per run (0 = all); stalest entities first.
    max_entities: int = 8
    # Effort for the research/extraction calls (low|medium|high|max).
    effort: str = "medium"
    # Continuation cap while the server-side web_search loop runs.
    research_max_continuations: int = 4


class Settings(_Base):
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    trending: TrendingConfig = Field(default_factory=TrendingConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    authenticity: AuthenticityConfig = Field(default_factory=AuthenticityConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    llm: LLMResearchConfig = Field(default_factory=LLMResearchConfig)
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
        slack_env = os.environ.get("SCOREDCLUB_SLACK_WEBHOOK_URL")
        if slack_env:
            settings.alerts.slack_webhook_url = slack_env
        return settings
