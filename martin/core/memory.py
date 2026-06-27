"""Martin's memory — persistent, pillar-tagged recollection.

Backed by ChromaDB running *embedded* (an in-process library writing to a local
folder), so memory works even with Docker Desktop closed. This module is the ONLY
place that knows ChromaDB exists: to move to a networked Chroma server later,
change the client construction here from ``PersistentClient`` to ``HttpClient`` —
nothing else in Martin changes.

Three operations:
- ``remember(text, pillar)``  — explicitly store a fact ("Martin, remember that…").
- ``consider(utterance)``     — let the model judge whether an utterance is
                                high-signal (a decision, preference, goal, recurring
                                fact) and, if so, store it tagged to a pillar.
                                Trivial chitchat is dropped.
- ``recall(query, pillars)``  — semantic search, optionally filtered by pillar(s).

Memories are tagged with a "pillar" (business / personal / automation, extensible
via config) so retrieval can be scoped, while a single unified store keeps
cross-pillar queries natural.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from martin.core.brain import Brain
from martin.core.config import Settings, get_settings

COLLECTION_NAME = "martin_memory"


@dataclass
class Recollection:
    """A single retrieved memory."""

    text: str
    pillar: str
    metadata: dict[str, Any]
    distance: float | None = None


class MemoryJudgment(BaseModel):
    """The model's decision about whether an utterance is worth remembering."""

    worth_storing: bool = Field(
        description="True only for durable, high-signal info: decisions, "
        "preferences, goals, plans, or recurring personal/business facts. "
        "False for chitchat, questions, and one-off trivia."
    )
    pillar: str = Field(
        description="Which pillar this belongs to. Must be one of the allowed pillars."
    )
    fact: str = Field(
        description="A concise, self-contained statement of the fact to store, "
        "rewritten in third person if helpful. Empty if not worth storing."
    )


class Memory:
    """Pillar-tagged vector memory over an embedded ChromaDB store.

    Args:
        brain: Brain used by ``consider()`` to classify utterances. Optional if
            you only call ``remember``/``recall``.
        settings: Settings override (defaults to the process singleton).
        client: Optional pre-built Chroma client (tests inject an ephemeral one).
        embedding_function: Optional Chroma embedding function override.
    """

    def __init__(
        self,
        brain: Brain | None = None,
        settings: Settings | None = None,
        client: Any | None = None,
        embedding_function: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.brain = brain

        if client is None:
            import chromadb  # imported lazily so importing this module stays cheap

            self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))

        # Pass embedding_function only when provided, so Chroma's sensible default
        # (a local MiniLM model) is used otherwise.
        kwargs = {"name": COLLECTION_NAME}
        if embedding_function is not None:
            kwargs["embedding_function"] = embedding_function
        self._collection = client.get_or_create_collection(**kwargs)

    # ── Explicit store ──────────────────────────────────────────────────────
    def remember(
        self,
        text: str,
        pillar: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store ``text`` tagged to ``pillar``; return the new memory id.

        Raises:
            ValueError: if ``pillar`` is not one of the configured pillars or
                ``text`` is empty.
        """
        text = text.strip()
        if not text:
            raise ValueError("Cannot remember empty text.")
        if pillar not in self.settings.pillars:
            raise ValueError(
                f"Unknown pillar {pillar!r}. Configured: {self.settings.pillars}"
            )

        mem_id = str(uuid.uuid4())
        meta: dict[str, Any] = {
            "pillar": pillar,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            meta.update(metadata)

        self._collection.add(ids=[mem_id], documents=[text], metadatas=[meta])
        return mem_id

    # ── Inferred store ──────────────────────────────────────────────────────
    def consider(self, utterance: str) -> str | None:
        """Judge whether ``utterance`` is worth storing; store it if so.

        Returns the stored memory id, or None if nothing was stored.

        Requires a Brain (raises if none was provided).
        """
        if self.brain is None:
            raise RuntimeError("Memory.consider() requires a Brain.")
        utterance = utterance.strip()
        if not utterance:
            return None

        pillars = self.settings.pillars
        judgment = self.brain.structured(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You decide what a personal assistant should remember "
                        "long-term. Store only durable, high-signal information: "
                        "decisions, preferences, goals, plans, and recurring "
                        "personal or business facts. Do NOT store questions, "
                        "greetings, or one-off chitchat. "
                        f"Allowed pillars: {', '.join(pillars)}."
                    ),
                },
                {"role": "user", "content": utterance},
            ],
            response_model=MemoryJudgment,
            model=self.settings.fast_model,
        )

        if not judgment.worth_storing or not judgment.fact.strip():
            return None

        # Defend against the model returning a pillar outside the allowed set.
        pillar = judgment.pillar if judgment.pillar in pillars else pillars[0]
        return self.remember(judgment.fact, pillar, metadata={"inferred": True})

    # ── Retrieval ───────────────────────────────────────────────────────────
    def recall(
        self,
        query: str,
        pillars: list[str] | None = None,
        n: int = 5,
    ) -> list[Recollection]:
        """Return up to ``n`` memories most relevant to ``query``.

        Args:
            query: The text to search for.
            pillars: Optional list to restrict results to certain pillars.
            n: Maximum number of results.
        """
        where = None
        if pillars:
            where = {"pillar": {"$in": pillars}} if len(pillars) > 1 else {
                "pillar": pillars[0]
            }

        result = self._collection.query(
            query_texts=[query],
            n_results=n,
            where=where,
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        recollections: list[Recollection] = []
        for i, text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            distance = distances[i] if i < len(distances) else None
            recollections.append(
                Recollection(
                    text=text,
                    pillar=meta.get("pillar", ""),
                    metadata=meta,
                    distance=distance,
                )
            )
        return recollections
