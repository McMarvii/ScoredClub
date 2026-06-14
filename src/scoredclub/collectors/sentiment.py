"""Sentiment enrichment collector (offline, deterministic).

Derives ``community.community_sentiment_hint`` from each entity's available
community/free text (Reddit thread title slugs + notes) using the lexicon
analyzer in :mod:`scoredclub.sentiment`, replacing the manually supplied hint.

Off by default (``sources.sentiment_enabled``). It only fills a hint that is
still ``unknown`` — a researcher-supplied sentiment is never overwritten — and
runs entirely offline, so it is failure-proof and CI-safe. As an *enrichment*
collector it augments existing entities only; it never creates new ones.
"""

from __future__ import annotations

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import (
    CommunityInfo,
    EntityProfile,
    SentimentHint,
    utcnow,
)
from scoredclub.sentiment import analyze_texts, texts_for_profile


class SentimentCollector:
    name = "sentiment"

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        if not settings.sources.sentiment_enabled or not entities:
            return result

        for entity in entities:
            # Respect a researcher-supplied hint — only fill unknowns.
            if entity.community.community_sentiment_hint != SentimentHint.unknown:
                continue
            texts = texts_for_profile(entity)
            if not texts:
                continue
            analysis = analyze_texts(texts)
            if analysis.hint == SentimentHint.unknown:
                continue
            result.profiles.append(
                EntityProfile(
                    name=entity.name,
                    community=CommunityInfo(community_sentiment_hint=analysis.hint),
                    last_verification=utcnow(),
                )
            )
        return result
