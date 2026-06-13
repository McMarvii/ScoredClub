"""Agentic LLM research collector (optional, off by default).

Automates the research that otherwise has to be produced by hand as a
``research.json``. For each entity it asks Claude (via the official Anthropic
SDK) to research the act with the server-side **web_search** tool and then
extract a structured :class:`~scoredclub.schemas.EntityProfile` via structured
outputs. The resulting partial profiles are merged into the existing entities,
so this is an *enrichment* collector — it never invents new entities.

Design constraints (so it's safe to wire into every run):

* **Off by default** — enabled via ``llm.enabled`` in the config.
* **Optional dependency** — needs ``pip install scoredclub[llm]`` and an
  ``ANTHROPIC_API_KEY``. Missing either degrades to a warning, never an error.
* **Failure-tolerant** — every per-entity exception becomes a warning; the
  collector aborts after repeated failures and never raises.

Because the Anthropic API is not reachable from CI/sandboxes (and costs money),
the client is injectable for tests, which exercise the parsing/merge logic with
a fake client and never make real calls.
"""

from __future__ import annotations

from scoredclub.collectors.base import CollectorResult
from scoredclub.config import Settings
from scoredclub.schemas import EntityProfile, utcnow

# Anthropic server-side web search tool (see Claude API reference).
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

_RESEARCH_SYSTEM = (
    "You are a research analyst for the Berlin techno scene. You produce concise, "
    "factual briefings grounded in current web sources. Prefer primary sources "
    "(official site, Resident Advisor, Instagram, reputable press). Note follower "
    "magnitudes, recent event activity, press features, awareness/safer-space "
    "policies, labels/podcasts, notable bookings, and any documented incidents. "
    "Do not speculate; if something is unknown, say so."
)


def _research_prompt(name: str, entity_type: str) -> str:
    return (
        f'Research the Berlin techno {entity_type} "{name}". Use web search to find: '
        "current status (active/closed) and most recent event; Instagram handle and "
        "approximate follower count; Resident Advisor profile and event cadence; press "
        "features (RA/Mixmag/Groove vs. local press); community discussion; safer-space / "
        "queer / FLINTA policy; own label or podcast; notable/international DJ bookings; "
        "Clubcommission membership or cultural-heritage recognition; documented incidents. "
        "Write a tight factual brief; cite what you found and flag unknowns."
    )


def _extract_prompt(name: str, entity_id: str, entity_type: str, brief: str) -> str:
    return (
        f"From the research brief below, extract a structured profile for the Berlin "
        f'techno {entity_type} "{name}". Use exactly entity_id="{entity_id}" and '
        f'name="{name}". Include only facts supported by the brief; leave unknown fields '
        "null and unknown lists empty. Use conservative round numbers for follower/event "
        "counts.\n\nRESEARCH BRIEF:\n" + brief
    )


class LLMResearchCollector:
    name = "llm_research"
    request_failures_abort = 3

    def __init__(self, client=None):
        # Injectable for tests; constructed lazily from the env otherwise.
        self._client = client

    def _ensure_client(self, result: CollectorResult):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # optional dependency
        except ImportError:
            result.ok = False
            result.warnings.append(
                f"{self.name}: anthropic SDK not installed (pip install scoredclub[llm])"
            )
            return None
        try:
            self._client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
        except Exception as exc:  # noqa: BLE001 — missing key etc.
            result.ok = False
            result.warnings.append(
                f"{self.name}: cannot init Anthropic client ({type(exc).__name__}); "
                "set ANTHROPIC_API_KEY"
            )
            return None
        return self._client

    @staticmethod
    def _select(entities: list[EntityProfile], limit: int) -> list[EntityProfile]:
        # Stalest first: never-verified before oldest verification.
        ordered = sorted(
            entities,
            key=lambda e: (e.last_verification is not None, e.last_verification or utcnow()),
        )
        return ordered if limit <= 0 else ordered[:limit]

    def collect(
        self, settings: Settings, entities: list[EntityProfile] | None = None
    ) -> CollectorResult:
        result = CollectorResult(collector=self.name)
        cfg = settings.llm
        if not cfg.enabled or not entities:
            return result

        client = self._ensure_client(result)
        if client is None:
            return result

        failures = 0
        for entity in self._select(entities, cfg.max_entities):
            try:
                brief = self._research_brief(client, cfg, entity.name, entity.type.value)
                profile = self._extract_profile(
                    client, cfg, entity.entity_id, entity.name, entity.type.value, brief
                )
            except Exception as exc:  # noqa: BLE001 — collectors must never raise
                failures += 1
                result.warnings.append(
                    f"{self.name}: research failed for {entity.name} ({type(exc).__name__})"
                )
                if failures >= self.request_failures_abort:
                    result.ok = False
                    result.warnings.append(
                        f"{self.name}: aborting after {failures} failures"
                    )
                    break
                continue

            if profile is not None:
                profile.entity_id = entity.entity_id
                profile.name = entity.name
                if profile.last_verification is None:
                    profile.last_verification = utcnow()
                result.profiles.append(profile)
        return result

    def _research_brief(self, client, cfg, name: str, entity_type: str) -> str:
        messages = [{"role": "user", "content": _research_prompt(name, entity_type)}]
        response = None
        for _ in range(cfg.research_max_continuations + 1):
            response = client.messages.create(
                model=cfg.model,
                max_tokens=6000,
                system=_RESEARCH_SYSTEM,
                tools=[_WEB_SEARCH_TOOL],
                output_config={"effort": cfg.effort},
                messages=messages,
            )
            if getattr(response, "stop_reason", None) == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            break
        return "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", None) == "text"
        ).strip()

    def _extract_profile(
        self, client, cfg, entity_id: str, name: str, entity_type: str, brief: str
    ) -> EntityProfile | None:
        if not brief:
            return None
        response = client.messages.parse(
            model=cfg.model,
            max_tokens=4000,
            messages=[
                {"role": "user", "content": _extract_prompt(name, entity_id, entity_type, brief)}
            ],
            output_format=EntityProfile,
        )
        parsed = getattr(response, "parsed_output", None)
        if isinstance(parsed, EntityProfile):
            return parsed
        if isinstance(parsed, dict):
            return EntityProfile.model_validate(parsed)
        return None
