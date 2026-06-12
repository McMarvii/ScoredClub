from scoredclub.collectors.base import CollectorResult
from scoredclub.collectors.clubcommission import ClubcommissionCollector
from scoredclub.collectors.resident_advisor import ResidentAdvisorCollector

NETWORK_COLLECTORS = [ClubcommissionCollector, ResidentAdvisorCollector]

__all__ = ["CollectorResult", "ClubcommissionCollector", "ResidentAdvisorCollector", "NETWORK_COLLECTORS"]
