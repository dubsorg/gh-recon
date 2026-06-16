"""Runners screen: org Actions self-hosted runners and their current job."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..api import GitHubClient, GitHubError
from ..models import Runner, RunnerJob


class RunnersScreen(Screen):
    """List self-hosted runners with status and the workflow each is running."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    #runner-status { height: 1; padding: 0 1; color: $text-muted; }
    #runners-table { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="runner-status")
        table = DataTable(id="runners-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("Runner", "OS", "Labels", "Status", "Workflow / Job", "Repo")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / runners"
        self.load_runners()

    def action_refresh(self) -> None:
        self.load_runners()

    @work(exclusive=True, thread=True)
    def load_runners(self) -> None:
        self.app.call_from_thread(
            self.query_one("#runner-status", Static).update, "[dim]loading runners…[/dim]"
        )
        try:
            runners = self.client.list_runners()
        except GitHubError as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return
        # Render runners immediately; busy ones get their job filled in after.
        self.app.call_from_thread(self._render_runners, runners, {})
        if any(r.busy for r in runners):
            try:
                jobs = self.client.running_jobs()
            except GitHubError:
                jobs = {}
            self.app.call_from_thread(self._render_runners, runners, jobs)

    def _show_error(self, msg: str) -> None:
        self.query_one("#runner-status", Static).update(
            f"[yellow]Runners unavailable: {msg}[/yellow]\n"
            "[dim]Requires an org-admin token with admin:org (or fine-grained "
            "self-hosted runners read) scope.[/dim]"
        )

    def _render_runners(
        self, runners: list[Runner], jobs: dict[str, RunnerJob]
    ) -> None:
        table = self.query_one("#runners-table", DataTable)
        table.clear()
        online = sum(1 for r in runners if r.status == "online")
        busy = sum(1 for r in runners if r.busy)
        if not runners:
            self.query_one("#runner-status", Static).update(
                "[dim]No self-hosted runners registered for this org.[/dim]"
            )
            return
        # Group by runner group; ungrouped runners fall into "Default".
        groups: dict[str, list[Runner]] = {}
        for r in runners:
            groups.setdefault(r.group or "Default", []).append(r)
        for gname in sorted(groups):
            grunners = groups[gname]
            g_busy = sum(1 for r in grunners if r.busy)
            table.add_row(
                f"[b]▌ {gname}[/b]",
                "",
                "",
                f"[dim]{len(grunners)} runner(s) · {g_busy} busy[/dim]",
                "",
                "",
                key=f"group:{gname}",
            )
            for r in grunners:
                if r.status == "online":
                    status = "[green]online[/green]" + (
                        " · busy" if r.busy else " · idle"
                    )
                else:
                    status = f"[dim]{r.status}[/dim]"
                job = jobs.get(r.name)
                if job:
                    activity = f"{job.workflow} / {job.job}"
                    repo = job.repo
                elif r.busy:
                    activity = "[dim]running (unknown)[/dim]"
                    repo = "—"
                else:
                    activity = "—"
                    repo = "—"
                labels = ", ".join(r.labels) if r.labels else "—"
                table.add_row(
                    f"  {r.name}", r.os, labels, status, activity, repo, key=str(r.id)
                )
        self.query_one("#runner-status", Static).update(
            f"[green]{len(runners)}[/green] runner(s) · {len(groups)} group(s) · "
            f"{online} online · {busy} busy — r to refresh, Esc to go back"
        )
        table.focus()
