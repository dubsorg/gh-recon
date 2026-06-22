"""GitHub Actions: self-hosted runners, current-job correlation, and usage."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import (
    ActionsPerformance,
    ActionsUsage,
    Runner,
    RunnerJob,
    WorkflowPerformance,
)
from .base import API_ROOT, GitHubError, _next_link, _parse_iso, _to_utc


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

    def actions_usage(self, run_scan_repos: int = 40) -> ActionsUsage:
        """Org Actions usage: billing minutes + a best-effort 30-day run count.

        Minutes come from the legacy org Actions billing endpoint (needs billing
        access; left ``None`` on 403/404, or 410 once the org has moved to the
        new enhanced billing platform, which retired it). GitHub has no
        org-level run count, so
        runs are summed from each repo's ``actions/runs?created=>=`` ``total_count``
        over the most-recently-pushed repos (bounded by ``run_scan_repos``).
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

        since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        runs = 0
        counted = False
        for repo in self._list_all_repos(max_results=run_scan_repos):
            try:
                data = self._get(
                    f"{API_ROOT}/repos/{repo.full_name}/actions/runs",
                    params={"created": f">={since}", "per_page": 1},
                ).json()
            except GitHubError:
                continue  # Actions disabled or inaccessible — skip
            runs += int(data.get("total_count", 0))
            counted = True

        return ActionsUsage(
            total_minutes=total,
            paid_minutes=paid,
            included_minutes=included,
            minutes_by_os=by_os,
            runs_last_30d=runs if counted else None,
        )

    def actions_performance(
        self, scan_repos: int = 30, window_days: int = 30, job_scan_cap: int = 300
    ) -> ActionsPerformance:
        """Org Actions performance over the past ``window_days`` (best-effort).

        GitHub has no org-level performance endpoint, so this samples the most
        recent page of workflow runs created within the window from each of the
        org's most-recently-pushed repos (bounded by ``scan_repos``) and
        aggregates conclusions and run durations. Bounded and best-effort: runs
        beyond the first page per repo, or on repos outside the scan window,
        aren't counted, so the figures describe the sample rather than the org.

        Runs are also grouped per ``(repo, workflow)`` into a breakdown
        (``workflows``). Job counts aren't carried on the runs endpoint, so
        ``WorkflowPerformance.jobs`` is estimated from a bounded, round-robin
        sample of per-run job counts (total budget ``job_scan_cap``) extrapolated
        to each workflow's run count — fair across workflows but still an estimate.
        """
        since = (
            datetime.now(timezone.utc) - timedelta(days=window_days)
        ).date().isoformat()
        by_conclusion: dict[str, int] = {}
        durations: list[float] = []
        sampled = completed = repos_scanned = 0
        # (repo_name, workflow) -> aggregation, including run ids for job sampling.
        agg: dict[tuple[str, str], dict[str, Any]] = {}
        for repo in self._list_all_repos(max_results=scan_repos):
            try:
                runs = (
                    self._get(
                        f"{API_ROOT}/repos/{repo.full_name}/actions/runs",
                        params={"created": f">={since}", "per_page": 100},
                    )
                    .json()
                    .get("workflow_runs", [])
                )
            except GitHubError:
                continue  # Actions disabled or inaccessible — skip
            repos_scanned += 1
            for run in runs:
                sampled += 1
                if run.get("status") != "completed":
                    continue  # queued / in_progress — no duration or conclusion yet
                completed += 1
                concl = run.get("conclusion") or "unknown"
                by_conclusion[concl] = by_conclusion.get(concl, 0) + 1
                wf = run.get("name") or run.get("display_title") or "?"
                row = agg.setdefault(
                    (repo.name, wf),
                    {
                        "full_name": repo.full_name,
                        "runs": 0,
                        "durations": [],
                        "fail": False,
                        "run_ids": [],
                    },
                )
                row["runs"] += 1
                if run.get("id") is not None:
                    row["run_ids"].append(run["id"])
                if concl == "failure":
                    row["fail"] = True
                start = _to_utc(
                    _parse_iso(run.get("run_started_at") or run.get("created_at"))
                )
                end = _to_utc(_parse_iso(run.get("updated_at")))
                if start and end and end >= start:
                    dur = (end - start).total_seconds()
                    durations.append(dur)
                    row["durations"].append(dur)

        jobs_by_key = self._sample_job_counts(agg, job_scan_cap)
        workflows = [
            WorkflowPerformance(
                workflow=wf,
                repo=repo_name,
                runs=row["runs"],
                jobs=jobs_by_key[(repo_name, wf)],
                has_failures=row["fail"],
                avg_duration_s=(
                    statistics.fmean(row["durations"]) if row["durations"] else None
                ),
            )
            for (repo_name, wf), row in agg.items()
        ]

        return ActionsPerformance(
            window_days=window_days,
            sampled_runs=sampled,
            completed_runs=completed,
            by_conclusion=by_conclusion,
            avg_duration_s=statistics.fmean(durations) if durations else None,
            median_duration_s=statistics.median(durations) if durations else None,
            repos_scanned=repos_scanned,
            workflows=workflows,
        )

    def _sample_job_counts(
        self, agg: dict[tuple[str, str], dict[str, Any]], budget: int
    ) -> dict[tuple[str, str], int]:
        """Estimate total jobs per workflow group within a global call budget.

        The runs endpoint has no job count, so this round-robins a bounded number
        of ``runs/{id}/jobs`` ``total_count`` lookups across groups (so every
        workflow is sampled before any is sampled twice) and extrapolates each
        group's mean jobs-per-run to its full run count. Best-effort: groups left
        unsampled when the budget runs out report ``0``.
        """
        sampled_sum: dict[tuple[str, str], int] = {k: 0 for k in agg}
        sampled_n: dict[tuple[str, str], int] = {k: 0 for k in agg}
        # Round-robin: one run id per group per pass until the budget is spent.
        cursors = {k: 0 for k in agg}
        spent = 0
        progressed = True
        while spent < budget and progressed:
            progressed = False
            for key, row in agg.items():
                if spent >= budget:
                    break
                idx = cursors[key]
                if idx >= len(row["run_ids"]):
                    continue
                cursors[key] = idx + 1
                progressed = True
                spent += 1
                sampled_sum[key] += self._run_job_count(
                    row["full_name"], row["run_ids"][idx]
                )
                sampled_n[key] += 1
        jobs: dict[tuple[str, str], int] = {}
        for key, row in agg.items():
            n = sampled_n[key]
            jobs[key] = round(sampled_sum[key] / n * row["runs"]) if n else 0
        return jobs

    def _run_job_count(self, full_name: str, run_id: int) -> int:
        """Total job count for one workflow run (0 if inaccessible)."""
        try:
            data = self._get(
                f"{API_ROOT}/repos/{full_name}/actions/runs/{run_id}/jobs",
                params={"per_page": 1},
            ).json()
            return int(data.get("total_count", 0))
        except GitHubError:
            return 0
