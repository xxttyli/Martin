"""Martin's router — turns an utterance into a skill choice.

This is the lightweight orchestration layer Martin owns completely (no n8n,
LangChain, or AutoGen). Given what the user said, it decides which skill (if any)
should handle it.

Two-stage selection:
1. Trigger fast-path: if the utterance contains a skill's trigger word/phrase
   (matched on word boundaries), route there immediately — cheap and instant.
2. Model selection: otherwise ask the fast model to pick the best skill from the
   manifest catalog, or decide nothing fits.
3. Fallback: if no skill matches (or there's no brain), route to plain
   conversation.

Adding a skill = drop a folder with a manifest. The router reads manifests; it
never hard-codes skill names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from martin.core.config import Settings, get_settings
from martin.skills._base import SkillManifest, discover_manifests

# Sentinel the model uses when no skill fits.
NO_SKILL = "none"


@dataclass
class Route:
    """The router's decision.

    Attributes:
        skill: The chosen skill name, or None to converse directly.
        via: How the decision was made: "trigger", "model", or "fallback".
    """

    skill: str | None
    via: str


class RouteDecision(BaseModel):
    """Structured output for model-based skill selection."""

    skill: str = Field(
        description="The exact name of the single best skill to handle the "
        f"request, or '{NO_SKILL}' if no skill fits and it should just be answered "
        "conversationally."
    )


class Router:
    """Selects a skill for an utterance from the available manifests.

    Args:
        brain: Brain used for model-based selection. Optional — without it the
            router uses only the trigger fast-path and conversational fallback.
        settings: Settings override (defaults to the process singleton).
        manifests: Skill manifests to route over. Defaults to discovering every
            manifest under martin/skills/.
    """

    def __init__(
        self,
        brain=None,
        settings: Settings | None = None,
        manifests: list[SkillManifest] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.brain = brain
        self.manifests = manifests if manifests is not None else discover_manifests()

    def route(self, utterance: str) -> Route:
        """Decide which skill should handle ``utterance`` (or None to converse)."""
        utterance = utterance.strip()
        if not utterance:
            return Route(skill=None, via="fallback")

        # 1. Trigger fast-path (word-boundary match so "search" != "research").
        triggered = self._match_trigger(utterance)
        if triggered:
            return Route(skill=triggered, via="trigger")

        # 2. Model-based selection.
        if self.brain and self.manifests:
            choice = self._model_select(utterance)
            if choice and choice != NO_SKILL:
                return Route(skill=choice, via="model")

        # 3. Conversational fallback.
        return Route(skill=None, via="fallback")

    # ── internals ───────────────────────────────────────────────────────────
    def _match_trigger(self, utterance: str) -> str | None:
        low = utterance.lower()
        for manifest in self.manifests:
            for trigger in manifest.triggers:
                trigger = trigger.strip().lower()
                if not trigger:
                    continue
                if re.search(rf"\b{re.escape(trigger)}\b", low):
                    return manifest.name
        return None

    def _model_select(self, utterance: str) -> str | None:
        catalog = "\n".join(
            f"- {m.name}: {m.description}" for m in self.manifests
        )
        valid = {m.name for m in self.manifests}

        decision = self.brain.structured(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You route a user's request to the single most "
                        "appropriate skill, or decide none is needed.\n"
                        "Available skills:\n"
                        f"{catalog}\n\n"
                        f"Reply with the exact skill name, or '{NO_SKILL}' if the "
                        "request is best answered by plain conversation."
                    ),
                },
                {"role": "user", "content": utterance},
            ],
            response_model=RouteDecision,
            model=self.settings.fast_model,
        )
        choice = decision.skill.strip()
        # Guard against the model inventing a skill name.
        return choice if choice in valid or choice == NO_SKILL else None
