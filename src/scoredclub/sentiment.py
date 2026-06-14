"""Deterministic lexicon sentiment analysis (German + English scene vocabulary).

A transparent, offline, fully testable replacement for the manually supplied
``community_sentiment_hint``. It is intentionally *not* a black-box transformer:
the lexicon, negation and intensifier rules are auditable, which fits the
project's "explainability is a feature" stance. It runs without network access
or model downloads, so it works in CI/sandbox.

Text is diacritic-folded the same way as ``normalize`` (ü→u, ß→ss …), so the
lexicon is written in folded ASCII and matches both German and English source
text. Negations within a small window flip polarity; intensifiers scale it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from scoredclub.schemas import SentimentHint

# Folded-ASCII lexicons (weights default to 1.0; a few strong terms weigh more).
_POSITIVE: dict[str, float] = {
    "best": 1.0, "amazing": 1.5, "incredible": 1.5, "legendary": 1.5, "iconic": 1.2,
    "love": 1.2, "loved": 1.2, "great": 1.0, "perfect": 1.2, "favorite": 1.0,
    "favourite": 1.0, "unforgettable": 1.2, "awesome": 1.2, "brilliant": 1.2,
    "beautiful": 1.0, "magic": 1.0, "magical": 1.2, "fun": 1.0, "recommend": 1.0,
    "recommended": 1.0, "welcoming": 1.2, "inclusive": 1.2, "friendly": 1.0,
    "safe": 1.0, "respectful": 1.0, "wonderful": 1.2, "stellar": 1.2,
    # German (folded)
    "super": 1.0, "toll": 1.0, "geil": 1.2, "beste": 1.2, "liebe": 1.0,
    "wunderbar": 1.2, "grossartig": 1.2, "genial": 1.2, "fantastisch": 1.2,
    "empfehlenswert": 1.0, "sicher": 1.0, "freundlich": 1.0, "herausragend": 1.2,
}
_NEGATIVE: dict[str, float] = {
    "terrible": 1.5, "awful": 1.5, "worst": 1.5, "hate": 1.2, "hated": 1.2,
    "bad": 1.0, "boring": 1.0, "overrated": 1.2, "racist": 1.5, "unsafe": 1.5,
    "dangerous": 1.5, "rude": 1.2, "aggressive": 1.2, "scam": 1.5, "ripoff": 1.2,
    "overpriced": 1.0, "disappointing": 1.2, "disappointed": 1.2, "dirty": 1.0,
    "gross": 1.0, "sketchy": 1.0, "nightmare": 1.5, "avoid": 1.2, "horrible": 1.5,
    "mess": 1.0, "trash": 1.2,
    # German (folded)
    "schlecht": 1.0, "schlimm": 1.2, "furchtbar": 1.5, "langweilig": 1.0,
    "ueberteuert": 1.0, "uberteuert": 1.0, "gefaehrlich": 1.5, "gefahrlich": 1.5,
    "unsicher": 1.2, "rassistisch": 1.5, "unfreundlich": 1.2, "enttaeuschend": 1.2,
    "enttauschend": 1.2, "abzocke": 1.2, "schmutzig": 1.0, "meiden": 1.2,
}
_NEGATIONS = {"not", "no", "never", "without", "kein", "keine", "nicht", "nie", "ohne"}
_INTENSIFIERS = {
    "very": 1.5, "really": 1.4, "so": 1.3, "super": 1.5, "absolutely": 1.6,
    "totally": 1.4, "sehr": 1.5, "absolut": 1.6, "mega": 1.6, "total": 1.4,
}
_NEGATION_WINDOW = 3


@dataclass
class SentimentResult:
    polarity: float  # -1..1 (0 = no signal)
    positive_hits: float
    negative_hits: float
    hint: SentimentHint
    samples: int  # number of input texts that carried any signal


def fold(text: str) -> str:
    text = text.lower().replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def _score_one(text: str) -> tuple[float, float]:
    """Weighted (positive, negative) signal for a single text."""
    tokens = tokenize(text)
    pos = neg = 0.0
    for i, token in enumerate(tokens):
        weight = _POSITIVE.get(token, 0.0) - _NEGATIVE.get(token, 0.0)
        if weight == 0.0:
            continue
        window = tokens[max(0, i - _NEGATION_WINDOW):i]
        if any(w in _NEGATIONS for w in window):
            weight = -weight
        for prev in tokens[max(0, i - 2):i]:
            if prev in _INTENSIFIERS:
                weight *= _INTENSIFIERS[prev]
                break
        if weight > 0:
            pos += weight
        else:
            neg += -weight
    return pos, neg


def analyze_texts(texts: list[str], *, mixed_band: float = 0.34) -> SentimentResult:
    """Aggregate sentiment over several texts into a polarity and a hint.

    ``polarity = (pos - neg) / (pos + neg)``. With signal on both sides and a
    near-neutral polarity (|polarity| ≤ ``mixed_band``) the result is ``mixed``;
    otherwise ``positive`` / ``negative``. No signal at all → ``unknown``.
    """
    pos = neg = 0.0
    samples = 0
    for text in texts:
        p, n = _score_one(text or "")
        if p or n:
            samples += 1
        pos += p
        neg += n
    total = pos + neg
    if total == 0:
        return SentimentResult(0.0, 0.0, 0.0, SentimentHint.unknown, 0)
    polarity = (pos - neg) / total
    if pos > 0 and neg > 0 and abs(polarity) <= mixed_band:
        hint = SentimentHint.mixed
    elif polarity > mixed_band:
        hint = SentimentHint.positive
    elif polarity < -mixed_band:
        hint = SentimentHint.negative
    else:
        hint = SentimentHint.mixed
    return SentimentResult(round(polarity, 3), round(pos, 2), round(neg, 2), hint, samples)


def text_from_reddit_permalink(url: str) -> str:
    """Extract the human-readable title slug from a Reddit permalink.

    ``/r/berlin/comments/abc/berghain_door_is_amazing/`` → ``berghain door is amazing``.
    """
    parts = [p for p in url.split("/") if p]
    if not parts:
        return ""
    slug = parts[-1]
    if re.fullmatch(r"[a-z0-9]+", slug) and len(parts) >= 2:
        # Last segment is an id, not a slug — nothing readable.
        return ""
    return slug.replace("_", " ").replace("-", " ")


def texts_for_profile(profile) -> list[str]:
    """Collect the community/free text a profile offers for sentiment analysis."""
    texts: list[str] = [
        text_from_reddit_permalink(url) for url in profile.community.reddit_threads
    ]
    if profile.notes:
        texts.append(profile.notes)
    return [t for t in texts if t.strip()]
