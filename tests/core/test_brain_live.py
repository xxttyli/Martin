"""Live smoke test: Ollama + LiteLLM + Instructor working together for real.

This is the briefing's step-8 gate ("Verify Ollama + LiteLLM + Instructor work
together before touching anything else"). It makes a real round-trip to a local
Ollama server.

It is marked ``live`` and SKIPS automatically when:
  - Ollama is not reachable at OLLAMA_BASE_URL, or
  - the configured model has not been pulled yet.

So it never breaks the normal `pytest` run on a machine without Ollama.

Run explicitly with:  pytest -m live
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel, Field

from martin.core.brain import Brain
from martin.core.config import get_settings

pytestmark = pytest.mark.live


def _installed_models(base_url: str) -> list[str] | None:
    """Return installed Ollama model tags, or None if the server is unreachable."""
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
    except Exception:
        return None
    return [m["name"] for m in resp.json().get("models", [])]


def _require_model(model_string: str) -> str:
    """Skip unless the given LiteLLM 'ollama/<tag>' model is installed."""
    settings = get_settings()
    installed = _installed_models(settings.ollama_base_url)
    if installed is None:
        pytest.skip(f"Ollama not reachable at {settings.ollama_base_url}")

    tag = model_string.split("/", 1)[-1]  # "ollama/qwen3:14b" -> "qwen3:14b"
    # Ollama may report "qwen3:14b" or default ":latest"; match leniently.
    if not any(t == tag or t.startswith(tag.split(":")[0]) for t in installed):
        pytest.skip(f"Model '{tag}' not pulled. Have: {installed}")
    return model_string


def test_live_chat_returns_text():
    settings = get_settings()
    model = _require_model(settings.fast_model)

    reply = Brain(settings).chat(
        [{"role": "user", "content": "Reply with the single word: pong"}],
        model=model,
    )
    assert isinstance(reply, str) and reply.strip(), "expected non-empty text"


class _City(BaseModel):
    name: str = Field(description="The city name only")
    country: str = Field(description="The country the city is in")


def test_live_structured_returns_typed_object():
    settings = get_settings()
    model = _require_model(settings.fast_model)

    result = Brain(settings).structured(
        [{"role": "user", "content": "Extract the city: 'I live in Paris, France.'"}],
        response_model=_City,
        model=model,
    )
    assert isinstance(result, _City)
    assert result.name and result.country
