"""Collector protocol.

Collectors NEVER raise: every network or parse failure is converted into a
warning and ``ok=False`` so the pipeline keeps working in sandboxed or
offline environments. The LLM research ingest is the authoritative data
source; network collectors only enrich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from scoredclub.config import Settings
from scoredclub.schemas import EntityProfile, SocialPresence


@dataclass
class CollectorResult:
    collector: str
    profiles: list[EntityProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = True


def social_username(presence: SocialPresence) -> str | None:
    """Extract a platform username/slug from a ``SocialPresence``.

    Prefers a plain ``handle`` (``@marcel`` -> ``marcel``) and otherwise falls
    back to the first path segment of the profile ``url``
    (``https://soundcloud.com/marcel-dettmann/`` -> ``marcel-dettmann``).
    Returns ``None`` when neither yields a username. Used by the music
    collectors (SoundCloud/Mixcloud) to address a user's API endpoint.
    """
    handle = (presence.handle or "").strip().lstrip("@").strip()
    if handle and "/" not in handle and not handle.lower().startswith("http"):
        return handle
    url = presence.url or (handle if handle.lower().startswith("http") else None)
    if url:
        path = urlparse(url).path.strip("/")
        if path:
            return path.split("/")[0]
    return handle or None


class Collector(Protocol):
    name: str

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        """Collect profiles.

        Discovery collectors ignore ``entities`` and return newly found
        profiles. Enrichment collectors use the supplied existing
        ``entities`` and return partial profiles (matched by name) that
        merge additional fields into them.
        """
        ...
