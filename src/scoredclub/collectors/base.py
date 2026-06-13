"""Collector protocol.

Collectors NEVER raise: every network or parse failure is converted into a
warning and ``ok=False`` so the pipeline keeps working in sandboxed or
offline environments. The LLM research ingest is the authoritative data
source; network collectors only enrich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from scoredclub.config import Settings
from scoredclub.schemas import EntityProfile


@dataclass
class CollectorResult:
    collector: str
    profiles: list[EntityProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = True


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
