from scoredclub.collectors.base import CollectorResult
from scoredclub.collectors.clubcommission import ClubcommissionCollector
from scoredclub.collectors.reddit import RedditCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector

# Discovery collectors may introduce new entities (upserted, create allowed).
DISCOVERY_COLLECTORS = [ClubcommissionCollector, ResidentAdvisorCollector]

# Enrichment collectors only augment existing entities (no creation); they
# receive the current entity list and return partial profiles matched by name.
ENRICHMENT_COLLECTORS = [RedditCollector]

# Backwards-compatible alias.
NETWORK_COLLECTORS = DISCOVERY_COLLECTORS

__all__ = [
    "CollectorResult",
    "ClubcommissionCollector",
    "ResidentAdvisorCollector",
    "RedditCollector",
    "DISCOVERY_COLLECTORS",
    "ENRICHMENT_COLLECTORS",
    "NETWORK_COLLECTORS",
]
