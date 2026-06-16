"""Entry point: python -m gh_recon [ORG]"""

from __future__ import annotations

import argparse
import os
import sys

from .api import resolve_token
from .app import GhReconApp


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
    args = parser.parse_args(argv)

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
