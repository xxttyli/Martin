# Martin — Personal AI Platform
## Claude Code Briefing Document

> This document captures all decisions made in the exploratory session prior to this Claude Code session. Read it fully before writing any code, creating any files, or asking clarifying questions. Everything here is decided. Where something is marked ⚠️ it means a decision is still open and Claude Code should raise it before proceeding.

---

## 1. What We're Building

**Martin** is a personal AI platform for a solo creator. It is not a chatbot wrapper. It is a modular, locally-run AI system with a voice interface, persistent memory, web awareness, and the ability to execute tasks and run sub-agents — designed to grow into a content creation and publishing platform over time.

The name is **Martin**. This is both the assistant's persona and the name of the codebase/repo.

### Core pillars (in priority order)
1. **Business & AI/Tech** — content creation, research, publishing, brand-building
2. **Daily assistant** — calendar, weather, reminders, personal context
3. **PC automation** — terminal commands, file management, app control, code execution

These pillars inform how memory is tagged and how skills are organized. They do not hard-limit what Martin can do — they are organizational categories, not walls.

---

## 2. Hardware & Environment

| Item | Detail |
|---|---|
| GPU | RTX 4060 Ti — **16GB VRAM** |
| RAM | 32GB system RAM |
| OS | Windows 11 |
| Target model tier | 13B–14B parameter models at Q4 quantization |
| Recommended default model | Qwen3 14B (Q4) via Ollama |
| Fallback / fast model | Mistral 7B (for low-latency tasks) |

The 4060 Ti 16GB comfortably fits a 13–14B model alongside Ollama's intent-judge model simultaneously. 32GB system RAM provides spill capacity if needed.

---

## 3. Architectural Decisions (All Decided)

### 3.1 Voice Interface
- **STT:** Faster-Whisper (local, runs on GPU)
- **TTS:** Piper (local, lightweight, good enough quality)
- **Trigger:** Push-to-talk hotkey (no always-on microphone)
- **No wake word in Phase 1** — hotkey only
- Phone access via Open WebUI browser interface (local network)

### 3.2 Brain
- **Model server:** Ollama — native Windows install (`.exe` installer), direct GPU access, no Docker passthrough complexity
- **Model abstraction:** LiteLLM — thin translation layer that normalizes all model provider APIs into one consistent interface. Martin's code calls LiteLLM; LiteLLM talks to Ollama, Anthropic, OpenAI, or any other provider. Swapping the underlying model requires zero code changes in Martin.
- **Structured outputs:** Instructor — wraps LiteLLM calls to guarantee the model returns typed, structured data (JSON, typed Python objects) reliably. Replaces fragile prompt engineering for any call where Martin needs a predictable output shape (intent parsing, memory classification, skill routing signals).
- **Chat UI / phone access:** Open WebUI — runs in Docker, accessible from phone browser on local network
- **Future remote access:** Tailscale VPN (Phase 2+)

#### Why LiteLLM and Instructor are tools, not frameworks
Both libraries do exactly one thing and stay completely out of everything else. LiteLLM sits only in `core/brain.py` — nothing else in Martin knows it exists. Instructor sits only at call sites where structured output is needed. Neither one shapes Martin's architecture. Both can be removed and replaced with ~40 lines of custom code at any time. This is the definition of leverage without lock-in.

### 3.3 Orchestration
- **No n8n or third-party orchestrators**
- Martin uses a **lightweight Python task router** we own completely
- The router receives parsed intent → selects skill(s) → executes → returns result
- This keeps zero external orchestration dependency and is fully testable
- Skills are self-contained modules discovered via manifests (see Section 5)

### 3.4 Memory
- **Backend:** ChromaDB — runs in Docker
- **Strategy:** Automatic inference of high-signal memories (decisions, preferences, goals, recurring context). Trivial chitchat is not stored.
- **Structure:** Single unified memory store, pillar-tagged per entry
- **Pillar tags:** `business`, `personal`, `automation` (extensible — adding a new pillar = new tag, not new database)
- **Retrieval:** Filtered by relevant pillar(s) at query time; cross-pillar queries supported naturally
- **Explicit saves:** User can also say "Martin, remember that..." to force-store something

### 3.5 Web Search
- Built-in skill, Phase 1
- Primary: Brave Search API (free tier: 2,000 queries/month) — requires API key in config
- Fallback: DuckDuckGo
- Martin never confabulates search failure — it reports honestly when search is unavailable

### 3.6 Infrastructure / Install strategy
| Service | Install method | Reason |
|---|---|---|
| Ollama | Native Windows `.exe` | Best GPU access, no passthrough needed |
| LiteLLM | `pip install litellm` | Model abstraction — one API for all providers |
| Instructor | `pip install instructor` | Structured outputs from any LLM reliably |
| ChromaDB | Docker | Clean isolation, stateless-ish |
| Open WebUI | Docker | Easy to run, easy to update |
| Martin (core code) | Python `venv`, native | Direct, debuggable, no container overhead |
| WSL2 | Required | Needed for Docker on Windows + Unix tooling |

### 3.7 Code & Repository
- **Language:** Python (primary) — best ecosystem for this stack
- **Repo:** GitHub, private
- **Environment:** WSL2 on Windows 11
- **Dependency management:** `pip` + `requirements.txt` to start; `pyproject.toml` if complexity warrants
- **Config:** All secrets, API keys, model names, and pillar definitions live in a `.env` file — never committed to git

---

## 4. Repository Structure

```
martin/
├── martin/
│   ├── core/
│   │   ├── brain.py          # LiteLLM client — model-agnostic brain interface
│   │   ├── memory.py         # ChromaDB read/write, pillar tagging
│   │   ├── router.py         # Intent → skill dispatcher
│   │   └── config.py         # Loads .env, exposes typed settings
│   ├── skills/
│   │   ├── _base.py          # Base skill class all skills inherit
│   │   ├── web_search/
│   │   ├── weather/
│   │   └── ...               # One folder per skill
│   └── interfaces/
│       ├── voice.py           # STT + TTS + push-to-talk loop
│       └── cli.py             # Text-mode interface for testing
├── tests/
│   ├── core/
│   ├── skills/
│   └── interfaces/
├── docs/
│   ├── PRD.md                 # To be written
│   ├── ARCHITECTURE.md        # To be written
│   └── skills/                # Per-skill sub-docs
├── docker-compose.yml         # ChromaDB + Open WebUI
├── .env.example               # Template — committed
├── .env                       # Real secrets — gitignored
├── requirements.txt
└── README.md
```

**Rules:**
- Never add a folder to `martin/` until a Phase explicitly calls for it
- `pipelines/` does not exist yet — it's Phase 3 thinking
- `docs/` grows as we build — PRD and ARCHITECTURE are written alongside code, not before everything is built

---

## 5. Skill System Design

Each skill is a self-contained module. Martin discovers skills at startup by reading manifests.

### Skill folder structure
```
skills/
└── web_search/
    ├── skill.py          # Logic
    ├── manifest.json     # Metadata
    └── test_skill.py     # Tests
```

### manifest.json schema
```json
{
  "name": "web_search",
  "description": "Search the web for current information",
  "pillar": ["business", "personal"],
  "triggers": ["search", "look up", "find", "what is", "who is"],
  "requires": ["BRAVE_API_KEY"],
  "phase": 1
}
```

Martin's router uses manifests for skill selection — adding a new skill means dropping in a folder, not editing core routing code.

---

## 6. Testing Philosophy

Martin uses **behavior-driven tests**, not output-exact tests. AI outputs are non-deterministic — we test structure and intent, not exact strings.

### What we test
- **Skills:** Given a known input, did the right tool get called? Did the response contain relevant content? Did it complete within latency threshold?
- **Memory:** Given a high-signal statement, was it stored? Was it tagged to the correct pillar? Is it retrievable?
- **Router:** Given an utterance, was the correct skill selected?
- **Voice pipeline:** Does STT → brain → TTS complete end-to-end? Latency within acceptable range?

### Test runner
- **pytest** — standard, well-supported, works well in WSL2
- One `test_*.py` per module, mirroring the source structure
- Tests run locally; CI can be added later via GitHub Actions

### What we don't test
- Exact LLM output wording
- Model quality / intelligence (that's a model selection concern, not a code concern)

---

## 7. Phasing

Claude Code determines the exact scope of each phase based on what's realistic. The following is directional, not a hard spec.

### Phase 1 — Solid Core
The goal is a working Martin you can actually talk to, that remembers things, and can search the web. Everything else is deferred.

Expected to include:
- Ollama running locally with Qwen3 14B
- Push-to-talk voice loop (Faster-Whisper in, Piper out)
- ChromaDB memory with pillar tagging and auto-inference of high-signal facts
- Web search skill (Brave + DDG fallback)
- Python task router
- CLI interface for testing without voice
- Open WebUI in Docker (accessible from phone on local network)
- Full test suite for all Phase 1 components
- `docker-compose.yml` for ChromaDB + Open WebUI
- `.env.example` and setup `README.md`

### Phase 2 (future)
- PC automation skills (shell commands, file management, app control)
- Calendar + weather skills
- Tailscale for remote/phone access outside home network
- Expanded memory: memory viewer, explicit save commands

### Phase 3 (future)
- Content pipelines (script generation, scheduling, social posting)
- Sub-agents for longer-running tasks
- PRD and architecture sub-documents per pipeline

---

## 8. Documents To Be Written (in Claude Code)

These do not exist yet. Claude Code will create them as the project matures:

- `docs/PRD.md` — Product Requirements Document (top-level)
- `docs/ARCHITECTURE.md` — Technical architecture (top-level)
- `docs/skills/` — Per-skill sub-PRDs as skills are built
- Phase sub-documents as phases are completed

---

## 9. What Claude Code Should Do First

1. Read this entire document before doing anything
2. Set up the repo structure exactly as defined in Section 4
3. Create `docker-compose.yml` for ChromaDB + Open WebUI
4. Create `.env.example` with all required keys documented
5. Create `README.md` with setup instructions (WSL2, Ollama install, Docker, venv, running Martin)
6. Implement `core/config.py` first — everything depends on config
7. Implement `core/brain.py` using LiteLLM as the model interface, Instructor for structured outputs, Ollama as the local backend — with tests
8. Verify Ollama + LiteLLM + Instructor work together before touching anything else
8. Implement `core/memory.py` (ChromaDB client) with tests
9. Implement `core/router.py` with tests
10. Implement first skill: `skills/web_search/` with tests
11. Implement `interfaces/cli.py` — text-mode Martin, fully testable without voice
12. Implement `interfaces/voice.py` — push-to-talk loop
13. Verify full end-to-end: speak → STT → router → web search → memory → TTS → hear response
14. Only after all tests pass: create `docs/PRD.md` and `docs/ARCHITECTURE.md` reflecting what was actually built

**Do not skip steps. Do not add features not listed in Phase 1. Do not create folders not in the defined structure.**

---

## 10. Key Principles (Never Violate These)

- **Own your architecture, leverage other people's hard work** — the distinction is: tools do one thing and stay out of your way (LiteLLM, Instructor, ChromaDB, Faster-Whisper); frameworks shape your whole system (LangChain, AutoGen, OpenClaw). Use the first category freely. Be very cautious with the second.
- **Modular by default** — every piece replaceable without rewriting everything else
- **Local first** — sensitive data never leaves the machine; cloud tools are opt-in per task
- **Test before ship** — no untested code merges to main
- **Flat until complex** — don't add structure until the problem demands it
- **Martin is a platform, not a chatbot** — every decision should support future growth, not just current features

### Approved third-party tools (Phase 1)
These are deliberate choices. Don't replace them without a documented reason.

| Tool | Category | What it does | Lock-in risk |
|---|---|---|---|
| Ollama | Model server | Runs local models, manages GPU | Low — standard REST API |
| LiteLLM | Model abstraction | One API for all providers | Very low — thin wrapper, ~40 lines to replace |
| Instructor | Structured output | Typed responses from LLMs | Very low — call-site only |
| ChromaDB | Vector memory | Stores and retrieves memories | Low — standard embeddings format |
| Faster-Whisper | STT | Speech to text, local GPU | None — drop-in replaceable |
| Piper | TTS | Text to speech, local | None — drop-in replaceable |
| Open WebUI | Chat UI | Browser interface + phone access | None — Martin doesn't depend on it |
| pytest | Testing | Test runner | None |

---

*Generated from exploratory session. All decisions herein were made deliberately. Revisit this document when starting Phase 2.*
