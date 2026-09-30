# Martin — Architecture

> **Scope:** The whole-system technical architecture for Martin — written around the
> **target agentic architecture we are building toward**, with **what is built
> today** and the **migration path** between them kept as supporting detail. Read
> the status markers: the target is mostly planned; the foundations it wraps are
> built.
>
> Status markers: ✅ built · 🔨 in progress · 🔜 planned.
>
> See [PRD.md](PRD.md) for product scope, [ROADMAP.md](ROADMAP.md) for phasing, and
> [MARTIN_BRIEFING.md](../MARTIN_BRIEFING.md) for the originating vision.

---

## 1. Guiding principle

**Own the boundaries; rent the loop.** Martin leverages best-in-class open-source
tooling for the hard, generic machinery (model server, agent loop, structured
output, vector/graph memory) but *owns the boundaries that define Martin*: the tools
it exposes and the routing of which model handles what. Every third-party dependency
is held to one test:

> Does it stay in its lane and stay replaceable (a **tool**), or does it shape the
> whole system (a **framework**)?

Tools are used freely. Frameworks are adopted only behind a seam we control, and only
when the problem demands it. This is the 2026 form of "own your architecture;
leverage other people's hard work" — the line moved (we now rent the agent loop), but
the principle (no lock-in, everything replaceable) did not.

---

## 2. Target architecture — the agentic Martin 🔜

This is the architecture we are building toward and the spine of this document. The
defining shape: the linear `route → act → remember` pipeline becomes an **agent
loop**, and a **local/cloud capability switch** decides where each step runs. Most of
what follows is **planned (🔜)**; it wraps the **built (✅)** Phase 1 core documented
in §3, and the migration that connects them is in §4.

```
   text / speech ─▶  interfaces (cli, voice + TTS)
                          │
                          ▼
                ┌───────────────────────────┐
                │   Agent harness (owned)    │   thin layer on PydanticAI
                │   loop: model → tools →    │
                │         observe → repeat   │
                └───┬───────────┬────────────┘
                    │           │
        ┌───────────┘           └───────────────┐
        ▼                                        ▼
  capability switch                        tools (skills)
  local ◀──default──┐  ┌──heavy──▶ cloud   BaseSkill + MCP (progressive)
        ▼           │  │           ▼        files · shell · calendar · web …
   Ollama (14B/7B)  │  │       Claude            │
        │           │  │           │             ▼
        ▼           │  │           ▼        ┌──────────────────────────┐
   local exec   ────┘  └────  cloud crews   │ memory (core/memory.py)  │
                              (Phase 3)     │ temporal graph (Graphiti │
                              spawn boundary │   + FalkorDB)            │
                              ↑ cost cap +   │ + scheduling (SQLite)    │
                                context      └──────────────────────────┘
                                handoff

         skill-writer (Phase 3): gap → author(cloud) → sandbox+approve → register
```

### 2.1 The agent harness 🔜 (Phase 2a)
A **thin layer we own** on top of a mature agent library (**PydanticAI**, the working
choice — type-safe, model-agnostic, fits the existing pydantic/Instructor stack, and
supports agents-as-tools for later sub-agents). The library provides the agent loop
and cross-model tool-calling; Martin owns what's exposed and how models are routed.

- Replaces the built `core/router.py`'s single-skill selection (§3) with a real
  tool-calling loop that can chain tools within a turn.
- `core/brain.py` becomes the **provider-config layer** the harness binds models
  through (still the only place that knows about LiteLLM/providers).
- Phase 1 skills are exposed to the harness as tools (see §2.4).
- **Validation spike first:** before building on it, prove the library drives local
  Ollama and that 14B tool-calling is reliable enough on the owner's GPU.

### 2.2 Local/cloud capability switch 🔜 (Phase 2a)
Default everything to the local model; escalate heavy work to the cloud. A
**predictable task-weight switch**, deliberately *not* a fuzzy classifier and
*explicitly not* tied to memory tags or data sensitivity — it is a capability/cost
decision only. The harness must support **per-step model binding** (local for the
conversational/operational loop, cloud for heavy reasoning and sub-agent fan-out).

### 2.3 Memory: temporal knowledge graph + scheduling 🔜 (Phase 2b)

> **Current vs target:** today `core/memory.py` is backed by an embedded **ChromaDB**
> vector store (built — see §3). The target **replaces that backing** with a
> bi-temporal knowledge graph. `core/memory.py` stays the single module the rest of
> Martin talks to: it was the only module that knew about Chroma; it becomes the only
> one that knows about the graph. We commit to this target *up front* because
> migrating a memory model later means migrating all stored data **and** every code
> path that reads it.

Three concerns live behind that one seam:

**1. Knowledge memory → Graphiti temporal graph (committed: Graphiti + FalkorDB).**
[Graphiti](https://github.com/getzep/graphiti) (MIT) builds an incremental,
**bi-temporal** knowledge graph: nodes are entities (people, projects, preferences,
tools, topics); edges are facts/relationships, each carrying a validity window —
*when it became true, when it was superseded, and a confidence*.
- **Ingestion**: an utterance becomes an *episode* → an LLM extracts entities and
  relationships → the graph updates. Contradictions **invalidate** the prior edge
  (set `invalid_at`) instead of deleting it, so full history is retained and
  point-in-time queries are possible ("what did I believe in March").
- **Extraction model**: the local **Qwen3 14B** (not the 7B — graph integrity is
  quality-sensitive). Memory stays local; cloud extraction is a fallback only if
  local quality proves insufficient.
- **Pillar tags** ride along as node/edge attributes — organizational, *not* routing.
- **Backend**: **FalkorDB** (lightweight, Redis-based graph DB) in Docker. Note this
  trades away Phase 1's "memory works with Docker off" property — that is the
  accepted cost of the temporal graph. (Graphiti's embeddable Kuzu backend is
  deprecated; the fully-embedded alternative would have been Cognee, not chosen.)

**2. Scheduling memory → SQLite.** Calendar, reminders, exact-time queries.
"Remind me at 3pm Tuesday" is a precise relational/temporal query, not graph
traversal — kept separate and relational.

**3. Human-readable projection → markdown/Obsidian (roadmap, optional).** A read
projection of the graph for the memory-viewer feature; the graph stays the source of
truth.

**Target `core/memory.py` API:**
- `remember(text, pillar)` → manual episode ingest.
- `consider(utterance)` → high-signal judge, then ingest as an episode.
- `recall(query, pillars=None, as_of=None, n=5)` → Graphiti **hybrid search**
  (semantic + keyword + graph traversal), optional pillar filter, optional
  **point-in-time** (`as_of`); returns facts with temporal context.

(The current API — same `remember`/`consider`/`recall` shape over ChromaDB — is in
§3; keeping the signatures stable is what makes the swap a backing change, not a
caller rewrite.)

**Synergy with the async job model:** Graphiti ingestion is LLM-heavy (slow); recall
is fast. So memory **writes** become background jobs (never block a turn) while
**reads** stay instant — the temporal-graph choice and the async-job choice reinforce
each other.

### 2.4 Skills as tools, MCP progressive 🔜 (Phase 2b–2c)
`BaseSkill` (built — §3) remains the internal interface. **MCP is adopted
progressively** — first where a mature server ecosystem already exists (filesystem,
shell, app control for the PC-automation pillar) or where cross-harness portability
matters; trivial internal skills stay plain Python until a second runtime forces
standardization. MCP servers run locally, so adopting them does not change where data
goes — it only standardizes the tool boundary, which keeps the harness underneath
swappable.

### 2.5 Cloud content crews + the spawn boundary 🔜 (Phase 3)
Heavy content production fans out to **cloud sub-agent crews spawned by the local
Martin**. PydanticAI agents-as-tools covers the common case; a durable-orchestration
library (**LangGraph**) is reserved for long-running pipelines needing checkpointing
and human-in-the-loop approval, and is adopted *only when that durability is needed* —
not by default (two harnesses is complexity to earn, not assume).

The **spawn boundary** is the single contract where local hands off to cloud. It is
the one seam that decides routing, enforces the **cost cap** (per-job token budget +
kill switch), and **marshals the context** handed to the crew. Because it is one
inspectable place, it is also where every cross-boundary handoff is logged.

### 2.6 Skill-writer + owned safety gate 🔜 (Phase 3)
Martin's runtime self-improvement (Version A: skills, not weights):
`gap-detect → author (cloud model) → sandbox + owner approval → register → refine`.
Gap detection reuses the existing "no skill matched" signal; registration reuses the
existing manifest loader. The **safety gate is owned and explicit** — sandboxed
execution, approval before trust, rollback — because it generates and runs code on
the owner's personal machine, which also has PC-automation access. This is the
deliberate reason the harness is built, not adopted.

### Tooling (target) — additions to the Phase 1 table (§3)
| Tool | Role | Isolated to | Replace cost |
|---|---|---|---|
| PydanticAI | Agent loop / harness primitives | the owned harness layer | Medium — behind our seam |
| Claude (via LiteLLM) | Cloud brain (heavy + crews) | `core/brain.py` config | Low — config string |
| Graphiti | Bi-temporal knowledge-graph memory | `core/memory.py` | Medium — supersedes Chroma |
| FalkorDB | Graph DB backing Graphiti | `core/memory.py` + compose | Low — Graphiti supports Neo4j too |
| SQLite | Scheduling/structured memory | `core/memory.py` | Low |
| MCP servers | Standard tool boundary (PC-automation, etc.) | tool layer | Low — protocol standard |
| LangGraph *(Phase 3, if needed)* | Durable pipeline orchestration | cloud-crew layer | Medium |
| Piper | Text-to-speech | `interfaces/voice.py` | drop-in |

---

## 3. Current implementation — what's built today ✅ (Phase 1)

This is the foundation the target wraps. It is real and shipping; the target above
changes how these pieces are orchestrated and swaps the memory backing, but keeps
these modules and their interfaces.

### Component map (as built)

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

### The pipeline (one turn)

`Martin.handle(utterance)` in [martin/interfaces/cli.py](../martin/interfaces/cli.py):

1. **Route** — `Router.route()` decides which skill handles it: trigger fast-path
   (word-boundary match against manifest triggers), else fast-model selection (an
   Instructor-typed `RouteDecision`), else conversational fallback. *(The target
   agent loop in §2.1 absorbs this step.)*
2. **Act** — run the selected skill → `SkillResult.content`; or `Brain.chat()` with
   the system prompt plus relevant recalled facts.
3. **Remember** — `Memory.consider(utterance)` stores it if high-signal, tagged to a
   pillar. Failures are swallowed so a turn never breaks.

Both interfaces call the *same* `Martin.handle`; voice merely turns speech into text.

### Core modules (as built)
- **`core/config.py`** — `pydantic-settings` `Settings` from env/`.env`, the single
  source of truth. Cached singleton; nothing else reads `os.environ`.
- **`core/brain.py`** — the only module importing LiteLLM/Instructor. `chat()`
  (free text, brain model) and `structured(..., response_model)` (Instructor-typed,
  JSON mode, fast model for routing/memory classification).
- **`core/memory.py`** — embedded ChromaDB (`PersistentClient` → `./data/chroma`),
  the only module importing chromadb. `remember`, `consider` (LLM-judged, with
  pillar hints + dedup against existing memories), `recall`. **This is the module the
  target (§2.3) re-backs with Graphiti — same callers, same method shape.**
- **`core/router.py`** — owned orchestration: loads manifests, trigger fast-path then
  model selection, guards hallucinated skill names, returns a `Route`. *(Superseded
  by the agent loop in the target.)*
- **`skills/`** — `_base.py` (`SkillManifest`, `SkillResult`, `BaseSkill`,
  discovery/loading); `web_search/` (Brave → DuckDuckGo, honest failure);
  `tokenized_equity/` (SEC EDGAR + news → tokenized equity launches, matched against a
  curated regulated-entity registry). Adding a skill = drop a folder; no core changes.
- **`interfaces/`** — `cli.py` (the `Martin` pipeline + REPL); `voice.py`
  (lazy Faster-Whisper transcriber + push-to-talk capture; TTS deferred to Phase 2).

### Tooling (Phase 1, built) — each isolated, each replaceable
| Tool | Role | Isolated to | Replace cost |
|---|---|---|---|
| Ollama | Local model server (GPU) | config (URL/model strings) | Low — REST API |
| LiteLLM | Model abstraction | `core/brain.py` | ~40 lines |
| Instructor | Structured LLM output | `core/brain.py` | call-site only |
| ChromaDB | Vector memory *(target replaces with Graphiti, §2.3)* | `core/memory.py` | Low |
| Faster-Whisper | Speech-to-text | `interfaces/voice.py` | drop-in |
| pydantic-settings | Typed config | `core/config.py` | Low |

---

## 4. Migration path — current → target (no throwaway)

The Phase 1 investment is preserved at every step; nothing is rebuilt:

1. **Keep** `config.py`, `memory.py`, `brain.py`, `skills/` as the core.
2. **Wrap** the harness (PydanticAI) around them; `brain.py` becomes its
   provider-config layer; skills become its tools. `router.py`'s job (skill choice)
   is absorbed by the agent loop.
3. **Add** the local/cloud switch and Claude provider (config-level).
4. **Replace** memory's internals behind `memory.py`'s interface: stand up Graphiti +
   FalkorDB, add the SQLite scheduling store, and **re-ingest** the Phase 1 Chroma
   facts as Graphiti episodes (one-time script over a small dataset).
5. **Add** the async job model + cost governor + spawn boundary for cloud crews.
6. **Add** the skill-writer on top of the existing manifest loader, behind the owned
   safety gate.

Each step is additive and independently shippable.

---

## 5. Models
- **Local brain:** `ollama/qwen3:14b` — fits the RTX 4060 Ti (16GB).
- **Local fast:** `ollama/mistral:7b` — routing + memory classification.
- **Cloud:** Claude — heavy reasoning, content generation, sub-agent crews, and the
  skill-writer's codegen step. Added as config + key via LiteLLM (target).
- **GPU reality:** the 4060 Ti (16GB, ~288 GB/s) runs one 14B-class model at ~21
  tok/s. It cannot run multiple large models concurrently, and agent loops multiply
  sequential calls — which is *consistent with* the design: parallel/heavy work goes
  to cloud, the local GPU stays free for the interactive loop. Raising the local
  ceiling means more hardware (a dedicated GPU node), not more cloud.

---

## 6. Data & process model
- **Today (built):** single process, native Windows, synchronous request→response
  REPL. Memory persists to `./data/chroma` (gitignored). Open WebUI (optional) in
  Docker reaches native Ollama via `host.docker.internal`.
- **Target (Phase 2b onward):** an **async job model** is required — long cloud work
  cannot block the interactive loop, so the synchronous REPL gains background
  dispatch, status tracking, and completion notifications. **Graphiti memory
  ingestion runs as one of these background jobs** (it is LLM-heavy), while recall
  stays synchronous.
- **Memory will then require a running service.** FalkorDB runs as a container
  (joining Open WebUI in `docker-compose.yml`); native Ollama reaches it as usual.
  This trades away today's "memory works with Docker off" property. Crew results are
  pulled back into the graph through `core/memory.py`, never written concurrently
  from elsewhere.

---

## 7. Tradeoffs & risks (and their mitigations)

These are the known friction points, recorded so each ships with a guardrail.

- **Agent loops gate on local-model reliability.** Routing, the local/cloud switch,
  and tool-call formatting all run on 14B/7B models whose mistakes compound in a
  loop. *Mitigation:* keep the switch dumb and explicit (clear task-type triggers,
  not a fuzzy classifier); route the hard reasoning to cloud; validation spike before
  building on it.
- **The spawn boundary concentrates risk.** Routing + cost + context handoff in one
  seam, with silent failure modes. *Mitigation:* make it loud — default-deny on what
  context crosses, log every handoff, hard per-job token cap + kill switch.
- **Framework sprawl.** Two harnesses (PydanticAI + LangGraph) is real complexity.
  *Mitigation:* start with one; add LangGraph only when durable orchestration is
  genuinely needed; MCP keeps tools portable across both.
- **Self-written code executes on a personal machine.** *Mitigation:* the owned
  safety gate — sandbox, approval before trust, rollback.
- **GPU contention.** 14B brain + 7B fast + Whisper (+ Piper) on one 16GB card is
  tight before cloud even enters. *Mitigation:* the local/cloud switch offloads
  parallel/heavy work; consider a dedicated GPU node (Phase 4).
- **Cost becomes variable.** Cloud crews loop and burn tokens. *Mitigation:* cost
  governor built into the spawn boundary, not bolted on later.
- **Temporal-graph memory adds operational weight + extraction risk.** It needs a
  graph DB (no more "Docker off"), and graph quality depends on LLM extraction that
  can be noisy on local models. *Mitigation:* FalkorDB keeps ops light; extract with
  the 14B (not the 7B); the bi-temporal model self-corrects over time as new episodes
  invalidate stale edges; cloud extraction is a fallback if local quality is poor.
- **Tests don't yet reach agentic behavior.** *Mitigation:* add eval-style tests for
  trajectories/routing and an explicit context-handoff test (see §8).

---

## 8. Testing strategy
- **Today — behavior-driven and offline by default** — LLM mocked (`FakeBrain`),
  ChromaDB exercised for real with a deterministic in-test embedding on per-test
  `tmp_path`, network mocked. A separate `live`-marked test does a real Ollama
  round-trip and auto-skips when unreachable.
- **Target additions:**
  - Eval-style tests for routing decisions and agentic trajectories (intent, not
    wording).
  - An explicit **spawn-boundary test**: assert only the intended context crosses to
    a cloud job and the cost cap is enforced.
  - A **skill-writer safety test**: a self-written skill is never executed or trusted
    without passing the sandbox/approval gate.
  - When memory is re-backed (§2.3), the existing memory tests run against the graph
    backing through the unchanged `memory.py` interface.

---

## 9. Extension points (designed-in)
- **New skill** — drop a folder under `skills/` (or an MCP server); the router today /
  the harness in the target picks it up.
- **New model/provider** — change config strings; `brain.py` stays provider-agnostic.
- **New pillar** — add a tag in `.env`; no schema change. (Pillars organize memory;
  they do **not** gate local/cloud routing.)
- **Swap graph backend** — Graphiti supports Neo4j/FalkorDB; change construction in
  `memory.py` only.
- **Spoken replies (TTS)** — add an output stage in `voice.py`; pipeline unchanged.
- **Durable pipelines** — introduce LangGraph behind the cloud-crew layer when needed.
