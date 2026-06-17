"""GitHub Actions self-hosted runners: listing and current-job correlation."""

from __future__ import annotations

from typing import Any

from ..models import Runner, RunnerJob
from .base import API_ROOT, GitHubError, _next_link, _parse_iso, _to_utc


class RunnersMixin:
    """Org Actions runner endpoints. Mixed into :class:`GitHubClient`.

    Listing runners needs an org-admin token (``admin:org``, or fine-grained
    *Self-hosted runners* read). Callers should degrade gracefully on 403.
    """

    def list_runners(self, max_results: int = 200) -> list[Runner]:
        """List the org's self-hosted runners (paginated), tagged with group."""
        group_by_id = self._runner_group_map()
        runners: list[Runner] = []
        url: str | None = f"{API_ROOT}/orgs/{self.org}/actions/runners"
        params: dict[str, Any] | None = {"per_page": 100}
        while url and len(runners) < max_results:
            resp = self._get(url, params=params)
            for r in resp.json().get("runners", []):
                runners.append(
                    Runner(
                        id=r["id"],
                        name=r.get("name", "?"),
                        os=r.get("os", "?"),
                        status=r.get("status", "?"),
                        busy=bool(r.get("busy", False)),
                        labels=[lbl.get("name", "") for lbl in r.get("labels", [])],
                        group=group_by_id.get(r["id"]),
                    )
                )
            url = _next_link(resp)
            params = None
        return runners

    def _runner_group_map(self) -> dict[int, str]:
        """Map runner id -> its runner group name (best-effort).

        Needs the same org-admin scope as listing runners. Runner groups aren't
        carried on the runners endpoint, so this lists the org's groups and the
        runners in each. Degrades to an empty map (runners shown ungrouped) if
        groups are unavailable on the plan or for the token's scope.
        """
        mapping: dict[int, str] = {}
        try:
            url: str | None = f"{API_ROOT}/orgs/{self.org}/actions/runner-groups"
            params: dict[str, Any] | None = {"per_page": 100}
            while url:
                resp = self._get(url, params=params)
                for g in resp.json().get("runner_groups", []):
                    gid, name = g.get("id"), g.get("name", "?")
                    if gid is not None:
                        self._fill_group_runners(gid, name, mapping)
                url = _next_link(resp)
                params = None
        except GitHubError:
            return mapping  # groups unavailable — fall back to ungrouped
        return mapping

    def _fill_group_runners(
        self, group_id: int, name: str, mapping: dict[int, str]
    ) -> None:
        """Record each runner id in the given group into ``mapping``."""
        url: str | None = (
            f"{API_ROOT}/orgs/{self.org}/actions/runner-groups/{group_id}/runners"
        )
        params: dict[str, Any] | None = {"per_page": 100}
        while url:
            resp = self._get(url, params=params)
            for r in resp.json().get("runners", []):
                rid = r.get("id")
                if rid is not None:
                    mapping[rid] = name
            url = _next_link(resp)
            params = None

    def running_jobs(self, max_repos: int = 60) -> dict[str, RunnerJob]:
        """Map runner name -> the job it is currently running.

        GitHub has no org-level "running jobs" endpoint, so this scans
        in-progress workflow runs across the org's most-recently-pushed repos
        (bounded by ``max_repos``) and matches their jobs by ``runner_name``.
        Best-effort: a job on a repo outside the scan window won't be found.
        """
        jobs_by_runner: dict[str, RunnerJob] = {}
        for repo in self._list_all_repos(max_results=max_repos):
            try:
                runs = (
                    self._get(
                        f"{API_ROOT}/repos/{repo.full_name}/actions/runs",
                        params={"status": "in_progress", "per_page": 50},
                    )
                    .json()
                    .get("workflow_runs", [])
                )
            except GitHubError:
                continue  # Actions disabled or inaccessible — skip
            for run in runs:
                try:
                    jobs = (
                        self._get(
                            f"{API_ROOT}/repos/{repo.full_name}/actions/runs/{run['id']}/jobs",
                            params={"per_page": 100},
                        )
                        .json()
                        .get("jobs", [])
                    )
                except GitHubError:
                    continue
                for job in jobs:
                    name = job.get("runner_name")
                    if not name or job.get("status") != "in_progress":
                        continue
                    jobs_by_runner[name] = RunnerJob(
                        runner_name=name,
                        workflow=run.get("name") or run.get("display_title") or "?",
                        job=job.get("name", "?"),
                        repo=repo.name,
                        html_url=job.get("html_url", ""),
                        started_at=_to_utc(_parse_iso(job.get("started_at"))),
                    )
        return jobs_by_runner
