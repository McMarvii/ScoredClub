from __future__ import annotations

from scoredclub.compare import (
    compare_scoring,
    render_comparison_json,
    render_comparison_markdown,
)
from scoredclub.config import ScoringConfig, ScoringWeights
from tests.conftest import TODAY, make_minimal_profile, make_top_profile


def _reach_profile():
    p = make_minimal_profile(name="Reach Club", status="active", active_since="2024")
    p.events.events_last_3_months = 12
    p.last_event_date = TODAY
    p.online.instagram.followers = 100_000
    p.online.instagram.handle = "reach"
    return p


def _safety_profile():
    p = make_minimal_profile(name="Safe Space", status="active", active_since="2024")
    p.events.events_last_3_months = 12
    p.last_event_date = TODAY
    p.policy_safety.safer_spaces_communicated = True
    p.policy_safety.queer_friendly = True
    p.policy_safety.flinta_focus = True
    return p


REACH_CFG = ScoringConfig(weights=ScoringWeights(
    event_activity=0.2, online_reach=0.5, press=0.0, community=0.0,
    networking=0.0, continuity=0.2, safety=0.1,
))
SAFETY_CFG = ScoringConfig(weights=ScoringWeights(
    event_activity=0.2, online_reach=0.1, press=0.0, community=0.0,
    networking=0.0, continuity=0.2, safety=0.5,
))


def test_identical_configs_no_change():
    profiles = [make_top_profile(), make_minimal_profile(name="X", status="active", active_since="2024")]
    cfg = ScoringConfig()
    report = compare_scoring(profiles, cfg, cfg, today=TODAY)
    assert report.rank_correlation == 1.0
    assert all(c.score_delta == 0.0 for c in report.entities)
    assert report.tier_changes == []
    assert report.mean_abs_delta == 0.0


def test_reweighting_swaps_ranks():
    reach, safe = _reach_profile(), _safety_profile()
    report = compare_scoring([reach, safe], REACH_CFG, SAFETY_CFG, today=TODAY,
                             label_a="reach", label_b="safety")
    by_id = {c.entity_id: c for c in report.entities}
    r, s = by_id[reach.entity_id], by_id[safe.entity_id]
    # Under reach config the reach-heavy club ranks first; under safety config it drops.
    assert r.rank_a == 1 and r.rank_b == 2
    assert s.rank_a == 2 and s.rank_b == 1
    # Full 2-entity reversal -> Spearman -1.0
    assert report.rank_correlation == -1.0
    assert r.rank_delta == -1 and s.rank_delta == 1


def test_metrics_and_render():
    reach, safe = _reach_profile(), _safety_profile()
    report = compare_scoring([reach, safe], REACH_CFG, SAFETY_CFG, today=TODAY)
    assert report.max_delta >= report.mean_abs_delta >= 0
    assert len(report.biggest_movers) == 2

    js = render_comparison_json(report)
    assert js["rank_correlation"] == report.rank_correlation
    assert len(js["entities"]) == 2

    md = render_comparison_markdown(report)
    assert "Scoring-Vergleich" in md
    assert "Rang-Korrelation" in md
    assert "Reach Club" in md


def test_empty_profiles():
    report = compare_scoring([], ScoringConfig(), ScoringConfig(), today=TODAY)
    assert report.entities == []
    assert report.rank_correlation == 1.0
    assert report.mean_abs_delta == 0.0
