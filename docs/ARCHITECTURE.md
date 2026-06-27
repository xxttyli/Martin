# Martin — Architecture

> Reflects the Phase 1 implementation as built. See [PRD.md](PRD.md) for product
> scope and [MARTIN_BRIEFING.md](../MARTIN_BRIEFING.md) for the originating vision.

## Guiding principle

**Own your architecture; leverage other people's hard work.** Martin depends only on
libraries that do one thing and stay out of the way (tools), never on libraries that
shape the whole system (frameworks). Every third-party tool here could be replaced
without rewriting Martin.

| Tool | Role | Isolated to | Replace cost |
|---|---|---|---|
| Ollama | Local model server (GPU) | config (URL/model strings) | Low — REST API |
| LiteLLM | Model abstraction | `core/brain.py` | ~40 lines |
| Instructor | Structured LLM output | `core/brain.py` | call-site only |
| ChromaDB | Vector memory | `core/memory.py` | Low |
| Faster-Whisper | Speech-to-text | `interfaces/voice.py` | drop-in |
| pydantic-settings | Typed config | `core/config.py` | Low |

## Component map

```
                    ┌─────────────────────────────────────────────┐
   speech ──STT──▶  │                interfaces                    │
   (voice.py)       │   cli.py  /  voice.py   (thin front-ends)    │
   text ──────────▶ │                  │                           │
                    └──────────────────┼───────────────────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │   Martin pipeline        │  (cli.Martin)
                          │   route → act → remember │
                          └───┬─────────┬─────────┬──┘
                  ┌───────────┘         │         └───────────┐
                  ▼                     ▼                     ▼
            core/router.py        core/brain.py         core/memory.py
            (skill choice)     (LiteLLM+Instructor)   (ChromaDB, embedded)
                  │                     │                     │
                  ▼                     ▼                     ▼
            skills/* (manifest)     Ollama models       ./data/chroma
            e.g. web_search

                  core/config.py  ── typed settings feeding everything
```

## The pipeline (one turn)

`Martin.handle(utterance)` in [martin/interfaces/cli.py](../martin/interfaces/cli.py):

1. **Route** — `Router.route()` decides which skill handles it:
   - *Trigger fast-path*: word-boundary match against manifest triggers (so
     "search" ≠ "research") → instant route.
   - *Model selection*: otherwise the **fast model** picks the best skill from the
     manifest catalog (via Instructor-typed `RouteDecision`), or `none`.
   - *Fallback*: no match → plain conversation.
2. **Act**:
   - *Skill path*: run the selected skill → `SkillResult.content`.
   - *Conversation path*: `Brain.chat()` with the system prompt plus any relevant
     facts recalled from memory.
3. **Remember** — `Memory.consider(utterance)` asks the fast model whether the
   utterance is high-signal and, if so, stores it tagged to a pillar. Failures here
   are swallowed so a turn never breaks.

Both interfaces (CLI, voice) call the *same* `Martin.handle`; voice merely turns
speech into the text that goes in.

## Core modules

### `core/config.py`
`pydantic-settings` `Settings` loaded from env/`.env`, the single source of truth.
Field names map case-insensitively to env vars (`DEFAULT_MODEL` → `default_model`).
Pillars are a comma-separated string exposed as a parsed list. `get_settings()` is a
cached singleton. Nothing else reads `os.environ` for configuration.

### `core/brain.py`
The only module that imports LiteLLM/Instructor.
- `chat(messages) -> str` — free-text completion (default = brain model).
- `structured(messages, response_model) -> BaseModel` — Instructor-validated typed
  output in **JSON mode** (most compatible with local Ollama models). Routing and
  memory classification pass the **fast model** here to keep the main model free.

### `core/memory.py`
Embedded ChromaDB (`PersistentClient` → `./data/chroma`); the only module that imports
chromadb.
- `remember(text, pillar)` — explicit store (validates the pillar).
- `consider(utterance)` — LLM-judged high-signal storage; chitchat returns `None`.
- `recall(query, pillars=None, n=5)` — semantic search, optional pillar filter,
  returns `Recollection` objects.

To move to a networked Chroma later, change the client construction here from
`PersistentClient` to `HttpClient`; no other file changes.

### `core/router.py`
Owned orchestration (no LangChain/n8n). Loads manifests, applies trigger fast-path
then model selection, guards against hallucinated skill names, returns a `Route`
(`skill` + `via`).

### `skills/`
- `_base.py`: `SkillManifest` (typed `manifest.json`), `SkillResult` (standard return
  shape), `BaseSkill` (ABC with `run()`), `discover_manifests()` and `load_skills()`
  (dynamic discovery + instantiation). Each skill module exposes a
  `load(brain, settings)` factory.
- `web_search/`: Brave Search API primary, DuckDuckGo fallback, honest `success=False`
  when both are down. Adding a skill = drop a folder with `skill.py` + `manifest.json`;
  no core changes.

### `interfaces/`
- `cli.py`: the `Martin` pipeline class (injectable, testable) + the REPL.
- `voice.py`: `WhisperTranscriber` (lazy Faster-Whisper) + `VoiceInterface`
  (push-to-talk capture → transcribe → `Martin.handle`). All heavy deps imported
  lazily so the module loads without the optional voice stack.

## Data & process model
- **Single process**, native Windows. Ollama runs as a native service; Martin talks to
  it over HTTP via LiteLLM.
- **Memory** persists to `./data/chroma` (gitignored). Embedded → no container needed.
- **Open WebUI** (optional) runs in Docker and reaches native Ollama via
  `host.docker.internal` for phone access on the LAN.

## Models
- **Brain (default):** `ollama/qwen3:14b` — fits comfortably on the RTX 4060 Ti (16GB).
- **Fast model:** `ollama/mistral:7b` — routing + memory classification, keeping the
  brain free. Both are config strings; swap freely.

## Testing strategy
Behavior-driven and **fully offline**:
- LLM calls mocked (`FakeBrain`) — we test structure/intent, not wording.
- ChromaDB exercised for real but with a deterministic in-test embedding function and
  per-test `tmp_path` isolation (its `EphemeralClient` is a process-wide singleton, so
  we use `PersistentClient` on unique paths).
- Network mocked for web search.
- A separate `live`-marked test does a real Ollama round-trip and auto-skips when
  Ollama isn't reachable or the model isn't pulled.

## Extension points (designed-in)
- **New skill:** drop a folder under `skills/`. Router and CLI pick it up via manifest.
- **New pillar:** add a tag to `PILLARS` in `.env`. No schema change.
- **New model/provider:** change config strings; `brain.py` is provider-agnostic.
- **Networked memory:** swap `PersistentClient` → `HttpClient` in `memory.py`.
- **Spoken replies (TTS):** add an output stage in `voice.py`; the pipeline is unchanged.
