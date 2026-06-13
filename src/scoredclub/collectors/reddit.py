"""Reddit enrichment collector.

For each existing entity this queries Reddit's public JSON search endpoint
(no authentication required for read access) and attaches the permalinks of
matching discussion threads to ``community.reddit_threads``. This feeds the
community-resonance dimension (D), which is otherwise hard to populate.

Like every collector this never raises: in sandboxed environments where
reddit.com is unreachable it degrades to a warning and ``ok=False``. In a
real deployment it fills the reddit_threads the scoring rubric reads.

This is an *enrichment* collector: it does not invent new entities, it only
returns partial profiles (matched by name) for entities passed to it.
"""

from __future__ import annotations

import time

import httpx

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import CommunityInfo, EntityProfile, utcnow

# Reddit requires a descriptive, non-browser User-Agent for its public API.
_UA = "scoredclub/0.1 (Berlin techno intelligence; +https://github.com/McMarvii/ScoredClub)"

# Subreddits that actually discuss the Berlin techno scene; threads outside
# these are ignored to keep the signal clean.
_RELEVANT_SUBREDDITS = {
    "berlin",
    "berghain_community",
    "techno",
    "aves",
    "de",
    "germany",
    "electronicmusic",
}


class RedditCollector:
    name = "reddit"
    request_delay = 1.0  # seconds between requests; be polite to the API

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        if not settings.sources.reddit_enabled:
            return result
        if not entities:
            return result

        limit = settings.sources.reddit_max_threads
        url = settings.sources.reddit_search_url
        failures = 0
        for index, entity in enumerate(entities):
            try:
                threads = self._search(url, entity.name, limit)
            except Exception as exc:  # noqa: BLE001 — collectors must never raise
                failures += 1
                # Stop hammering a blocked endpoint after the first failures.
                if failures <= 2:
                    result.warnings.append(
                        f"{self.name}: search failed for {entity.name} "
                        f"({type(exc).__name__})"
                    )
                if failures >= 3:
                    result.ok = False
                    result.warnings.append(
                        f"{self.name}: endpoint unreachable, aborting after {failures} failures"
                    )
                    break
                continue

            if threads:
                result.profiles.append(
                    EntityProfile(
                        name=entity.name,
                        community=CommunityInfo(reddit_threads=threads),
                        last_verification=utcnow(),
                    )
                )
            if self.request_delay and index < len(entities) - 1:
                time.sleep(self.request_delay)

        if failures and result.profiles:
            result.warnings.append(
                f"{self.name}: {failures} entity searches failed (partial results kept)"
            )
        return result

    def _search(self, url: str, name: str, limit: int) -> list[str]:
        response = httpx.get(
            url,
            params={
                "q": f'"{name}" berlin',
                "limit": max(limit * 2, 10),
                "sort": "relevance",
                "type": "link",
            },
            headers={"User-Agent": _UA},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        children = payload.get("data", {}).get("children", [])
        threads: list[str] = []
        for child in children:
            data = child.get("data", {})
            subreddit = (data.get("subreddit") or "").lower()
            permalink = data.get("permalink")
            if not permalink or subreddit not in _RELEVANT_SUBREDDITS:
                continue
            threads.append(f"https://www.reddit.com{permalink}")
            if len(threads) >= limit:
                break
        return threads
