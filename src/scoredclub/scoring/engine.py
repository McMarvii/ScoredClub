"""Combine rubric subscores into the final 0-100 score and tier."""

from __future__ import annotations

from datetime import date

from scoredclub.config import ScoringConfig
from scoredclub.schemas import EntityProfile, EntityStatus, ScoreBreakdown
from scoredclub.scoring import rubric

TIER_TOP = "TOP-TIER"
TIER_MID = "MID-TIER"
TIER_EMERGING = "EMERGING"
TIER_INACTIVE = "INAKTIV/GESCHLOSSEN"


def score_entity(
    profile: EntityProfile, config: ScoringConfig, today: date | None = None
) -> ScoreBreakdown:
    today = today or date.today()
    weights = config.weights

    subscores = {
        "A_event_activity": rubric.event_activity(profile, today),
        "B_online_reach": rubric.online_reach(profile),
        "C_press_presence": rubric.press(profile),
        "D_community_resonance": rubric.community(profile),
        "E_scene_networking": rubric.networking(profile),
        "F_continuity": rubric.continuity(profile, today),
        "G_safety_inclusivity": rubric.safety(profile),
    }
    weight_map = {
        "A_event_activity": weights.event_activity,
        "B_online_reach": weights.online_reach,
        "C_press_presence": weights.press,
        "D_community_resonance": weights.community,
        "E_scene_networking": weights.networking,
        "F_continuity": weights.continuity,
        "G_safety_inclusivity": weights.safety,
    }
    points = {dim: round(weight_map[dim] * sub, 2) for dim, sub in subscores.items()}
    base = sum(points.values())

    bonus_list = rubric.bonus_items(profile)
    malus_list = rubric.malus_items(profile)
    bonus = min(len(bonus_list) * config.bonus_per_item, config.bonus_cap)
    malus = min(len(malus_list) * config.malus_per_incident, config.malus_cap)

    total = max(0.0, min(100.0, base + bonus - malus))
    tier = classify_tier(profile, total, config, today)

    return ScoreBreakdown(
        subscores=subscores,
        points=points,
        bonus_items=bonus_list,
        malus_items=malus_list,
        bonus=bonus,
        malus=malus,
        base=round(base, 2),
        total=round(total, 2),
        tier=tier,
    )


def classify_tier(
    profile: EntityProfile, total: float, config: ScoringConfig, today: date | None = None
) -> str:
    today = today or date.today()
    thresholds = config.tier_thresholds

    if profile.status in (EntityStatus.inactive, EntityStatus.closed):
        return TIER_INACTIVE
    if (
        profile.last_event_date is not None
        and (today - profile.last_event_date).days > config.inactive_after_days
    ):
        return TIER_INACTIVE
    if total >= thresholds.top:
        return TIER_TOP
    if total >= thresholds.mid:
        return TIER_MID
    if total >= thresholds.emerging:
        return TIER_EMERGING
    return TIER_INACTIVE
