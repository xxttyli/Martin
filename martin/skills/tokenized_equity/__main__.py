"""Run the tokenized equity checker directly.

    python -m martin.skills.tokenized_equity               # last 90 days
    python -m martin.skills.tokenized_equity --days 30 --json
    python -m martin.skills.tokenized_equity --no-news     # SEC EDGAR only
"""

from __future__ import annotations

import argparse
import sys

from martin.skills.tokenized_equity.skill import DEFAULT_DAYS, DEFAULT_MAX_DOCS, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m martin.skills.tokenized_equity",
        description="Find new equity launches via tokens through regulated entities.",
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="look-back window")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-news", action="store_true", help="skip news search")
    parser.add_argument("--no-edgar", action="store_true", help="skip SEC EDGAR")
    parser.add_argument(
        "--max-docs",
        type=int,
        default=DEFAULT_MAX_DOCS,
        help="how many SEC filings to download and scan for regulated partners",
    )
    args = parser.parse_args(argv)

    result = load().run(
        "",
        context={
            "days": args.days,
            "edgar": not args.no_edgar,
            "news": not args.no_news,
            "max_docs": args.max_docs,
            "format": "json" if args.json else "text",
        },
    )
    print(result.content)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
