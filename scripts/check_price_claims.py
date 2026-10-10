#!/usr/bin/env python3
"""Fail when a docs page calls a paid Limitguard tool or endpoint free.

Hand-written sentences are not touched by the generated-content sync, so they
can go stale when a price changes: on 2026-10-11 pricing.mdx and the AI-agent
guide still said `verify_wallet` was free after it became $0.11 (#216). This
check reads what is paid and what is free from two sources that are generated
from the product itself, never from a list kept here:

- MCP tools: the tools table in the public limitguard-mcp README (each row
  states the tool's price, or that it is free);
- REST paths: the live https://api.limitguard.ai/.well-known/x402.json.

Rule: in a clause (text between sentence ends, semicolons or line breaks) that
claims "free" or "$0", no paid tool or paid path may be named. A clause such as
"`verify_wallet` costs $0.11" next to "... are free" passes, because the two
claims sit in different clauses.

Exit 1 with one line per finding; exit 0 when clean. Network errors fail the
check, because a check that cannot read its sources has not checked anything.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

README = "https://raw.githubusercontent.com/jwconsultancyteam/limitguard-mcp/main/README.md"
X402 = "https://api.limitguard.ai/.well-known/x402.json"
UA = {"User-Agent": "limitguard-docs-price-claims"}

FREE_CLAIM = re.compile(r"\bfree\b|\$0(?:\.00)?(?![.\d])", re.I)
TICKED = re.compile(r"`([^`]+)`")
CLAUSE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n")


def fetch(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8")


def tool_prices(readme: str) -> tuple[set[str], set[str]]:
    """(paid tools, free tools) from the README tools table."""
    paid, free = set(), set()
    for line in readme.splitlines():
        m = re.match(r"\|\s*`([a-z_]+)`\s*\|(.*)", line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2)
        if re.match(r"\s*Free\b", rest) or re.search(r"\bFree \(\$0\)", rest):
            free.add(name)
        else:
            paid.add(name)
    return paid, free


def paid_paths(x402_json: str) -> set[str]:
    paths = set()
    for ep in json.loads(x402_json).get("endpoints", []):
        if float(ep.get("price_usdc") or 0) > 0:
            paths.add(ep["path"])
    return paths


def findings(docs_root: pathlib.Path, paid: set[str]) -> list[str]:
    out = []
    # The self-test fixture uses a .fixture extension: Mintlify publishes every
    # .mdx file as a page, and a page holding a stale claim must never go live.
    pattern = "*.fixture" if docs_root.name == "price-claims-fixture" else "*.mdx"
    for page in sorted(docs_root.rglob(pattern)):
        if "node_modules" in page.parts:
            continue
        for lineno, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("|"):
                continue  # tables are generated and carry their own price column
            for clause in CLAUSE_SPLIT.split(line):
                if not FREE_CLAIM.search(clause):
                    continue
                for ident in TICKED.findall(clause):
                    key = ident.split()[-1] if ident.startswith(("POST ", "GET ")) else ident
                    if key in paid:
                        out.append(f"{page.relative_to(docs_root)}:{lineno}: `{ident}` is paid but this clause says free: {clause.strip()[:160]}")
    return out


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    try:
        paid_tools, free_tools = tool_prices(fetch(README))
        paths = paid_paths(fetch(X402))
    except Exception as exc:  # noqa: BLE001
        print(f"cannot read the price sources: {type(exc).__name__}: {exc}")
        return 1
    if not paid_tools or not paths:
        print(f"price sources look empty (paid tools {len(paid_tools)}, paid paths {len(paths)})")
        return 1
    found = findings(root, paid_tools | paths)
    for f in found:
        print(f)
    print(f"checked: {len(paid_tools)} paid tools, {len(free_tools)} free tools, {len(paths)} paid paths; findings: {len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
