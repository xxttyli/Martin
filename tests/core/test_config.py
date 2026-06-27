"""Tests for martin.core.config.

These verify behavior, not specific copy: defaults apply, env overrides win,
pillars parse from a comma-separated string, and the Brave helper reflects
whether a key is present. We pass ``_env_file=None`` to isolate from any real
``.env`` on the machine.
"""

from pathlib import Path

import pytest

from martin.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_apply_when_env_empty(monkeypatch):
    # Strip any Martin-related env so defaults are exercised.
    for key in ("DEFAULT_MODEL", "FAST_MODEL", "OLLAMA_BASE_URL", "BRAVE_API_KEY",
                "CHROMA_DIR", "PILLARS"):
        monkeypatch.delenv(key, raising=False)

    s = Settings(_env_file=None)

    assert s.default_model == "ollama/qwen3:14b"
    assert s.fast_model == "ollama/mistral:7b"
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.chroma_dir == Path("./data/chroma")
    assert s.pillars == ["business", "personal", "automation"]


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "ollama/llama3:8b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.50:11434")

    s = Settings(_env_file=None)

    assert s.default_model == "ollama/llama3:8b"
    assert s.ollama_base_url == "http://192.168.1.50:11434"


def test_pillars_parse_from_comma_string(monkeypatch):
    monkeypatch.setenv("PILLARS", "business, personal , automation,content")
    s = Settings(_env_file=None)
    # Whitespace trimmed, order preserved, extensible.
    assert s.pillars == ["business", "personal", "automation", "content"]


def test_pillars_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv("PILLARS", "business,,personal,")
    s = Settings(_env_file=None)
    assert s.pillars == ["business", "personal"]


def test_brave_helper_reflects_key_presence(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert Settings(_env_file=None).has_brave is False

    # Empty string (as in .env.example) counts as "no key".
    monkeypatch.setenv("BRAVE_API_KEY", "")
    assert Settings(_env_file=None).has_brave is False

    monkeypatch.setenv("BRAVE_API_KEY", "BSA-secret")
    s = Settings(_env_file=None)
    assert s.has_brave is True
    assert s.brave_api_key == "BSA-secret"


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "ollama/first")
    first = get_settings()
    # Changing env afterwards should NOT change the cached instance.
    monkeypatch.setenv("DEFAULT_MODEL", "ollama/second")
    second = get_settings()
    assert first is second
    assert second.default_model == "ollama/first"
