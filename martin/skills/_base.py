"""Base classes for Martin's skill system.

A skill is a self-contained capability living in its own folder under
``martin/skills/`` with three files:

    skills/<name>/
        skill.py        # a BaseSkill subclass
        manifest.json   # metadata (name, description, pillar, triggers, ...)
        test_skill.py   # behavior tests

Martin discovers skills at startup by reading the manifests — adding a skill is
dropping in a folder, never editing core routing code.

This module defines:
- ``SkillManifest``  — the typed manifest schema + loader.
- ``SkillResult``    — the standard return shape from running a skill.
- ``BaseSkill``      — the abstract base every skill inherits.
- ``discover_manifests`` / ``discover_manifest_for`` — manifest discovery helpers.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from martin.core.config import Settings, get_settings

# The directory that contains all skill folders (this file lives in it).
SKILLS_DIR = Path(__file__).resolve().parent


@dataclass
class SkillResult:
    """The standard result of running a skill.

    Attributes:
        content: Human-readable text to surface to the user / feed onward.
        success: Whether the skill completed its job. On failure, ``content``
            should honestly explain what went wrong (never confabulate).
        source: Optional provenance label (e.g. "brave", "duckduckgo").
        latency: Optional seconds the skill took, for latency-aware testing.
    """

    content: str
    success: bool = True
    source: str | None = None
    latency: float | None = None


class SkillManifest(BaseModel):
    """Typed view of a skill's ``manifest.json`` (briefing §5 schema)."""

    name: str
    description: str
    pillar: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    phase: int = 1

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillManifest":
        """Load and validate a manifest from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)


class BaseSkill(ABC):
    """Abstract base class all skills inherit.

    Args:
        manifest: The skill's parsed manifest.
        brain: Optional Brain, for skills that need the LLM.
        settings: Settings override (defaults to the process singleton).
    """

    def __init__(
        self,
        manifest: SkillManifest,
        brain=None,
        settings: Settings | None = None,
    ) -> None:
        self.manifest = manifest
        self.brain = brain
        self.settings = settings or get_settings()

    @property
    def name(self) -> str:
        return self.manifest.name

    def missing_requirements(self) -> list[str]:
        """Return any required environment keys that are absent or blank.

        Best-effort check against the process environment. A skill may still be
        usable in a degraded mode when a requirement is missing (e.g. web_search
        falls back to DuckDuckGo without a Brave key) — that is the skill's call.
        """
        return [
            key
            for key in self.manifest.requires
            if not os.environ.get(key, "").strip()
        ]

    @abstractmethod
    def run(self, query: str, context: dict | None = None) -> SkillResult:
        """Execute the skill for ``query`` and return a SkillResult."""
        raise NotImplementedError


def discover_manifests(skills_dir: str | Path | None = None) -> list[SkillManifest]:
    """Find and load every ``manifest.json`` under ``skills_dir``.

    Args:
        skills_dir: Directory to scan (defaults to martin/skills/).
    """
    root = Path(skills_dir) if skills_dir else SKILLS_DIR
    manifests: list[SkillManifest] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifests.append(SkillManifest.from_file(manifest_path))
    return manifests
