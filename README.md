# Martin

A personal AI platform — local-first, modular, voice-capable. Not a chatbot wrapper.

Martin is a system you own: a model-agnostic brain, persistent pillar-tagged memory,
web awareness, and a skill system that grows over time. It runs on your machine; sensitive
data never leaves it unless you opt in per task.

See [MARTIN_BRIEFING.md](MARTIN_BRIEFING.md) for the full vision and design decisions,
and [docs/](docs/) for the PRD, roadmap, and architecture (written as the project matures).

---

## What's in Phase 1

A working Martin you can talk to that remembers things and searches the web:

- **Brain** — Ollama (local models) via LiteLLM, with Instructor for structured outputs
- **Memory** — ChromaDB (embedded), pillar-tagged, auto-stores high-signal facts
- **Router** — our own lightweight intent → skill dispatcher (no LangChain/n8n)
- **Web search** — Brave Search API with DuckDuckGo fallback
- **CLI** — a text interface that exercises the whole pipeline
- **Tokenized equity tracker** — which companies are launching equity via tokens
  through a regulated entity (SEC EDGAR + news, checked against a curated registry)
- **Voice (STT)** — push-to-talk: speak → local Whisper → text → same pipeline

---

## Setup (native Windows 11)

> Martin runs natively on Windows + PowerShell. Only Open WebUI (the phone UI) needs
> Docker. ChromaDB runs embedded inside Martin — no container required.

### 1. Install Ollama (native)

Download and run the Windows installer from <https://ollama.com/download>. Then pull the
models (confirm exact tags with `ollama list`):

```powershell
ollama pull qwen3:14b      # default brain
ollama pull mistral:7b     # fast model for routing / memory classification
```

The RTX 4060 Ti (16GB) comfortably fits a 13–14B Q4 model alongside the fast model.

### 2. Create the Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure

```powershell
Copy-Item .env.example .env
# Edit .env: set model tags to match `ollama list`, optionally add BRAVE_API_KEY.
```

### 4. Run Martin (CLI)

```powershell
python -m martin.interfaces.cli
```

### 5. Tokenized equity launch checker

Ask Martin ("which companies launched tokenized shares this month?") or run it directly:

```powershell
python -m martin.skills.tokenized_equity               # last 90 days
python -m martin.skills.tokenized_equity --days 30 --json
python -m martin.skills.tokenized_equity --no-news     # SEC EDGAR only
```

It searches SEC EDGAR full-text (S-1, F-1, 1-A, D, C, 424B4, 8-K) and the news for
tokenized-equity launches, scans each filing for regulated partners listed in
`martin/skills/tokenized_equity/regulated_entities.json` (transfer agents,
broker-dealers, ATSs, EU/UK/CH/SG DLT venues), and ranks them:

- **confirmed** — SEC filing + named regulated partner
- **likely** — regulated partner named, or SEC filing with no partner found
- **unverified** — news mention only

Set `SEC_USER_AGENT` in `.env` to your name + email (SEC requires it). A registry match
is a lead, not a licence check — confirm on FINRA BrokerCheck / the regulator's register.
Edit the registry JSON to add venues as they appear.

**Run it daily** (Windows Task Scheduler, current user, 08:00 by default):

```powershell
.\scripts\schedule-tokenized-equity.ps1              # or -Time 07:30, -RunNow, -Remove
```

Each run saves `data\tokenized_equity\report-YYYY-MM-DD.txt`, marks launches not seen by
earlier runs as **[NEW]**, and appends output/errors to `data\tokenized_equity\run.log`.
Missed runs (PC off) catch up at next start.

### 6. (Optional) Voice input

```powershell
pip install -r requirements-voice.txt
python -m martin.interfaces.voice
```

Push-to-talk: hold the hotkey, speak, release — your words are transcribed locally and
fed into the same pipeline as the CLI. (Speech-to-text only in Phase 1; spoken replies
come later.)

### 7. (Optional) Open WebUI on your phone

```powershell
docker compose up -d
```

Open `http://localhost:3000` on this PC, or `http://<this-PC-LAN-IP>:3000` from your
phone on the same Wi-Fi.

---

## Running tests

```powershell
pytest                  # full suite (skips live Ollama tests automatically)
pytest -m "not live"    # explicitly skip tests needing a running Ollama
pytest -m live          # only the live Ollama round-trip checks
```

Tests are behavior-driven: we test that the right thing happened (correct skill chosen,
fact stored and retrievable), not the exact wording of non-deterministic LLM output.

---

## Project layout

```
martin/
  core/        config, brain (LiteLLM+Instructor), memory (ChromaDB), router
  skills/      _base + one folder per skill (web_search, tokenized_equity, ...)
  interfaces/  cli, voice
tests/         mirrors the source tree
docs/          PRD + ROADMAP + ARCHITECTURE (written as we build)
```

Adding a skill = drop a folder with `skill.py` + `manifest.json` into `martin/skills/`.
No core code changes.
