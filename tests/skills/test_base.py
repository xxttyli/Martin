"""Tests for martin.skills._base — manifest parsing, discovery, BaseSkill."""

from __future__ import annotations

import json

import pytest

from martin.core.config import Settings
from martin.skills._base import (
    BaseSkill,
    SkillManifest,
    SkillResult,
    discover_manifests,
)


def _write_manifest(folder, **overrides):
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "name": folder.name,
        "description": "A test skill",
        "pillar": ["business"],
        "triggers": ["test"],
        "requires": [],
        "phase": 1,
    }
    data.update(overrides)
    (folder / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return folder / "manifest.json"


def test_manifest_from_file_parses(tmp_path):
    path = _write_manifest(
        tmp_path / "web_search",
        name="web_search",
        triggers=["search", "look up"],
        requires=["BRAVE_API_KEY"],
    )
    m = SkillManifest.from_file(path)
    assert m.name == "web_search"
    assert "look up" in m.triggers
    assert m.requires == ["BRAVE_API_KEY"]
    assert m.phase == 1


def test_manifest_applies_sensible_defaults(tmp_path):
    # Minimal manifest with only required-ish fields.
    folder = tmp_path / "minimal"
    folder.mkdir()
    (folder / "manifest.json").write_text(
        json.dumps({"name": "minimal", "description": "x"}), encoding="utf-8"
    )
    m = SkillManifest.from_file(folder / "manifest.json")
    assert m.pillar == [] and m.triggers == [] and m.requires == []
    assert m.phase == 1


def test_discover_manifests_finds_all(tmp_path):
    _write_manifest(tmp_path / "alpha")
    _write_manifest(tmp_path / "beta")
    # A folder without a manifest is ignored.
    (tmp_path / "not_a_skill").mkdir()

    found = {m.name for m in discover_manifests(tmp_path)}
    assert found == {"alpha", "beta"}


# ── BaseSkill ───────────────────────────────────────────────────────────────
class _EchoSkill(BaseSkill):
    def run(self, query, context=None):
        return SkillResult(content=f"echo: {query}", source="echo")


def _manifest(**overrides):
    base = {"name": "echo", "description": "echoes", "requires": []}
    base.update(overrides)
    return SkillManifest.model_validate(base)


def test_skill_exposes_name_and_runs():
    skill = _EchoSkill(_manifest(), settings=Settings(_env_file=None))
    assert skill.name == "echo"
    result = skill.run("hello")
    assert isinstance(result, SkillResult)
    assert result.content == "echo: hello"
    assert result.success is True
    assert result.source == "echo"


def test_missing_requirements_reflects_env(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    skill = _EchoSkill(_manifest(requires=["SOME_KEY"]), settings=Settings(_env_file=None))
    assert skill.missing_requirements() == ["SOME_KEY"]

    monkeypatch.setenv("SOME_KEY", "value")
    assert skill.missing_requirements() == []


def test_base_skill_is_abstract():
    with pytest.raises(TypeError):
        BaseSkill(_manifest())  # type: ignore[abstract]
