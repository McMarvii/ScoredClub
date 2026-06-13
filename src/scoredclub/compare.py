"""A/B comparison of scoring configurations.

Scores the same set of entities under two scoring configurations and reports
the differences: per-entity score/rank deltas, tier changes, and headline
metrics (mean absolute delta, Spearman rank correlation, biggest movers).
This is the domain-meaningful form of "A/B testing" for a scoring system —
it answers "how would the rankings change if I tuned the weights?" without
touching the stored data.

Pure functions over ``EntityProfile`` + ``ScoringConfig``; no DB, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from scoredclub.config import ScoringConfig
from scoredclub.schemas import EntityProfile
from scoredclub.scoring.engine import score_entity


@dataclass
class EntityComparison:
    entity_id: str
    name: str
    score_a: float
    score_b: float
    score_delta: float
    tier_a: str
    tier_b: str
    tier_changed: bool
    rank_a: int
    rank_b: int
    rank_delta: int  # positive = moved up under B


@dataclass
class ComparisonReport:
    label_a: str
    label_b: str
    entities: list[EntityComparison] = field(default_factory=list)
    mean_abs_delta: float = 0.0
    max_delta: float = 0.0
    rank_correlation: float = 1.0
    tier_changes: list[EntityComparison] = field(default_factory=list)
    biggest_movers: list[EntityComparison] = field(default_factory=list)


def _ranks(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return {entity_id: i + 1 for i, (entity_id, _) in enumerate(ordered)}


def _spearman(ranks_a: dict[str, int], ranks_b: dict[str, int]) -> float:
    """Spearman rank correlation over the common entities (distinct ranks)."""
    common = sorted(set(ranks_a) & set(ranks_b))
    n = len(common)
    if n < 2:
        return 1.0
    d2 = sum((ranks_a[e] - ranks_b[e]) ** 2 for e in common)
    return round(1 - (6 * d2) / (n * (n * n - 1)), 4)


def compare_scoring(
    profiles: list[EntityProfile],
    scoring_a: ScoringConfig,
    scoring_b: ScoringConfig,
    today: date | None = None,
    label_a: str = "A",
    label_b: str = "B",
    movers_limit: int = 10,
) -> ComparisonReport:
    today = today or date.today()

    breakdown_a = {p.entity_id: score_entity(p, scoring_a, today) for p in profiles}
    breakdown_b = {p.entity_id: score_entity(p, scoring_b, today) for p in profiles}
    scores_a = {eid: b.total for eid, b in breakdown_a.items()}
    scores_b = {eid: b.total for eid, b in breakdown_b.items()}
    ranks_a = _ranks(scores_a)
    ranks_b = _ranks(scores_b)

    names = {p.entity_id: p.name for p in profiles}
    comparisons: list[EntityComparison] = []
    for eid in names:
        ta, tb = breakdown_a[eid].tier, breakdown_b[eid].tier
        comparisons.append(
            EntityComparison(
                entity_id=eid,
                name=names[eid],
                score_a=round(scores_a[eid], 2),
                score_b=round(scores_b[eid], 2),
                score_delta=round(scores_b[eid] - scores_a[eid], 2),
                tier_a=ta,
                tier_b=tb,
                tier_changed=ta != tb,
                rank_a=ranks_a[eid],
                rank_b=ranks_b[eid],
                rank_delta=ranks_a[eid] - ranks_b[eid],
            )
        )

    comparisons.sort(key=lambda c: c.score_b, reverse=True)
    deltas = [abs(c.score_delta) for c in comparisons]
    report = ComparisonReport(
        label_a=label_a,
        label_b=label_b,
        entities=comparisons,
        mean_abs_delta=round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        max_delta=round(max(deltas), 2) if deltas else 0.0,
        rank_correlation=_spearman(ranks_a, ranks_b),
        tier_changes=[c for c in comparisons if c.tier_changed],
        biggest_movers=sorted(comparisons, key=lambda c: abs(c.rank_delta), reverse=True)[
            :movers_limit
        ],
    )
    return report


def render_comparison_json(report: ComparisonReport) -> dict:
    return {
        "label_a": report.label_a,
        "label_b": report.label_b,
        "rank_correlation": report.rank_correlation,
        "mean_abs_delta": report.mean_abs_delta,
        "max_delta": report.max_delta,
        "tier_change_count": len(report.tier_changes),
        "entities": [
            {
                "entity_id": c.entity_id,
                "name": c.name,
                "score_a": c.score_a,
                "score_b": c.score_b,
                "score_delta": c.score_delta,
                "tier_a": c.tier_a,
                "tier_b": c.tier_b,
                "tier_changed": c.tier_changed,
                "rank_a": c.rank_a,
                "rank_b": c.rank_b,
                "rank_delta": c.rank_delta,
            }
            for c in report.entities
        ],
    }


def render_comparison_markdown(report: ComparisonReport) -> str:
    lines: list[str] = []
    a, b = report.label_a, report.label_b
    lines.append(f"# Scoring-Vergleich: {a} vs. {b}")
    lines.append("")
    lines.append(f"- **Rang-Korrelation (Spearman):** {report.rank_correlation} "
                 f"(1.0 = identische Reihenfolge)")
    lines.append(f"- **Mittlere absolute Score-Differenz:** {report.mean_abs_delta}")
    lines.append(f"- **Größte Score-Differenz:** {report.max_delta}")
    lines.append(f"- **Tier-Wechsel:** {len(report.tier_changes)}")
    lines.append("")
    lines.append(f"| Entität | Score {a} | Score {b} | Δ | Tier {a} → {b} | Rang Δ |")
    lines.append("|---------|----------:|----------:|---:|----------------|-------:|")
    for c in report.entities:
        tier = c.tier_a if not c.tier_changed else f"{c.tier_a} → {c.tier_b}"
        rank_delta = f"{c.rank_delta:+d}" if c.rank_delta else "0"
        lines.append(
            f"| {c.name} | {c.score_a:.1f} | {c.score_b:.1f} | {c.score_delta:+.1f} "
            f"| {tier} | {rank_delta} |"
        )
    lines.append("")
    if report.tier_changes:
        lines.append("## Tier-Wechsel")
        for c in report.tier_changes:
            lines.append(f"- **{c.name}**: {c.tier_a} → {c.tier_b} "
                         f"(Score {c.score_a:.1f} → {c.score_b:.1f})")
        lines.append("")
    return "\n".join(lines)
