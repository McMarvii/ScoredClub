"""Clubcommission Berlin public club directory collector.

Fetches the public member/club listing and produces minimal stub profiles
(name, type=club, source URL) with the Clubcommission membership flag set,
which feeds the cultural-recognition bonus when merged into existing
entities. Page structure changes are expected — failures degrade to a
warning, never an exception.
"""

from __future__ import annotations

from datetime import date

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
            names = self._parse(response.text)
            if not names:
                result.ok = False
                result.warnings.append(
                    f"{self.name}: no club names parsed from {url} (page structure changed?)"
                )
                return result
            for club_name in names:
                result.profiles.append(
                    EntityProfile(
                        name=club_name,
                        type=EntityType.club,
                        cultural_recognition=CulturalRecognition(clubcommission_member=True),
                        sources=[SourceRef(url=url, accessed_at=date.today())],
                        last_verification=utcnow(),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — collectors must never raise
            result.ok = False
            result.warnings.append(f"{self.name}: fetch failed ({type(exc).__name__}: {exc})")
        return result

    @staticmethod
    def _parse(html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        names: list[str] = []
        # The directory renders club names as card headings/list items;
        # collect short heading texts as a best-effort heuristic.
        for tag in soup.select("h2, h3, h4, li a"):
            text = tag.get_text(strip=True)
            if 2 < len(text) <= 60 and "\n" not in text:
                names.append(text)
        # Drop obvious navigation noise.
        blocklist = {"clubs", "news", "events", "kontakt", "impressum", "datenschutz",
                     "mitglieder", "über uns", "newsletter", "english", "deutsch"}
        return [n for n in dict.fromkeys(names) if n.lower() not in blocklist]
