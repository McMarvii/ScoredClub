"""Per-dimension scoring rubrics.

Scoring semantics
-----------------
The original spec multiplies dimension points (already on different max
scales, summing to 100) by weights a second time. We resolve this as:

* every rubric returns a normalized subscore in 0..100,
* the engine computes ``base = sum(weight_i * subscore_i)`` with weights
  summing to 1.0 (configurable),
* per-dimension *points* shown in reports are ``weight * subscore`` so the
  visible maxima match the spec (A max 20 pts, C max 15 pts, ...),
* ``total = clamp(base + bonus - malus, 0, 100)``.

All rubrics are pure functions over :class:`~scoredclub.schemas.EntityProfile`
and tolerate missing data (``None`` scores as "unknown", usually 0).
"""

from __future__ import annotations

from datetime import date

from scoredclub.schemas import EntityProfile, EntityStatus, SentimentHint

_FOLLOWER_BANDS = [
    (100_000, 100.0),
    (50_000, 85.0),
    (20_000, 70.0),
    (10_000, 55.0),
    (5_000, 40.0),
    (1_000, 25.0),
    (1, 10.0),
]

_SENTIMENT_MULTIPLIER = {
    SentimentHint.positive: 1.3,
    SentimentHint.mixed: 1.0,
    SentimentHint.negative: 0.6,
    SentimentHint.unknown: 0.9,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def event_activity(profile: EntityProfile, today: date) -> float:
    """A — Event activity, based on the 3/6-month event counts."""
    last_3 = profile.events.events_last_3_months
    last_6 = profile.events.events_last_6_months

    if last_3:
        per_month = last_3 / 3.0
        if per_month >= 4:
            score = 100.0
        elif per_month >= 2:
            score = 75.0
        elif per_month >= 1:
            score = 50.0
        else:
            score = 30.0
    elif last_6:
        score = 15.0
    else:
        score = 0.0

    # Stale-data guard: claimed activity but last known event is >90 days old.
    if score > 0 and profile.last_event_date and (today - profile.last_event_date).days > 90:
        score -= 20.0
    return _clamp(score)


def online_reach(profile: EntityProfile) -> float:
    """B — Online reach: 70% follower band + 30% platform breadth."""
    followers = profile.max_followers()
    band = 0.0
    for threshold, value in _FOLLOWER_BANDS:
        if followers >= threshold:
            band = value
            break

    active = [
        p
        for p in profile.online.platforms().values()
        if (p.url or p.handle) and (p.activity_hint or "").lower() != "inactive"
    ]
    breadth = min(len(active), 6) / 6.0 * 100.0
    return _clamp(0.7 * band + 0.3 * breadth)


def press(profile: EntityProfile) -> float:
    """C — Press presence."""
    score = min(len(profile.press.major_features) * 40.0, 80.0)
    score += min(len(profile.press.local_press_mentions) * 5.0, 10.0)
    if profile.press.international_mentions:
        score += 5.0
    if profile.press.cultural_funding_mentions:
        score += 5.0
    return _clamp(score)


def community(profile: EntityProfile) -> float:
    """D — Community resonance."""
    threads = len(profile.community.reddit_threads)
    if threads >= 10:
        score = 60.0
    elif threads >= 5:
        score = 45.0
    elif threads >= 1:
        score = 25.0
    else:
        score = 0.0
    if profile.community.twitter_handles:
        score += 10.0
    score *= _SENTIMENT_MULTIPLIER[profile.community.community_sentiment_hint]
    return _clamp(score)


def networking(profile: EntityProfile) -> float:
    """E — Scene networking."""
    score = min(len(profile.networking.booked_djs) * 8.0, 56.0)
    score += min(len(profile.networking.collaborations) * 10.0, 30.0)
    score += min(len(profile.networking.cross_promotions) * 7.0, 14.0)
    return _clamp(score)


def continuity(profile: EntityProfile, today: date) -> float:
    """F — Continuity (years active)."""
    if profile.status == EntityStatus.closed:
        return 0.0
    year = profile.active_since_year()
    if year is None:
        return 10.0
    years = today.year - year
    if years >= 20:
        return 100.0
    if years >= 10:
        return 80.0
    if years >= 5:
        return 60.0
    if years >= 2:
        return 40.0
    if years >= 1:
        return 25.0
    return 10.0


def safety(profile: EntityProfile) -> float:
    """G — Safety & inclusivity (tri-state flags, None counts as 0)."""
    score = 0.0
    if profile.policy_safety.safer_spaces_communicated:
        score += 40.0
    if profile.policy_safety.queer_friendly:
        score += 40.0
    if profile.policy_safety.flinta_focus:
        score += 20.0
    return _clamp(score)


def bonus_items(profile: EntityProfile) -> list[str]:
    """Bonus criteria, +bonus_per_item each, capped by the engine."""
    items: list[str] = []
    rec = profile.cultural_recognition
    if rec.clubcommission_member or rec.unesco_mention or rec.cultural_funding or profile.press.cultural_funding_mentions:
        items.append("Kulturelle Anerkennung (Clubcommission/UNESCO/Förderung)")
    if profile.labels_podcasts.own_label or profile.labels_podcasts.podcast_series:
        items.append("Eigenes Label oder Podcast-Reihe")
    if profile.networking.international_booking or profile.press.international_mentions:
        items.append("Internationales Booking / internationale Resonanz")
    return items


def malus_items(profile: EntityProfile) -> list[str]:
    """Malus criteria, -malus_per_incident each, capped by the engine."""
    items = [f"Vorfall: {incident.description}" for incident in profile.incidents]
    if profile.status == EntityStatus.inactive:
        items.append("Längere Inaktivität")
    return items
