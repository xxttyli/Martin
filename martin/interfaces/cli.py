"""Text interface for Martin — the full pipeline without voice.

This wires every core piece together:

    utterance
        -> router         (pick a skill, or converse)
        -> skill.run()    (e.g. web_search) OR brain.chat() with recalled memory
        -> memory.consider()  (auto-store high-signal facts)
        -> reply

The orchestration lives in the ``Martin`` class so it can be tested with mocks
and reused by other interfaces (the voice loop simply feeds it transcribed text).
``run_repl`` / ``main`` provide the interactive text loop.
"""

from __future__ import annotations

from martin.core.brain import Brain
from martin.core.config import Settings, get_settings
from martin.core.memory import Memory
from martin.core.router import Router
from martin.skills._base import BaseSkill, load_skills

SYSTEM_PROMPT = (
    "You are Martin, a personal AI assistant for a solo creator. Be concise, "
    "direct, and genuinely helpful. If you don't know something, say so plainly."
)

EXIT_WORDS = {"quit", "exit", ":q", "bye"}


class Martin:
    """The Martin pipeline: route -> skill/converse -> remember -> reply.

    All collaborators are injectable so the pipeline is fully testable without a
    live model, network, or database.

    Args:
        brain: Brain (LLM interface). Built from settings if omitted.
        memory: Memory store. Built (embedded ChromaDB) if omitted.
        router: Router. Built over the loaded skills if omitted.
        skills: name -> BaseSkill map. Discovered from martin/skills/ if omitted.
        settings: Settings override (defaults to the process singleton).
    """

    def __init__(
        self,
        brain: Brain | None = None,
        memory: Memory | None = None,
        router: Router | None = None,
        skills: dict[str, BaseSkill] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.brain = brain or Brain(self.settings)
        self.memory = memory or Memory(brain=self.brain, settings=self.settings)
        self.skills = (
            skills
            if skills is not None
            else load_skills(brain=self.brain, settings=self.settings)
        )
        self.router = router or Router(
            brain=self.brain,
            settings=self.settings,
            manifests=[s.manifest for s in self.skills.values()],
        )

    def handle(self, utterance: str) -> str:
        """Process one utterance and return Martin's reply."""
        utterance = utterance.strip()
        if not utterance:
            return ""

        route = self.router.route(utterance)
        if route.skill and route.skill in self.skills:
            answer = self.skills[route.skill].run(utterance).content
        else:
            answer = self._converse(utterance)

        # Auto-store high-signal facts. Never let a memory hiccup break the turn.
        try:
            self.memory.consider(utterance)
        except Exception:
            pass

        return answer

    def _converse(self, utterance: str) -> str:
        """Answer conversationally, grounded in any relevant remembered facts."""
        system = SYSTEM_PROMPT
        try:
            memories = self.memory.recall(utterance, n=3)
        except Exception:
            memories = []
        if memories:
            facts = "\n".join(f"- {m.text}" for m in memories)
            system += f"\n\nRelevant things you remember about the user:\n{facts}"

        return self.brain.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": utterance},
            ]
        )


def run_repl(agent: Martin | None = None) -> None:
    """Run the interactive text loop. Builds a real Martin if none is given."""
    agent = agent or Martin()
    print("Martin (text mode). Type 'quit' to exit.\n")
    while True:
        try:
            utterance = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not utterance:
            continue
        if utterance.lower() in EXIT_WORDS:
            break
        try:
            reply = agent.handle(utterance)
        except Exception as exc:  # keep the session alive on runtime errors
            print(f"martin > [error] {exc}\n")
            continue
        print(f"martin > {reply}\n")
    print("Goodbye.")


def main() -> None:
    run_repl()


if __name__ == "__main__":
    main()
