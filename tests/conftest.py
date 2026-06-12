from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scoredclub.config import Settings
from scoredclub.db.models import Base
from scoredclub.schemas import (
    CommunityInfo,
    CulturalRecognition,
    EntityProfile,
    EntityStatus,
    EntityType,
    EventsInfo,
    LabelsPodcasts,
    NetworkingInfo,
    OnlinePresence,
    PolicySafety,
    PressInfo,
    SentimentHint,
    SocialPresence,
)

TODAY = date(2026, 6, 12)


@pytest.fixture()
def session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture()
def settings(tmp_path) -> Settings:
    s = Settings()
    s.run.output_dir = str(tmp_path / "output")
    return s


def make_top_profile(**overrides) -> EntityProfile:
    """A Berghain-like maxed-out profile."""
    defaults = dict(
        entity_id="testclub",
        name="Testclub",
        type=EntityType.club,
        status=EntityStatus.active,
        district="Friedrichshain",
        active_since="2004",
        last_event_date=TODAY,
        online=OnlinePresence(
            website=SocialPresence(url="https://testclub.de"),
            instagram=SocialPresence(handle="testclub", followers=120_000),
            facebook=SocialPresence(url="https://facebook.com/testclub", followers=80_000),
            soundcloud=SocialPresence(url="https://soundcloud.com/testclub", followers=30_000),
            youtube=SocialPresence(url="https://youtube.com/@testclub", followers=10_000),
            bandcamp=SocialPresence(url="https://testclub.bandcamp.com"),
        ),
        events=EventsInfo(
            ra_profile_url="https://ra.co/clubs/test",
            ra_followers=90_000,
            events_last_3_months=14,
            events_last_6_months=28,
        ),
        press=PressInfo(
            major_features=["RA Feature 2025", "Mixmag Cover Story"],
            local_press_mentions=["taz", "tip Berlin"],
            international_mentions=["The Guardian"],
            cultural_funding_mentions=["Clubkultur-Förderung 2024"],
        ),
        community=CommunityInfo(
            reddit_threads=[f"https://reddit.com/r/berlin/{i}" for i in range(12)],
            twitter_handles=["@testclub"],
            community_sentiment_hint=SentimentHint.positive,
        ),
        networking=NetworkingInfo(
            booked_djs=[f"DJ {i}" for i in range(8)],
            collaborations=["Label X", "Festival Y", "Kollektiv Z"],
            cross_promotions=["Club A", "Club B"],
            international_booking=True,
        ),
        policy_safety=PolicySafety(
            safer_spaces_communicated=True, queer_friendly=True, flinta_focus=True
        ),
        labels_podcasts=LabelsPodcasts(own_label=True, podcast_series=True),
        cultural_recognition=CulturalRecognition(clubcommission_member=True),
        last_verification=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return EntityProfile(**defaults)


def make_minimal_profile(**overrides) -> EntityProfile:
    """A minimal emerging collective."""
    defaults = dict(
        name="Neues Kollektiv",
        type=EntityType.collective,
        status=EntityStatus.emerging,
        active_since="2025",
    )
    defaults.update(overrides)
    return EntityProfile(**defaults)
