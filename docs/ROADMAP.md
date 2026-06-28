# Martin — Roadmap

> **Scope:** *When* and *in what order* Martin gets built — the phases, what each
> delivers, the dependencies between them, and their per-phase requirements. It is
> both a record of what's shipped and a forward-looking sequence.
>
> The roadmap is **directional and dependency-ordered, with no calendar dates.**
> Phase boundaries are deliberate: the foundational decisions land *before* the
> features that depend on them, and features are not pulled forward across a
> boundary.
>
> Status markers: ✅ delivered · 🔨 in progress · 🔜 planned.
>
> For *what* Martin is and *why* (vision, principles, capabilities, non-goals), see
> [PRD.md](PRD.md). For the technical design, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Sequencing rationale

Why the phase boundaries are where they are:

- **Foundations before features.** The agent harness, the local/cloud capability
  switch, the owned safety gate, and the committed memory model are foundational —
  everything later depends on them, so they land first.
- **Commit memory early.** The temporal-graph memory model is adopted in Phase 2
  rather than retrofitted, because migrating a memory model later means migrating
  all stored data *and* every code path that reads it.
- **Earn complexity.** Heavier machinery (durable orchestration, a second harness)
  is added only when the problem demands it, not by default.
- **No pulling forward.** Features do not jump phase boundaries; the order is the
  point.

---

## 2. Phase overview

| Phase | Theme | One-line goal | Status |
|---|---|---|---|
| **1** | Solid Core | Talk to Martin, he remembers, he can search the web | ✅ Delivered |
| **2** | Agentic Assistant | A tool-using agent that acts on your machine and your day, local-first | 🔜 Planned |
| **3** | Production & Self-Improvement | Cloud crews that produce content; Martin writes his own skills | 🔜 Planned |
| **4** | Horizon | Publishing automation, remote/multi-machine, optional model fine-tuning | 🔜 Future |

---

## 3. Phase 1 — Solid Core ✅ (delivered)

> A working Martin you can talk to, that remembers things, and can search the web.

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

### Decisions that adapted the briefing
- **Native Windows**, not WSL2. Ollama is native; only Open WebUI needs Docker.
- **ChromaDB runs embedded** (`PersistentClient`), not in a container.
- **Voice is speech-to-text only**; spoken replies (TTS) deferred to Phase 2.

### Behavior delivered
- **Conversation** grounded in relevant remembered facts injected into the prompt.
- **Memory honesty & signal**: only durable, high-signal statements are stored,
  pillar-tagged, retrievable by semantic search.
- **Web search honesty**: Brave when keyed, else DuckDuckGo; if both are down, Martin
  says so and never fabricates.
- **Routing**: trigger fast-path, else fast-model skill selection, else conversation;
  invented skill names rejected.
- **Resilience**: a memory hiccup never breaks a turn.

---

## 4. Phase 2 — Agentic Assistant 🔜 (planned)

> Martin stops being a one-skill-per-turn pipeline and becomes a real tool-using
> agent that can act on your machine and manage your day — local-first, escalating
> heavy work to the cloud.

This is the foundational phase: it replaces the linear `route → act → remember`
pipeline with an **agent loop**, and establishes the local/cloud capability switch
that everything after it depends on.

**Dependencies**
- *Requires:* Phase 1 core (config, brain, memory, skills) as the substrate to wrap.
- *Gated by:* a validation spike proving the agent library drives local Ollama and
  that 14B tool-calling is reliable enough on the owner's GPU — done **before**
  building on it.
- *Unblocks:* Phase 3 (cloud crews need the harness, the cloud provider, the cost
  governor, and the async job model established here).

### 2a — The agent harness (foundation)
- **Thin agent harness on a mature agent library** (PydanticAI as the working
  choice) — owns the agent loop (model → tool calls → observe → repeat), exposing
  Phase 1 skills as tools. Replaces the hand-rolled single-skill router.
- **Local/cloud capability switch** — default local; escalate heavy tasks to cloud.
  A simple, predictable task-weight switch, not a fuzzy classifier.
- **Claude added as the cloud provider** (config + key via LiteLLM).

### 2b — Hardening (the seams that fail silently)
- **Async job model** — long cloud work can't block an interactive conversation;
  dispatch + status + "ready shortly" notifications.
- **Cost governor** — per-job token budgets + kill switch, so a runaway loop can't
  produce a surprise bill.
- **Observability** — inspectable agent trajectories and what crosses to the cloud.
- **Extended testing** — eval sets for routing decisions and agentic trajectories,
  not just single-turn mocks.
- **Temporal-graph memory (committed design)** — replace the flat Phase 1 vector
  store with a **bi-temporal knowledge graph** (Graphiti + FalkorDB): facts are graph
  edges with validity windows, so updates *supersede* rather than duplicate, and
  point-in-time recall is possible. A separate **SQLite** store handles scheduling
  (calendar/reminders), which needs exact time queries. Committed up front because
  migrating a memory model later means migrating all stored data and every reader.
  See [ARCHITECTURE.md §2.3](ARCHITECTURE.md). Accepted cost: memory now needs a
  running graph DB (no longer "works with Docker off").

### 2c — Daily-assistant & PC-automation skills
- **Daily assistant**: calendar, weather, reminders.
- **PC automation**: files, shell, app control — adopted via MCP where a mature
  server ecosystem already exists, behind a safety gate.
- **Spoken replies (Piper TTS)** — the deferred half of the voice loop.
- **Optional**: Tailscale remote access; memory viewer + explicit save/forget.

### Phase 2 requirements
- The agent can chain multiple tools within a single turn to complete a task.
- Local is the default execution path; escalation to cloud is explicit, logged, and
  governed by a token budget.
- PC-automation actions that modify the machine are gated (sandbox/approval) and
  never run silently.
- Temporal queries ("what's on Tuesday", "remind me in 2 hours") are answered from
  the structured store, not vector recall.
- The Phase 1 Chroma facts are re-ingested into the temporal graph (one-time
  migration over a small dataset) with no loss.

---

## 5. Phase 3 — Production & Self-Improvement 🔜 (planned)

> Martin dispatches cloud sub-agent crews to create content, and grows his own
> capabilities by writing and refining his own skills.

**Dependencies**
- *Requires:* the Phase 2 harness, the cloud provider, the local/cloud switch, the
  async job model, and the cost governor — cloud crews and the skill-writer all
  build directly on them.
- *Unblocks:* Phase 4 publishing automation (publishing rides on the content
  pipelines) and trajectory logging toward Version B.

### Cloud content crews
- **Multi-agent fan-out** for content production, *spawned by the local Martin*.
  PydanticAI agents-as-tools for the common case; a durable-orchestration library
  (LangGraph) reserved for long-running pipelines that need checkpointing and
  human-in-the-loop approval — adopted only if and when that durability is needed.
- **The spawn boundary** is the single contract that decides routing (heavy → cloud),
  enforces the cost cap, and marshals the context handed to the crew. One inspectable
  seam.
- **Content pipelines** — script/post generation, scheduling support.

### Self-improvement (Version A — skills, not weights)
This is "whatever Hermes does" at runtime, built custom and owned:
- **Skill-writer loop**: gap-detect (router returns `none` / a tool fails) → author a
  new skill (routed to the cloud model) → sandbox + owner approval → register (the
  existing loader picks it up) → refine underperforming skills over time.
- **Owned safety gate** — generating and executing code on the owner's personal
  machine is a surface Martin controls explicitly: sandboxed execution, approval
  before trust, rollback. This is the deliberate reason to build rather than adopt.
- **Procedural memory** — Martin remembers what worked, so he gets more capable the
  longer he runs.

### Build-vs-adopt rationale (why not just adopt Hermes)
Hermes is a SOTA local-first harness with persistent memory and skill creation
already built. We evaluated adopting it and chose to **build a thin custom harness**
instead, for documented reasons:
- The hard parts (agent loop, cross-model tool-calling) come free from a mature
  agent library; the parts unique to Martin (memory, skills, persona, routing) are
  already built and would become plumbing under Hermes's runtime.
- The runtime self-improvement that makes Hermes valuable is **Version A** (skill
  creation + procedural memory) — buildable on Martin's existing skill system. The
  **Version B** capability (model fine-tuning on exported trajectories) is
  research-grade *and cannot run on the owner's GPU regardless*, so adopting Hermes
  would not unlock it.
- The self-improvement surface (code generation + execution on a personal machine
  with PC-automation access) is precisely the thing to *own*, not outsource to a
  fast-moving third-party runtime.

### Phase 3 requirements
- Local Martin can dispatch a cloud crew without blocking the conversation, within a
  per-job budget, and report results back into memory.
- Martin can author a working new skill for a capability gap, and that skill is never
  trusted or executed without passing the safety gate.
- A self-written skill that underperforms can be regenerated/patched.

---

## 6. Phase 4 — Horizon 🔜 (future, directional)

**Dependencies:** rides on the Phase 3 content pipelines and spawn boundary;
Version B additionally gated on training hardware that does not exist yet.

- **Publishing automation** — social posting, scheduling daemon.
- **Remote / multi-machine** — Tailscale beyond the LAN; a dedicated GPU node to run
  larger local models (the privacy-preserving way to raise the local capability
  ceiling is more hardware, not more cloud).
- **Version B self-improvement** — fine-tuning on logged trajectories, *if* training
  hardware or a cloud-train path becomes available. Trajectory logging may be added
  earlier as cheap, separable preparation.
- **Voice** — wake word / always-on, if desired.

---

## 7. Testing additions by phase

The baseline quality bar (behavior-driven, offline-by-default, live round-trip) is
in [PRD.md §6](PRD.md). Each phase adds:

- **Phase 2:** eval-style tests for routing decisions and agentic trajectories
  (intent, not wording); explicit tests for the cost governor.
- **Phase 3:** a **spawn-boundary test** (assert only the intended context crosses
  to a cloud job and the cost cap is enforced); a **skill-writer safety test** (a
  self-written skill is never executed or trusted without passing the
  sandbox/approval gate).

---

## 8. Dependency summary

The cross-phase prerequisites, at a glance:

```
Phase 1 core (config · brain · memory · skills)
   └─▶ Phase 2: agent harness + local/cloud switch + cloud provider
          ├─ async job model + cost governor      ─┐
          ├─ temporal-graph memory (committed now) │ (migrate-later is expensive)
          └─ daily-assistant + PC-automation skills │
                 └─▶ Phase 3: cloud crews (spawn boundary needs cost governor) ─┐
                        └─ skill-writer (needs owned safety gate)                │
                               └─▶ Phase 4: publishing · multi-machine · Version B
                                          (Version B also gated on training hardware)
```

Key chains: **agent harness → cloud crews**; **cost governor → spawn boundary**;
**temporal memory committed in Phase 2** because retrofitting it later means
migrating all data and every reader.
