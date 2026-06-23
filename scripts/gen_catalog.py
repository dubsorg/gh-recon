#!/usr/bin/env python3
"""Generate the API-explorer endpoint catalog from GitHub's OpenAPI description.

Downloads (or reads) the GitHub REST OpenAPI spec, filters it to org-scoped and
GitHub Enterprise Cloud endpoints (plus a few general utility endpoints), and
writes ``gh_recon/api/_catalog_data.py`` — a committed, data-only module the app
imports at runtime. Keeping generation offline-of-runtime means the extension
needs no extra dependency or network call to populate the explorer.

Usage:
    python scripts/gen_catalog.py                 # download the latest spec
    python scripts/gen_catalog.py --spec FILE     # use a local spec JSON
    python scripts/gen_catalog.py --out PATH      # override output module
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

SPEC_URL = (
    "https://raw.githubusercontent.com/github/rest-api-description/main/"
    "descriptions/api.github.com/api.github.com.json"
)
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "gh_recon" / "api" / "_catalog_data.py"

_METHODS = ("get", "post", "put", "patch", "delete")
# Non-scoped endpoints worth keeping for recon convenience.
_GENERAL_PATHS = {"/user", "/rate_limit", "/meta"}


def _is_scoped(path: str) -> bool:
    return "/orgs/" in path or "/enterprises/" in path or path in _GENERAL_PATHS


def _load_spec(spec_arg: str | None) -> dict:
    if spec_arg:
        return json.loads(Path(spec_arg).read_text())
    import requests  # only needed when downloading

    print(f"downloading {SPEC_URL} …", file=sys.stderr)
    resp = requests.get(SPEC_URL, timeout=180)
    resp.raise_for_status()
    return resp.json()


def _category(op: dict, path: str) -> str:
    xg = op.get("x-github", {})
    if xg.get("category"):
        return xg["category"]
    tags = op.get("tags")
    if tags:
        return tags[0]
    if path in _GENERAL_PATHS:
        return "general"
    return "other"


def _summary(op: dict) -> str:
    return (op.get("summary") or op.get("operationId") or "").strip()


def build_rows(spec: dict) -> list[tuple[str, str, str, str]]:
    paths = spec.get("paths", {})
    rows: list[tuple[str, str, str, str]] = []
    for path, item in paths.items():
        if not _is_scoped(path):
            continue
        for method, op in item.items():
            if method.lower() not in _METHODS or not isinstance(op, dict):
                continue
            rows.append(
                (method.upper(), path, _summary(op), _category(op, path))
            )
    # Deterministic: group by path, then by HTTP-verb order.
    order = {m.upper(): i for i, m in enumerate(_METHODS)}
    rows.sort(key=lambda r: (r[1], order.get(r[0], 99)))
    return rows


def render_module(rows: list[tuple[str, str, str, str]], version: str) -> str:
    today = _dt.date.today().isoformat()
    lines = [
        '"""Auto-generated API-explorer catalog. DO NOT EDIT BY HAND.',
        "",
        "Regenerate with ``python scripts/gen_catalog.py``.",
        f"Source: GitHub OpenAPI (github/rest-api-description), info.version {version}.",
        f"Generated: {today}. Each row is (method, path, summary, category).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "ENDPOINTS: list[tuple[str, str, str, str]] = [",
    ]
    for method, path, summary, category in rows:
        lines.append(
            f"    ({method!r}, {path!r}, {summary!r}, {category!r}),"
        )
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", help="path to a local OpenAPI JSON (else download)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output module path")
    args = ap.parse_args()

    spec = _load_spec(args.spec)
    version = spec.get("info", {}).get("version", "unknown")
    rows = build_rows(spec)
    Path(args.out).write_text(render_module(rows, version))
    print(f"wrote {len(rows)} endpoints to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
