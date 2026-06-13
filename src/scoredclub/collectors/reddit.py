"""Reddit enrichment collector.

For each existing entity this searches Reddit and attaches the permalinks of
matching discussion threads to ``community.reddit_threads`` — feeding the
community-resonance dimension (D), which is otherwise hard to populate.

Two access modes, chosen automatically:

* **OAuth (preferred, reliable).** When ``REDDIT_CLIENT_ID`` and
  ``REDDIT_CLIENT_SECRET`` are set in the environment, the collector obtains an
  application-only token (client-credentials grant) and queries the
  authenticated ``oauth.reddit.com`` endpoint. This is the path that makes
  dimension D dependable in production (proper rate limits, not blocked).
* **Public fallback.** Without credentials it uses the public ``search.json``
  endpoint — best effort, frequently blocked/rate-limited outside a browser.

Create a Reddit "script" app at https://www.reddit.com/prefs/apps to get the
client id/secret. Set a descriptive ``REDDIT_USER_AGENT`` too (Reddit requires
a unique UA).

Like every collector this never raises: failures degrade to warnings, and it
aborts after repeated failures. It is an *enrichment* collector — it augments
existing entities (matched by name), never invents new ones.
"""

from __future__ import annotations

import os
import time

import httpx

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import CommunityInfo, EntityProfile, utcnow

_DEFAULT_UA = "scoredclub/0.1 (Berlin techno intelligence; +https://github.com/McMarvii/ScoredClub)"

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


def _user_agent() -> str:
    return os.environ.get("REDDIT_USER_AGENT") or _DEFAULT_UA


class RedditCollector:
    name = "reddit"
    request_delay = 1.0  # seconds between requests; be polite to the API

    def __init__(self):
        self._token: str | None = None
        self._token_tried = False

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        if not settings.sources.reddit_enabled or not entities:
            return result

        token = self._ensure_token(settings, result)
        ua = _user_agent()
        if token:
            base = settings.sources.reddit_oauth_search_url
            headers = {"Authorization": f"Bearer {token}", "User-Agent": ua}
        else:
            base = settings.sources.reddit_search_url
            headers = {"User-Agent": ua}

        limit = settings.sources.reddit_max_threads
        failures = 0
        for index, entity in enumerate(entities):
            try:
                threads = self._search(base, headers, entity.name, limit)
            except Exception as exc:  # noqa: BLE001 — collectors must never raise
                failures += 1
                if failures <= 2:
                    result.warnings.append(
                        f"{self.name}: search failed for {entity.name} ({type(exc).__name__})"
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

    def _ensure_token(self, settings: Settings, result: CollectorResult) -> str | None:
        """Obtain an application-only OAuth token, if credentials are configured."""
        if self._token_tried:
            return self._token
        self._token_tried = True
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        if not (client_id and client_secret):
            return None  # no creds -> public fallback (expected, not a warning)
        try:
            response = httpx.post(
                settings.sources.reddit_oauth_token_url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": _user_agent()},
                timeout=10.0,
            )
            response.raise_for_status()
            self._token = response.json().get("access_token")
            if not self._token:
                result.warnings.append(f"{self.name}: OAuth response had no access_token")
        except Exception as exc:  # noqa: BLE001 — never fatal; fall back to public
            result.warnings.append(
                f"{self.name}: OAuth token request failed ({type(exc).__name__}); "
                "using public endpoint"
            )
            self._token = None
        return self._token

    def _search(self, base: str, headers: dict, name: str, limit: int) -> list[str]:
        response = httpx.get(
            base,
            params={
                "q": f'"{name}" berlin',
                "limit": max(limit * 2, 10),
                "sort": "relevance",
                "type": "link",
                "raw_json": 1,
            },
            headers=headers,
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
