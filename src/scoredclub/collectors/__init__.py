from scoredclub.collectors.bandsintown import BandsintownCollector
from scoredclub.collectors.base import CollectorResult
from scoredclub.collectors.clubcommission import ClubcommissionCollector
from scoredclub.collectors.follower_audit import FollowerAuditCollector
from scoredclub.collectors.llm_research import LLMResearchCollector
from scoredclub.collectors.mixcloud import MixcloudCollector
from scoredclub.collectors.reddit import RedditCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector
from scoredclub.collectors.sentiment import SentimentCollector
from scoredclub.collectors.songkick import SongkickCollector
from scoredclub.collectors.soundcloud import SoundCloudCollector

# Discovery collectors may introduce new entities (upserted, create allowed).
DISCOVERY_COLLECTORS = [ClubcommissionCollector, ResidentAdvisorCollector]

# Enrichment collectors only augment existing entities (no creation); they
# receive the current entity list and return partial profiles matched by name.
# LLMResearchCollector is a no-op unless llm.enabled is set in the config.
# BandsintownCollector is a no-op unless BANDSINTOWN_APP_ID is set and artist
# entities are present. SoundCloudCollector (tracks) is a no-op unless
# SOUNDCLOUD_CLIENT_ID is set; MixcloudCollector (sets) unless
# sources.mixcloud_enabled — both also need a matching handle on the entity and
# fill the dossier (top_tracks/top_sets) plus follower reach. SentimentCollector
# runs after Reddit (so it sees the freshly attached threads) and is a no-op
# unless sources.sentiment_enabled. FollowerAuditCollector pulls an external
# follower-quality dataset; no-op unless FOLLOWER_AUDIT_API_KEY is set.
ENRICHMENT_COLLECTORS = [
    LLMResearchCollector,
    RedditCollector,
    BandsintownCollector,
    SongkickCollector,
    SoundCloudCollector,
    MixcloudCollector,
    SentimentCollector,
    FollowerAuditCollector,
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
    "SoundCloudCollector",
    "MixcloudCollector",
    "SentimentCollector",
    "FollowerAuditCollector",
    "DISCOVERY_COLLECTORS",
    "ENRICHMENT_COLLECTORS",
    "NETWORK_COLLECTORS",
]
