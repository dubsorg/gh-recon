"""Transport layer: HTTP session, error handling, and parsing helpers."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

import requests

from ..models import Page

API_ROOT = "https://api.github.com"
USER_AGENT = "gh-recon-tui"
DEFAULT_PAGE_SIZE = 20


class GitHubError(RuntimeError):
    """Raised when the GitHub API returns an error we want to surface in the UI."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def resolve_token(explicit: str | None = None) -> str | None:
    """Find a token from arg, env, or the gh CLI."""
    import os

    if explicit:
        return explicit
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


class BaseClient:
    """Shared HTTP plumbing for the domain mixins.

    Holds the org scope and authenticated session; provides the low-level
    ``_get``/``_graphql`` primitives the mixins build on.
    """

    def __init__(self, org: str, token: str | None):
        self.org = org
        self.token = token
        self.session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update(headers)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            raise GitHubError(f"network error: {exc}") from exc
        if resp.status_code == 401:
            raise GitHubError("unauthorized — token missing or invalid", 401)
        if resp.status_code == 403:
            msg = resp.json().get("message", "forbidden") if _is_json(resp) else "forbidden"
            raise GitHubError(f"forbidden — {msg}", 403)
        if resp.status_code == 404:
            raise GitHubError("not found", 404)
        if resp.status_code >= 400:
            msg = resp.json().get("message", resp.reason) if _is_json(resp) else resp.reason
            raise GitHubError(f"HTTP {resp.status_code}: {msg}", resp.status_code)
        return resp

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.session.post(
                f"{API_ROOT}/graphql",
                json={"query": query, "variables": variables},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GitHubError(f"network error: {exc}") from exc
        if resp.status_code == 401:
            raise GitHubError("unauthorized — token missing or invalid", 401)
        if resp.status_code >= 400:
            msg = resp.json().get("message", resp.reason) if _is_json(resp) else resp.reason
            raise GitHubError(f"HTTP {resp.status_code}: {msg}", resp.status_code)
        body = resp.json()
        errors = body.get("errors")
        if errors:
            raise GitHubError(errors[0].get("message", "graphql error"))
        return body.get("data") or {}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_utc(dt: datetime | None) -> datetime | None:
    return dt.astimezone(timezone.utc) if dt is not None else None


def _is_json(resp: requests.Response) -> bool:
    return resp.headers.get("Content-Type", "").startswith("application/json")


def _paginate_list(items: list, page: int, per_page: int) -> Page:
    """Slice an in-memory list into a :class:`Page` (for client-side filtering)."""
    start = (page - 1) * per_page
    chunk = items[start : start + per_page]
    has_next = start + per_page < len(items)
    return Page(
        items=chunk,
        next_cursor=(page + 1) if has_next else None,
        total=len(items),
    )


def _next_link(resp: requests.Response) -> str | None:
    link = resp.headers.get("Link", "")
    for part in link.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().strip("<>")
        rel = section[1].strip()
        if rel == 'rel="next"':
            return url
    return None
