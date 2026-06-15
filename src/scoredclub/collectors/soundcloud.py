"""SoundCloud enrichment collector — tracks/releases + follower reach.

SoundCloud is a primary publishing platform for techno tracks and edits, so it
is the natural source for the dossier's **top tracks**. For each entity that
carries a SoundCloud handle (in ``online.soundcloud``) this resolves the user,
fetches their tracks and attaches:

* the released tracks as ``top_tracks`` (title, plays, release date, url) — the
  Steckbrief/[dossier](../../docs/dossier.md) building block,
* the SoundCloud **follower count** as ``online.soundcloud.followers`` (online
  reach, dimension B).

Access requires a SoundCloud ``client_id`` (register an app at
https://developers.soundcloud.com/) set as ``SOUNDCLOUD_CLIENT_ID``. Without it
— or for entities without a SoundCloud handle — the collector is a silent no-op,
so the canonical run is unaffected. Enrichment only — it never invents entities.
Failure-tolerant: failures degrade to warnings and it aborts after repeated
failures; a user that cannot be resolved is skipped, not counted as a failure.
"""

from __future__ import annotations

import os
import re
import time

import httpx

from scoredclub.collectors.base import CollectorResult, social_username
from scoredclub.config import Settings
from scoredclub.schemas import (
    EntityProfile,
    OnlinePresence,
    SocialPresence,
    Track,
    utcnow,
)


def _client_id() -> str | None:
    return os.environ.get("SOUNDCLOUD_CLIENT_ID")


def _released(raw: object) -> str | None:
    """Normalise a SoundCloud ``created_at`` to ``YYYY-MM-DD`` (or ``YYYY``).

    SoundCloud has used both ``2014/01/05 12:00:00 +0000`` and ISO
    ``2014-01-05T12:00:00Z``; we keep just the date, falling back to the year.
    """
    if not isinstance(raw, str) or not raw:
        return None
    iso = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", raw.strip())
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    year = re.match(r"(\d{4})", raw.strip())
    return year.group(1) if year else None


def _parse_tracks(tracks: list[dict]) -> list[Track]:
    """Reduce a SoundCloud ``tracks`` payload to dossier ``Track`` items."""
    out: list[Track] = []
    for t in tracks:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        plays = t.get("playback_count")
        out.append(
            Track(
                title=title,
                url=t.get("permalink_url"),
                plays=plays if isinstance(plays, int) else None,
                released=_released(t.get("created_at")),
                source="soundcloud",
            )
        )
    return out


class SoundCloudCollector:
    name = "soundcloud"
    request_delay = 0.5  # seconds between users; be polite to the API

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        client_id = _client_id()
        if not client_id or not entities:
            return result  # no creds or nothing to enrich -> silent no-op

        targets = [
            (e, username)
            for e in entities
            if (username := social_username(e.online.soundcloud))
        ]
        if not targets:
            return result  # no SoundCloud handles -> no-op
        targets = targets[: settings.sources.soundcloud_max_entities]

        base = settings.sources.soundcloud_url.rstrip("/")
        failures = 0
        for index, (entity, username) in enumerate(targets):
            try:
                user = self._resolve_user(base, username, client_id)
                tracks = (
                    self._fetch_tracks(
                        base, user["id"], client_id, settings.sources.soundcloud_max_tracks
                    )
                    if user is not None
                    else []
                )
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

            if user is None:
                continue  # user not found on SoundCloud -> nothing to add

            top_tracks = _parse_tracks(tracks)
            followers = user.get("followers_count")
            result.profiles.append(
                EntityProfile(
                    name=entity.name,
                    type=entity.type,
                    top_tracks=top_tracks,
                    online=OnlinePresence(
                        soundcloud=SocialPresence(
                            url=user.get("permalink_url")
                            or f"https://soundcloud.com/{username}",
                            handle=username,
                            followers=followers if isinstance(followers, int) else None,
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

    def _resolve_user(self, base: str, username: str, client_id: str) -> dict | None:
        response = httpx.get(
            f"{base}/resolve",
            params={"url": f"https://soundcloud.com/{username}", "client_id": client_id},
            timeout=10.0,
            follow_redirects=True,
        )
        if response.status_code == 404:
            return None  # unknown user -> skip, not a hard failure
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("id") is not None:
            return payload
        return None

    def _fetch_tracks(
        self, base: str, user_id: int, client_id: str, limit: int
    ) -> list[dict]:
        response = httpx.get(
            f"{base}/users/{user_id}/tracks",
            params={"client_id": client_id, "limit": limit},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        # The API may return a bare list or a paginated {"collection": [...]}.
        if isinstance(payload, list):
            return payload
        collection = payload.get("collection") if isinstance(payload, dict) else None
        return collection if isinstance(collection, list) else []
