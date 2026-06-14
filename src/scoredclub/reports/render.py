"""Report rendering: Markdown (Jinja2), entities JSON and next_run.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from scoredclub.config import Settings
from scoredclub.pipeline.diff import RunDiff
from scoredclub.schemas import EntityProfile, EntityType, ScoreBreakdown
from scoredclub.scoring.engine import TIER_EMERGING, TIER_INACTIVE, TIER_MID, TIER_TOP

TYPE_LABELS = {
    "club": "Club",
    "collective": "Kollektiv",
    "label": "Label",
    "series": "Partyreihe",
    "artist": "DJ/Artist",
}

SENTIMENT_LABELS = {
    "positive": "überwiegend positiv",
    "mixed": "gemischt",
    "negative": "überwiegend kritisch",
    "unknown": "unbekannt",
}


@dataclass
class ScoredEntity:
    profile: EntityProfile
    breakdown: ScoreBreakdown
    delta: float | None = None
    is_new: bool = False  # not present in the previous run (run-over-run)
    discovered: bool = False  # not part of the seed list (off-seed find)
    trend: dict | None = None  # direction/score_delta/rank/rank_delta/momentum/sparkline

    @property
    def tier(self) -> str:
        return self.breakdown.tier

    @property
    def safety_summary(self) -> str:
        ps = self.profile.policy_safety
        parts = []
        if ps.safer_spaces_communicated:
            parts.append("klar kommuniziertes Safer-Space-Konzept")
        if ps.queer_friendly:
            parts.append("queer-freundlich")
        if ps.flinta_focus:
            parts.append("FLINTA*-Fokus")
        if not parts:
            if ps.safer_spaces_communicated is False:
                return "keine Awareness-Kommunikation erkennbar"
            return "keine Angaben verfügbar"
        return ", ".join(parts)


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("scoredclub.reports", "templates"),
        autoescape=select_autoescape(default=False),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _recommendations(scored: list[ScoredEntity]) -> list[str]:
    recs: list[str] = []
    emerging = sorted(
        (e for e in scored if e.tier == TIER_EMERGING),
        key=lambda e: e.breakdown.total,
        reverse=True,
    )[:3]
    for e in emerging:
        recs.append(
            f"{e.profile.name} ({TYPE_LABELS[e.profile.type.value]}, Score "
            f"{e.breakdown.total:.0f}) — aufstrebend, tiefere manuelle Recherche lohnt sich."
        )
    falling = [e for e in scored if e.delta is not None and e.delta <= -10]
    for e in falling:
        recs.append(
            f"{e.profile.name}: Score deutlich gefallen (Δ {e.delta:+.1f}) — Ursachen prüfen."
        )
    top_safety = [
        e
        for e in scored
        if e.tier == TIER_TOP and e.profile.policy_safety.safer_spaces_communicated
    ][:2]
    for e in top_safety:
        recs.append(
            f"{e.profile.name}: starkes Profil inkl. Awareness-Konzept — interessant für "
            "Kooperationen oder Bookings."
        )
    if not recs:
        recs.append("Keine besonderen Auffälligkeiten — Routine-Monitoring fortsetzen.")
    return recs


def _movers(scored: list[ScoredEntity], trend_report) -> dict:
    """Build {risers, fallers} as (name, delta) lists for the report."""
    if trend_report is None:
        return {"risers": [], "fallers": []}
    names = {e.profile.entity_id: e.profile.name for e in scored}

    def rows(items):
        return [
            {"name": names.get(t.entity_id, t.entity_id), "delta": t.score_delta}
            for t in items
        ]

    return {"risers": rows(trend_report.risers), "fallers": rows(trend_report.fallers)}


def render_markdown(
    scored: list[ScoredEntity],
    alerts: list,
    run_date: date,
    settings: Settings,
    trend_report=None,
) -> str:
    template = _env().get_template("report.md.j2")
    next_run = run_date + timedelta(days=settings.run.next_run_interval_days)
    ordered = sorted(scored, key=lambda e: e.breakdown.total, reverse=True)
    clubs = [e for e in ordered if e.profile.type == EntityType.club]
    collectives = [e for e in ordered if e.profile.type != EntityType.club]
    thresholds = settings.scoring.tier_thresholds
    tiers = [
        (TIER_TOP, f"TOP-TIER (Score ≥ {thresholds.top:.0f})"),
        (TIER_MID, f"MID-TIER (Score {thresholds.mid:.0f}–{thresholds.top - 1:.0f})"),
        (TIER_EMERGING, f"EMERGING (Score {thresholds.emerging:.0f}–{thresholds.mid - 1:.0f})"),
        (TIER_INACTIVE, f"INAKTIV / GESCHLOSSEN (Score < {thresholds.emerging:.0f} oder keine Events)"),
    ]
    return template.render(
        generated_at=run_date.isoformat(),
        next_run=next_run.isoformat(),
        entities=ordered,
        new_entities=[e for e in ordered if e.is_new],
        discovered_entities=[e for e in ordered if e.discovered],
        alerts=alerts,
        tiers=tiers,
        type_labels=TYPE_LABELS,
        sentiment_labels=SENTIMENT_LABELS,
        top_clubs=clubs[:5],
        top_collectives=collectives[:5],
        recommendations=_recommendations(scored),
        movers=_movers(scored, trend_report),
    )


def render_entities_json(
    scored: list[ScoredEntity], run_date: date, settings: Settings
) -> dict:
    next_run = run_date + timedelta(days=settings.run.next_run_interval_days)

    def _profile_dict(profile) -> dict:
        data = json.loads(profile.model_dump_json())
        # Keep the output clean: omit optional structures when they are empty.
        for optional in ("provenance", "lifecycle_events", "displacement_signals",
                         "demand", "follower_history"):
            if not data.get(optional):
                data.pop(optional, None)
        return data

    return {
        "generated_at": run_date.isoformat(),
        "next_run": next_run.isoformat(),
        "entities": [
            {
                **_profile_dict(e.profile),
                "score": json.loads(e.breakdown.model_dump_json()),
                "trend": e.trend,
            }
            for e in sorted(scored, key=lambda x: x.breakdown.total, reverse=True)
        ],
    }


def render_next_run_json(
    diff: RunDiff,
    alerts: list,
    run_date: date,
    entities_tracked: int,
    settings: Settings,
) -> dict:
    next_run = run_date + timedelta(days=settings.run.next_run_interval_days)
    return {
        "last_run": run_date.isoformat(),
        "next_run": next_run.isoformat(),
        "entities_tracked": entities_tracked,
        "new_entities_found": len(diff.new_entities),
        "score_changes": [
            {
                "entity_id": d.entity_id,
                "name": d.name,
                "old_score": d.old_score,
                "new_score": d.new_score,
            }
            for d in diff.score_changes(settings.alerts.score_change_threshold)
        ],
        "alerts": [
            {
                "entity_id": a.entity_id,
                "name": next(
                    (d.name for d in diff.deltas if d.entity_id == a.entity_id),
                    a.entity_id,
                ),
                "reason": a.alert_type,
                "details": a.message,
            }
            for a in alerts
        ],
    }


def write_reports(
    scored: list[ScoredEntity],
    diff: RunDiff,
    alerts: list,
    run_date: date,
    settings: Settings,
    trend_report=None,
) -> tuple[Path, Path, Path]:
    out_dir = Path(settings.run.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = run_date.isoformat()

    md_path = out_dir / f"berlin_techno_check_{date_str}.md"
    md_path.write_text(
        render_markdown(scored, alerts, run_date, settings, trend_report),
        encoding="utf-8",
    )

    json_path = out_dir / f"berlin_techno_entities_{date_str}.json"
    json_path.write_text(
        json.dumps(render_entities_json(scored, run_date, settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    next_run_path = out_dir / "next_run.json"
    next_run_path.write_text(
        json.dumps(
            render_next_run_json(diff, alerts, run_date, len(scored), settings),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return md_path, json_path, next_run_path
