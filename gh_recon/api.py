"""Minimal GitHub REST client for recon, scoped to a single organization."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

API_ROOT = "https://api.github.com"
USER_AGENT = "gh-recon-tui"


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


@dataclass
class Member:
    login: str
    id: int
    type: str
    site_admin: bool
    html_url: str


@dataclass
class UserInfo:
    login: str
    name: str | None
    id: int
    type: str
    company: str | None
    email: str | None
    location: str | None
    bio: str | None
    blog: str | None
    public_repos: int
    followers: int
    following: int
    created_at: str | None
    updated_at: str | None
    html_url: str
    org_role: str | None = None  # admin/member or None if not a member
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepoCommitActivity:
    repo: str
    last_commit: datetime | None
    count: int


@dataclass
class AuditEvent:
    timestamp: datetime | None
    action: str
    actor: str | None
    repo: str | None
    raw: dict[str, Any]


class GitHubClient:
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

    # -- low level ---------------------------------------------------------
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

    # -- org membership ----------------------------------------------------
    def list_members(self, max_results: int = 500) -> list[Member]:
        """List org members (paginated)."""
        members: list[Member] = []
        url: str | None = f"{API_ROOT}/orgs/{self.org}/members"
        params: dict[str, Any] | None = {"per_page": 100}
        while url and len(members) < max_results:
            resp = self._get(url, params=params)
            for m in resp.json():
                members.append(
                    Member(
                        login=m["login"],
                        id=m["id"],
                        type=m.get("type", "User"),
                        site_admin=m.get("site_admin", False),
                        html_url=m.get("html_url", ""),
                    )
                )
            url = _next_link(resp)
            params = None  # subsequent URLs carry their own query
        return members

    def search_members(self, query: str, max_results: int = 500) -> list[Member]:
        """Org-scoped user search: filter members by login substring."""
        members = self.list_members(max_results=max_results)
        if not query:
            return members
        q = query.lower()
        return [m for m in members if q in m.login.lower()]

    def org_role(self, login: str) -> str | None:
        """Return 'admin'/'member' if the user belongs to the org, else None."""
        try:
            resp = self._get(f"{API_ROOT}/orgs/{self.org}/memberships/{login}")
        except GitHubError as exc:
            if exc.status in (403, 404):
                return None
            raise
        data = resp.json()
        if data.get("state") == "active":
            return data.get("role")
        return data.get("state")  # e.g. "pending"

    # -- user --------------------------------------------------------------
    def get_user(self, login: str) -> UserInfo:
        data = self._get(f"{API_ROOT}/users/{login}").json()
        info = UserInfo(
            login=data["login"],
            name=data.get("name"),
            id=data["id"],
            type=data.get("type", "User"),
            company=data.get("company"),
            email=data.get("email"),
            location=data.get("location"),
            bio=data.get("bio"),
            blog=data.get("blog"),
            public_repos=data.get("public_repos", 0),
            followers=data.get("followers", 0),
            following=data.get("following", 0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            html_url=data.get("html_url", ""),
            raw=data,
        )
        try:
            info.org_role = self.org_role(login)
        except GitHubError:
            info.org_role = None
        return info

    def audit_events(self, login: str, limit: int = 30) -> list[AuditEvent]:
        """Recent audit-log entries for a given actor within the org."""
        params = {
            "phrase": f"actor:{login}",
            "per_page": min(limit, 100),
            "order": "desc",
        }
        resp = self._get(f"{API_ROOT}/orgs/{self.org}/audit-log", params=params)
        events: list[AuditEvent] = []
        for e in resp.json()[:limit]:
            ts = e.get("@timestamp") or e.get("created_at")
            dt = (
                datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                if isinstance(ts, (int, float))
                else None
            )
            events.append(
                AuditEvent(
                    timestamp=dt,
                    action=e.get("action", "?"),
                    actor=e.get("actor"),
                    repo=e.get("repo") or e.get("repository"),
                    raw=e,
                )
            )
        return events

    def recent_commit_repos(
        self, login: str, limit: int = 100
    ) -> list[RepoCommitActivity]:
        """Repos in the org the user has recently authored commits to.

        Uses the commit search API (default-branch commits, may lag indexing).
        """
        params = {
            "q": f"author:{login} org:{self.org}",
            "sort": "author-date",
            "order": "desc",
            "per_page": min(limit, 100),
        }
        resp = self._get(f"{API_ROOT}/search/commits", params=params)
        agg: dict[str, RepoCommitActivity] = {}
        for item in resp.json().get("items", []):
            repo = (item.get("repository") or {}).get("full_name")
            if not repo:
                continue
            date_str = ((item.get("commit") or {}).get("author") or {}).get("date")
            dt = _parse_iso(date_str)
            if dt is not None:
                dt = dt.astimezone(timezone.utc)
            entry = agg.get(repo)
            if entry is None:
                agg[repo] = RepoCommitActivity(repo=repo, last_commit=dt, count=1)
            else:
                entry.count += 1
                if dt and (entry.last_commit is None or dt > entry.last_commit):
                    entry.last_commit = dt
        return sorted(
            agg.values(),
            key=lambda a: a.last_commit or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def whoami(self) -> str | None:
        try:
            return self._get(f"{API_ROOT}/user").json().get("login")
        except GitHubError:
            return None

    # -- teams -------------------------------------------------------------
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

    def user_teams(self, login: str) -> list[str]:
        """Org teams the given user belongs to (requires read:org)."""
        query = """
        query($org: String!, $user: String!, $cursor: String) {
          organization(login: $org) {
            teams(first: 100, userLogins: [$user], after: $cursor) {
              pageInfo { hasNextPage endCursor }
              nodes { name slug }
            }
          }
        }
        """
        teams: list[str] = []
        cursor: str | None = None
        while True:
            data = self._graphql(query, {"org": self.org, "user": login, "cursor": cursor})
            org = data.get("organization")
            if not org:
                break
            conn = org["teams"]
            teams.extend(n["name"] for n in conn["nodes"])
            page = conn["pageInfo"]
            if page["hasNextPage"]:
                cursor = page["endCursor"]
            else:
                break
        return teams


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_json(resp: requests.Response) -> bool:
    return resp.headers.get("Content-Type", "").startswith("application/json")


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
