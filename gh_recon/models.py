"""Dataclasses returned by the GitHub client and rendered by the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """One page of a larger list.

    ``next_cursor`` is an opaque token to pass back to the same client method to
    fetch the following page (a page number for REST list endpoints, a Link URL
    for the audit log, a slice index for client-side filtered lists). It is
    ``None`` when this is the last page. ``total`` is the full match count when
    known (client-side filtered lists), else ``None``.
    """

    items: list[T]
    next_cursor: Any = None
    total: int | None = None


@dataclass
class Member:
    login: str
    id: int
    type: str
    site_admin: bool
    html_url: str


@dataclass
class Repo:
    name: str
    full_name: str
    private: bool
    archived: bool
    fork: bool
    language: str | None
    stars: int
    forks: int
    open_issues: int
    pushed_at: datetime | None
    description: str | None
    default_branch: str
    html_url: str
    watchers: int = 0
    size: int = 0
    created_at: datetime | None = None


@dataclass
class CommitInfo:
    sha: str
    author: str | None
    date: datetime | None
    message: str


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
class PublicKeys:
    ssh: list[tuple[str, str]] = field(default_factory=list)  # (type, fingerprint)
    gpg: list[tuple[str, list[str]]] = field(default_factory=list)  # (key_id, emails)


@dataclass
class AuditEvent:
    timestamp: datetime | None
    action: str
    actor: str | None
    repo: str | None
    raw: dict[str, Any]


@dataclass
class Runner:
    id: int
    name: str
    os: str
    status: str  # "online" / "offline"
    busy: bool
    labels: list[str] = field(default_factory=list)
    group: str | None = None  # runner group name; None if unknown/ungrouped


@dataclass
class RunnerJob:
    """The job a busy runner is currently executing (best-effort correlation)."""

    runner_name: str
    workflow: str
    job: str
    repo: str
    html_url: str
    started_at: datetime | None
