"""District-based geocoding.

The research data carries a Berlin district per entity but no coordinates.
Rather than calling an external geocoding service, we map each district to a
static centroid (public knowledge) and apply a small deterministic jitter so
that entities in the same district don't overlap on the map. This is enough to
plot a district-level map; precise per-address geocoding is left to v2.

Pure functions over :class:`~scoredclub.schemas.EntityProfile`.
"""

from __future__ import annotations

import hashlib
import re

from scoredclub.schemas import EntityProfile

# Approximate centroids (lat, lon) of Berlin districts / Ortsteile that appear
# in the data, plus common Bezirke. Lower-case keys.
BERLIN_DISTRICTS: dict[str, tuple[float, float]] = {
    "mitte": (52.5200, 13.4050),
    "friedrichshain": (52.5155, 13.4540),
    "kreuzberg": (52.4990, 13.4030),
    "lichtenberg": (52.5160, 13.4980),
    "treptow": (52.4940, 13.4560),
    "schöneweide": (52.4560, 13.5160),
    "schoeneweide": (52.4560, 13.5160),
    "pankow": (52.5690, 13.4020),
    "neukölln": (52.4810, 13.4350),
    "neukoelln": (52.4810, 13.4350),
    "prenzlauer berg": (52.5400, 13.4240),
    "wedding": (52.5500, 13.3650),
    "charlottenburg": (52.5050, 13.3030),
    "schöneberg": (52.4830, 13.3550),
    "schoeneberg": (52.4830, 13.3550),
    "tempelhof": (52.4700, 13.3850),
    "köpenick": (52.4450, 13.5750),
    "koepenick": (52.4450, 13.5750),
    "wilmersdorf": (52.4870, 13.3200),
    "moabit": (52.5300, 13.3420),
}

_JITTER_SPAN = 0.006  # ~0.5 km


def _jitter(entity_id: str) -> tuple[float, float]:
    h = int(hashlib.sha1(entity_id.encode("utf-8")).hexdigest(), 16)
    dlat = ((h % 1000) / 1000 - 0.5) * 2 * _JITTER_SPAN
    dlon = (((h // 1000) % 1000) / 1000 - 0.5) * 2 * _JITTER_SPAN
    return dlat, dlon


def geocode_district(district: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) centroid for a district name, or None if unknown."""
    if not district:
        return None
    key = district.strip().lower()
    if key in BERLIN_DISTRICTS:
        return BERLIN_DISTRICTS[key]
    # Handle composite names like "Friedrichshain-Kreuzberg".
    for part in re.split(r"[-/ ]+", key):
        if part in BERLIN_DISTRICTS:
            return BERLIN_DISTRICTS[part]
    return None


def apply_geocoding(profile: EntityProfile) -> bool:
    """Fill profile.geo from its district if empty. Returns True if changed."""
    if profile.geo.lat is not None and profile.geo.lon is not None:
        return False
    coords = geocode_district(profile.district)
    if coords is None:
        return False
    lat, lon = coords
    dlat, dlon = _jitter(profile.entity_id)
    profile.geo.lat = round(lat + dlat, 5)
    profile.geo.lon = round(lon + dlon, 5)
    return True
