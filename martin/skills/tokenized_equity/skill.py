"""Tokenized equity skill — which companies are launching equity via tokens
through a regulated entity.

Two sources, one registry:

1. **SEC EDGAR full-text search** (free, no key). Finds recent offering and
   disclosure filings (S-1, F-1, 1-A, D, C, 424B4, 8-K) whose text talks about
   tokenized shares / security tokens. Each filing document is then fetched and
   scanned for regulated partners.
2. **News search** via the ``web_search`` skill (Brave → DuckDuckGo) for launches
   announced outside EDGAR (EU/UK/CH/SG venues, press releases).
3. **Regulated-entity registry** (``regulated_entities.json``) — a curated list of
   licensed transfer agents, broker-dealers, ATSs and DLT venues. A launch that
   names one of them is "via a regulated entity".

Each launch gets a verdict:
- ``confirmed``  — SEC filing AND a named regulated partner.
- ``likely``     — a named regulated partner (news), or an SEC filing about
                   tokenized equity with no partner found in the text.
- ``unverified`` — news mention only, no regulated partner named.

Honesty rule (briefing §3.5): if every source fails the skill says so with
``success=False``; it never invents launches. A registry match is a lead, not a
licence check — the report tells the user where to verify.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx

from martin.core.config import Settings
from martin.skills._base import BaseSkill, SkillManifest, SkillResult

SKILL_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SKILL_DIR / "manifest.json"
REGISTRY_PATH = SKILL_DIR / "regulated_entities.json"

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data"

# Filing types where a company launches or discloses an equity offering.
EDGAR_FORMS = ["S-1", "F-1", "1-A", "D", "C", "424B4", "8-K"]
EDGAR_PHRASES = [
    "tokenized shares",
    "tokenized equity",
    "tokenized common stock",
    "tokenized stock",
    "security token",
    "digital asset securities",
]
NEWS_QUERIES = [
    "company launches tokenized shares",
    "tokenized equity offering regulated transfer agent",
    "tokenized stock launch broker-dealer ATS",
    "tokenised shares launch regulated exchange",
]

DEFAULT_DAYS = 90
DEFAULT_MAX_DOCS = 15
MAX_DOC_BYTES = 750_000

EQUITY_RE = re.compile(
    r"\b(shares?|stock|equity|IPO|common|preferred|Reg(?:ulation)?\s?(?:A|D|CF)|"
    r"S-1|F-1|1-A|pre-IPO|share class)\b",
    re.IGNORECASE,
)
NON_EQUITY_RE = re.compile(
    r"\b(stablecoin|treasur(?:y|ies)|money market|bonds?|notes?|credit fund|"
    r"private credit|gold|commodit(?:y|ies))\b",
    re.IGNORECASE,
)

VERDICT_ORDER = {"confirmed": 0, "likely": 1, "unverified": 2}


# ── registry ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RegulatedEntity:
    name: str
    roles: tuple[str, ...]
    regulator: str
    jurisdiction: str
    patterns: tuple[str, ...]

    def label(self) -> str:
        return (
            f"{self.name} ({', '.join(self.roles)}; {self.regulator}) "
            f"[{self.jurisdiction}]"
        )


def load_registry(path: str | Path = REGISTRY_PATH) -> list[RegulatedEntity]:
    """Load the curated regulated-entity registry."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entities = []
    for e in data["entities"]:
        patterns = list(e.get("aliases", []))
        if e.get("match_name", True):
            patterns.insert(0, e["name"])
        entities.append(
            RegulatedEntity(
                name=e["name"],
                roles=tuple(e.get("roles", [])),
                regulator=e.get("regulator", ""),
                jurisdiction=e.get("jurisdiction", ""),
                patterns=tuple(patterns),
            )
        )
    return entities


def match_entities(text: str, registry: list[RegulatedEntity]) -> list[RegulatedEntity]:
    """Return registry entities named in ``text`` (case-sensitive, whole words)."""
    found = []
    for entity in registry:
        for pattern in entity.patterns:
            if re.search(rf"(?<![\w.]){re.escape(pattern)}(?![\w])", text):
                found.append(entity)
                break
    return found


# ── launches ────────────────────────────────────────────────────────────────
@dataclass
class Launch:
    """One company/announcement that looks like a tokenized equity launch."""

    company: str
    url: str
    source: str  # "sec-edgar" or the news provider
    date: str | None = None
    forms: list[str] = field(default_factory=list)
    snippet: str = ""
    partners: list[RegulatedEntity] = field(default_factory=list)
    verdict: str = "unverified"
    new: bool = False  # not seen by a previous run (only set with a state file)

    @property
    def sec_filed(self) -> bool:
        return self.source == "sec-edgar"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["partners"] = [asdict(p) | {"patterns": list(p.patterns)} for p in self.partners]
        return d


def classify(launch: Launch) -> str:
    if launch.sec_filed and launch.partners:
        return "confirmed"
    if launch.partners or launch.sec_filed:
        return "likely"
    return "unverified"


def looks_like_equity(text: str) -> bool:
    """Keep equity launches; drop tokenized treasuries/stablecoins/credit."""
    if EQUITY_RE.search(text):
        return True
    return not NON_EQUITY_RE.search(text)


def parse_days(query: str, default: int = DEFAULT_DAYS) -> int:
    """Pull a look-back window out of a natural-language query."""
    low = query.lower()
    m = re.search(r"(\d+)\s*(day|week|month|year)s?", low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
    for word, days in (
        ("today", 1),
        ("this week", 7),
        ("past week", 7),
        ("last week", 7),
        ("this month", 30),
        ("past month", 30),
        ("last month", 30),
        ("this quarter", 90),
        ("this year", 365),
        ("past year", 365),
        ("last year", 365),
    ):
        if word in low:
            return days
    return default


def _freshness(days: int) -> str:
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"


# ── skill ───────────────────────────────────────────────────────────────────
class TokenizedEquitySkill(BaseSkill):
    """Finds new equity launches via tokens that name a regulated entity."""

    def __init__(self, *args, registry: list[RegulatedEntity] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry = registry if registry is not None else load_registry()

    def run(self, query: str, context: dict | None = None) -> SkillResult:
        context = context or {}
        start = time.perf_counter()
        days = int(context.get("days") or parse_days(query))
        launches, sources, errors = self.scan(
            days=days,
            use_edgar=context.get("edgar", True),
            use_news=context.get("news", True),
            max_docs=int(context.get("max_docs", DEFAULT_MAX_DOCS)),
        )
        if context.get("state_path"):
            mark_new(launches, context["state_path"])
        latency = time.perf_counter() - start

        if not sources:
            return SkillResult(
                content=(
                    "I couldn't check for tokenized equity launches — every source "
                    f"failed. {'; '.join(errors)}"
                ),
                success=False,
                latency=latency,
            )

        if context.get("format") == "json":
            content = json.dumps(
                {
                    "as_of": date.today().isoformat(),
                    "days": days,
                    "sources": sources,
                    "errors": errors,
                    "launches": [l.to_dict() for l in launches],
                },
                indent=2,
            )
        else:
            content = self.format_report(launches, days, sources, errors)
        return SkillResult(
            content=content,
            success=True,
            source="+".join(sources),
            latency=latency,
        )

    def scan(
        self,
        days: int = DEFAULT_DAYS,
        use_edgar: bool = True,
        use_news: bool = True,
        max_docs: int = DEFAULT_MAX_DOCS,
    ) -> tuple[list[Launch], list[str], list[str]]:
        """Return ``(launches, sources_that_worked, error_messages)``."""
        launches: list[Launch] = []
        sources: list[str] = []
        errors: list[str] = []

        if use_edgar:
            try:
                launches += self._edgar_launches(days, max_docs)
                sources.append("sec-edgar")
            except Exception as exc:
                errors.append(f"SEC EDGAR failed ({exc})")

        if use_news:
            try:
                news, provider = self._news_launches(days)
                launches += news
                sources.append(provider)
            except Exception as exc:
                errors.append(f"News search failed ({exc})")

        for launch in launches:
            launch.verdict = classify(launch)
        launches.sort(
            key=lambda l: (VERDICT_ORDER[l.verdict], _neg_date(l.date))
        )
        return launches, sources, errors

    # ── SEC EDGAR ───────────────────────────────────────────────────────────
    def _edgar_headers(self) -> dict[str, str]:
        return {"User-Agent": self.settings.sec_user_agent, "Accept": "*/*"}

    def _edgar_launches(self, days: int, max_docs: int) -> list[Launch]:
        end = date.today()
        begin = end - timedelta(days=days)
        by_company: dict[str, Launch] = {}
        failures = 0

        for phrase in EDGAR_PHRASES:
            try:
                resp = httpx.get(
                    EDGAR_SEARCH_URL,
                    params={
                        "q": f'"{phrase}"',
                        "forms": ",".join(EDGAR_FORMS),
                        "dateRange": "custom",
                        "startdt": begin.isoformat(),
                        "enddt": end.isoformat(),
                    },
                    headers=self._edgar_headers(),
                    timeout=15.0,
                )
                resp.raise_for_status()
                hits = (resp.json().get("hits") or {}).get("hits") or []
            except Exception:
                failures += 1
                continue

            for hit in hits:
                launch = _edgar_hit_to_launch(hit)
                if launch is None:
                    continue
                existing = by_company.get(launch.company)
                if existing is None:
                    launch.snippet = f'mentions "{phrase}"'
                    by_company[launch.company] = launch
                else:
                    for form in launch.forms:
                        if form not in existing.forms:
                            existing.forms.append(form)
                    if (launch.date or "") > (existing.date or ""):
                        existing.date, existing.url = launch.date, launch.url

        if failures == len(EDGAR_PHRASES):
            raise RuntimeError("every EDGAR full-text query failed")

        launches = sorted(by_company.values(), key=lambda l: _neg_date(l.date))
        for launch in launches[:max_docs]:
            text = self._fetch_text(launch.url)
            if text:
                launch.partners = match_entities(text, self.registry)
        return launches

    def _fetch_text(self, url: str) -> str:
        """Fetch a filing document and reduce it to plain text (best-effort)."""
        try:
            resp = httpx.get(url, headers=self._edgar_headers(), timeout=20.0)
            resp.raise_for_status()
        except Exception:
            return ""
        raw = resp.text[:MAX_DOC_BYTES]
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = raw.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#160;", " ")
        return re.sub(r"\s+", " ", raw)

    # ── news ────────────────────────────────────────────────────────────────
    def _news_launches(self, days: int) -> tuple[list[Launch], str]:
        from martin.skills.web_search.skill import load as load_web_search

        searcher = load_web_search(settings=self.settings)
        freshness = _freshness(days)
        launches: list[Launch] = []
        seen: set[str] = set()
        provider = "news"
        last_error: Exception | None = None
        any_ok = False

        for q in NEWS_QUERIES:
            try:
                hits, provider = searcher.search(q, count=8, freshness=freshness)
                any_ok = True
            except Exception as exc:
                last_error = exc
                continue
            for hit in hits:
                if not hit.url or hit.url in seen:
                    continue
                text = f"{hit.title} {hit.snippet}"
                if not re.search(r"(?i)\btoken", text) or not looks_like_equity(text):
                    continue
                seen.add(hit.url)
                launches.append(
                    Launch(
                        company=hit.title,
                        url=hit.url,
                        source=provider,
                        date=hit.date,
                        snippet=hit.snippet,
                        partners=match_entities(text, self.registry),
                    )
                )
        if not any_ok:
            raise RuntimeError(str(last_error) if last_error else "no results")
        return launches, provider

    # ── formatting ──────────────────────────────────────────────────────────
    @staticmethod
    def format_report(
        launches: list[Launch], days: int, sources: list[str], errors: list[str]
    ) -> str:
        lines = [
            f"Tokenized equity launches — last {days} days "
            f"(as of {date.today().isoformat()}, sources: {', '.join(sources)})"
        ]
        if errors:
            lines.append("Partial results: " + "; ".join(errors))
        if not launches:
            lines.append("No tokenized equity launches found in this window.")
            return "\n".join(lines)

        headings = {
            "confirmed": "CONFIRMED — SEC filing + named regulated partner",
            "likely": "LIKELY — regulated partner named, or SEC filing with no partner found",
            "unverified": "UNVERIFIED — news mention, no regulated partner named",
        }
        for verdict, heading in headings.items():
            group = [l for l in launches if l.verdict == verdict]
            if not group:
                continue
            lines.append("")
            lines.append(f"{heading} ({len(group)})")
            for i, l in enumerate(group, start=1):
                meta = []
                if l.forms:
                    meta.append("Form " + "/".join(l.forms))
                if l.date:
                    meta.append(l.date)
                suffix = f" — {', '.join(meta)}" if meta else ""
                tag = "[NEW] " if l.new else ""
                lines.append(f"{i}. {tag}{l.company}{suffix}")
                for p in l.partners:
                    lines.append(f"   ✓ {p.label()}")
                lines.append(f"   {l.url}")
        lines.append("")
        lines.append(
            "A registry match means the launch names a regulated firm — confirm the "
            "licence on FINRA BrokerCheck, the SEC transfer-agent list, or the local "
            "regulator's register before relying on it."
        )
        return "\n".join(lines)


def mark_new(launches: list[Launch], state_path: str | Path) -> None:
    """Flag launches whose URL no previous run has seen, then record them.

    The state file is a JSON list of seen URLs, so daily runs highlight what is
    new since yesterday instead of repeating the whole window.
    """
    path = Path(state_path)
    try:
        seen = set(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        seen = set()
    for launch in launches:
        launch.new = launch.url not in seen
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(seen | {l.url for l in launches}), indent=0),
        encoding="utf-8",
    )


def _edgar_hit_to_launch(hit: dict) -> Launch | None:
    src = hit.get("_source") or {}
    names = src.get("display_names") or []
    ciks = src.get("ciks") or []
    adsh = src.get("adsh") or ""
    doc_id = hit.get("_id") or ""
    if not names or not ciks or not adsh:
        return None
    company = re.split(r"\s{2,}\(|\s\(CIK", names[0])[0].strip()
    filename = doc_id.split(":", 1)[1] if ":" in doc_id else ""
    url = f"{EDGAR_ARCHIVE_URL}/{int(ciks[0])}/{adsh.replace('-', '')}/{filename}"
    form = src.get("form") or (src.get("root_forms") or [""])[0]
    return Launch(
        company=company,
        url=url,
        source="sec-edgar",
        date=src.get("file_date"),
        forms=[form] if form else [],
    )


def _neg_date(d: str | None) -> str:
    """Sort key putting newest ISO dates first and undated items last."""
    if not d or not re.match(r"\d{4}-\d{2}-\d{2}", d):
        return "~"
    # Invert each digit so ascending sort = descending date.
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in d[:10])


def load(brain=None, settings: Settings | None = None) -> TokenizedEquitySkill:
    """Instantiate the skill from its own manifest (skill-loading convention)."""
    manifest = SkillManifest.from_file(MANIFEST_PATH)
    return TokenizedEquitySkill(manifest=manifest, brain=brain, settings=settings)
