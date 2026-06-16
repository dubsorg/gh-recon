"""GitHub REST client for recon, scoped to a single organization.

The client is assembled from per-domain mixins so HTTP/parsing for members,
repos, and users live in their own modules. The dataclasses they return are in
:mod:`gh_recon.models`.
"""

from __future__ import annotations

from .base import BaseClient, GitHubError, resolve_token
from .members import MembersMixin
from .mock import MockClient
from .repos import ReposMixin
from .runners import RunnersMixin
from .users import UsersMixin


class GitHubClient(MembersMixin, ReposMixin, RunnersMixin, UsersMixin, BaseClient):
    """GitHub REST client scoped to a single org (``self.org``)."""


__all__ = ["GitHubClient", "MockClient", "GitHubError", "resolve_token"]
