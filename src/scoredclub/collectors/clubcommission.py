"""Clubcommission Berlin member directory collector.

The Clubcommission homepage renders its members as a list of links of the
form ``<a href="https://www.clubcommission.de/members/<slug>/">``. We parse
those member links and derive a readable name from the slug, which is far
more reliable than scraping page headings. Each parsed member becomes a
minimal stub profile with the Clubcommission-membership flag set, feeding
the cultural-recognition bonus when merged into an existing entity.

Page-structure changes are expected — any failure (and an empty parse)
degrades to a warning and ``ok=False``; the collector never raises.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import (
    CulturalRecognition,
    EntityProfile,
    EntityType,
    SourceRef,
    utcnow,
)

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Member links look like .../members/<slug>/ ; slugs that are clearly not
# venues are skipped.
_MEMBER_HREF = re.compile(r"/members/([a-z0-9][a-z0-9\-]*)/?$", re.IGNORECASE)
_SLUG_BLOCKLIST = {"join", "all", "overview", "list"}

# Slug-token fixups so derived names read naturally.
_TOKEN_FIXUPS = {
    "und": "und",
    "berlin": "Berlin",
}


def _name_from_slug(slug: str) -> str:
    slug = slug.lower()
    suffix = ""
    # German "eingetragener Verein" suffix: ...-e-v -> " e.V."
    if slug.endswith("-e-v"):
        slug = slug[: -len("-e-v")]
        suffix = " e.V."
    tokens = [tok for tok in slug.split("-") if tok]
    words = [_TOKEN_FIXUPS.get(tok, tok.capitalize()) for tok in tokens]
    return " ".join(words) + suffix


class ClubcommissionCollector:
    name = "clubcommission"

    def collect(self, settings: Settings) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        url = settings.sources.clubcommission_url
        try:
            response = httpx.get(
                url, headers={"User-Agent": _UA}, timeout=10.0, follow_redirects=True
            )
            response.raise_for_status()
            members = self._parse(response.text)
            if not members:
                result.ok = False
                result.warnings.append(
                    f"{self.name}: no member links parsed from {url} (page structure changed?)"
                )
                return result
            for name, member_url in members:
                result.profiles.append(
                    EntityProfile(
                        name=name,
                        type=EntityType.club,
                        cultural_recognition=CulturalRecognition(clubcommission_member=True),
                        sources=[SourceRef(url=member_url, accessed_at=date.today())],
                        last_verification=utcnow(),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — collectors must never raise
            result.ok = False
            result.warnings.append(f"{self.name}: fetch failed ({type(exc).__name__}: {exc})")
        return result

    @staticmethod
    def _parse(html: str) -> list[tuple[str, str]]:
        """Return (name, member_url) pairs from the members section."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "/members/" not in href:
                continue
            match = _MEMBER_HREF.search(urlparse(href).path)
            if not match:
                continue
            slug = match.group(1).lower()
            if slug in _SLUG_BLOCKLIST or slug in seen:
                continue
            seen.add(slug)
            # Prefer visible link text when present, else derive from the slug.
            text = anchor.get_text(strip=True)
            name = text if 1 < len(text) <= 60 else _name_from_slug(slug)
            results.append((name, href))
        return results
