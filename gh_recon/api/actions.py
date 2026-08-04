"""GitHub Actions: self-hosted runners, current-job correlation, and usage."""

from __future__ import annotations

from typing import Any

from ..models import ActionsUsage, Runner, RunnerJob, WorkflowInfo
from .base import API_ROOT, GitHubError, _next_link, _parse_iso, _to_utc

# Run statuses that count as "currently running" for a workflow.
_ACTIVE_RUN_STATUSES = frozenset(
    {"queued", "in_progress", "waiting", "requested", "pending"}
)


def _workflow_order(w: WorkflowInfo):
    """Sort key: running first, then most recent run, never-run last."""
    ts = w.last_run_at.timestamp() if w.last_run_at else float("-inf")
    return (not w.running, -ts)


class ActionsMixin:
    """Org Actions endpoints. Mixed into :class:`GitHubClient`.

    Listing runners needs an org-admin token (``admin:org``, or fine-grained
    *Self-hosted runners* read); usage minutes need org billing access. Callers
    should degrade gracefully on 403.
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

    def repo_workflows(self, name: str, limit: int = 30) -> list[WorkflowInfo]:
        """The repo's workflows, each tagged with its most recent run.

        Two bounded calls: the workflow list, then the repo's ~100 most recent
        runs, correlated by ``workflow_id`` (runs come newest-first). Best-effort
        — a workflow whose latest run has aged out of that window shows as never
        run. Returns ``[]`` when Actions is disabled for the repo (404); a
        forbidden runs listing degrades to the bare workflow list.
        """
        repo = self._repo_path(name)
        try:
            data = self._get(
                f"{API_ROOT}/repos/{repo}/actions/workflows",
                params={"per_page": min(limit, 100)},
            ).json()
        except GitHubError as exc:
            if exc.status == 404:
                return []  # Actions disabled for this repo
            raise
        workflows = data.get("workflows", [])[:limit]
        if not workflows:
            return []
        try:
            runs = (
                self._get(
                    f"{API_ROOT}/repos/{repo}/actions/runs",
                    params={"per_page": 100},
                )
                .json()
                .get("workflow_runs", [])
            )
        except GitHubError:
            runs = []  # runs inaccessible — still show the workflow list
        latest: dict[int, dict[str, Any]] = {}
        active: set[int] = set()
        for run in runs:
            wid = run.get("workflow_id")
            if wid is None:
                continue
            latest.setdefault(wid, run)
            if run.get("status") in _ACTIVE_RUN_STATUSES:
                active.add(wid)
        out: list[WorkflowInfo] = []
        for wf in workflows:
            run = latest.get(wf.get("id"))
            status = conclusion = None
            started = None
            duration = None
            if run:
                status = run.get("status")
                conclusion = run.get("conclusion")
                started = _to_utc(
                    _parse_iso(run.get("run_started_at") or run.get("created_at"))
                )
                ended = _to_utc(_parse_iso(run.get("updated_at")))
                if status == "completed" and started and ended:
                    duration = max(0, int((ended - started).total_seconds()))
            out.append(
                WorkflowInfo(
                    id=wf.get("id", 0),
                    name=wf.get("name", "?"),
                    path=wf.get("path", ""),
                    state=wf.get("state", "?"),
                    running=wf.get("id") in active,
                    last_status=status,
                    last_conclusion=conclusion,
                    last_run_at=started,
                    last_duration_s=duration,
                )
            )
        out.sort(key=_workflow_order)
        return out

    def actions_usage(self) -> ActionsUsage:
        """Org Actions usage: billing minutes from the org billing endpoint.

        Minutes come from the legacy org Actions billing endpoint (needs billing
        access; left ``None`` on 403/404, or 410 once the org has moved to the
        new enhanced billing platform, which retired it).
        """
        total = paid = included = None
        by_os: dict[str, int] = {}
        try:
            b = self._get(
                f"{API_ROOT}/orgs/{self.org}/settings/billing/actions"
            ).json()
            total = b.get("total_minutes_used")
            paid = b.get("total_paid_minutes_used")
            included = b.get("included_minutes")
            by_os = {
                k: int(v)
                for k, v in (b.get("minutes_used_breakdown") or {}).items()
                if v
            }
        except GitHubError as exc:
            # 403/404 = no billing access; 410 Gone = org migrated to the new
            # enhanced billing platform, which retired this endpoint. In all
            # three cases leave minutes None and degrade. Surface real errors.
            if exc.status not in (403, 404, 410):
                raise

        return ActionsUsage(
            total_minutes=total,
            paid_minutes=paid,
            included_minutes=included,
            minutes_by_os=by_os,
        )

