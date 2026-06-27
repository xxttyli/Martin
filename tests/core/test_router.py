"""Tests for martin.core.router.

We assert routing behavior (which skill is chosen, and how) using injected
manifests and a FakeBrain — no live model. Trigger matching, model fallback,
conversational fallback, and guarding against invented skill names are covered.
"""

from __future__ import annotations

import pytest

from martin.core.config import Settings
from martin.core.router import NO_SKILL, RouteDecision, Router
from martin.skills._base import SkillManifest


def manifest(name, triggers, description="desc"):
    return SkillManifest(name=name, description=description, triggers=triggers)


WEB = manifest("web_search", ["search", "look up", "what is"])
WEATHER = manifest("weather", ["weather", "forecast"])
MANIFESTS = [WEB, WEATHER]


class FakeBrain:
    """Returns a preset RouteDecision and records the call."""

    def __init__(self, skill):
        self.decision = RouteDecision(skill=skill)
        self.calls = []

    def structured(self, messages, response_model, **kwargs):
        self.calls.append(kwargs)
        return self.decision


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def test_trigger_fast_path_selects_skill(settings):
    router = Router(brain=None, settings=settings, manifests=MANIFESTS)
    route = router.route("Please search for the latest GPU prices")
    assert route.skill == "web_search"
    assert route.via == "trigger"


def test_trigger_matches_multiword_phrase(settings):
    router = Router(brain=None, settings=settings, manifests=MANIFESTS)
    route = router.route("Can you look up the train times?")
    assert route.skill == "web_search"
    assert route.via == "trigger"


def test_trigger_respects_word_boundaries(settings):
    # "research" must NOT trigger the "search" keyword.
    brain = FakeBrain(skill=NO_SKILL)
    router = Router(brain=brain, settings=settings, manifests=MANIFESTS)
    route = router.route("I spent the day on research and writing")
    assert route.via != "trigger"


def test_model_selection_when_no_trigger(settings):
    brain = FakeBrain(skill="weather")
    router = Router(brain=brain, settings=settings, manifests=MANIFESTS)
    route = router.route("Will I need an umbrella tomorrow?")
    assert route.skill == "weather"
    assert route.via == "model"
    assert brain.calls[0]["model"] == settings.fast_model


def test_model_none_falls_back_to_conversation(settings):
    brain = FakeBrain(skill=NO_SKILL)
    router = Router(brain=brain, settings=settings, manifests=MANIFESTS)
    route = router.route("Tell me a joke about cats")
    assert route.skill is None
    assert route.via == "fallback"


def test_invented_skill_name_is_rejected(settings):
    # Model hallucinates a skill that doesn't exist -> conversational fallback.
    brain = FakeBrain(skill="teleport")
    router = Router(brain=brain, settings=settings, manifests=MANIFESTS)
    route = router.route("Beam me up")
    assert route.skill is None
    assert route.via == "fallback"


def test_no_brain_no_trigger_falls_back(settings):
    router = Router(brain=None, settings=settings, manifests=MANIFESTS)
    route = router.route("Just thinking out loud here")
    assert route.skill is None
    assert route.via == "fallback"


def test_empty_utterance_falls_back(settings):
    router = Router(brain=None, settings=settings, manifests=MANIFESTS)
    assert router.route("   ").skill is None
