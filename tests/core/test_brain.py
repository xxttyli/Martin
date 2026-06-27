"""Tests for martin.core.brain.

We don't call a real model here (that's the live smoke test). We verify the
contract: chat() returns the model's text and forwards the right model/api_base;
structured() returns the requested pydantic type. The LLM calls are mocked.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from martin.core.brain import Brain
from martin.core.config import Settings


@pytest.fixture
def settings():
    # Use field-name kwargs (pydantic-settings ignores uppercase env-style kwargs).
    return Settings(
        _env_file=None,
        default_model="ollama/qwen3:14b",
        fast_model="ollama/mistral:7b",
        ollama_base_url="http://localhost:11434",
    )


def _fake_completion(content: str):
    """Build a minimal stand-in for a LiteLLM completion response."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_chat_returns_text_and_uses_default_model(settings, mocker):
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_completion("hello from Martin")

    mocker.patch("martin.core.brain.litellm.completion", side_effect=fake)

    brain = Brain(settings)
    out = brain.chat([{"role": "user", "content": "hi"}])

    assert out == "hello from Martin"
    assert captured["model"] == "ollama/qwen3:14b"
    assert captured["api_base"] == "http://localhost:11434"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_accepts_model_override(settings, mocker):
    captured = {}
    mocker.patch(
        "martin.core.brain.litellm.completion",
        side_effect=lambda **kw: captured.update(kw) or _fake_completion("ok"),
    )

    Brain(settings).chat([{"role": "user", "content": "x"}], model="ollama/llama3")
    assert captured["model"] == "ollama/llama3"


def test_chat_handles_none_content(settings, mocker):
    mocker.patch(
        "martin.core.brain.litellm.completion",
        return_value=_fake_completion(None),
    )
    assert Brain(settings).chat([{"role": "user", "content": "x"}]) == ""


class _Intent(BaseModel):
    skill: str
    confidence: float


def test_structured_returns_requested_type(settings, mocker):
    brain = Brain(settings)

    # Patch the instructor-wrapped client to return a populated model.
    create = mocker.patch.object(
        brain._structured_client.chat.completions,
        "create",
        return_value=_Intent(skill="web_search", confidence=0.9),
    )

    result = brain.structured(
        [{"role": "user", "content": "search the web for X"}],
        response_model=_Intent,
        model=settings.fast_model,
    )

    assert isinstance(result, _Intent)
    assert result.skill == "web_search"
    # The fast model and response_model were forwarded to instructor.
    _, kwargs = create.call_args
    assert kwargs["model"] == "ollama/mistral:7b"
    assert kwargs["response_model"] is _Intent
