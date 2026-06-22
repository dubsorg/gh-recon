"""Offline mock client: synthetic data generated at start time.

Mirrors the public surface of :class:`GitHubClient` so the Textual UI can run
without a token or network access (``--mock``). Every dataset is generated once
in :meth:`__init__` from a seed derived from the org name, so a given org yields
stable, internally-consistent data for the life of the process. No HTTP, no auth.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

from ..models import (
    ActionsPerformance,
    ActionsUsage,
    AuditEvent,
    CommitInfo,
    CopilotBilling,
    CopilotLangStat,
    CopilotMetrics,
    Member,
    Page,
    PublicKeys,
    RepoCommitActivity,
    Runner,
    RunnerJob,
    UserInfo,
    WorkflowPerformance,
)
from .base import DEFAULT_PAGE_SIZE, GitHubError, _paginate_list

_FIRST = [
    "ada", "alan", "grace", "linus", "margaret", "dennis", "ken", "barbara",
    "guido", "yukihiro", "bjarne", "anders", "rich", "rob", "brian", "donald",
    "edsger", "john", "joan", "katherine", "radia", "leslie",
]
_LAST = [
    "lovelace", "turing", "hopper", "torvalds", "hamilton", "ritchie",
    "thompson", "liskov", "rossum", "matsumoto", "stroustrup", "perlis",
    "knuth", "dijkstra", "mccarthy", "clarke", "johnson", "perlman", "lamport",
]
_LANGS = ["Python", "Go", "Rust", "TypeScript", "JavaScript", "Ruby", "Java",
          "C", "C++", "Shell", "HTML", "Kotlin", "Swift"]
_LOCATIONS = ["Berlin, DE", "Austin, TX", "Tokyo, JP", "London, UK",
              "Toronto, CA", "São Paulo, BR", "Bangalore, IN", "Remote"]
_REPO_WORDS = ["core", "api", "web", "infra", "cli", "auth", "data", "edge",
               "service", "worker", "bridge", "engine", "gateway", "sdk",
               "pipeline", "dashboard", "scheduler", "registry", "proxy"]
_ACTIONS = ["repo.create", "repo.destroy", "team.add_member", "org.update_member",
            "protected_branch.update", "members.remove", "oauth_access.create",
            "repo.access", "workflows.approve_workflow_job", "secret_scanning.enable"]
_WORKFLOWS = ["CI", "Release", "Deploy", "Lint", "Nightly", "Integration Tests"]
_JOBS = ["build", "test", "lint", "publish", "package", "e2e"]


def _latent(method):
    """Wrap a client method so it sleeps a little first, faking network latency.

    Mock data is generated in-memory and returns instantly, which hides the
    app's async/loading behavior. A short randomized delay makes ``--mock`` feel
    like real round-trips and exercises the loading indicators.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        self._sleep()
        return method(self, *args, **kwargs)

    return wrapper


class MockClient:
    """Drop-in stand-in for :class:`GitHubClient` backed by synthetic data."""

    def __init__(
        self,
        org: str,
        token: str | None = None,
        seed: int | None = None,
        latency: tuple[float, float] | None = (0.4, 1.1),
    ):
        self.org = org
        self.token = token
        self._latency = latency  # (min, max) seconds per call; None disables
        rng = random.Random(seed if seed is not None else _seed_from(org))
        self._now = datetime.now(timezone.utc)
        self._rng = rng

        self._members = self._gen_members(rng, count=rng.randint(24, 40))
        self._logins = [m.login for m in self._members]
        self._repos = self._gen_repos(rng, count=rng.randint(18, 30))
        self._repos_by_name = {r.name: r for r in self._repos}
        self._runners = self._gen_runners(rng, count=rng.randint(4, 10))
        self._user_cache: dict[str, UserInfo] = {}

    # -- generation -------------------------------------------------------

    def _gen_members(self, rng: random.Random, count: int) -> list[Member]:
        logins: list[str] = []
        seen: set[str] = set()
        while len(logins) < count:
            login = f"{rng.choice(_FIRST)}-{rng.choice(_LAST)}"
            if login in seen:
                login = f"{login}{rng.randint(1, 99)}"
            seen.add(login)
            logins.append(login)
        members = []
        for i, login in enumerate(sorted(logins)):
            members.append(
                Member(
                    login=login,
                    id=1000 + i,
                    type="User",
                    site_admin=rng.random() < 0.05,
                    html_url=f"https://github.com/{login}",
                )
            )
        return members

    def _gen_repos(self, rng: random.Random, count: int):
        from ..models import Repo

        names: list[str] = []
        seen: set[str] = set()
        while len(names) < count:
            n = rng.randint(1, 2)
            name = "-".join(rng.sample(_REPO_WORDS, n))
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        repos = []
        for name in names:
            created = self._now - timedelta(days=rng.randint(120, 2000))
            pushed = self._now - timedelta(days=rng.randint(0, 200),
                                           hours=rng.randint(0, 23))
            repos.append(
                Repo(
                    name=name,
                    full_name=f"{self.org}/{name}",
                    private=rng.random() < 0.4,
                    archived=rng.random() < 0.1,
                    fork=rng.random() < 0.15,
                    language=rng.choice(_LANGS),
                    stars=rng.randint(0, 4000),
                    forks=rng.randint(0, 600),
                    open_issues=rng.randint(0, 120),
                    pushed_at=pushed,
                    description=rng.choice([
                        None,
                        f"{name} service for the {self.org} platform",
                        f"Internal tooling: {name}",
                        f"Experimental {rng.choice(_LANGS)} project",
                    ]),
                    default_branch=rng.choice(["main", "master", "trunk"]),
                    html_url=f"https://github.com/{self.org}/{name}",
                    watchers=rng.randint(0, 500),
                    size=rng.randint(50, 500000),
                    created_at=created,
                )
            )
        # most-recently-pushed first, matching list_repos
        repos.sort(key=lambda r: r.pushed_at or self._now, reverse=True)
        return repos

    def _gen_runners(self, rng: random.Random, count: int) -> list[Runner]:
        runners = []
        oses = ["linux", "macos", "windows"]
        groups = ["Default", "gpu-pool", "deploy", "macos-fleet"]
        for i in range(count):
            online = rng.random() < 0.85
            runners.append(
                Runner(
                    id=200 + i,
                    name=f"{rng.choice(['ip', 'gh', 'self'])}-runner-{i:02d}",
                    os=rng.choice(oses),
                    status="online" if online else "offline",
                    busy=online and rng.random() < 0.5,
                    labels=sorted(set(
                        ["self-hosted", rng.choice(oses)]
                        + rng.sample(["x64", "arm64", "gpu", "large"],
                                     rng.randint(0, 2))
                    )),
                    group=rng.choice(groups),
                )
            )
        return runners

    def _user_seed(self, login: str) -> random.Random:
        return random.Random(f"{self.org}/{login}")

    def _sleep(self) -> None:
        if self._latency:
            time.sleep(random.uniform(*self._latency))

    # -- members ----------------------------------------------------------

    @_latent
    def list_members(
        self, cursor: int | None = None, per_page: int = DEFAULT_PAGE_SIZE
    ) -> Page[Member]:
        return _paginate_list(self._members, cursor or 1, per_page)

    @_latent
    def search_members(
        self,
        query: str,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Member]:
        if not query:
            return _paginate_list(self._members, cursor or 1, per_page)
        q = query.lower()
        matches = [m for m in self._members if q in m.login.lower()]
        return _paginate_list(matches, cursor or 1, per_page)

    @_latent
    def member_count(self) -> int:
        return len(self._members)

    @_latent
    def repo_count(self) -> int:
        return len(self._repos)

    # -- copilot ----------------------------------------------------------

    @_latent
    def copilot_billing(self) -> CopilotBilling:
        rng = random.Random(f"{self.org}/copilot/billing")
        total = max(5, int(len(self._members) * rng.uniform(0.4, 0.8)))
        active = int(total * rng.uniform(0.5, 0.95))
        return CopilotBilling(
            total_seats=total,
            active_this_cycle=active,
            inactive_this_cycle=total - active,
            added_this_cycle=rng.randint(0, 5),
            seat_management_setting=rng.choice(
                ["assign_selected", "assign_all", "disabled"]
            ),
            public_code_suggestions=rng.choice(["allow", "block"]),
        )

    @_latent
    def copilot_metrics(self) -> CopilotMetrics:
        rng = random.Random(f"{self.org}/copilot/metrics")
        seats = max(5, int(len(self._members) * 0.6))
        langs = []
        for name in rng.sample(_LANGS, rng.randint(4, 8)):
            suggestions = rng.randint(200, 9000)
            acceptances = int(suggestions * rng.uniform(0.2, 0.55))
            lines_sug = suggestions * rng.randint(1, 4)
            langs.append(
                CopilotLangStat(
                    language=name,
                    engaged_users=rng.randint(1, seats),
                    suggestions=suggestions,
                    acceptances=acceptances,
                    lines_suggested=lines_sug,
                    lines_accepted=int(lines_sug * rng.uniform(0.2, 0.55)),
                )
            )
        langs.sort(key=lambda s: s.suggestions, reverse=True)
        active = rng.randint(int(seats * 0.4), seats)
        end = self._now.date()
        return CopilotMetrics(
            start=(end - timedelta(days=27)).isoformat(),
            end=end.isoformat(),
            days=28,
            active_users_latest=active,
            engaged_users_latest=int(active * rng.uniform(0.6, 0.95)),
            active_users_peak=min(seats, active + rng.randint(0, 6)),
            languages=langs,
        )

    def org_role(self, login: str) -> str | None:
        if login not in self._logins:
            return None
        return "admin" if self._user_seed(login).random() < 0.2 else "member"

    # -- repos ------------------------------------------------------------

    @_latent
    def list_repos(
        self, cursor: int | None = None, per_page: int = DEFAULT_PAGE_SIZE
    ) -> Page:
        return _paginate_list(self._repos, cursor or 1, per_page)

    def _list_all_repos(self, max_results: int = 500) -> list:
        return self._repos[:max_results]

    @_latent
    def search_repos(
        self,
        query: str,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page:
        if not query:
            return _paginate_list(self._repos, cursor or 1, per_page)
        q = query.lower()
        matches = [
            r for r in self._repos
            if q in r.name.lower() or (r.description and q in r.description.lower())
        ]
        return _paginate_list(matches, cursor or 1, per_page)

    @_latent
    def get_repo(self, name: str):
        key = name.split("/")[-1]
        repo = self._repos_by_name.get(key)
        if repo is None:
            raise GitHubError("not found", 404)
        return repo

    @_latent
    def get_readme(self, name: str) -> str | None:
        key = name.split("/")[-1]
        repo = self._repos_by_name.get(key)
        if repo is None:
            return None
        rng = random.Random(f"{self.org}/{key}/readme")
        if rng.random() < 0.15:
            return None  # some repos have no README
        lang = repo.language or "Python"
        desc = repo.description or f"The {key} service."
        return (
            f"# {key}\n\n"
            f"{desc}\n\n"
            f"![build](https://img.shields.io/badge/build-passing-brightgreen) "
            f"![lang](https://img.shields.io/badge/{lang}-blue)\n\n"
            "## Overview\n\n"
            f"`{key}` is part of the **{self.org}** platform. It is written in "
            f"{lang} and follows the org's standard service layout.\n\n"
            "## Installation\n\n"
            "```bash\n"
            f"git clone https://github.com/{self.org}/{key}.git\n"
            f"cd {key}\n"
            "make bootstrap\n"
            "```\n\n"
            "## Usage\n\n"
            "Run the service locally:\n\n"
            "```bash\n"
            "make run\n"
            "```\n\n"
            "## Features\n\n"
            "- Fast and reliable\n"
            "- Fully observable\n"
            "- Battle-tested in production\n\n"
            "## Contributing\n\n"
            "See `CONTRIBUTING.md`. Open a PR against `"
            f"{repo.default_branch}` and request review.\n\n"
            "## License\n\n"
            "Internal — all rights reserved.\n"
        )

    @_latent
    def repo_contributors(self, name: str, limit: int = 15) -> list[tuple[str, int]]:
        rng = random.Random(f"{self.org}/{name}/contributors")
        n = min(limit, rng.randint(3, 15), len(self._logins))
        people = rng.sample(self._logins, n)
        out = [(login, rng.randint(1, 800)) for login in people]
        out.sort(key=lambda kv: kv[1], reverse=True)
        return out[:limit]

    @_latent
    def repo_commits(self, name: str, limit: int = 20) -> list[CommitInfo]:
        rng = random.Random(f"{self.org}/{name}/commits")
        verbs = ["Add", "Fix", "Refactor", "Remove", "Update", "Bump", "Wire up"]
        nouns = ["pagination", "auth flow", "error handling", "the cache layer",
                 "CI config", "the README", "retry logic", "type hints"]
        commits = []
        when = self._now
        for _ in range(min(limit, rng.randint(5, 20))):
            when = when - timedelta(hours=rng.randint(1, 72))
            sha = hashlib.sha1(f"{name}{when}".encode()).hexdigest()[:7]
            commits.append(
                CommitInfo(
                    sha=sha,
                    author=rng.choice(self._logins),
                    date=when,
                    message=f"{rng.choice(verbs)} {rng.choice(nouns)}",
                )
            )
        return commits

    @_latent
    def language_bytes(self, repo_full_names: list[str],
                       max_repos: int = 25) -> list[tuple[str, int]]:
        totals: dict[str, int] = {}
        for full in repo_full_names[:max_repos]:
            rng = random.Random(f"{full}/languages")
            for lang in rng.sample(_LANGS, rng.randint(1, 4)):
                totals[lang] = totals.get(lang, 0) + rng.randint(1000, 800000)
        return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)

    # -- runners ----------------------------------------------------------

    @_latent
    def list_runners(self, max_results: int = 200) -> list[Runner]:
        return self._runners[:max_results]

    @_latent
    def running_jobs(self, max_repos: int = 60) -> dict[str, RunnerJob]:
        jobs: dict[str, RunnerJob] = {}
        for r in self._runners:
            if not r.busy:
                continue
            rng = random.Random(f"{self.org}/{r.name}/job")
            repo = rng.choice(self._repos)
            jobs[r.name] = RunnerJob(
                runner_name=r.name,
                workflow=rng.choice(_WORKFLOWS),
                job=rng.choice(_JOBS),
                repo=repo.name,
                html_url=f"{repo.html_url}/actions/runs/{rng.randint(1, 99999)}",
                started_at=self._now - timedelta(minutes=rng.randint(1, 90)),
            )
        return jobs

    @_latent
    def actions_usage(self, run_scan_repos: int = 40) -> ActionsUsage:
        rng = random.Random(f"{self.org}/actions/usage")
        by_os = {
            "UBUNTU": rng.randint(500, 9000),
            "MACOS": rng.randint(0, 2500),
            "WINDOWS": rng.randint(0, 3500),
        }
        total = sum(by_os.values())
        included = rng.choice([2000, 3000, 50000])
        return ActionsUsage(
            total_minutes=total,
            paid_minutes=max(0, total - included),
            included_minutes=included,
            minutes_by_os=by_os,
            runs_last_30d=rng.randint(50, 6000),
        )

    @_latent
    def actions_performance(
        self, scan_repos: int = 30, window_days: int = 30, job_scan_cap: int = 300
    ) -> ActionsPerformance:
        rng = random.Random(f"{self.org}/actions/perf")
        repos_scanned = rng.randint(5, scan_repos)
        # Build a per-(repo, workflow) breakdown, then derive the aggregate from it.
        workflows: list[WorkflowPerformance] = []
        by_conclusion = {"success": 0, "failure": 0, "cancelled": 0}
        durations: list[float] = []
        for repo in self._repos[:repos_scanned]:
            for wf in rng.sample(_WORKFLOWS, rng.randint(1, len(_WORKFLOWS))):
                runs = rng.randint(3, 120)
                success = int(runs * rng.uniform(0.6, 0.97))
                failure = rng.randint(0, runs - success)
                cancelled = runs - success - failure
                by_conclusion["success"] += success
                by_conclusion["failure"] += failure
                by_conclusion["cancelled"] += cancelled
                avg = rng.uniform(45, 1800)
                durations.extend([avg] * runs)
                workflows.append(
                    WorkflowPerformance(
                        workflow=wf,
                        repo=repo.name,
                        runs=runs,
                        jobs=runs * rng.randint(1, 6),
                        has_failures=failure > 0,
                        avg_duration_s=avg,
                    )
                )
        completed = sum(by_conclusion.values())
        avg_all = statistics.fmean(durations) if durations else None
        return ActionsPerformance(
            window_days=window_days,
            sampled_runs=completed + rng.randint(0, 40),
            completed_runs=completed,
            by_conclusion=by_conclusion,
            avg_duration_s=avg_all,
            median_duration_s=avg_all * rng.uniform(0.6, 0.95) if avg_all else None,
            repos_scanned=repos_scanned,
            workflows=workflows,
        )

    # -- users ------------------------------------------------------------

    @_latent
    def get_user(self, login: str) -> UserInfo:
        if login in self._user_cache:
            return self._user_cache[login]
        rng = self._user_seed(login)
        created = self._now - timedelta(days=rng.randint(400, 5000))
        updated = self._now - timedelta(days=rng.randint(0, 400))
        name_parts = login.replace("-", " ").split()
        name = " ".join(p.capitalize() for p in name_parts) or None
        info = UserInfo(
            login=login,
            name=name,
            id=1000 + (hash(login) % 9000),
            type="User",
            company=rng.choice([None, f"@{self.org}", "Freelance", "Acme Corp"]),
            email=rng.choice([None, f"{login}@example.com"]),
            location=rng.choice([None] + _LOCATIONS),
            bio=rng.choice([
                None,
                "Building things with code.",
                f"{rng.choice(_LANGS)} enthusiast. Opinions my own.",
                "Coffee in, software out.",
            ]),
            blog=rng.choice(["", f"https://{login}.dev"]),
            public_repos=rng.randint(0, 200),
            followers=rng.randint(0, 5000),
            following=rng.randint(0, 500),
            created_at=created.isoformat(),
            updated_at=updated.isoformat(),
            html_url=f"https://github.com/{login}",
            org_role=self.org_role(login),
            raw={},
        )
        self._user_cache[login] = info
        return info

    @_latent
    def audit_events(
        self,
        login: str,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditEvent]:
        rng = random.Random(f"{self.org}/{login}/audit")
        events = []
        when = self._now
        for _ in range(rng.randint(0, 55)):
            when = when - timedelta(hours=rng.randint(1, 200))
            repo = rng.choice(self._repos)
            events.append(
                AuditEvent(
                    timestamp=when,
                    action=rng.choice(_ACTIONS),
                    actor=login,
                    repo=rng.choice([None, repo.full_name]),
                    raw={},
                )
            )
        return _paginate_list(events, cursor or 1, per_page)

    @_latent
    def recent_commit_repos(self, login: str,
                            limit: int = 100) -> list[RepoCommitActivity]:
        rng = random.Random(f"{self.org}/{login}/activity")
        n = min(limit, rng.randint(1, 8), len(self._repos))
        chosen = rng.sample(self._repos, n)
        out = []
        for repo in chosen:
            last = self._now - timedelta(days=rng.randint(0, 120),
                                         hours=rng.randint(0, 23))
            out.append(
                RepoCommitActivity(
                    repo=repo.full_name,
                    last_commit=last,
                    count=rng.randint(1, 60),
                )
            )
        out.sort(
            key=lambda a: a.last_commit or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return out

    @_latent
    def public_keys(self, login: str) -> PublicKeys:
        rng = random.Random(f"{self.org}/{login}/keys")
        keys = PublicKeys()
        for _ in range(rng.randint(0, 3)):
            blob = rng.getrandbits(2048).to_bytes(256, "big")
            digest = hashlib.sha256(blob).digest()
            fp = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
            keys.ssh.append((rng.choice(["ssh-ed25519", "ssh-rsa"]), fp))
        for _ in range(rng.randint(0, 2)):
            key_id = "".join(rng.choice("0123456789ABCDEF") for _ in range(16))
            keys.gpg.append((key_id, [f"{login}@example.com"]))
        return keys

    def whoami(self) -> str | None:
        return "mock-user"

    @_latent
    def user_teams(self, login: str) -> list[str]:
        rng = random.Random(f"{self.org}/{login}/teams")
        pool = ["Platform", "Security", "Frontend", "Backend", "SRE", "Data",
                "Design", "Release Engineering", "Developer Experience"]
        return sorted(rng.sample(pool, rng.randint(0, 4)))


def _seed_from(org: str) -> int:
    return int(hashlib.sha256(org.encode()).hexdigest(), 16) % (2**32)
