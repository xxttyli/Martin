# Martin — Product Requirements Document

> **Scope:** This is the whole-system PRD for Martin — *what* Martin is and *why*
> it is built the way it is: the product vision, who it's for, the design
> principles that govern every part of it, the capabilities it provides and the
> behaviors those capabilities must always honor, the non-goals, and the quality
> bar. It is phase-agnostic.
>
> For *when* and *in what order* things get built, see
> [ROADMAP.md](ROADMAP.md). For the technical design, see
> [ARCHITECTURE.md](ARCHITECTURE.md). For the originating vision, see
> [MARTIN_BRIEFING.md](../MARTIN_BRIEFING.md).

---

## 1. What Martin is

Martin is a personal AI platform for a solo creator — local-first, modular, and
voice-capable. It is explicitly **not** a chatbot wrapper: it is a system the owner
controls, built to grow into a content-creation and publishing platform that can
**act on the owner's machine, manage their day, produce content through cloud
sub-agents, and extend its own capabilities over time.**

The product arc, in one line per stage:

1. **Talk & remember** — a local assistant you converse with that remembers
   high-signal facts and can search the web.
2. **Act** — a real tool-using agent that can operate your machine and manage your
   day, local-first, escalating heavy work to the cloud.
3. **Produce & grow** — dispatches cloud sub-agent crews to create content, and
   writes/refines its own skills.

(This arc is the product's direction. Its sequencing — what lands when, and why in
that order — lives in [ROADMAP.md](ROADMAP.md).)

Three organizational **pillars** shape how memory is tagged and skills are grouped
(they are categories, not walls):

1. **Business & AI/Tech** — content, research, publishing, brand-building
2. **Daily assistant** — calendar, weather, reminders, personal context
3. **PC automation** — terminal, files, app control, code execution

---

## 2. Personas & user stories

### Primary persona — the owner

A **solo creator/founder** working in business and AI/tech. Technically capable
(writes Python, comfortable on the command line), local-first by conviction —
wants a system they *own* rather than a rented chatbot, where sensitive data stays
on the machine unless they opt in. Works on a single Windows box with one
consumer GPU (16GB), so the system must respect a real hardware ceiling. Values
honesty over polish: would rather Martin say "I couldn't" than fabricate. There is
exactly one user; Martin is not multi-tenant.

### User stories

**Business & AI/Tech**
- As the creator, I want Martin to research a topic and remember the key findings
  so that I can build content without re-searching the same ground.
- As the creator, I want Martin to dispatch heavier content work to the cloud so
  that my local machine stays responsive while a draft is produced.

**Daily assistant**
- As the creator, I want to ask what's on today and set reminders by voice so that
  I can manage my day without breaking focus.
- As the creator, I want time-based questions ("what's on Tuesday", "remind me in
  two hours") answered precisely so that I can trust them.

**PC automation**
- As the creator, I want Martin to run shell commands, manage files, and control
  apps on request so that I can drive my machine by voice or text.
- As the creator, I want any action that *modifies* my machine to be gated so that
  nothing destructive happens silently.

**Cross-cutting**
- As the creator, I want to talk to Martin and have him remember only what matters
  so that my memory store stays high-signal rather than a transcript.
- As the creator, I want Martin to fail honestly so that I never mistake a
  fabrication for a result.
- As the creator, I want Martin to close his own capability gaps over time so that
  he gets more useful the longer he runs.

---

## 3. Design principles (govern every phase)

These are the decisions made up front so that each stage stays consistent with the
last. They are binding, not aspirational.

- **Own the boundaries, rent the loop.** Martin leverages best-in-class open-source
  agent tooling (model server, agent library, structured output, vector memory)
  rather than reinventing it — but *owns the boundaries that matter*: the tools it
  exposes and the routing of which model handles what. This is the 2026 form of
  "own your architecture; leverage other people's hard work." The test for any
  dependency: does it stay in its lane and stay replaceable (a *tool*), or does it
  shape the whole system (a *framework*)? Prefer tools; adopt frameworks only behind
  a seam we control.
- **Local-first, cloud for heavy.** Default everything to the local model. Escalate
  to the cloud for compute-intensive work and sub-agent fan-out. This is a
  **capability/cost switch**, *not* a privacy/data-classification gate — it is
  decided by how heavy the task is, never by memory tags.
- **Build the thin custom harness; don't adopt a whole one.** Martin's agent runtime
  is a thin layer we own on top of a mature agent library. We do not adopt a full
  third-party harness (e.g. Hermes) wholesale, because that would subsume the memory
  and skill systems we already own and turn Martin into a skin over someone else's
  runtime. (The detailed build-vs-adopt rationale lives in
  [ROADMAP.md](ROADMAP.md), where it justifies the relevant phase.)
- **Self-improvement means skills, not weights.** "Martin improves himself" means he
  **writes and refines his own skills** (procedural growth on the existing skill
  system), not that the underlying model retrains itself. The codegen-and-execute
  safety gate for self-written skills is **owned by Martin**, because it touches the
  owner's machine.
- **Modular by default** — every piece replaceable without rewriting everything else.
- **Flat until complex** — no structure (or framework) added until the problem
  demands it.
- **Honest by default** — Martin never fabricates a search result, an answer, or a
  success. Failures are reported plainly.
- **Test before ship** — behavior-driven; no untested code merges to main.

---

## 4. Capabilities

Each capability below is described together with the **invariant behaviors** it
must always honor — the things that are true of Martin regardless of how far along
the roadmap it is. Phase-specific delivery and acceptance criteria (which
capabilities exist *yet*, and what "done" means for a given phase) live in
[ROADMAP.md](ROADMAP.md).

### Conversation & memory
Martin holds a conversation grounded in what he remembers, and stores only durable,
high-signal facts.
- Conversation is grounded in relevant remembered facts injected into context.
- Only durable, high-signal statements are stored; trivial chitchat is dropped.
- Stored facts are pillar-tagged and retrievable by meaning, not just keyword.
- A memory hiccup never breaks a turn.

### Web awareness
Martin can search the web for current information.
- Uses a keyed primary provider when available, a fallback otherwise.
- If search is unavailable, Martin says so and **never fabricates** a result.

### Agentic action
Martin acts as a tool-using agent, not a single-skill responder.
- He can chain multiple tools within a single turn to complete a task.
- Local is the default execution path; escalation to the cloud is **explicit and
  logged**, and governed by a cost budget.
- Cloud escalation is a capability/cost decision only — it is never driven by data
  sensitivity or memory tags, and personal context is never leaked into a cloud
  payload that doesn't need it.

### Daily assistant
Martin manages the owner's day.
- Calendar, weather, and reminders.
- Time-based questions are answered from an exact, structured source — not from
  fuzzy semantic recall.

### PC automation
Martin operates the owner's machine.
- Files, shell, and app control.
- Any action that **modifies** the machine is gated (sandbox/approval) and never
  runs silently.

### Cloud production
Martin produces content by fanning out to cloud sub-agent crews.
- Crews are spawned by the local Martin and run without blocking the conversation.
- Every crew runs within a per-job cost cap, and results are pulled back into
  memory.

### Self-improvement
Martin closes his own capability gaps (skills, not weights).
- When he hits a gap, he can author a new skill for it.
- A self-written skill is **never trusted or executed** without passing the owned
  safety gate (sandbox, approval before trust, rollback).
- A self-written skill that underperforms can be regenerated or patched.

---

## 5. Non-goals
- **Never** a framework that shapes the whole system (LangChain-as-architecture,
  AutoGen-as-architecture). Frameworks only behind an owned seam.
- **Not** privacy-gated routing — local/cloud is a capability switch, full stop.
- **Not** adopting a third-party harness wholesale.
- **Not** live model fine-tuning on the owner's current hardware (it is gated on
  training hardware that does not exist yet).
- **Not** a multi-tenant or multi-user product — Martin serves one owner.
- **No pulling features forward across phase boundaries** — the foundational
  decisions land first (see [ROADMAP.md](ROADMAP.md)).

---

## 6. Quality bar
- **Behavior-driven tests** — assert the right thing happened (correct skill/tool
  chosen, fact stored and retrievable, honest failure, *personal context not leaked
  into a cloud job's payload*), never exact LLM wording.
- **Offline by default** — the suite runs with no model, network, or downloads: the
  LLM is mocked, the vector store uses a deterministic in-test embedding, network is
  mocked.
- **Live round-trip** is a separate `live`-marked test that auto-skips when the
  local model server isn't running.

(Phase-specific testing additions — eval-style trajectory/routing tests, the
spawn-boundary context-handoff test, the skill-writer safety test — are listed in
[ROADMAP.md](ROADMAP.md) alongside the phases that introduce them.)

---

## 7. Assumptions & open questions

Recorded so they're tracked rather than implicit. Assumptions are what the design
currently takes for granted; open questions are decisions deliberately left open.

### Assumptions
- **Single-GPU ceiling.** One consumer GPU (16GB) runs a single 14B-class model at
  a time. It cannot run multiple large models concurrently; raising the local
  ceiling means more hardware, not more cloud.
- **One owner.** Martin is single-user; there is no multi-tenancy to design around.
- **Local-first stays viable.** The interactive loop runs acceptably on local
  models, with the cloud reserved for heavy/parallel work — not as a crutch for
  everyday turns.
- **Memory is committed to its target model up front.** Because migrating a memory
  model later means migrating all stored data and every reader, the temporal-graph
  design is adopted early rather than retrofitted (see ARCHITECTURE.md).

### Open questions
- **Is local 14B/7B tool-calling reliable enough to drive an agent loop?** This is
  unproven and gated by a validation spike before the agentic work is built on it.
- **Is local-model extraction good enough for graph-memory integrity,** or is cloud
  extraction needed as a fallback?
- **What is the right default per-job cost cap** for cloud crews, and how loud
  should the kill switch be?
- **When (if ever) does durable orchestration become necessary** for long-running
  content pipelines, versus the simpler agents-as-tools approach?
- **Will training hardware or a cloud-train path ever become available** to make
  weight-level self-improvement (Version B) worth revisiting?
