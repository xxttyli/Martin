# Martin — Product Requirements Document

> Status: **Phase 1 complete.** This PRD reflects what was actually built, not a
> forward-looking spec. See [MARTIN_BRIEFING.md](../MARTIN_BRIEFING.md) for the
> originating vision and [ARCHITECTURE.md](ARCHITECTURE.md) for the technical design.

## 1. What Martin is

Martin is a personal AI platform for a solo creator — local-first, modular, and
voice-capable. It is explicitly **not** a chatbot wrapper: it is a system the owner
controls, built to grow into a content-creation and publishing platform.

Three organizational **pillars** shape how memory is tagged and skills are grouped
(they are categories, not walls):

1. **Business & AI/Tech** — content, research, publishing, brand-building
2. **Daily assistant** — calendar, weather, reminders, personal context
3. **PC automation** — terminal, files, app control, code execution

## 2. Phase 1 goal (delivered)

> A working Martin you can talk to, that remembers things, and can search the web.

Delivered capabilities:

| Capability | Status | Where |
|---|---|---|
| Model-agnostic brain (Ollama via LiteLLM) | ✅ | [martin/core/brain.py](../martin/core/brain.py) |
| Structured/typed LLM outputs (Instructor) | ✅ | [martin/core/brain.py](../martin/core/brain.py) |
| Persistent, pillar-tagged memory (ChromaDB, embedded) | ✅ | [martin/core/memory.py](../martin/core/memory.py) |
| Auto-inference of high-signal facts (chitchat dropped) | ✅ | `Memory.consider` |
| Typed configuration from `.env` | ✅ | [martin/core/config.py](../martin/core/config.py) |
| Lightweight, owned task router | ✅ | [martin/core/router.py](../martin/core/router.py) |
| Skill system (manifest-discovered) | ✅ | [martin/skills/_base.py](../martin/skills/_base.py) |
| Web search (Brave → DuckDuckGo, honest failure) | ✅ | [martin/skills/web_search/](../martin/skills/web_search/) |
| CLI text interface (full pipeline) | ✅ | [martin/interfaces/cli.py](../martin/interfaces/cli.py) |
| Voice input — push-to-talk STT | ✅ | [martin/interfaces/voice.py](../martin/interfaces/voice.py) |
| Open WebUI for phone access (Docker) | ✅ (infra) | [docker-compose.yml](../docker-compose.yml) |
| Behavior-driven test suite | ✅ | 46 tests, offline |

### Phase 1 decisions that adapted the briefing
- **Native Windows**, not WSL2. Ollama is native; only Open WebUI needs Docker.
- **ChromaDB runs embedded** (`PersistentClient`), not in a container — memory works
  with Docker off. Swapping to a Chroma server later is a one-line change in
  `memory.py`.
- **Voice is speech-to-text only** in Phase 1; spoken replies (TTS) are deferred.
  Voice deps are an optional install so the core never depends on the GPU/audio
  stack.

## 3. Behavior requirements (and how they're met)

- **Conversation:** Replies are concise and grounded in relevant remembered facts,
  which the pipeline injects into the system prompt.
- **Memory honesty & signal:** Only durable, high-signal statements (decisions,
  preferences, goals, recurring facts) are stored; trivia and chitchat are dropped.
  Memories are tagged to a pillar and are retrievable by semantic search, optionally
  filtered by pillar.
- **Web search honesty:** Brave is used when a key is configured, otherwise
  DuckDuckGo. If **both** providers are unavailable, Martin says so plainly and never
  fabricates an answer.
- **Routing:** A trigger-word fast path handles obvious cases instantly; otherwise the
  fast model selects the best skill, with a conversational fallback. Invented skill
  names are rejected.
- **Resilience:** A memory hiccup never breaks a turn; the CLI survives runtime errors
  and keeps the session alive.

## 4. Non-goals (Phase 1)
- No spoken replies (TTS), no wake word, no always-on mic.
- No PC-automation, calendar, or weather skills yet (Phase 2).
- No content pipelines or sub-agents yet (Phase 3).
- No remote access beyond the local network (Tailscale is Phase 2).

## 5. Quality bar
- Behavior-driven tests only — we assert that the right thing happened (correct skill
  chosen, fact stored and retrievable, honest failure), never exact LLM wording.
- The full suite runs **offline** (no model, network, or downloads): the LLM is mocked,
  ChromaDB uses a deterministic in-test embedding, and the live Ollama round-trip is a
  separate `live`-marked test that auto-skips when Ollama isn't running.

## 6. What's next (Phase 2 candidates)
- PC-automation skills (shell, files, app control), calendar + weather skills.
- Spoken replies (Piper TTS) and optional wake word.
- Tailscale for remote/phone access outside the home network.
- Memory viewer + explicit save/forget commands.
