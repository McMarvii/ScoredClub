from scoredclub.collectors.bandsintown import BandsintownCollector
from scoredclub.collectors.base import CollectorResult
from scoredclub.collectors.clubcommission import ClubcommissionCollector
from scoredclub.collectors.llm_research import LLMResearchCollector
from scoredclub.collectors.reddit import RedditCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector

# Discovery collectors may introduce new entities (upserted, create allowed).
DISCOVERY_COLLECTORS = [ClubcommissionCollector, ResidentAdvisorCollector]

# Enrichment collectors only augment existing entities (no creation); they
# receive the current entity list and return partial profiles matched by name.
# LLMResearchCollector is a no-op unless llm.enabled is set in the config.
# BandsintownCollector is a no-op unless BANDSINTOWN_APP_ID is set and artist
# entities are present.
ENRICHMENT_COLLECTORS = [LLMResearchCollector, RedditCollector, BandsintownCollector]

# Backwards-compatible alias.
NETWORK_COLLECTORS = DISCOVERY_COLLECTORS

__all__ = [
    "CollectorResult",
    "ClubcommissionCollector",
    "ResidentAdvisorCollector",
    "RedditCollector",
    "LLMResearchCollector",
    "BandsintownCollector",
    "DISCOVERY_COLLECTORS",
    "ENRICHMENT_COLLECTORS",
    "NETWORK_COLLECTORS",
]
