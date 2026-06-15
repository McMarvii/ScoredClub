"""Bandsintown enrichment collector for artist-type entities.

Resident Advisor has no sanctioned public API (scraping it carries ToS risk),
so the booking signal for DJs/artists comes from Bandsintown's official REST
API instead. For each ``artist`` entity this fetches the artist's events and
attaches:

* event counts in the trailing 3- and 6-month windows (dimension A),
* the most recent past event as ``last_event_date`` (freshness / continuity),
* the venues played as ``networking.collaborations`` — the seed of a
  booking graph (which clubs an artist actually plays).

Access requires a Bandsintown ``app_id``: register one at
https://www.artists.bandsintown.com/support/api-installation and set it in the
environment as ``BANDSINTOWN_APP_ID``. Without it — or when no artist entities
are present — the collector is a no-op (the canonical run has no artists, so it
stays silent there).

Like every collector this never raises: failures degrade to warnings and it
aborts after repeated failures. It is an *enrichment* collector — it augments
existing artist entities (matched by name), never invents new ones.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from urllib.parse import quote

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


def _app_id() -> str | None:
    return os.environ.get("BANDSINTOWN_APP_ID")


def _parse_events(events: list[dict], today: dt.date) -> dict:
    """Reduce a Bandsintown events payload to the fields we score on.

    Counts past events within the trailing 90/180-day windows, finds the most
    recent past event date, and collects the distinct venues played (past and
    upcoming) as "Name, City" strings.
    """
    last_3 = 0
    last_6 = 0
    last_event_date: dt.date | None = None
    venues: list[str] = []
    seen: set[str] = set()

    for event in events:
        raw = event.get("datetime")
        event_date: dt.date | None = None
        if isinstance(raw, str) and raw:
            try:
                event_date = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
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
        name = (venue.get("name") or "").strip()
        if name:
            city = (venue.get("city") or "").strip()
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


class BandsintownCollector:
    name = "bandsintown"
    request_delay = 0.5  # seconds between requests; be polite to the API

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        app_id = _app_id()
        if not app_id or not entities:
            return result  # no creds or nothing to enrich -> silent no-op

        artists = [e for e in entities if e.type == EntityType.artist]
        if not artists:
            return result
        artists = artists[: settings.sources.bandsintown_max_artists]

        base = settings.sources.bandsintown_url
        today = utcnow().date()
        failures = 0
        for index, entity in enumerate(artists):
            try:
                events = self._fetch_events(base, entity.name, app_id)
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

            # No events (artist not found / nothing booked) -> emit nothing, so a
            # zero-count stub can't overwrite richer research-sourced counts.
            if not events:
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
                        ticketing_platforms=["Bandsintown"],
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

    def _fetch_events(self, base: str, name: str, app_id: str) -> list[dict]:
        url = f"{base.rstrip('/')}/{quote(name, safe='')}/events"
        response = httpx.get(
            url,
            params={"app_id": app_id, "date": "all"},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        # The events endpoint returns a JSON array; an error object (dict) means
        # the artist was not found or the request was rejected.
        if isinstance(payload, list):
            return payload
        return []
