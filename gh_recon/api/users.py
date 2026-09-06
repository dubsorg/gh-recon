"""Users: profile, public keys, teams, audit log, and authored-commit activity."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone

from ..models import AuditEvent, Page, PublicKeys, RepoCommitActivity, UserInfo
from .base import API_ROOT, DEFAULT_PAGE_SIZE, GitHubError, _next_link, _parse_iso


class UsersMixin:
    """User-centric endpoints. Mixed into :class:`GitHubClient`."""

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

    def audit_events(
        self,
        login: str,
        cursor: str | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditEvent]:
        """One page of audit-log entries for a given actor within the org."""
        return self.org_audit_events(
            phrase=f"actor:{login}", cursor=cursor, per_page=per_page
        )

    def org_audit_events(
        self,
        phrase: str | None = None,
        cursor: str | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditEvent]:
        """One page of org-wide audit-log entries, optionally search-filtered.

        ``phrase`` uses the audit-log search syntax (``action:``, ``actor:``,
        ``repo:``, ``created:``, free text, …). The audit-log API is
        cursor-paginated, so ``cursor`` is the Link-header URL of the next page
        (returned as ``next_cursor``); ``None`` fetches the first page.
        """
        if cursor:
            resp = self._get(cursor)
        else:
            params: dict = {"per_page": per_page, "order": "desc"}
            if phrase:
                params["phrase"] = phrase
            resp = self._get(f"{API_ROOT}/orgs/{self.org}/audit-log", params=params)
        events: list[AuditEvent] = []
        for e in resp.json():
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
        return Page(items=events, next_cursor=_next_link(resp))

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

    def public_keys(self, login: str) -> PublicKeys:
        """Public SSH and GPG keys for a user (both are public, no special scope)."""
        keys = PublicKeys()
        for k in self._get(f"{API_ROOT}/users/{login}/keys").json():
            keys.ssh.append(_ssh_fingerprint(k.get("key", "")))
        for g in self._get(f"{API_ROOT}/users/{login}/gpg_keys").json():
            emails = [e["email"] for e in (g.get("emails") or []) if e.get("email")]
            key_id = g.get("key_id") or g.get("raw_key", "")[:16]
            keys.gpg.append((key_id, emails))
        return keys

    def whoami(self) -> str | None:
        try:
            return self._get(f"{API_ROOT}/user").json().get("login")
        except GitHubError:
            return None

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


def _ssh_fingerprint(keystr: str) -> tuple[str, str]:
    """Return (key_type, 'SHA256:...') for an OpenSSH public key string."""
    parts = keystr.split()
    if len(parts) < 2:
        return ("?", "")
    ktype = parts[0]
    try:
        blob = base64.b64decode(parts[1])
        digest = hashlib.sha256(blob).digest()
        return (ktype, "SHA256:" + base64.b64encode(digest).decode().rstrip("="))
    except (ValueError, base64.binascii.Error):
        return (ktype, "")
