"""Web search skill — Brave Search API primary, DuckDuckGo fallback.

Honesty rule (briefing §3.5): Martin never confabulates a search failure. If both
providers are unavailable, the skill returns ``success=False`` with a plain
explanation rather than inventing an answer.

Selection logic:
- If a Brave API key is configured, try Brave first.
- Otherwise (or if Brave errors), fall back to DuckDuckGo (no key required).
- If both fail, report the failure honestly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from martin.core.config import Settings
from martin.skills._base import BaseSkill, SkillManifest, SkillResult

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"
DEFAULT_MAX_RESULTS = 5


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class WebSearchSkill(BaseSkill):
    """Searches the web, preferring Brave and falling back to DuckDuckGo."""

    def run(self, query: str, context: dict | None = None) -> SkillResult:
        query = query.strip()
        start = time.perf_counter()
        if not query:
            return SkillResult(
                content="No search query was provided.",
                success=False,
                latency=time.perf_counter() - start,
            )

        brave_error: str | None = None
        hits: list[SearchHit] | None = None
        source: str | None = None

        # 1. Brave (only when a key is configured).
        if self.settings.has_brave:
            try:
                hits = self._brave_search(query)
                source = "brave"
            except Exception as exc:  # network/HTTP/parse — fall back gracefully
                brave_error = f"Brave search failed ({exc})"

        # 2. DuckDuckGo fallback.
        if not hits:
            try:
                hits = self._ddg_search(query)
                source = "duckduckgo"
            except Exception as exc:
                # Both providers are down — report honestly, never confabulate.
                detail = f"DuckDuckGo failed ({exc})"
                if brave_error:
                    detail = f"{brave_error}; {detail}"
                return SkillResult(
                    content=(
                        "I couldn't search the web right now — both providers are "
                        f"unavailable. {detail}"
                    ),
                    success=False,
                    source=source,
                    latency=time.perf_counter() - start,
                )

        latency = time.perf_counter() - start
        if not hits:
            return SkillResult(
                content=f'No web results found for "{query}".',
                success=True,
                source=source,
                latency=latency,
            )

        return SkillResult(
            content=self._format(query, hits, source or "web"),
            success=True,
            source=source,
            latency=latency,
        )

    # ── providers ───────────────────────────────────────────────────────────
    def _brave_search(self, query: str, count: int = DEFAULT_MAX_RESULTS) -> list[SearchHit]:
        resp = httpx.get(
            BRAVE_ENDPOINT,
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.settings.brave_api_key or "",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        results = (resp.json().get("web") or {}).get("results") or []
        return [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in results[:count]
        ]

    def _ddg_search(self, query: str, count: int = DEFAULT_MAX_RESULTS) -> list[SearchHit]:
        from ddgs import DDGS  # imported lazily; keeps import of this module cheap

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=count))
        return [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("href", "") or r.get("url", ""),
                snippet=r.get("body", "") or r.get("snippet", ""),
            )
            for r in results[:count]
        ]

    # ── formatting ──────────────────────────────────────────────────────────
    @staticmethod
    def _format(query: str, hits: list[SearchHit], source: str) -> str:
        lines = [f'Top web results for "{query}" (via {source}):']
        for i, hit in enumerate(hits, start=1):
            lines.append(f"{i}. {hit.title} — {hit.url}")
            if hit.snippet:
                lines.append(f"   {hit.snippet}")
        return "\n".join(lines)


def load(brain=None, settings: Settings | None = None) -> WebSearchSkill:
    """Instantiate the skill from its own manifest (skill-loading convention).

    Every Martin skill module exposes ``load(brain, settings)`` so the CLI can
    build a registry without hard-coding skill classes.
    """
    manifest = SkillManifest.from_file(MANIFEST_PATH)
    return WebSearchSkill(manifest=manifest, brain=brain, settings=settings)
