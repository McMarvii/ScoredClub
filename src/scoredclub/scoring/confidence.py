"""Confidence-aware scoring.

The relevance score treats missing data as a zero — which means a club we
simply haven't researched looks identical to one that is genuinely small. This
module quantifies *how much we actually know* so consumers can tell "low score
because it's small" from "low score because the data is thin":

* **dimension presence** — per dimension (A-G), the fraction of its input
  signals that are actually filled in;
* **data completeness** — the weighted average presence across dimensions;
* **freshness** — derived from ``last_verification`` (decays as data ages);
* **overall confidence** — a blend of completeness and freshness (0-100).

These are pure functions over :class:`~scoredclub.schemas.EntityProfile`; the
engine attaches the results to the score breakdown and also computes a
confidence-adjusted score (relevance over the dimensions we have data for).
"""

from __future__ import annotations

from datetime import date

from scoredclub.config import ConfidenceConfig
from scoredclub.schemas import EntityProfile, SentimentHint

# Per-dimension presence checks (each contributes equally within its dimension).
# Keys match the engine's subscore keys.


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


def dimension_presence(profile: EntityProfile) -> dict[str, float]:
    """Per-dimension fraction of input signals present, as a 0-100 value."""
    online_active = [
        p for p in profile.online.platforms().values() if (p.url or p.handle)
    ]
    checks: dict[str, list[bool]] = {
        "A_event_activity": [
            profile.events.events_last_3_months is not None,
            profile.events.events_last_6_months is not None,
            profile.last_event_date is not None,
        ],
        "B_online_reach": [
            profile.max_followers() > 0,
            len(online_active) > 0,
        ],
        "C_press_presence": [
            _present(profile.press.major_features),
            _present(profile.press.local_press_mentions),
            _present(profile.press.international_mentions),
            _present(profile.press.cultural_funding_mentions),
        ],
        "D_community_resonance": [
            _present(profile.community.reddit_threads),
            _present(profile.community.twitter_handles),
            profile.community.community_sentiment_hint != SentimentHint.unknown,
        ],
        "E_scene_networking": [
            _present(profile.networking.booked_djs),
            _present(profile.networking.collaborations),
            _present(profile.networking.cross_promotions),
        ],
        "F_continuity": [
            profile.active_since_year() is not None,
        ],
        "G_safety_inclusivity": [
            profile.policy_safety.safer_spaces_communicated is not None,
            profile.policy_safety.queer_friendly is not None,
            profile.policy_safety.flinta_focus is not None,
        ],
    }
    return {
        dim: round(100.0 * sum(1 for c in items if c) / len(items), 1)
        for dim, items in checks.items()
    }


def data_completeness(presence: dict[str, float], weight_map: dict[str, float]) -> float:
    """Weighted average presence across dimensions (weights sum to ~1.0)."""
    total_w = sum(weight_map.values()) or 1.0
    return round(sum(presence[d] * weight_map[d] for d in presence) / total_w, 1)


def freshness(profile: EntityProfile, cfg: ConfidenceConfig, today: date) -> float:
    """Freshness 0-100 from ``last_verification`` (decays with age)."""
    if profile.last_verification is None:
        return cfg.unknown_verification_confidence
    age_days = (today - profile.last_verification.date()).days
    if age_days <= cfg.freshness_full_days:
        return 100.0
    decay_window = max(1, cfg.freshness_full_days * 3)
    frac = (age_days - cfg.freshness_full_days) / decay_window
    value = 100.0 - frac * (100.0 - cfg.freshness_floor)
    return round(max(cfg.freshness_floor, min(100.0, value)), 1)


def overall_confidence(completeness: float, fresh: float, cfg: ConfidenceConfig) -> float:
    cw, fw = cfg.completeness_weight, cfg.freshness_weight
    denom = (cw + fw) or 1.0
    return round((completeness * cw + fresh * fw) / denom, 1)
