"""Follower authenticity heuristics — informational, never affects scoring.

A *separate* assessment of whether an entity's follower counts look organic,
surfaced next to the score but deliberately kept OUT of the scoring engine
(``scoring/`` never imports this module). It flags the classic inflated-reach
patterns from data we already hold — offline and deterministic:

* **Spikes** in the ``follower_history`` time-series — a sudden jump far out of
  line with the entity's usual growth is the classic purchased-followers signal.
* **Reach without footprint** — a high follower count with almost no real-world
  activity/resonance (events, press, community, bookings).
* **Large but dormant** accounts — many followers, virtually no posting.

This is a *heuristic*, not proof. A deep check (engagement rate, follower
account ages, audience geography) needs platform APIs and is a follow-up; the
thresholds below are intentionally conservative so a single signal reads as
"auffällig" (questionable) and only several together as "verdächtig".
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from scoredclub.schemas import EntityProfile, FollowerPoint

# --- thresholds (kept in sync with the JS port in frontend/app.js) -----------
HIGH_FOLLOWERS = 50_000      # "high reach" trigger for the footprint check
LOW_FOOTPRINT = 2            # footprint at/below this counts as "almost none"
DORMANT_FOLLOWERS = 20_000   # large account...
DORMANT_POSTS = 0.5          # ...with posts_per_month below this = dormant
SPIKE_MIN_ABS = 5_000        # a step must add at least this many followers
SPIKE_RATIO = 5.0            # ...and be this many times the typical step
SPIKE_PCT = 0.5             # ...or jump by this fraction of the prior value

PENALTY_SPIKE = 45
PENALTY_REACH = 35
PENALTY_DORMANT = 25
PENALTY_DROP = 35       # sharp follower loss = likely bot purge / churned bought followers

VERDICT_AUTHENTIC = "authentic"
VERDICT_QUESTIONABLE = "questionable"
VERDICT_SUSPICIOUS = "suspicious"
VERDICT_INCONCLUSIVE = "inconclusive"

THRESHOLD_AUTHENTIC = 80
THRESHOLD_QUESTIONABLE = 50


@dataclass
class FollowerAuthenticity:
    verdict: str
    score: float | None  # 0..100 (higher = more organic); None when inconclusive
    flags: list[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)


def footprint(profile: EntityProfile) -> int:
    """A rough real-world footprint proxy (events, press, community, bookings)."""
    p = 0
    p += min(profile.events.events_last_6_months or 0, 12)
    p += 2 * len(profile.press.major_features)
    p += len(profile.press.international_mentions)
    p += len(profile.press.local_press_mentions)
    p += min(len(profile.community.reddit_threads), 5)
    p += len(profile.networking.booked_djs)
    p += len(profile.networking.collaborations)
    if profile.networking.international_booking:
        p += 5
    if profile.cultural_recognition.clubcommission_member:
        p += 3
    return p


def _ordered(points: list) -> tuple[list[int], list]:
    ordered = sorted(points, key=lambda pt: (pt.date is None, pt.date))
    return [pt.followers for pt in ordered], [pt.date for pt in ordered]


def _anomalous_steps(values: list[int], dates: list, *, direction: int) -> list[dict]:
    """Steps that are abnormal relative to the series' own typical movement.

    ``direction`` is +1 for upward jumps (spikes) or -1 for downward jumps
    (drops). Needs ≥3 points so the *other* steps form a baseline.
    """
    out: list[dict] = []
    if len(values) < 3:
        return out
    steps = [values[i] - values[i - 1] for i in range(1, len(values))]
    for i, step in enumerate(steps):
        signed = step * direction
        if signed <= 0:
            continue
        others = [abs(s) for j, s in enumerate(steps) if j != i]
        baseline = statistics.median(others) if others else 0.0
        prev = values[i]
        big_abs = signed >= SPIKE_MIN_ABS
        big_rel = signed >= SPIKE_RATIO * max(baseline, 1.0)
        big_pct = prev > 0 and signed >= SPIKE_PCT * prev
        if big_abs and (big_rel or big_pct):
            out.append({"delta": step, "date": dates[i + 1].isoformat() if dates[i + 1] else None})
    return out


def detect_spikes(follower_history: dict[str, list]) -> list[dict]:
    """Abnormal upward follower jumps per platform (purchased-followers signal)."""
    spikes: list[dict] = []
    for platform, points in follower_history.items():
        values, dates = _ordered(points)
        for step in _anomalous_steps(values, dates, direction=1):
            spikes.append({"platform": platform, **step})
    return spikes


def detect_drops(follower_history: dict[str, list]) -> list[dict]:
    """Abnormal downward follower jumps per platform (bot-purge / churn signal)."""
    drops: list[dict] = []
    for platform, points in follower_history.items():
        values, dates = _ordered(points)
        for step in _anomalous_steps(values, dates, direction=-1):
            drops.append({"platform": platform, **step})
    return drops


def evaluate_history(follower_history: dict[str, list]) -> dict:
    """Retrieve and summarise the historical follower trajectory per platform.

    Reuses the growth analysis from :mod:`scoredclub.followers` and adds the
    volatility of the step-to-step changes — the basis for the spike/drop checks.
    """
    from scoredclub.followers import compute_growth

    summary: dict[str, dict] = {}
    for platform, points in follower_history.items():
        values, dates = _ordered(points)
        if len(values) < 2:
            continue
        steps = [values[i] - values[i - 1] for i in range(1, len(values))]
        growth = compute_growth(points)
        summary[platform] = {
            "points": len(values),
            "start": values[0],
            "end": values[-1],
            "growth_pct": growth.pct if growth else None,
            "slope": growth.slope if growth else 0.0,
            "volatility": round(statistics.pstdev(steps), 1) if len(steps) >= 2 else 0.0,
            "spikes": _anomalous_steps(values, dates, direction=1),
            "drops": _anomalous_steps(values, dates, direction=-1),
        }
    return summary


def assess(profile: EntityProfile) -> FollowerAuthenticity:
    """Assess follower authenticity for one entity. Pure; no scoring impact."""
    max_followers = profile.max_followers()
    has_data = max_followers > 0 or any(profile.follower_history.values())
    if not has_data:
        return FollowerAuthenticity(
            verdict=VERDICT_INCONCLUSIVE, score=None, flags=[],
            signals={"checked": False, "reason": "keine Follower-Daten"},
        )

    score = 100.0
    flags: list[str] = []

    spikes = detect_spikes(profile.follower_history)
    for spike in spikes:
        when = f" am {spike['date']}" if spike["date"] else ""
        flags.append(
            f"Auffälliger Follower-Sprung ({spike['platform']}): "
            f"+{spike['delta']:,}{when}".replace(",", ".")
        )
        score -= PENALTY_SPIKE

    drops = detect_drops(profile.follower_history)
    for drop in drops:
        when = f" am {drop['date']}" if drop["date"] else ""
        flags.append(
            f"Starker Follower-Verlust ({drop['platform']}): "
            f"{drop['delta']:,}{when} (mögliche Bot-Bereinigung)".replace(",", ".")
        )
        score -= PENALTY_DROP

    fp = footprint(profile)
    reach_flag = max_followers >= HIGH_FOLLOWERS and fp <= LOW_FOOTPRINT
    if reach_flag:
        flags.append(
            f"Hohe Reichweite ({max_followers:,} Follower) bei geringer realer "
            f"Aktivität/Resonanz".replace(",", ".")
        )
        score -= PENALTY_REACH

    dormant = []
    for name, presence in profile.online.platforms().items():
        followers = presence.followers or 0
        ppm = presence.posts_per_month
        if followers >= DORMANT_FOLLOWERS and ppm is not None and ppm < DORMANT_POSTS:
            flags.append(
                f"{name}: große Reichweite, aber kaum Aktivität "
                f"({followers:,} Follower, {ppm}/Monat)".replace(",", ".")
            )
            dormant.append(name)
            score -= PENALTY_DORMANT

    score = max(0.0, min(100.0, score))
    if score >= THRESHOLD_AUTHENTIC:
        verdict = VERDICT_AUTHENTIC
    elif score >= THRESHOLD_QUESTIONABLE:
        verdict = VERDICT_QUESTIONABLE
    else:
        verdict = VERDICT_SUSPICIOUS

    return FollowerAuthenticity(
        verdict=verdict,
        score=round(score, 1),
        flags=flags,
        signals={
            "checked": True,
            "max_followers": max_followers,
            "footprint": fp,
            "spikes": spikes,
            "drops": drops,
            "dormant_platforms": dormant,
            # Retrieved + evaluated historical trajectory per platform.
            "history": evaluate_history(profile.follower_history),
        },
    )


def capture_follower_history(profile: EntityProfile, today=None) -> bool:
    """Append today's follower counts to ``follower_history`` per platform.

    This is how the system *builds up* the historical record the authenticity
    check evaluates: called once per run (opt-in via
    ``authenticity.capture_history``), it snapshots each platform's current
    follower count plus the RA following. A same-day or unchanged value is not
    duplicated. Returns True if anything was appended. Never affects scoring.
    """
    import datetime as _dt

    today = today or _dt.date.today()
    counts: dict[str, int] = {}
    for name, presence in profile.online.platforms().items():
        if isinstance(presence.followers, int) and presence.followers > 0:
            counts[name] = presence.followers
    if isinstance(profile.events.ra_followers, int) and profile.events.ra_followers > 0:
        counts["resident_advisor"] = profile.events.ra_followers

    changed = False
    for platform, value in counts.items():
        series = profile.follower_history.setdefault(platform, [])
        last = series[-1] if series else None
        # Skip if the most recent point already records this value or this day.
        if last is not None and (last.followers == value or last.date == today):
            continue
        series.append(FollowerPoint(date=today, followers=value))
        changed = True
    return changed


def to_dict(result: FollowerAuthenticity) -> dict:
    return {
        "verdict": result.verdict,
        "score": result.score,
        "flags": result.flags,
        "signals": result.signals,
    }
