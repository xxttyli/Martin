"""Tests for the Martin pipeline in martin.interfaces.cli.

End-to-end through the real Router, with brain/memory/skills mocked. We assert
the pipeline's behavior: a triggered utterance runs the skill; otherwise Martin
converses; remembered facts are injected into the conversation; auto-store never
crashes the turn.
"""

from __future__ import annotations

import pytest

from martin.core.config import Settings
from martin.core.memory import Recollection
from martin.core.router import NO_SKILL, RouteDecision, Router
from martin.interfaces.cli import Martin
from martin.skills._base import BaseSkill, SkillManifest, SkillResult


class FakeBrain:
    def __init__(self, chat_reply="a friendly reply", route_skill=NO_SKILL):
        self.chat_reply = chat_reply
        self.route_skill = route_skill
        self.chat_messages = None

    def chat(self, messages, **kwargs):
        self.chat_messages = messages
        return self.chat_reply

    def structured(self, messages, response_model, **kwargs):
        return RouteDecision(skill=self.route_skill)


class FakeMemory:
    def __init__(self, recall_result=None, consider_raises=False):
        self.recall_result = recall_result or []
        self.consider_raises = consider_raises
        self.considered = []

    def consider(self, utterance):
        if self.consider_raises:
            raise RuntimeError("memory unavailable")
        self.considered.append(utterance)
        return "mem-id"

    def recall(self, query, pillars=None, n=5):
        return self.recall_result


class FakeSkill(BaseSkill):
    def __init__(self, manifest, settings):
        super().__init__(manifest, settings=settings)
        self.ran_with = None

    def run(self, query, context=None):
        self.ran_with = query
        return SkillResult(content=f"RESULTS for: {query}", source="fake")


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def build(settings, brain, memory, skill):
    router = Router(brain=brain, settings=settings, manifests=[skill.manifest])
    return Martin(
        brain=brain,
        memory=memory,
        router=router,
        skills={skill.name: skill},
        settings=settings,
    )


def make_skill(settings):
    manifest = SkillManifest(
        name="web_search", description="search the web", triggers=["search"]
    )
    return FakeSkill(manifest, settings)


def test_triggered_utterance_runs_skill(settings):
    brain = FakeBrain()
    memory = FakeMemory()
    skill = make_skill(settings)
    agent = build(settings, brain, memory, skill)

    reply = agent.handle("search for the latest GPU prices")

    assert reply == "RESULTS for: search for the latest GPU prices"
    assert skill.ran_with == "search for the latest GPU prices"
    # The utterance was offered to memory for possible storage.
    assert memory.considered == ["search for the latest GPU prices"]


def test_non_skill_utterance_is_conversational(settings):
    brain = FakeBrain(chat_reply="Here's a joke about cats.", route_skill=NO_SKILL)
    memory = FakeMemory()
    skill = make_skill(settings)
    agent = build(settings, brain, memory, skill)

    reply = agent.handle("tell me a joke about cats")

    assert reply == "Here's a joke about cats."
    assert memory.considered == ["tell me a joke about cats"]


def test_recalled_memory_is_injected_into_conversation(settings):
    brain = FakeBrain(chat_reply="ok", route_skill=NO_SKILL)
    memory = FakeMemory(
        recall_result=[
            Recollection(text="The user publishes on Tuesdays", pillar="business",
                         metadata={})
        ]
    )
    skill = make_skill(settings)
    agent = build(settings, brain, memory, skill)

    agent.handle("what should I work on?")

    system_msg = brain.chat_messages[0]["content"]
    assert system_msg.startswith("You are Martin")
    assert "publishes on Tuesdays" in system_msg


def test_memory_failure_does_not_break_turn(settings):
    brain = FakeBrain(chat_reply="still works", route_skill=NO_SKILL)
    memory = FakeMemory(consider_raises=True)
    skill = make_skill(settings)
    agent = build(settings, brain, memory, skill)

    # consider() raising must not propagate.
    assert agent.handle("hello there") == "still works"


def test_empty_utterance_returns_empty(settings):
    agent = build(settings, FakeBrain(), FakeMemory(), make_skill(settings))
    assert agent.handle("   ") == ""
