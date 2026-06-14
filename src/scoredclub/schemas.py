"""Pydantic models for entity profiles.

This is the canonical data schema shared by the LLM research ingest,
the network collectors, the database (stored as JSON), the scoring
engine and the report renderers. Unknown/extra keys are ignored so
research JSON produced by an LLM with additional fields still validates.
Unknown values are expressed as ``None`` (or empty lists) — the scoring
rubrics tolerate missing data.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EntityType(str, Enum):
    club = "club"
    collective = "collective"
    label = "label"
    series = "series"
    artist = "artist"


class EntityStatus(str, Enum):
    active = "active"
    emerging = "emerging"
    inactive = "inactive"
    closed = "closed"
    unknown = "unknown"


class SentimentHint(str, Enum):
    positive = "positive"
    mixed = "mixed"
    negative = "negative"
    unknown = "unknown"


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Geo(_Base):
    lat: float | None = None
    lon: float | None = None


class SocialPresence(_Base):
    url: str | None = None
    handle: str | None = None
    followers: int | None = None
    posts_per_month: float | None = None
    last_activity: date | None = None
    activity_hint: str | None = None


class OnlinePresence(_Base):
    website: SocialPresence = Field(default_factory=SocialPresence)
    instagram: SocialPresence = Field(default_factory=SocialPresence)
    facebook: SocialPresence = Field(default_factory=SocialPresence)
    soundcloud: SocialPresence = Field(default_factory=SocialPresence)
    mixcloud: SocialPresence = Field(default_factory=SocialPresence)
    bandcamp: SocialPresence = Field(default_factory=SocialPresence)
    youtube: SocialPresence = Field(default_factory=SocialPresence)
    tiktok: SocialPresence = Field(default_factory=SocialPresence)

    def platforms(self) -> dict[str, SocialPresence]:
        return {
            "website": self.website,
            "instagram": self.instagram,
            "facebook": self.facebook,
            "soundcloud": self.soundcloud,
            "mixcloud": self.mixcloud,
            "bandcamp": self.bandcamp,
            "youtube": self.youtube,
            "tiktok": self.tiktok,
        }


class EventsInfo(_Base):
    ra_profile_url: str | None = None
    ra_followers: int | None = None
    events_last_3_months: int | None = None
    events_last_6_months: int | None = None
    ticketing_platforms: list[str] = Field(default_factory=list)


class DemandInfo(_Base):
    """Event-demand proxies (RA 'going', sold-out/waitlist from Dice/Shotgun)."""

    going_count: int | None = None  # interest/"going" count for recent events
    sold_out: bool | None = None
    waitlist: bool | None = None
    source: str | None = None

    @field_validator("sold_out", "waitlist", mode="before")
    @classmethod
    def _coerce_yes_no(cls, v: object) -> object:
        return PolicySafety._coerce_yes_no(v)


class FollowerPoint(_Base):
    date: dt.date | None = None
    followers: int


class PressInfo(_Base):
    major_features: list[str] = Field(default_factory=list)
    local_press_mentions: list[str] = Field(default_factory=list)
    international_mentions: list[str] = Field(default_factory=list)
    cultural_funding_mentions: list[str] = Field(default_factory=list)


class CommunityInfo(_Base):
    reddit_threads: list[str] = Field(default_factory=list)
    twitter_handles: list[str] = Field(default_factory=list)
    community_sentiment_hint: SentimentHint = SentimentHint.unknown


class NetworkingInfo(_Base):
    booked_djs: list[str] = Field(default_factory=list)
    cross_promotions: list[str] = Field(default_factory=list)
    collaborations: list[str] = Field(default_factory=list)
    international_booking: bool | None = None


class PolicySafety(_Base):
    """Tri-state flags: True / False / None (= unknown)."""

    safer_spaces_communicated: bool | None = None
    queer_friendly: bool | None = None
    flinta_focus: bool | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_yes_no(cls, v: object) -> object:
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered in {"yes", "ja", "true"}:
                return True
            if lowered in {"no", "nein", "false"}:
                return False
            if lowered in {"unclear", "unknown", ""}:
                return None
        return v


class LabelsPodcasts(_Base):
    own_label: bool | None = None
    podcast_series: bool | None = None
    details: list[str] = Field(default_factory=list)

    @field_validator("own_label", "podcast_series", mode="before")
    @classmethod
    def _coerce_yes_no(cls, v: object) -> object:
        return PolicySafety._coerce_yes_no(v)


class Incident(_Base):
    date: dt.date | None = None  # field name shadows the type, hence the dt alias
    description: str
    source: str | None = None


class SourceRef(_Base):
    url: str
    accessed_at: date | None = None
    note: str | None = None


class LifecycleEventType(str, Enum):
    opening = "opening"
    closure = "closure"
    reopening = "reopening"
    relocation = "relocation"
    threatened = "threatened"  # at risk but not (yet) closed


class ClosureCause(str, Enum):
    """Taxonomy of why a venue closes/is threatened (Berlin 'Clubsterben')."""

    rent = "rent"
    noise = "noise"
    redevelopment = "redevelopment"
    insolvency = "insolvency"
    pandemic = "pandemic"
    licensing = "licensing"
    sale = "sale"
    other = "other"
    unknown = "unknown"


class LifecycleEvent(_Base):
    date: dt.date | None = None  # field name shadows the type, hence the dt alias
    event_type: LifecycleEventType
    cause: ClosureCause | None = None
    description: str | None = None
    source: str | None = None


class DisplacementSignalType(str, Enum):
    rent_increase = "rent_increase"
    property_sale = "property_sale"
    rezoning = "rezoning"
    noise_complaint = "noise_complaint"
    construction = "construction"
    other = "other"


class DisplacementSignal(_Base):
    signal_type: DisplacementSignalType = DisplacementSignalType.other
    description: str | None = None
    date: dt.date | None = None
    source: str | None = None


class FieldProvenance(_Base):
    """Where a single field's value came from, and how trustworthy it is.

    Keyed in :attr:`EntityProfile.provenance` by a dotted field path
    (e.g. ``"events.ra_followers"``). Optional throughout — entities without
    provenance simply carry an empty map.
    """

    source: str  # URL or source name
    confidence: float | None = None  # 0..100
    accessed_at: date | None = None
    note: str | None = None


class CulturalRecognition(_Base):
    clubcommission_member: bool | None = None
    unesco_mention: bool | None = None
    cultural_funding: bool | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_yes_no(cls, v: object) -> object:
        return PolicySafety._coerce_yes_no(v)


def slugify(name: str) -> str:
    """Derive a stable entity_id slug from a name."""
    norm = unicodedata.normalize("NFKD", name)
    norm = norm.encode("ascii", "ignore").decode("ascii").lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm or "entity"


class EntityProfile(_Base):
    entity_id: str = ""
    name: str
    aliases: list[str] = Field(default_factory=list)
    type: EntityType = EntityType.club
    status: EntityStatus = EntityStatus.unknown
    address: str | None = None
    district: str | None = None
    geo: Geo = Field(default_factory=Geo)
    active_since: str | None = None  # "YYYY" or "YYYY-MM"
    last_event_date: date | None = None
    online: OnlinePresence = Field(default_factory=OnlinePresence)
    events: EventsInfo = Field(default_factory=EventsInfo)
    # Optional event-demand proxies and per-platform follower time-series.
    demand: DemandInfo | None = None
    follower_history: dict[str, list[FollowerPoint]] = Field(default_factory=dict)
    press: PressInfo = Field(default_factory=PressInfo)
    community: CommunityInfo = Field(default_factory=CommunityInfo)
    networking: NetworkingInfo = Field(default_factory=NetworkingInfo)
    policy_safety: PolicySafety = Field(default_factory=PolicySafety)
    labels_podcasts: LabelsPodcasts = Field(default_factory=LabelsPodcasts)
    cultural_recognition: CulturalRecognition = Field(default_factory=CulturalRecognition)
    incidents: list[Incident] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    # Cultural-ecosystem monitoring (Berlin 'Clubsterben'). Both optional.
    lifecycle_events: list[LifecycleEvent] = Field(default_factory=list)
    displacement_signals: list[DisplacementSignal] = Field(default_factory=list)
    # Per-field provenance: dotted field path -> source/confidence. Optional.
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    notes: str | None = None
    last_verification: datetime | None = None

    @model_validator(mode="after")
    def _derive_entity_id(self) -> "EntityProfile":
        if not self.entity_id:
            self.entity_id = slugify(self.name)
        return self

    @field_validator("active_since", mode="before")
    @classmethod
    def _coerce_active_since(cls, v: object) -> object:
        if isinstance(v, int):
            return str(v)
        return v

    def active_since_year(self) -> int | None:
        if not self.active_since:
            return None
        match = re.match(r"(\d{4})", self.active_since)
        return int(match.group(1)) if match else None

    def max_followers(self) -> int:
        candidates = [p.followers or 0 for p in self.online.platforms().values()]
        candidates.append(self.events.ra_followers or 0)
        return max(candidates)


class ScoreBreakdown(_Base):
    """Computed scoring result — output only, never part of research input."""

    subscores: dict[str, float] = Field(default_factory=dict)  # dimension -> 0..100
    points: dict[str, float] = Field(default_factory=dict)  # dimension -> weighted points
    bonus_items: list[str] = Field(default_factory=list)
    malus_items: list[str] = Field(default_factory=list)
    bonus: float = 0.0
    malus: float = 0.0
    base: float = 0.0
    total: float = 0.0
    tier: str = ""
    # Confidence-awareness (additive; total/tier are unaffected).
    confidence: float = 100.0  # overall 0-100 (completeness + freshness)
    dimension_confidence: dict[str, float] = Field(default_factory=dict)  # dim -> presence %
    freshness: float = 100.0
    low_confidence: bool = False
    # Relevance computed over the dimensions we actually have data for.
    confidence_adjusted_total: float = 0.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
