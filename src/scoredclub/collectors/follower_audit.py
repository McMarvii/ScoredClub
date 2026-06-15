"""External follower-audit collector — verifies followers against a real dataset.

The internal :mod:`scoredclub.authenticity` heuristics only *compare* an entity's
own series. This collector additionally **pulls an external dataset** to verify
follower quality: it queries a follower-audit provider (Social-Blade-/HypeAuditor-
style: suspected-fake share, engagement rate, historical follower counts) and
attaches the result so the authenticity assessment uses verified data, not just
internal comparison.

Provider-agnostic: set ``FOLLOWER_AUDIT_API_KEY`` and point
``sources.follower_audit_url`` at an endpoint (or a thin adapter) that returns
the normalised JSON shape::

    {
      "fake_follower_pct": 42.0,        # 0..100 (optional)
      "engagement_rate": 0.4,           # %, optional
      "quality_score": 35,              # 0..100, optional
      "source": "provider-x",           # optional
      "checked_at": "2026-06-15",       # optional
      "history": [ {"date": "2026-01-01", "followers": 5000}, ... ]   # optional
    }

The query uses the entity's Instagram handle (the primary follower metric). The
collector is a no-op without the key or a handle, failure-tolerant (aborts after
repeated failures), and *enrichment-only* — it never creates entities. The
returned ``history`` is folded into ``follower_history`` so the trajectory checks
gain real external data points.
"""

from __future__ import annotations

import datetime as dt
import os
import time

import httpx

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import (
    EntityProfile,
    FollowerAudit,
    FollowerPoint,
    utcnow,
)


def _api_key() -> str | None:
    return os.environ.get("FOLLOWER_AUDIT_API_KEY")


def _instagram_handle(profile: EntityProfile) -> str | None:
    """Best-effort Instagram handle for the audit query.

    Prefers an explicit handle, else derives it from the profile URL. We strip a
    leading ``@`` and any query string / fragment, because a URL like
    ``instagram.com/berghain?hl=en`` must yield ``berghain`` — sending the raw
    ``berghain?hl=en`` would be a malformed handle the provider can't resolve.
    """
    ig = profile.online.instagram
    if ig.handle:
        return ig.handle.lstrip("@").strip() or None
    if ig.url and "instagram.com/" in ig.url:
        tail = ig.url.rstrip("/").split("instagram.com/")[-1]
        # Drop the path tail after the username plus any ?query / #fragment.
        handle = tail.split("/")[0].split("?")[0].split("#")[0].lstrip("@").strip()
        return handle or None
    return None


def _parse_audit(payload: dict) -> tuple[FollowerAudit, list[FollowerPoint]]:
    """Map the normalised provider response to a FollowerAudit + history points."""
    def _num(key):
        v = payload.get(key)
        # bool is a subclass of int — exclude it so a stray ``true`` does not
        # silently become ``1.0`` for a percentage/rate field.
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    checked = payload.get("checked_at")
    checked_date = None
    if isinstance(checked, str) and checked:
        try:
            checked_date = dt.date.fromisoformat(checked)
        except ValueError:
            checked_date = None

    audit = FollowerAudit(
        fake_follower_pct=_num("fake_follower_pct"),
        engagement_rate=_num("engagement_rate"),
        quality_score=_num("quality_score"),
        source=payload.get("source") if isinstance(payload.get("source"), str) else None,
        checked_at=checked_date,
    )

    history: list[FollowerPoint] = []
    for row in payload.get("history") or []:
        if not isinstance(row, dict) or not isinstance(row.get("followers"), int):
            continue
        raw_date = row.get("date")
        when = None
        if isinstance(raw_date, str) and raw_date:
            try:
                when = dt.date.fromisoformat(raw_date)
            except ValueError:
                when = None
        history.append(FollowerPoint(date=when, followers=row["followers"]))
    return audit, history


class FollowerAuditCollector:
    name = "follower_audit"
    request_delay = 0.5

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        api_key = _api_key()
        if not api_key or not entities:
            return result  # no key or nothing to enrich -> silent no-op

        # Only entities with a resolvable handle can be audited; the cap keeps a
        # single run's external API spend (and rate-limit exposure) bounded.
        candidates = [(e, _instagram_handle(e)) for e in entities]
        candidates = [(e, h) for e, h in candidates if h]
        candidates = candidates[: settings.sources.follower_audit_max_entities]
        if not candidates:
            return result

        base = settings.sources.follower_audit_url
        failures = 0
        for index, (entity, handle) in enumerate(candidates):
            try:
                payload = self._fetch(base, handle, api_key)
            except Exception as exc:  # noqa: BLE001 — collectors must never raise
                failures += 1
                if failures <= 2:
                    result.warnings.append(
                        f"{self.name}: fetch failed for {entity.name} ({type(exc).__name__})"
                    )
                if failures >= 3:
                    result.ok = False
                    result.warnings.append(
                        f"{self.name}: endpoint unreachable, aborting after {failures} failures"
                    )
                    break
                continue

            if not isinstance(payload, dict):
                continue
            audit, history = _parse_audit(payload)
            result.profiles.append(
                EntityProfile(
                    name=entity.name,
                    follower_audit=audit,
                    follower_history={"instagram": history} if history else {},
                    last_verification=utcnow(),
                )
            )
            if self.request_delay and index < len(candidates) - 1:
                time.sleep(self.request_delay)

        if failures and result.profiles:
            result.warnings.append(
                f"{self.name}: {failures} audits failed (partial results kept)"
            )
        return result

    def _fetch(self, base: str, handle: str, api_key: str) -> dict:
        response = httpx.get(
            base,
            params={"platform": "instagram", "handle": handle},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
