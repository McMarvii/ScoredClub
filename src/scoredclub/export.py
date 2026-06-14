"""Tabular CSV/BI export of the tracked entities.

A flat, spreadsheet/BI-friendly view: one row per entity with the summary
fields plus the weighted points of every scoring dimension from the latest
snapshot. Pure string output (uses the stdlib ``csv`` writer), so it is easy to
test and serve from both the CLI and the API.
"""

from __future__ import annotations

import csv
import io

SUMMARY_COLUMNS = [
    "entity_id", "name", "type", "status", "district", "tier",
    "current_score", "confidence", "last_event_date",
]


def build_entity_rows(session) -> list[dict]:
    """One dict per entity: summary fields + per-dimension weighted points.

    Lazy ``repo`` import keeps this module DB-free for unit tests of
    :func:`rows_to_csv`.
    """
    from scoredclub.db import repo

    rows: list[dict] = []
    for entity in repo.all_entities(session):
        history = repo.score_history(session, entity.entity_id)
        breakdown = history[-1].breakdown if history else {}
        points = breakdown.get("points", {}) if isinstance(breakdown, dict) else {}
        row = {
            "entity_id": entity.entity_id,
            "name": entity.name,
            "type": entity.type,
            "status": entity.status,
            "district": entity.district or "",
            "tier": entity.tier or "",
            "current_score": entity.current_score if entity.current_score is not None else "",
            "confidence": breakdown.get("confidence", "") if isinstance(breakdown, dict) else "",
            "last_event_date": entity.last_event_date.isoformat() if entity.last_event_date else "",
        }
        row.update(points)
        rows.append(row)
    return rows


def rows_to_csv(rows: list[dict]) -> str:
    """Render entity rows to CSV. Dimension-point columns are appended, sorted."""
    point_cols = sorted(
        {k for row in rows for k in row.keys()} - set(SUMMARY_COLUMNS)
    )
    columns = SUMMARY_COLUMNS + point_cols
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in sorted(rows, key=lambda r: (-(r.get("current_score") or 0), r["entity_id"])):
        writer.writerow({col: row.get(col, "") for col in columns})
    return buffer.getvalue()


def export_csv(session) -> str:
    return rows_to_csv(build_entity_rows(session))
