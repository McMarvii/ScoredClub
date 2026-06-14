from scoredclub.collectors.bandsintown import BandsintownCollector
from scoredclub.collectors.base import CollectorResult
from scoredclub.collectors.clubcommission import ClubcommissionCollector
from scoredclub.collectors.llm_research import LLMResearchCollector
from scoredclub.collectors.reddit import RedditCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector
from scoredclub.collectors.sentiment import SentimentCollector
from scoredclub.collectors.songkick import SongkickCollector

# Discovery collectors may introduce new entities (upserted, create allowed).
DISCOVERY_COLLECTORS = [ClubcommissionCollector, ResidentAdvisorCollector]

# Enrichment collectors only augment existing entities (no creation); they
# receive the current entity list and return partial profiles matched by name.
# LLMResearchCollector is a no-op unless llm.enabled is set in the config.
# BandsintownCollector is a no-op unless BANDSINTOWN_APP_ID is set and artist
# entities are present. SentimentCollector runs after Reddit (so it sees the
# freshly attached threads) and is a no-op unless sources.sentiment_enabled.
ENRICHMENT_COLLECTORS = [
    LLMResearchCollector,
    RedditCollector,
    BandsintownCollector,
    SongkickCollector,
    SentimentCollector,
]

# Backwards-compatible alias.
NETWORK_COLLECTORS = DISCOVERY_COLLECTORS

__all__ = [
    "CollectorResult",
    "ClubcommissionCollector",
    "ResidentAdvisorCollector",
    "RedditCollector",
    "LLMResearchCollector",
    "BandsintownCollector",
    "SongkickCollector",
    "SentimentCollector",
    "DISCOVERY_COLLECTORS",
    "ENRICHMENT_COLLECTORS",
    "NETWORK_COLLECTORS",
]
