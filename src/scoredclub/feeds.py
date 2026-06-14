"""RSS 2.0 feed of recent activity (alerts / movers).

A standards-compliant feed so changes can be followed in any RSS reader — a
push channel beyond webhooks. Pure: build the XML from plain item dicts; the
API serves it and a loader assembles items from the stored alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape

_RSS_DATE = "%a, %d %b %Y %H:%M:%S +0000"


@dataclass
class FeedItem:
    title: str
    description: str
    guid: str
    pub_date: datetime | None = None
    link: str | None = None


def _rfc822(dt: datetime | None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(_RSS_DATE)


def render_rss(
    items: list[FeedItem],
    *,
    title: str = "ScoredClub — Berlin Techno Updates",
    link: str = "https://github.com/McMarvii/ScoredClub",
    description: str = "Score-Änderungen, Status-Wechsel und neue Entitäten.",
    now: datetime | None = None,
) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        f"<description>{escape(description)}</description>",
        f"<lastBuildDate>{_rfc822(now)}</lastBuildDate>",
    ]
    for item in items:
        parts.append("<item>")
        parts.append(f"<title>{escape(item.title)}</title>")
        parts.append(f"<description>{escape(item.description)}</description>")
        if item.link:
            parts.append(f"<link>{escape(item.link)}</link>")
        parts.append(f'<guid isPermaLink="false">{escape(item.guid)}</guid>')
        parts.append(f"<pubDate>{_rfc822(item.pub_date)}</pubDate>")
        parts.append("</item>")
    parts.append("</channel>")
    parts.append("</rss>")
    return "\n".join(parts)


def alerts_to_items(alerts) -> list[FeedItem]:
    """Build feed items from Alert ORM rows (newest first)."""
    items: list[FeedItem] = []
    for alert in alerts:
        detail = alert.message
        if alert.old_value is not None or alert.new_value is not None:
            detail += f" ({alert.old_value} → {alert.new_value})"
        items.append(
            FeedItem(
                title=f"[{alert.alert_type}] {alert.entity_id}",
                description=detail,
                guid=f"scoredclub-alert-{alert.id}",
                pub_date=getattr(alert, "created_at", None),
            )
        )
    return items


def build_feed(session, limit: int = 50) -> str:
    """Render the most recent alerts as an RSS feed (lazy DB import)."""
    from sqlalchemy import select

    from scoredclub.db.models import Alert

    rows = session.scalars(select(Alert).order_by(Alert.id.desc()).limit(limit)).all()
    return render_rss(alerts_to_items(rows))
