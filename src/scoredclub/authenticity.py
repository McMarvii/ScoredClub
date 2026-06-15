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

from scoredclub.analytics import linear_slope
from scoredclub.schemas import EntityProfile, FollowerPoint

# Verdict calibration: each signal subtracts a penalty from a starting 100, and
# the thresholds below are chosen so that ONE signal lands in "questionable"
# (auffällig) while TWO push into "suspicious" (verdächtig). The smallest single
# penalty (25) leaves 75 < THRESHOLD_AUTHENTIC, so any signal at all forfeits the
# "authentic" verdict — a deliberately cautious design.
#
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

# External audit-dataset thresholds (verified follower quality, not internal comparison).
FAKE_PCT_HIGH = 30.0      # suspected-fake share that warrants a flag
FAKE_PCT_SEVERE = 50.0    # share at which the account is almost certainly inflated
ENGAGEMENT_LOW = 0.5      # avg engagement rate (%) below which large reach is implausible
PENALTY_FAKE = 30
PENALTY_FAKE_SEVERE = 55
PENALTY_ENGAGEMENT = 20

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

    This is the single place that walks each series: it returns growth (delta %,
    least-squares slope), volatility of the step-to-step changes, and the spike/
    drop anomalies — so :func:`assess` can reuse this one pass instead of
    re-scanning the history three times. Platforms with fewer than two points are
    skipped (no trajectory to evaluate; they also carry no anomalies anyway).
    """
    summary: dict[str, dict] = {}
    for platform, points in follower_history.items():
        values, dates = _ordered(points)
        if len(values) < 2:
            continue
        steps = [values[i] - values[i - 1] for i in range(1, len(values))]
        start, end = values[0], values[-1]
        delta = end - start
        summary[platform] = {
            "points": len(values),
            "start": start,
            "end": end,
            # pct is undefined from a zero base; slope is per-step (least squares).
            "growth_pct": round(100.0 * delta / start, 1) if start else None,
            "slope": round(linear_slope([float(v) for v in values]), 2),
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

    # One walk over the history; spikes/drops are flattened from that result
    # (each carries its platform) instead of re-scanning via detect_spikes/drops.
    history = evaluate_history(profile.follower_history)
    spikes = [{"platform": p, **s} for p, summary in history.items() for s in summary["spikes"]]
    drops = [{"platform": p, **s} for p, summary in history.items() for s in summary["drops"]]

    for spike in spikes:
        when = f" am {spike['date']}" if spike["date"] else ""
        flags.append(
            f"Auffälliger Follower-Sprung ({spike['platform']}): "
            f"+{spike['delta']:,}{when}".replace(",", ".")
        )
        score -= PENALTY_SPIKE

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

    # External audit dataset (pulled by the follower-audit collector) — verified
    # follower quality, not an internal comparison.
    audit = profile.follower_audit
    if audit is not None:
        fake = audit.fake_follower_pct
        if fake is not None and fake >= FAKE_PCT_SEVERE:
            flags.append(
                f"Externe Prüfung ({audit.source or 'Audit'}): ~{fake:.0f}% unechte Follower"
            )
            score -= PENALTY_FAKE_SEVERE
        elif fake is not None and fake >= FAKE_PCT_HIGH:
            flags.append(
                f"Externe Prüfung ({audit.source or 'Audit'}): ~{fake:.0f}% unechte Follower"
            )
            score -= PENALTY_FAKE
        eng = audit.engagement_rate
        if eng is not None and eng < ENGAGEMENT_LOW and max_followers >= DORMANT_FOLLOWERS:
            flags.append(
                f"Externe Prüfung ({audit.source or 'Audit'}): sehr niedrige "
                f"Engagement-Rate ({eng:.2f}%)"
            )
            score -= PENALTY_ENGAGEMENT

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
            # Retrieved + evaluated historical trajectory per platform (reused
            # from the single walk above — not recomputed).
            "history": history,
            # External verification dataset (None unless an audit was pulled).
            "audit": (
                {
                    "fake_follower_pct": audit.fake_follower_pct,
                    "engagement_rate": audit.engagement_rate,
                    "quality_score": audit.quality_score,
                    "source": audit.source,
                    "checked_at": audit.checked_at.isoformat() if audit.checked_at else None,
                }
                if audit is not None else None
            ),
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
