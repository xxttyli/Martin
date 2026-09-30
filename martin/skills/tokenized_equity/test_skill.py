"""Tests for the tokenized_equity skill.

Network is fully mocked. We verify behavior: EDGAR hits become launches, filing
text is scanned for regulated partners, news is filtered to equity, verdicts
rank correctly, and total source failure is reported honestly.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from martin.core.config import Settings
from martin.skills.tokenized_equity.skill import (
    EDGAR_SEARCH_URL,
    Launch,
    TokenizedEquitySkill,
    classify,
    load,
    load_registry,
    looks_like_equity,
    match_entities,
    parse_days,
)
from martin.skills.web_search.skill import SearchHit, SearchUnavailable

REGISTRY = load_registry()


def make_skill() -> TokenizedEquitySkill:
    return load(settings=Settings(_env_file=None, brave_api_key=""))


def fake_response(payload=None, text=""):
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
        text=text,
    )


EDGAR_PAYLOAD = {
    "hits": {
        "hits": [
            {
                "_id": "0001234567-26-000010:acme-s1.htm",
                "_source": {
                    "display_names": ["Acme Robotics Inc.  (ACME)  (CIK 0001234567)"],
                    "ciks": ["0001234567"],
                    "adsh": "0001234567-26-000010",
                    "form": "S-1",
                    "file_date": "2026-09-12",
                },
            },
            {
                "_id": "0007654321-26-000002:primary_doc.xml",
                "_source": {
                    "display_names": ["Beta Farms LLC  (CIK 0007654321)"],
                    "ciks": ["0007654321"],
                    "adsh": "0007654321-26-000002",
                    "form": "D",
                    "file_date": "2026-08-01",
                },
            },
        ]
    }
}

DOCS = {
    "acme-s1.htm": "<html><p>Our tokenized shares are recorded by "
    "<b>Securitize</b>, an SEC-registered transfer agent.</p></html>",
    "primary_doc.xml": "<xml>Offering of tokenized common stock.</xml>",
}


def fake_httpx_get(url, params=None, headers=None, timeout=None):
    assert headers and "User-Agent" in headers  # SEC requires a declared UA
    if url == EDGAR_SEARCH_URL:
        return fake_response(EDGAR_PAYLOAD)
    for name, body in DOCS.items():
        if url.endswith(name):
            return fake_response(text=body)
    raise AssertionError(f"unexpected URL {url}")


class FakeSearcher:
    def __init__(self, hits=None, fail=False):
        self.hits = hits or []
        self.fail = fail

    def search(self, query, count=5, freshness=None):
        if self.fail:
            raise SearchUnavailable("ddg down")
        return self.hits, "duckduckgo"


def patch_news(mocker, searcher):
    mocker.patch(
        "martin.skills.web_search.skill.load", return_value=searcher
    )


NEWS_HITS = [
    SearchHit(
        title="Gamma Air launches tokenized shares on Archax",
        url="http://news.example/gamma",
        snippet="UK airline start-up offers tokenised equity to investors.",
        date="2026-09-20T09:00:00",
    ),
    SearchHit(
        title="Delta Coffee to issue stock tokens",
        url="http://news.example/delta",
        snippet="Delta plans a token for its shares.",
    ),
    SearchHit(
        title="Fund launches tokenized treasury fund",
        url="http://news.example/treasury",
        snippet="A tokenized money market product.",
    ),
]


# ── registry ────────────────────────────────────────────────────────────────
def test_registry_matches_names_and_aliases():
    names = {e.name for e in match_entities("Listed via Securitize and xStocks.", REGISTRY)}
    assert names == {"Securitize", "Backed"}


def test_ambiguous_names_only_match_aliases():
    # "Republic" / "Figure" are common words — only their aliases count.
    text = "The Republic of Figure 3 shows shares were Backed by assets."
    assert match_entities(text, REGISTRY) == []
    assert [e.name for e in match_entities("via OpenDeal Broker LLC", REGISTRY)] == [
        "Republic"
    ]


# ── helpers ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "query,days",
    [
        ("tokenized shares in the last 30 days", 30),
        ("equity tokens past 2 weeks", 14),
        ("security tokens this month", 30),
        ("tokenized equity", 90),
    ],
)
def test_parse_days(query, days):
    assert parse_days(query) == days


def test_equity_filter_drops_treasuries():
    assert looks_like_equity("tokenized shares of Acme")
    assert not looks_like_equity("tokenized treasury money market fund")


def test_classify_verdicts():
    partner = REGISTRY[0]
    assert classify(Launch("a", "u", "sec-edgar", partners=[partner])) == "confirmed"
    assert classify(Launch("a", "u", "sec-edgar")) == "likely"
    assert classify(Launch("a", "u", "brave", partners=[partner])) == "likely"
    assert classify(Launch("a", "u", "brave")) == "unverified"


# ── end to end ──────────────────────────────────────────────────────────────
def test_scan_combines_edgar_and_news(mocker):
    mocker.patch(
        "martin.skills.tokenized_equity.skill.httpx.get", side_effect=fake_httpx_get
    )
    patch_news(mocker, FakeSearcher(NEWS_HITS))
    skill = make_skill()

    launches, sources, errors = skill.scan(days=90)

    assert sources == ["sec-edgar", "duckduckgo"]
    assert errors == []
    by_name = {l.company: l for l in launches}
    # Deduped across the EDGAR phrase queries.
    assert list(by_name).count("Acme Robotics Inc.") == 1

    acme = by_name["Acme Robotics Inc."]
    assert acme.verdict == "confirmed"
    assert acme.forms == ["S-1"]
    assert acme.url.endswith("/1234567/000123456726000010/acme-s1.htm")
    assert [p.name for p in acme.partners] == ["Securitize"]

    assert by_name["Beta Farms LLC"].verdict == "likely"
    gamma = by_name["Gamma Air launches tokenized shares on Archax"]
    assert gamma.verdict == "likely"
    assert by_name["Delta Coffee to issue stock tokens"].verdict == "unverified"
    # Tokenized treasuries are not equity launches.
    assert "Fund launches tokenized treasury fund" not in by_name

    # Ranked: confirmed first, unverified last.
    assert launches[0].company == "Acme Robotics Inc."
    assert launches[-1].verdict == "unverified"


def test_run_text_report(mocker):
    mocker.patch(
        "martin.skills.tokenized_equity.skill.httpx.get", side_effect=fake_httpx_get
    )
    patch_news(mocker, FakeSearcher(NEWS_HITS))

    result = make_skill().run("which companies launched tokenized shares in the last 30 days")

    assert result.success is True
    assert "last 30 days" in result.content
    assert "CONFIRMED" in result.content
    assert "Securitize (transfer agent, broker-dealer, ATS; SEC / FINRA) [US]" in result.content
    assert "BrokerCheck" in result.content  # tells the user to verify


def test_run_json(mocker):
    mocker.patch(
        "martin.skills.tokenized_equity.skill.httpx.get", side_effect=fake_httpx_get
    )
    patch_news(mocker, FakeSearcher([]))

    result = make_skill().run("", context={"days": 7, "format": "json"})

    data = json.loads(result.content)
    assert data["days"] == 7
    assert data["launches"][0]["verdict"] == "confirmed"
    assert data["launches"][0]["partners"][0]["regulator"] == "SEC / FINRA"


def test_partial_failure_still_reports(mocker):
    mocker.patch(
        "martin.skills.tokenized_equity.skill.httpx.get",
        side_effect=RuntimeError("403"),
    )
    patch_news(mocker, FakeSearcher(NEWS_HITS))

    result = make_skill().run("tokenized equity")

    assert result.success is True
    assert "Partial results: SEC EDGAR failed" in result.content
    assert "Gamma Air" in result.content


def test_all_sources_down_fails_honestly(mocker):
    mocker.patch(
        "martin.skills.tokenized_equity.skill.httpx.get",
        side_effect=RuntimeError("403"),
    )
    patch_news(mocker, FakeSearcher(fail=True))

    result = make_skill().run("tokenized equity")

    assert result.success is False
    assert "couldn't check" in result.content.lower()
    assert "SEC EDGAR failed" in result.content


def test_load_builds_skill_from_manifest():
    skill = load(settings=Settings(_env_file=None))
    assert isinstance(skill, TokenizedEquitySkill)
    assert skill.name == "tokenized_equity"
    assert "tokenized shares" in skill.manifest.triggers
    assert skill.manifest.requires == []
