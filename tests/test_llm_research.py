from __future__ import annotations

import builtins
from datetime import datetime, timezone

from scoredclub.collectors.llm_research import LLMResearchCollector
from scoredclub.config import Settings
from scoredclub.schemas import EntityProfile, OnlinePresence, SocialPresence


# ---- fake Anthropic client -------------------------------------------------

class _Block:
    def __init__(self, text, type="text"):
        self.text = text
        self.type = type


class _Resp:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class _ParseResp:
    def __init__(self, parsed):
        self.parsed_output = parsed


class _FakeMessages:
    def __init__(self, brief="Brief.", parsed_factory=None, create_hook=None, create_error=None):
        self.brief = brief
        self.parsed_factory = parsed_factory
        self.create_hook = create_hook
        self.create_error = create_error
        self.create_calls = []
        self.parse_calls = []

    def create(self, **kw):
        self.create_calls.append(kw)
        if self.create_error:
            raise self.create_error
        if self.create_hook:
            return self.create_hook(kw, len(self.create_calls))
        return _Resp([_Block(self.brief)])

    def parse(self, **kw):
        self.parse_calls.append(kw)
        profile = self.parsed_factory(kw) if self.parsed_factory else EntityProfile(name="x", type="club")
        return _ParseResp(profile)


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


def _enriched_profile(_kw):
    return EntityProfile(
        name="model-supplied",
        type="club",
        status="active",
        online=OnlinePresence(instagram=SocialPresence(handle="x", followers=250000)),
    )


def _settings(**llm):
    s = Settings()
    s.llm.enabled = True
    for k, v in llm.items():
        setattr(s.llm, k, v)
    return s


# ---- tests -----------------------------------------------------------------

def test_disabled_is_noop():
    msgs = _FakeMessages()
    collector = LLMResearchCollector(client=_FakeClient(msgs))
    result = collector.collect(Settings(), entities=[EntityProfile(name="Berghain", type="club")])
    assert result.ok
    assert result.profiles == []
    assert msgs.create_calls == []  # never touched the client


def test_enabled_enriches_and_preserves_identity():
    msgs = _FakeMessages(parsed_factory=_enriched_profile)
    collector = LLMResearchCollector(client=_FakeClient(msgs))
    entities = [EntityProfile(entity_id="berghain", name="Berghain", type="club")]
    result = collector.collect(_settings(), entities=entities)

    assert result.ok
    assert len(result.profiles) == 1
    p = result.profiles[0]
    # Identity is forced back to the original entity so the merge matches.
    assert p.entity_id == "berghain" and p.name == "Berghain"
    assert p.online.instagram.followers == 250000
    assert p.last_verification is not None
    # Used web search + structured outputs.
    assert msgs.create_calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert msgs.parse_calls[0]["output_format"] is EntityProfile


def test_respects_max_entities_stalest_first():
    msgs = _FakeMessages(parsed_factory=_enriched_profile)
    collector = LLMResearchCollector(client=_FakeClient(msgs))
    entities = [
        EntityProfile(entity_id="fresh", name="Fresh", type="club",
                      last_verification=datetime(2026, 6, 1, tzinfo=timezone.utc)),
        EntityProfile(entity_id="never", name="Never", type="club"),  # last_verification None
        EntityProfile(entity_id="old", name="Old", type="club",
                      last_verification=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    result = collector.collect(_settings(max_entities=2), entities=entities)
    ids = [p.entity_id for p in result.profiles]
    # Never-verified first, then the older one; the fresh one is skipped.
    assert ids == ["never", "old"]


def test_pause_turn_continuation():
    def hook(kw, n):
        if n == 1:
            return _Resp([_Block("partial")], stop_reason="pause_turn")
        return _Resp([_Block("Final brief.")])

    msgs = _FakeMessages(parsed_factory=_enriched_profile, create_hook=hook)
    collector = LLMResearchCollector(client=_FakeClient(msgs))
    result = collector.collect(_settings(max_entities=1),
                               entities=[EntityProfile(entity_id="b", name="B", type="club")])
    assert len(result.profiles) == 1
    assert len(msgs.create_calls) == 2  # paused once, then resumed


def test_failures_abort_and_are_nonfatal():
    msgs = _FakeMessages(create_error=RuntimeError("api down"))
    collector = LLMResearchCollector(client=_FakeClient(msgs))
    entities = [EntityProfile(entity_id=f"c{i}", name=f"C{i}", type="club") for i in range(5)]
    result = collector.collect(_settings(max_entities=0), entities=entities)
    assert result.ok is False
    assert result.profiles == []
    assert len(msgs.create_calls) == 3  # aborted after 3 failures
    assert any("aborting" in w for w in result.warnings)


def test_missing_sdk_is_graceful(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    collector = LLMResearchCollector()  # no injected client -> tries to import
    result = collector.collect(_settings(), entities=[EntityProfile(name="B", type="club")])
    assert result.ok is False
    assert result.profiles == []
    assert any("anthropic SDK not installed" in w for w in result.warnings)
