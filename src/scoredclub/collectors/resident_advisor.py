"""Best-effort Resident Advisor collector.

RA is JavaScript-heavy and protected by bot mitigation; this collector
attempts a single query against the public GraphQL endpoint and degrades
to a warning on any failure (403/Cloudflare/non-JSON). V1 stance: no
headless browser — the LLM research path is the authoritative source for
RA followers and event counts. This collector only opportunistically
enriches when the endpoint happens to be reachable.
"""

from __future__ import annotations

import httpx

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import EntityProfile, EntityType, EventsInfo, utcnow

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_CLUB_SEARCH_QUERY = """
query searchClubs($searchTerm: String!) {
  search(searchTerm: $searchTerm, indices: [CLUB], limit: 20) {
    id
    value
    contentUrl
  }
}
"""


class ResidentAdvisorCollector:
    name = "resident_advisor"

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        url = settings.sources.ra_graphql_url
        try:
            response = httpx.post(
                url,
                json={
                    "query": _CLUB_SEARCH_QUERY,
                    "variables": {"searchTerm": "berlin techno"},
                },
                headers={
                    "User-Agent": _UA,
                    "Content-Type": "application/json",
                    "Referer": "https://ra.co/",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
            hits = (payload.get("data") or {}).get("search") or []
            for hit in hits:
                name = hit.get("value")
                content_url = hit.get("contentUrl")
                if not name:
                    continue
                profile = EntityProfile(
                    name=name,
                    type=EntityType.club,
                    events=EventsInfo(
                        ra_profile_url=f"https://ra.co{content_url}" if content_url else None
                    ),
                    last_verification=utcnow(),
                )
                result.profiles.append(profile)
            if not hits:
                result.warnings.append(f"{self.name}: query returned no results")
        except Exception as exc:  # noqa: BLE001 — collectors must never raise
            result.ok = False
            result.warnings.append(
                f"{self.name}: unreachable or blocked ({type(exc).__name__}); "
                "use the LLM research path for RA data"
            )
        return result
