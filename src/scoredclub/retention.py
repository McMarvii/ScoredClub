"""GDPR-minded retention for community/personal data.

Community signals (Reddit thread links, Twitter handles) are the most
person-adjacent data the system keeps. This module expires them once they are
older than a retention window — derived from ``last_verification`` — while
keeping the *aggregate* signal (the sentiment hint, thread counts already folded
into scores) intact. Pure functions over a profile; the CLI applies them across
the database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from scoredclub.schemas import EntityProfile


@dataclass
class RetentionResult:
    entity_id: str
    redacted_fields: list[str]


def apply_retention(
    profile: EntityProfile, *, retention_days: int, today: dt.date | None = None
) -> list[str]:
    """Redact stale community/personal data in place. Returns redacted fields.

    A profile is only redacted when its ``last_verification`` is older than
    ``retention_days``; without a verification date nothing is touched (we can't
    prove it is stale).
    """
    today = today or dt.date.today()
    last = profile.last_verification
    if last is None:
        return []
    age = (today - last.date()).days
    if age <= retention_days:
        return []

    redacted: list[str] = []
    if profile.community.reddit_threads:
        profile.community.reddit_threads = []
        redacted.append("community.reddit_threads")
    if profile.community.twitter_handles:
        profile.community.twitter_handles = []
        redacted.append("community.twitter_handles")
    return redacted
