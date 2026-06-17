"""Repositories: listing, search, metadata, contributors, commits, languages."""

from __future__ import annotations

from typing import Any

from ..models import CommitInfo, Page, Repo
from .base import (
    API_ROOT,
    DEFAULT_PAGE_SIZE,
    GitHubError,
    _next_link,
    _paginate_list,
    _parse_iso,
    _to_utc,
)


class ReposMixin:
    """Org repository endpoints. Mixed into :class:`GitHubClient`."""

    def _repo_from_json(self, r: dict[str, Any]) -> Repo:
        return Repo(
            name=r["name"],
            full_name=r.get("full_name", ""),
            private=r.get("private", False),
            archived=r.get("archived", False),
            fork=r.get("fork", False),
            language=r.get("language"),
            stars=r.get("stargazers_count", 0),
            forks=r.get("forks_count", 0),
            open_issues=r.get("open_issues_count", 0),
            pushed_at=_to_utc(_parse_iso(r.get("pushed_at"))),
            description=r.get("description"),
            default_branch=r.get("default_branch", "main"),
            html_url=r.get("html_url", ""),
            watchers=r.get("watchers_count", 0),
            size=r.get("size", 0),
            created_at=_to_utc(_parse_iso(r.get("created_at"))),
        )

    def list_repos(
        self, cursor: int | None = None, per_page: int = DEFAULT_PAGE_SIZE
    ) -> Page[Repo]:
        """One page of org repositories, most recently pushed first."""
        page = cursor or 1
        resp = self._get(
            f"{API_ROOT}/orgs/{self.org}/repos",
            params={"per_page": per_page, "page": page, "sort": "pushed"},
        )
        repos = [self._repo_from_json(r) for r in resp.json()]
        has_next = _next_link(resp) is not None
        return Page(items=repos, next_cursor=(page + 1) if has_next else None)

    def _list_all_repos(self, max_results: int = 500) -> list[Repo]:
        """Accumulate every org repo (for client-side search and run scans)."""
        repos: list[Repo] = []
        url: str | None = f"{API_ROOT}/orgs/{self.org}/repos"
        params: dict[str, Any] | None = {"per_page": 100, "sort": "pushed"}
        while url and len(repos) < max_results:
            resp = self._get(url, params=params)
            repos.extend(self._repo_from_json(r) for r in resp.json())
            url = _next_link(resp)
            params = None
        return repos

    def search_repos(
        self,
        query: str,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Repo]:
        """Filter org repos by name/description substring, one page at a time.

        With no query this is a plain paged listing; a query lists all repos and
        filters client-side (no org-scoped repo search endpoint), then slices.
        """
        if not query:
            return self.list_repos(cursor=cursor, per_page=per_page)
        q = query.lower()
        matches = [
            r
            for r in self._list_all_repos()
            if q in r.name.lower() or (r.description and q in r.description.lower())
        ]
        return _paginate_list(matches, cursor or 1, per_page)

    def _repo_path(self, name: str) -> str:
        return name if "/" in name else f"{self.org}/{name}"

    def get_repo(self, name: str) -> Repo:
        return self._repo_from_json(self._get(f"{API_ROOT}/repos/{self._repo_path(name)}").json())

    def repo_contributors(self, name: str, limit: int = 15) -> list[tuple[str, int]]:
        data = self._get(
            f"{API_ROOT}/repos/{self._repo_path(name)}/contributors",
            params={"per_page": min(limit, 100)},
        ).json()
        return [(c.get("login", "?"), c.get("contributions", 0)) for c in data][:limit]

    def repo_commits(self, name: str, limit: int = 20) -> list[CommitInfo]:
        data = self._get(
            f"{API_ROOT}/repos/{self._repo_path(name)}/commits",
            params={"per_page": min(limit, 100)},
        ).json()
        out: list[CommitInfo] = []
        for c in data:
            commit = c.get("commit") or {}
            author = (c.get("author") or {}).get("login") or (
                commit.get("author") or {}
            ).get("name")
            date = _to_utc(_parse_iso((commit.get("author") or {}).get("date")))
            message = (commit.get("message") or "").splitlines()
            out.append(
                CommitInfo(
                    sha=(c.get("sha") or "")[:7],
                    author=author,
                    date=date,
                    message=message[0] if message else "",
                )
            )
        return out

    def language_bytes(
        self, repo_full_names: list[str], max_repos: int = 25
    ) -> list[tuple[str, int]]:
        """Aggregate language byte counts across the given repos, desc by bytes."""
        totals: dict[str, int] = {}
        for full in repo_full_names[:max_repos]:
            try:
                data = self._get(f"{API_ROOT}/repos/{full}/languages").json()
            except GitHubError:
                continue  # repo gone or inaccessible — skip
            for lang, count in data.items():
                totals[lang] = totals.get(lang, 0) + int(count)
        return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
