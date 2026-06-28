"""Tests for martin.core.memory.

We exercise the REAL ChromaDB store/retrieve path, but with:
  - a PersistentClient on a per-test tmp_path (full isolation; Chroma's
    EphemeralClient is a process-wide singleton and would leak state), and
  - a tiny deterministic embedding function (no model download, no network).

The LLM judgment used by consider() is supplied by a FakeBrain so tests are
deterministic. We assert behavior (stored? right pillar? retrievable? chitchat
dropped?), never exact LLM wording.
"""

from __future__ import annotations

import chromadb
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from martin.core.config import Settings
from martin.core.memory import Memory, MemoryJudgment


class HashingEmbedding(EmbeddingFunction):
    """Deterministic bag-of-words embedding: identical text -> identical vector.

    Good enough for nearest-neighbour retrieval in tests, with zero downloads.
    """

    def __init__(self) -> None:  # silences chromadb deprecation warning
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vec = [0.0] * 64
            for word in text.lower().split():
                vec[hash(word) % 64] += 1.0
            vectors.append(vec)
        return vectors

    @staticmethod
    def name() -> str:
        return "hashing_test_ef"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashingEmbedding":
        return HashingEmbedding()


class FakeBrain:
    """Stand-in Brain whose structured() returns a preset MemoryJudgment."""

    def __init__(self, judgment: MemoryJudgment) -> None:
        self.judgment = judgment
        self.calls: list[dict] = []

    def structured(self, messages, response_model, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.judgment


@pytest.fixture
def settings():
    return Settings(_env_file=None)  # pillars: business, personal, automation


def make_memory(settings, tmp_path, brain=None):
    """Memory backed by an isolated Chroma store + offline embeddings.

    Each test gets its own ``tmp_path``, which yields a distinct PersistentClient
    (Chroma caches clients by path) and therefore full isolation. (EphemeralClient
    is a process-wide singleton and would leak state across tests.)
    """
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    return Memory(
        brain=brain,
        settings=settings,
        client=client,
        embedding_function=HashingEmbedding(),
    )


# ── remember / recall ───────────────────────────────────────────────────────
def test_remember_then_recall_roundtrip(settings, tmp_path):
    mem = make_memory(settings, tmp_path)
    mem.remember("I publish videos on Tuesdays", pillar="business")

    results = mem.recall("When do I publish videos on Tuesdays?")
    assert results, "expected at least one recollection"
    top = results[0]
    assert "Tuesdays" in top.text
    assert top.pillar == "business"
    assert top.metadata.get("pillar") == "business"
    assert "stored_at" in top.metadata


def test_remember_rejects_unknown_pillar(settings, tmp_path):
    mem = make_memory(settings, tmp_path)
    with pytest.raises(ValueError):
        mem.remember("something", pillar="not_a_pillar")


def test_remember_rejects_empty_text(settings, tmp_path):
    mem = make_memory(settings, tmp_path)
    with pytest.raises(ValueError):
        mem.remember("   ", pillar="personal")


# ── consider (inferred storage) ─────────────────────────────────────────────
def test_consider_stores_high_signal_fact(settings, tmp_path):
    brain = FakeBrain(
        MemoryJudgment(
            worth_storing=True,
            pillar="business",
            fact="The user publishes videos on Tuesdays.",
        )
    )
    mem = make_memory(settings, tmp_path, brain=brain)

    mem_id = mem.consider("From now on I'm publishing my videos on Tuesdays")
    assert mem_id is not None

    results = mem.recall("publishing schedule")
    assert any("Tuesdays" in r.text for r in results)
    # Inferred memories are flagged as such.
    stored = next(r for r in results if "Tuesdays" in r.text)
    assert stored.metadata.get("inferred") is True
    # consider() used the fast model.
    assert brain.calls[0]["model"] == settings.fast_model


def test_consider_drops_chitchat(settings, tmp_path):
    brain = FakeBrain(
        MemoryJudgment(worth_storing=False, pillar="personal", fact="")
    )
    mem = make_memory(settings, tmp_path, brain=brain)

    assert mem.consider("haha that's funny") is None
    assert mem.recall("anything") == []


def test_consider_coerces_invalid_pillar(settings, tmp_path):
    brain = FakeBrain(
        MemoryJudgment(
            worth_storing=True,
            pillar="nonsense",  # model returned a pillar outside the allowed set
            fact="The user prefers dark roast coffee.",
        )
    )
    mem = make_memory(settings, tmp_path, brain=brain)
    mem.consider("I really only drink dark roast")

    results = mem.recall("coffee preference")
    assert results
    # Coerced to the first configured pillar rather than stored invalid.
    assert results[0].pillar in settings.pillars


def test_consider_without_brain_raises(settings, tmp_path):
    mem = make_memory(settings, tmp_path, brain=None)
    with pytest.raises(RuntimeError):
        mem.consider("anything")


def test_consider_prompt_includes_pillar_definitions(settings, tmp_path):
    # The classifier should be told what each pillar means, so it tags correctly.
    brain = FakeBrain(
        MemoryJudgment(worth_storing=True, pillar="business", fact="A fact.")
    )
    mem = make_memory(settings, tmp_path, brain=brain)
    mem.consider("I'm launching a paid course")

    system_msg = brain.calls[0]["messages"][0]["content"]
    assert "business:" in system_msg
    assert "content creation" in system_msg  # the business hint
    assert "personal:" in system_msg


def test_consider_surfaces_existing_memories_for_dedup(settings, tmp_path):
    # Pre-store a fact, then consider a related utterance: the existing memory
    # must be shown to the model so it can avoid storing a duplicate.
    brain = FakeBrain(
        MemoryJudgment(worth_storing=False, pillar="business", fact="")
    )
    mem = make_memory(settings, tmp_path, brain=brain)
    mem.remember("The user publishes videos on Tuesdays", pillar="business")

    result = mem.consider("I publish videos on Tuesdays")

    # Model judged it already-known -> nothing new stored.
    assert result is None
    system_msg = brain.calls[0]["messages"][0]["content"]
    assert "publishes videos on Tuesdays" in system_msg
    assert "duplicate" in system_msg.lower()


# ── pillar-filtered recall ──────────────────────────────────────────────────
def test_recall_filters_by_pillar(settings, tmp_path):
    mem = make_memory(settings, tmp_path)
    mem.remember("Launch the course in March", pillar="business")
    mem.remember("Dentist appointment next week", pillar="personal")

    business_only = mem.recall("plans", pillars=["business"], n=10)
    assert business_only
    assert all(r.pillar == "business" for r in business_only)
