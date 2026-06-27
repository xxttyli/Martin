"""Tests for the web_search skill.

Network is fully mocked. We verify behavior: Brave is used when a key exists,
DuckDuckGo is the fallback, both-down fails honestly (no confabulation), and the
skill loads from its own manifest.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from martin.core.config import Settings
from martin.skills.web_search.skill import WebSearchSkill, load


def make_skill(with_brave: bool):
    # Field-name kwargs override env/defaults (uppercase env-style kwargs are
    # ignored by pydantic-settings). "" disables Brave regardless of environment.
    settings = Settings(
        _env_file=None,
        brave_api_key="brave-key" if with_brave else "",
    )
    return load(settings=settings)


def fake_brave_response(payload):
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
    )


class FakeDDGS:
    """Context-manager stand-in for ddgs.DDGS."""

    results = [
        {"title": "DDG Result", "href": "http://ddg.example", "body": "ddg snippet"}
    ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, max_results=5):
        return self.results


# ── Brave path ──────────────────────────────────────────────────────────────
def test_uses_brave_when_key_present(mocker):
    skill = make_skill(with_brave=True)
    payload = {
        "web": {
            "results": [
                {
                    "title": "GPU Prices 2026",
                    "url": "http://example.com/gpu",
                    "description": "Latest GPU pricing",
                }
            ]
        }
    }
    get = mocker.patch(
        "martin.skills.web_search.skill.httpx.get",
        return_value=fake_brave_response(payload),
    )

    result = skill.run("latest GPU prices")

    assert result.success is True
    assert result.source == "brave"
    assert "GPU Prices 2026" in result.content
    assert "http://example.com/gpu" in result.content
    # The Brave token header was sent.
    _, kwargs = get.call_args
    assert kwargs["headers"]["X-Subscription-Token"] == "brave-key"


# ── DuckDuckGo fallback ─────────────────────────────────────────────────────
def test_falls_back_to_ddg_without_key(mocker):
    skill = make_skill(with_brave=False)
    mocker.patch("ddgs.DDGS", FakeDDGS)
    # httpx.get should never be called when there's no Brave key.
    get = mocker.patch("martin.skills.web_search.skill.httpx.get")

    result = skill.run("who is Ada Lovelace")

    assert result.success is True
    assert result.source == "duckduckgo"
    assert "DDG Result" in result.content
    get.assert_not_called()


def test_ddg_used_when_brave_errors(mocker):
    skill = make_skill(with_brave=True)
    mocker.patch(
        "martin.skills.web_search.skill.httpx.get",
        side_effect=RuntimeError("brave 500"),
    )
    mocker.patch("ddgs.DDGS", FakeDDGS)

    result = skill.run("some query")

    assert result.success is True
    assert result.source == "duckduckgo"


# ── Honest failure ──────────────────────────────────────────────────────────
def test_both_providers_down_fails_honestly(mocker):
    skill = make_skill(with_brave=True)
    mocker.patch(
        "martin.skills.web_search.skill.httpx.get",
        side_effect=RuntimeError("brave down"),
    )

    class BrokenDDGS(FakeDDGS):
        def text(self, query, max_results=5):
            raise RuntimeError("ddg down")

    mocker.patch("ddgs.DDGS", BrokenDDGS)

    result = skill.run("anything")

    assert result.success is False
    assert "couldn't search" in result.content.lower()
    # Honest: it names that providers were unavailable, not a fake answer.
    assert "unavailable" in result.content.lower()


def test_empty_query_fails():
    skill = make_skill(with_brave=False)
    result = skill.run("   ")
    assert result.success is False


# ── Loader / manifest ───────────────────────────────────────────────────────
def test_load_builds_skill_from_manifest():
    skill = load(settings=Settings(_env_file=None))
    assert isinstance(skill, WebSearchSkill)
    assert skill.name == "web_search"
    assert "search" in skill.manifest.triggers
    assert skill.manifest.requires == ["BRAVE_API_KEY"]
