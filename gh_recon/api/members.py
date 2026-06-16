"""Org membership: listing, search, and role lookup."""

from __future__ import annotations

from typing import Any

from ..models import Member
from .base import API_ROOT, GitHubError, _next_link


class MembersMixin:
    """Org member endpoints. Mixed into :class:`GitHubClient`."""

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
