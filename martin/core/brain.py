"""Martin's brain — the model-agnostic interface to the LLM.

This is the ONLY module in Martin that knows LiteLLM and Instructor exist.

- LiteLLM normalizes every model provider (Ollama, Anthropic, OpenAI, ...) behind
  one ``completion`` call. Swapping the underlying model is a config change, not a
  code change.
- Instructor wraps that call to guarantee typed, validated output (a pydantic
  model) instead of fragile free-text parsing. Used wherever Martin needs a
  predictable shape: intent routing, memory classification.

Both are tools, not frameworks: this whole file could be replaced by ~40 lines of
custom HTTP code without touching anything else in Martin.

Two methods:
- ``chat(messages)``      -> free-text string (conversation, summaries, answers)
- ``structured(...)``     -> a populated pydantic model (routing, classification)
"""

from __future__ import annotations

from typing import TypeVar

import instructor
import litellm
from pydantic import BaseModel

from martin.core.config import Settings, get_settings

# A chat message is the standard {"role": ..., "content": ...} dict.
Message = dict[str, str]

T = TypeVar("T", bound=BaseModel)


class Brain:
    """Model-agnostic LLM interface backed by LiteLLM + Instructor.

    Args:
        settings: Optional Settings override (defaults to the process singleton).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # JSON mode is the most compatible Instructor strategy for local Ollama
        # models (tool/function-calling support varies by model).
        self._structured_client = instructor.from_litellm(
            litellm.completion, mode=instructor.Mode.JSON
        )

    # ── Free-text completion ────────────────────────────────────────────────
    def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Return a free-text reply for a list of chat messages.

        Args:
            messages: Standard role/content message dicts.
            model: LiteLLM model string; defaults to the configured brain model.
            temperature: Sampling temperature.
        """
        response = litellm.completion(
            model=model or self.settings.default_model,
            messages=messages,
            api_base=self.settings.ollama_base_url,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    # ── Structured (typed) completion ───────────────────────────────────────
    def structured(
        self,
        messages: list[Message],
        response_model: type[T],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 2,
    ) -> T:
        """Return a populated instance of ``response_model``.

        Instructor coerces and validates the model's output into the given
        pydantic type, retrying on validation failure.

        Args:
            messages: Standard role/content message dicts.
            response_model: The pydantic type to return.
            model: LiteLLM model string; callers that want cheap classification
                should pass ``settings.fast_model``. Defaults to the brain model.
            temperature: Sampling temperature (0.0 for deterministic structure).
            max_retries: How many times Instructor may re-ask on a bad parse.
        """
        return self._structured_client.chat.completions.create(
            model=model or self.settings.default_model,
            messages=messages,
            response_model=response_model,
            api_base=self.settings.ollama_base_url,
            temperature=temperature,
            max_retries=max_retries,
        )
