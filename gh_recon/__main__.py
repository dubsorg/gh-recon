"""Entry point: python -m gh_recon [ORG]"""

from __future__ import annotations

import argparse
import os
import sys

from .api import resolve_token
from .ui import GhReconApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gh-recon",
        description="TUI for GitHub organization recon (member search + user info + audit log).",
    )
    parser.add_argument(
        "org",
        nargs="?",
        default=os.environ.get("GH_RECON_ORG"),
        help="GitHub organization to scope to (or set GH_RECON_ORG). Prompted if omitted.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub token. Defaults to GH_TOKEN/GITHUB_TOKEN env or `gh auth token`.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run against synthetic data generated at start time (no token/network).",
    )
    args = parser.parse_args(argv)

    if args.mock:
        org = args.org or "mock-org"
        app = GhReconApp(org=org, token=None, mock=True)
        app.run()
        return 0

    token = resolve_token(args.token)
    if not token:
        print(
            "warning: no GitHub token found (GH_TOKEN/GITHUB_TOKEN/`gh auth token`).\n"
            "         Unauthenticated requests are heavily rate-limited and audit log "
            "will be unavailable.",
            file=sys.stderr,
        )

    app = GhReconApp(org=args.org, token=token)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
