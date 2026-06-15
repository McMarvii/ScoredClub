"""Mixcloud enrichment collector — DJ sets/mixes + follower reach.

Mixcloud is where techno DJs, residents and collectives publish their recorded
sets/mixes, so it is the natural source for the dossier's **top sets**. For each
entity that carries a Mixcloud handle (in ``online.mixcloud``) this fetches the
user's cloudcasts and attaches:

* the recorded sets as ``top_sets`` (title, plays, date, length, url) — the
  Steckbrief/[dossier](../../docs/dossier.md) building block,
* the Mixcloud **follower count** as ``online.mixcloud.followers`` (online
  reach, dimension B).

Mixcloud's public API needs no key. To keep the canonical run reproducible the
collector is therefore **off by default** (``sources.mixcloud_enabled``); it is
also a silent no-op for entities without a Mixcloud handle. Enrichment only — it
never invents entities. Failure-tolerant like every collector: failures degrade
to warnings and it aborts after repeated failures.
"""

from __future__ import annotations

import datetime as dt
import time
from urllib.parse import quote

import httpx

from scoredclub.collectors.base import CollectorResult, social_username
from scoredclub.config import Settings
from scoredclub.schemas import (
    DJSet,
    EntityProfile,
    OnlinePresence,
    SocialPresence,
    utcnow,
)


def _parse_date(raw: object) -> dt.date | None:
    """Parse a Mixcloud ``created_time`` ISO timestamp into a date."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _minutes(seconds: object) -> int | None:
    return seconds // 60 if isinstance(seconds, int) and seconds > 0 else None


def _parse_cloudcasts(cloudcasts: list[dict]) -> list[DJSet]:
    """Reduce a Mixcloud ``cloudcasts`` payload to dossier ``DJSet`` items."""
    sets: list[DJSet] = []
    for cc in cloudcasts:
        name = (cc.get("name") or "").strip()
        if not name:
            continue
        plays = cc.get("play_count")
        sets.append(
            DJSet(
                title=name,
                date=_parse_date(cc.get("created_time")),
                url=cc.get("url"),
                plays=plays if isinstance(plays, int) else None,
                duration_min=_minutes(cc.get("audio_length")),
                source="mixcloud",
            )
        )
    return sets


class MixcloudCollector:
    name = "mixcloud"
    request_delay = 0.5  # seconds between users; be polite to the API

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        if not settings.sources.mixcloud_enabled or not entities:
            return result  # disabled or nothing to enrich -> silent no-op

        targets = [
            (e, username)
            for e in entities
            if (username := social_username(e.online.mixcloud))
        ]
        if not targets:
            return result  # no Mixcloud handles -> no-op
        targets = targets[: settings.sources.mixcloud_max_entities]

        base = settings.sources.mixcloud_url.rstrip("/")
        failures = 0
        for index, (entity, username) in enumerate(targets):
            try:
                cloudcasts = self._fetch_cloudcasts(
                    base, username, settings.sources.mixcloud_max_sets
                )
                followers = self._fetch_followers(base, username)
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

            sets = _parse_cloudcasts(cloudcasts)
            if not sets and followers is None:
                continue  # nothing to add for this entity
            result.profiles.append(
                EntityProfile(
                    name=entity.name,
                    type=entity.type,
                    top_sets=sets,
                    online=OnlinePresence(
                        mixcloud=SocialPresence(
                            url=f"https://www.mixcloud.com/{username}/",
                            handle=username,
                            followers=followers,
                        )
                    ),
                    last_verification=utcnow(),
                )
            )
            if self.request_delay and index < len(targets) - 1:
                time.sleep(self.request_delay)

        if failures and result.profiles:
            result.warnings.append(
                f"{self.name}: {failures} user fetches failed (partial results kept)"
            )
        return result

    def _fetch_cloudcasts(self, base: str, username: str, limit: int) -> list[dict]:
        response = httpx.get(
            f"{base}/{quote(username, safe='')}/cloudcasts/",
            params={"limit": limit},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json().get("data")
        return data if isinstance(data, list) else []

    def _fetch_followers(self, base: str, username: str) -> int | None:
        response = httpx.get(
            f"{base}/{quote(username, safe='')}/",
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        count = response.json().get("follower_count")
        return count if isinstance(count, int) else None
