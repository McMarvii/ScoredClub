"""The heart of ScoredClub ♥ — a single living view of the whole system.

Two complementary tools that tie every module together:

* :func:`build_pulse` — the *pulse*: one snapshot that pulls the leaderboard,
  movers, breakouts, at-risk venues, strongest collaborations, data-health and
  upcoming funding deadlines into a single picture. The terminal heartbeat.
* :func:`build_health` — the *doctor*: a runnability check (config, database,
  schema, seeds, configured integrations, writable output) so an operator can
  see at a glance whether the system is wired up and ready.

Both are failure-tolerant: a problem in one section degrades to a note rather
than breaking the whole view, so the pulse always beats.
"""

from __future__ import annotations

import os
from collections import Counter

HEART = "♥"  # ♥


def _safe(section, default):
    """Run a pulse section, swallowing any error into a ``{"error": ...}``."""
    try:
        return section()
    except Exception as exc:  # noqa: BLE001 — the pulse must always beat
        return {**default, "error": f"{type(exc).__name__}: {exc}"}


def build_pulse(session, settings, *, top: int = 5) -> dict:
    """Assemble the system pulse from every module (defensive, read-only)."""
    from scoredclub.db import repo

    entities = repo.all_entities(session)
    profiles = {e.entity_id: repo.profile_from_row(e) for e in entities}
    names = {e.entity_id: e.name for e in entities}
    run = repo.latest_run(session)

    def overview() -> dict:
        return {
            "entities": len(entities),
            "by_type": dict(Counter(e.type for e in entities)),
            "by_tier": dict(Counter(e.tier or "—" for e in entities)),
            "last_run": run.id if run else None,
            "last_run_finished": run.finished_at.isoformat() if run and run.finished_at else None,
        }

    def leaderboard() -> list[dict]:
        scored = sorted(
            (e for e in entities if e.current_score is not None),
            key=lambda e: -e.current_score,
        )
        return [
            {"entity_id": e.entity_id, "name": e.name, "score": round(e.current_score, 1),
             "tier": e.tier}
            for e in scored[:top]
        ]

    def movers() -> dict:
        if run is None:
            return {"risers": [], "fallers": []}
        trends = [t for t in repo.trends_for_run(session, run.id).values()
                  if t.score_delta is not None]
        risers = sorted((t for t in trends if t.score_delta > 0),
                        key=lambda t: -t.score_delta)[:top]
        fallers = sorted((t for t in trends if t.score_delta < 0),
                         key=lambda t: t.score_delta)[:top]
        fmt = lambda t: {"name": names.get(t.entity_id, t.entity_id),
                         "score_delta": round(t.score_delta, 1)}
        return {"risers": [fmt(t) for t in risers], "fallers": [fmt(t) for t in fallers]}

    def breakouts() -> list[dict]:
        from scoredclub.analytics import BUCKET_INSUFFICIENT, BUCKET_NONE, compute_intelligence

        intel, _ = compute_intelligence(session, settings)
        out = [
            {"name": names.get(eid, eid), "bucket": i.breakout.bucket,
             "slope": i.breakout.slope}
            for eid, i in intel.items()
            if i.breakout.bucket not in (BUCKET_NONE, BUCKET_INSUFFICIENT)
        ]
        return sorted(out, key=lambda r: -r["slope"])[:top]

    def at_risk() -> list[dict]:
        from scoredclub.clubsterben import build_register

        reg = build_register(list(profiles.values()))
        return reg.at_risk[:top]

    def collaborations() -> list[dict]:
        from scoredclub.graph import build_booking_graph, collaboration_pairs

        graph = build_booking_graph(list(profiles.values()))
        return [
            {"a": p["a_label"], "b": p["b_label"], "weight": p["weight"]}
            for p in collaboration_pairs(graph, top=top)
        ]

    def data_health() -> dict:
        from scoredclub.authenticity import (
            VERDICT_AUTHENTIC, VERDICT_INCONCLUSIVE, assess,
        )

        confidences, low = [], 0
        if run is not None:
            for snap in repo.snapshots_for_run(session, run.id).values():
                conf = (snap.breakdown or {}).get("confidence")
                if isinstance(conf, (int, float)):
                    confidences.append(conf)
                if (snap.breakdown or {}).get("low_confidence"):
                    low += 1
        flagged = sum(
            1 for p in profiles.values()
            if assess(p).verdict not in (VERDICT_AUTHENTIC, VERDICT_INCONCLUSIVE)
        )
        return {
            "avg_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
            "low_confidence_entities": low,
            "follower_flagged": flagged,
        }

    def funding() -> list[dict]:
        from scoredclub.funding import load_funding, upcoming_deadlines

        feed = load_funding(settings.sources.funding_feed_path)
        return [
            {"name": p.name, "deadline": p.deadline.isoformat() if p.deadline else None}
            for p in upcoming_deadlines(feed)[:top]
        ]

    return {
        "heart": HEART,
        "overview": _safe(overview, {}),
        "leaderboard": _safe(leaderboard, []) if entities else [],
        "movers": _safe(movers, {"risers": [], "fallers": []}),
        "breakouts": _safe(breakouts, []),
        "at_risk": _safe(at_risk, []),
        "collaborations": _safe(collaborations, []),
        "data_health": _safe(data_health, {}),
        "funding_deadlines": _safe(funding, []),
    }


# --- doctor: runnability health-check ---------------------------------------

# Integration env vars and what enabling each unlocks.
INTEGRATIONS = {
    "SCOREDCLUB_API_KEY": "Schreib-/Trigger-Endpunkte der API",
    "REDDIT_CLIENT_ID": "Reddit-Collector (Dimension D)",
    "BANDSINTOWN_APP_ID": "Bandsintown-Events (Artists)",
    "SONGKICK_API_KEY": "Songkick-Events (Artists)",
    "FOLLOWER_AUDIT_API_KEY": "Externer Follower-Audit",
    "ANTHROPIC_API_KEY": "Agentischer LLM-Research-Collector",
    "SCOREDCLUB_SLACK_WEBHOOK_URL": "Slack-Alert-Digest",
    "SCOREDCLUB_SMTP_PASSWORD": "E-Mail-Alert-Digest",
}


def build_health(settings) -> dict:
    """A runnability check: config, database, schema, seeds, integrations, output."""
    from pathlib import Path

    from sqlalchemy import inspect

    from scoredclub.db import get_session
    from scoredclub.db.session import get_engine

    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, *, critical: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "critical": critical, "detail": detail})

    add("config", True, f"DATABASE_URL={settings.database_url}")

    entities = runs = None
    try:
        engine = get_engine(settings.database_url)
        tables = set(inspect(engine).get_table_names())
        have_schema = "entities" in tables
        add("database", True, f"erreichbar, {len(tables)} Tabellen")
        add("schema", have_schema,
            "Tabellen vorhanden" if have_schema else "fehlt — 'scoredclub migrate' / 'init-db'")
        if have_schema:
            from scoredclub.db.models import Entity, Run
            from sqlalchemy import func, select

            with get_session(settings.database_url) as session:
                entities = session.scalar(select(func.count()).select_from(Entity))
                runs = session.scalar(select(func.count()).select_from(Run))
            add("seeds", (entities or 0) > 0,
                f"{entities} Entitäten" if entities else "leer — 'scoredclub seed'",
                critical=False)
            add("runs", True, f"{runs} Läufe" + ("" if runs else " — 'scoredclub run'"),
                critical=False)
    except Exception as exc:  # noqa: BLE001
        add("database", False, f"nicht erreichbar ({type(exc).__name__}: {exc})")

    out_dir = Path(settings.run.output_dir)
    writable = True
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".scoredclub_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception:  # noqa: BLE001
        writable = False
    add("output_dir", writable,
        f"{out_dir} {'beschreibbar' if writable else 'NICHT beschreibbar'}", critical=False)

    integrations = {
        env: {"enabled": bool(os.environ.get(env)), "unlocks": desc}
        for env, desc in INTEGRATIONS.items()
    }

    critical_ok = all(c["ok"] for c in checks if c["critical"])
    return {
        "healthy": critical_ok,
        "checks": checks,
        "integrations": integrations,
        "entities": entities,
        "runs": runs,
    }
