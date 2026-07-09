"""Name normalization, alias resolution and profile merging for dedup."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from scoredclub.schemas import EntityProfile

# Tokens dropped from the start/end of names during normalization.
_STRIP_TOKENS = {"club", "berlin", "the", "der", "die", "das"}

# Known aliases for seed entities: normalized alias -> canonical entity_id.
SEED_ALIASES: dict[str, str] = {
    "kitkat": "kitkat-club",
    "kit kat club": "kitkat-club",
    "rso": "rso-berlin",
    "revier sudost": "rso-berlin",
    "aboutblank": "about-blank",
    "about:blank": "about-blank",
    "cdv": "club-der-visionaere",
    "aeden": "aeden",
    "wilde renate": "wilde-renate",
    "salon zur wilden renate": "wilde-renate",
    "renate": "wilde-renate",
    "lokschuppen": "lokschuppen-berlin",
    "ost": "ost-berlin",
    "rave the planet parade": "rave-the-planet",
    "staub": "staub-berlin",
}

FUZZY_THRESHOLD = 0.92


def normalize_name(name: str) -> str:
    """Lowercase, strip diacritics and punctuation, drop filler tokens.

    ``://about blank`` -> ``about blank``, ``ÆDEN`` -> ``aeden``,
    ``RSO.Berlin`` -> ``rso``.
    """
    norm = unicodedata.normalize("NFKD", name.lower())
    norm = norm.replace("æ", "ae").replace("ø", "o").replace("ß", "ss")
    norm = norm.encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^a-z0-9 ]+", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    tokens = norm.split(" ")
    while len(tokens) > 1 and tokens[0] in _STRIP_TOKENS:
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _STRIP_TOKENS:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _shared_evidence(a: EntityProfile, b: EntityProfile) -> bool:
    """Corroboration required before a fuzzy name match may merge."""
    if a.district and b.district and a.district.lower() == b.district.lower():
        return True
    for attr in ("website", "instagram"):
        url_a = getattr(a.online, attr).url
        url_b = getattr(b.online, attr).url
        if url_a and url_b and url_a.rstrip("/").lower() == url_b.rstrip("/").lower():
            return True
        handle_a = getattr(a.online, attr).handle
        handle_b = getattr(b.online, attr).handle
        if handle_a and handle_b and handle_a.lstrip("@").lower() == handle_b.lstrip("@").lower():
            return True
    return False


def find_match(
    incoming: EntityProfile, existing: list[EntityProfile]
) -> EntityProfile | None:
    """Find the existing profile the incoming one refers to, if any.

    Match order: exact entity_id -> seed alias -> normalized name ->
    conservative fuzzy match (ratio >= 0.92 AND shared district/URL/handle).
    """
    by_id = {e.entity_id: e for e in existing}
    if incoming.entity_id in by_id:
        return by_id[incoming.entity_id]

    incoming_norm = normalize_name(incoming.name)
    alias_target = SEED_ALIASES.get(incoming_norm)
    if alias_target and alias_target in by_id:
        return by_id[alias_target]

    norm_index: dict[str, EntityProfile] = {}
    for entity in existing:
        norm_index[normalize_name(entity.name)] = entity
        for alias in entity.aliases:
            norm_index.setdefault(normalize_name(alias), entity)
    if incoming_norm in norm_index:
        return norm_index[incoming_norm]

    for candidate_norm, candidate in norm_index.items():
        ratio = SequenceMatcher(None, incoming_norm, candidate_norm).ratio()
        if ratio >= FUZZY_THRESHOLD and _shared_evidence(incoming, candidate):
            return candidate
    return None


def _union(a: list, b: list) -> list:
    seen: set[str] = set()
    merged = []
    for item in [*a, *b]:
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _union_by_key(existing: list, incoming: list, key) -> list:
    """Union two model lists, deduping by a natural ``key``; incoming wins.

    Unlike :func:`_union` (which keys on the full repr) this keeps a single
    entry per natural key and lets the *incoming* item win on a collision. The
    dossier lists (tracks/sets/parties) use it so a re-fetch with updated play
    counts updates in place instead of accumulating near-duplicate rows.
    """
    order: list = []
    chosen: dict = {}
    for item in [*existing, *incoming]:
        k = key(item)
        if k not in chosen:
            order.append(k)
        chosen[k] = item  # later (incoming) wins on collision
    return [chosen[k] for k in order]


def merge_profiles(existing: EntityProfile, incoming: EntityProfile) -> EntityProfile:
    """Merge an incoming profile into an existing one.

    Non-null incoming scalar fields win when the incoming data is newer
    (or the existing field is empty); lists are unioned; the existing
    (seed) name and entity_id are never downgraded.
    """
    incoming_newer = (
        existing.last_verification is None
        or (
            incoming.last_verification is not None
            and incoming.last_verification >= existing.last_verification
        )
    )

    merged = existing.model_copy(deep=True)
    # Only explicitly provided scalar fields may overwrite — otherwise stub
    # profiles (e.g. from collectors) would reset type/status to defaults.
    incoming_set = incoming.model_dump(exclude_unset=True)

    def take(field: str) -> None:
        if field not in incoming_set:
            return
        new_value = incoming_set[field]
        if new_value in (None, "", [], {}) or new_value == "unknown":
            return
        current = getattr(merged, field)
        if current in (None, "", [], {}) or incoming_newer:
            setattr(merged, field, getattr(incoming, field))

    for field in ("type", "status", "address", "district", "active_since",
                  "last_event_date", "notes"):
        take(field)

    # Nested structures: per-leaf "non-null incoming wins if newer".
    for section in ("events", "press", "community", "networking",
                    "policy_safety", "labels_podcasts", "cultural_recognition", "geo"):
        current_section = getattr(merged, section)
        incoming_section = getattr(incoming, section)
        merged_section = current_section.model_copy(deep=True)
        for leaf, new_value in incoming_section.model_dump().items():
            if new_value in (None, "", [], {}) or new_value == "unknown":
                continue
            current_value = getattr(merged_section, leaf)
            if isinstance(current_value, list):
                setattr(merged_section, leaf, _union(current_value, getattr(incoming_section, leaf)))
            elif current_value in (None, "", {}) or incoming_newer:
                setattr(merged_section, leaf, getattr(incoming_section, leaf))
        setattr(merged, section, merged_section)

    # OnlinePresence leaves are models themselves — handle per platform.
    online = merged.online.model_copy(deep=True)
    for platform, incoming_presence in incoming.online.platforms().items():
        current_presence = getattr(online, platform).model_copy(deep=True)
        for leaf, new_value in incoming_presence.model_dump().items():
            if new_value in (None, "", []):
                continue
            if getattr(current_presence, leaf) in (None, "", []) or incoming_newer:
                setattr(current_presence, leaf, getattr(incoming_presence, leaf))
        setattr(online, platform, current_presence)
    merged.online = online

    merged.aliases = _union(existing.aliases, [incoming.name, *incoming.aliases])
    merged.incidents = _union(existing.incidents, incoming.incidents)
    merged.sources = _union(existing.sources, incoming.sources)
    merged.lifecycle_events = _union(existing.lifecycle_events, incoming.lifecycle_events)
    merged.displacement_signals = _union(
        existing.displacement_signals, incoming.displacement_signals
    )
    # Dossier lists dedup by a natural key (not full repr) so re-fetched music
    # data updates in place — incoming (fresher) play counts win.
    merged.top_tracks = _union_by_key(
        existing.top_tracks, incoming.top_tracks,
        key=lambda t: (t.title.strip().lower(), (t.url or "").strip().lower()),
    )
    merged.top_sets = _union_by_key(
        existing.top_sets, incoming.top_sets,
        key=lambda s: (s.title.strip().lower(), (s.url or "").strip().lower()),
    )
    merged.parties = _union_by_key(
        existing.parties, incoming.parties,
        key=lambda p: (p.name.strip().lower(), (p.venue or "").strip().lower(), p.date),
    )
    # Event-demand: newer non-null wins; follower history merges per platform.
    if incoming.demand is not None and (merged.demand is None or incoming_newer):
        merged.demand = incoming.demand
    if incoming.follower_audit is not None and (merged.follower_audit is None or incoming_newer):
        merged.follower_audit = incoming.follower_audit
    follower_history = {k: list(v) for k, v in existing.follower_history.items()}
    for platform, points in incoming.follower_history.items():
        series = follower_history.setdefault(platform, [])
        seen = {(p.date, p.followers) for p in series}
        for point in points:
            if (point.date, point.followers) not in seen:
                series.append(point)
    merged.follower_history = follower_history
    # Per-field provenance: incoming entries win when newer, else fill gaps.
    merged_provenance = dict(existing.provenance)
    for key, value in incoming.provenance.items():
        if incoming_newer or key not in merged_provenance:
            merged_provenance[key] = value
    merged.provenance = merged_provenance
    if incoming.last_verification and (
        existing.last_verification is None
        or incoming.last_verification > existing.last_verification
    ):
        merged.last_verification = incoming.last_verification
    return merged
