from __future__ import annotations

from scoredclub.collectors.sentiment import SentimentCollector
from scoredclub.config import Settings
from scoredclub.db import repo
from scoredclub.schemas import (
    CommunityInfo,
    EntityProfile,
    EntityType,
    SentimentHint,
)
from scoredclub.sentiment import (
    analyze_texts,
    fold,
    text_from_reddit_permalink,
    texts_for_profile,
    tokenize,
)


def test_fold_and_tokenize():
    assert fold("Über GROSSARTIG ß") == "uber grossartig ss"
    assert tokenize("Berghain: amazing!! night") == ["berghain", "amazing", "night"]


def test_positive_negative_unknown():
    assert analyze_texts(["absolutely amazing night, best club"]).hint == SentimentHint.positive
    assert analyze_texts(["terrible door, rude and overpriced"]).hint == SentimentHint.negative
    assert analyze_texts(["the event starts at ten"]).hint == SentimentHint.unknown
    assert analyze_texts([]).hint == SentimentHint.unknown


def test_mixed_when_both_sides_present():
    res = analyze_texts(["great music but terrible door and rude staff", "amazing crowd, awful sound"])
    assert res.hint == SentimentHint.mixed
    assert res.positive_hits > 0 and res.negative_hits > 0


def test_negation_flips_polarity():
    assert analyze_texts(["not great at all"]).hint != SentimentHint.positive
    # "not bad" should not read as negative.
    res = analyze_texts(["the club is not bad"])
    assert res.hint in (SentimentHint.positive, SentimentHint.mixed, SentimentHint.unknown)
    assert res.negative_hits == 0


def test_intensifier_scales():
    plain = analyze_texts(["good vibes great"])
    strong = analyze_texts(["very great absolutely amazing"])
    assert strong.positive_hits > plain.positive_hits


def test_german_terms():
    assert analyze_texts(["super geiler Laden, beste Crew"]).hint == SentimentHint.positive
    assert analyze_texts(["total überteuert und gefährlich"]).hint == SentimentHint.negative


def test_reddit_permalink_extraction():
    url = "https://www.reddit.com/r/berlin/comments/abc123/berghain_door_is_amazing/"
    assert text_from_reddit_permalink(url) == "berghain door is amazing"
    # A bare id segment yields nothing readable.
    assert text_from_reddit_permalink("https://reddit.com/r/x/comments/abc123/") == ""
    assert text_from_reddit_permalink("") == ""


def test_texts_for_profile():
    profile = EntityProfile(
        name="X",
        community=CommunityInfo(reddit_threads=[
            "https://www.reddit.com/r/berlin/comments/a/best_techno_club_ever/",
        ]),
        notes="Awesome safer-spaces policy.",
    )
    texts = texts_for_profile(profile)
    assert "best techno club ever" in texts
    assert any("safer" in t.lower() for t in texts)


def test_collector_disabled_is_noop():
    settings = Settings()  # sentiment_enabled defaults False
    profile = EntityProfile(
        name="X",
        community=CommunityInfo(reddit_threads=[
            "https://www.reddit.com/r/berlin/comments/a/amazing_best_night/",
        ]),
    )
    result = SentimentCollector().collect(settings, entities=[profile])
    assert result.ok
    assert result.profiles == []


def test_collector_fills_unknown_hint_when_enabled():
    settings = Settings()
    settings.sources.sentiment_enabled = True
    profile = EntityProfile(
        name="Berghain", type=EntityType.club,
        community=CommunityInfo(reddit_threads=[
            "https://www.reddit.com/r/berlin/comments/a/amazing_best_night_ever/",
            "https://www.reddit.com/r/techno/comments/b/legendary_sound_system/",
        ]),
    )
    result = SentimentCollector().collect(settings, entities=[profile])
    assert len(result.profiles) == 1
    assert result.profiles[0].community.community_sentiment_hint == SentimentHint.positive


def test_collector_respects_existing_hint():
    settings = Settings()
    settings.sources.sentiment_enabled = True
    profile = EntityProfile(
        name="X",
        community=CommunityInfo(
            community_sentiment_hint=SentimentHint.negative,  # researcher-set
            reddit_threads=["https://www.reddit.com/r/berlin/comments/a/amazing_best/"],
        ),
    )
    result = SentimentCollector().collect(settings, entities=[profile])
    assert result.profiles == []  # does not override an existing hint


def test_collector_merges_into_entity(session):
    seed = EntityProfile(
        entity_id="berghain", name="Berghain", type=EntityType.club,
        community=CommunityInfo(reddit_threads=[
            "https://www.reddit.com/r/berlin/comments/a/best_club_amazing_crew/",
        ]),
    )
    repo.upsert_profile(session, seed)
    settings = Settings()
    settings.sources.sentiment_enabled = True
    current = [repo.profile_from_row(e) for e in repo.all_entities(session)]
    result = SentimentCollector().collect(settings, entities=current)
    for profile in result.profiles:
        repo.upsert_profile(session, profile, create_if_missing=False)
    merged = repo.profile_from_row(repo.get_entity(session, "berghain"))
    assert merged.community.community_sentiment_hint == SentimentHint.positive
    # Existing threads preserved.
    assert merged.community.reddit_threads
