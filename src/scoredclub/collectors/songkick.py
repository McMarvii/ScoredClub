"""Songkick enrichment collector for artist-type entities.

A second *sanctioned* event source alongside Bandsintown (Resident Advisor has
no official public API). For each ``artist`` entity this resolves the artist on
Songkick, fetches their gigography (past events) and attaches the same booking
signal as Bandsintown:

* event counts in the trailing 3- and 6-month windows (dimension A),
* the most recent past event as ``last_event_date``,
* the venues played as ``networking.collaborations`` (booking-graph edges).

Access requires a Songkick API key (apply at https://www.songkick.com/developer)
set as ``SONGKICK_API_KEY``. Without it — or with no artist entities — the
collector is a silent no-op, so the canonical run is unaffected. Failure-
tolerant like every collector: failures degrade to warnings and it aborts after
repeated failures. Enrichment only — it never creates new entities.
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
    EntityType,
    EventsInfo,
    NetworkingInfo,
    utcnow,
)


def _api_key() -> str | None:
    return os.environ.get("SONGKICK_API_KEY")


def _parse_events(events: list[dict], today: dt.date) -> dict:
    """Reduce a Songkick gigography ``event[]`` list to the scored fields.

    Songkick events carry ``start.date`` (YYYY-MM-DD) and a ``venue`` with a
    ``displayName`` plus an optional ``metroArea.displayName`` (the city).
    """
    last_3 = 0
    last_6 = 0
    last_event_date: dt.date | None = None
    venues: list[str] = []
    seen: set[str] = set()

    for event in events:
        raw = (event.get("start") or {}).get("date")
        event_date: dt.date | None = None
        if isinstance(raw, str) and raw:
            try:
                event_date = dt.date.fromisoformat(raw)
            except ValueError:
                event_date = None

        if event_date is not None and event_date <= today:
            delta = (today - event_date).days
            if delta <= 90:
                last_3 += 1
            if delta <= 180:
                last_6 += 1
            if last_event_date is None or event_date > last_event_date:
                last_event_date = event_date

        venue = event.get("venue") or {}
        name = (venue.get("displayName") or "").strip()
        if name:
            city = ((venue.get("metroArea") or {}).get("displayName") or "").strip()
            label = f"{name}, {city}" if city else name
            key = label.lower()
            if key not in seen:
                seen.add(key)
                venues.append(label)

    return {
        "events_last_3_months": last_3,
        "events_last_6_months": last_6,
        "last_event_date": last_event_date,
        "venues": venues,
    }


class SongkickCollector:
    name = "songkick"
    request_delay = 0.5  # seconds between requests; be polite to the API

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        api_key = _api_key()
        if not api_key or not entities:
            return result  # no creds or nothing to enrich -> silent no-op

        artists = [e for e in entities if e.type == EntityType.artist]
        if not artists:
            return result
        artists = artists[: settings.sources.songkick_max_artists]

        base = settings.sources.songkick_url.rstrip("/")
        today = utcnow().date()
        failures = 0
        for index, entity in enumerate(artists):
            try:
                artist_id = self._search_artist_id(base, entity.name, api_key)
                events = (
                    self._fetch_gigography(base, artist_id, api_key)
                    if artist_id is not None
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

            if artist_id is None or not events:
                # Not found, or no gigography -> add nothing, so a zero-count
                # stub can't overwrite richer research-sourced counts.
                continue

            parsed = _parse_events(events, today)
            result.profiles.append(
                EntityProfile(
                    name=entity.name,
                    type=EntityType.artist,
                    last_event_date=parsed["last_event_date"],
                    events=EventsInfo(
                        events_last_3_months=parsed["events_last_3_months"],
                        events_last_6_months=parsed["events_last_6_months"],
                        ticketing_platforms=["Songkick"],
                    ),
                    networking=NetworkingInfo(collaborations=parsed["venues"]),
                    last_verification=utcnow(),
                )
            )
            if self.request_delay and index < len(artists) - 1:
                time.sleep(self.request_delay)

        if failures and result.profiles:
            result.warnings.append(
                f"{self.name}: {failures} artist fetches failed (partial results kept)"
            )
        return result

    def _search_artist_id(self, base: str, name: str, api_key: str) -> int | None:
        response = httpx.get(
            f"{base}/search/artists.json",
            params={"apikey": api_key, "query": name},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        results = (response.json().get("resultsPage") or {}).get("results") or {}
        artists = results.get("artist") or []
        if not artists:
            return None
        return artists[0].get("id")

    def _fetch_gigography(self, base: str, artist_id: int, api_key: str) -> list[dict]:
        response = httpx.get(
            f"{base}/artists/{artist_id}/gigography.json",
            params={"apikey": api_key},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        results = (response.json().get("resultsPage") or {}).get("results") or {}
        events = results.get("event")
        return events if isinstance(events, list) else []
