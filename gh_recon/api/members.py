"""Org membership: listing, search, and role lookup."""

from __future__ import annotations

from typing import Any

from ..models import Member, Page
from .base import API_ROOT, DEFAULT_PAGE_SIZE, GitHubError, _next_link, _paginate_list


class MembersMixin:
    """Org member endpoints. Mixed into :class:`GitHubClient`."""

    def _member_from_json(self, m: dict[str, Any]) -> Member:
        return Member(
            login=m["login"],
            id=m["id"],
            type=m.get("type", "User"),
            site_admin=m.get("site_admin", False),
            html_url=m.get("html_url", ""),
        )

    def list_members(
        self, cursor: int | None = None, per_page: int = DEFAULT_PAGE_SIZE
    ) -> Page[Member]:
        """One page of org members (REST ``page``/``per_page`` paging)."""
        page = cursor or 1
        resp = self._get(
            f"{API_ROOT}/orgs/{self.org}/members",
            params={"per_page": per_page, "page": page},
        )
        members = [self._member_from_json(m) for m in resp.json()]
        has_next = _next_link(resp) is not None
        return Page(items=members, next_cursor=(page + 1) if has_next else None)

    def _list_all_members(self, max_results: int = 500) -> list[Member]:
        """Accumulate every org member (used for client-side search filtering)."""
        members: list[Member] = []
        url: str | None = f"{API_ROOT}/orgs/{self.org}/members"
        params: dict[str, Any] | None = {"per_page": 100}
        while url and len(members) < max_results:
            resp = self._get(url, params=params)
            members.extend(self._member_from_json(m) for m in resp.json())
            url = _next_link(resp)
            params = None  # subsequent URLs carry their own query
        return members

    def search_members(
        self,
        query: str,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Member]:
        """Org-scoped user search, one page at a time.

        With no query this is a plain paged listing. GitHub's search API has no
        ``org:`` qualifier, so a substring query falls back to listing members
        and filtering client-side, then slicing the requested page.
        """
        if not query:
            return self.list_members(cursor=cursor, per_page=per_page)
        q = query.lower()
        matches = [m for m in self._list_all_members() if q in m.login.lower()]
        return _paginate_list(matches, cursor or 1, per_page)

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
