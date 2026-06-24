"""Actions screen: org Actions usage metrics plus self-hosted runners."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Digits, Footer, Header, Label, Static

from ..api import GitHubClient, GitHubError
from ..models import ActionsUsage, Runner, RunnerJob

# Braille spinner frames cycled for busy (actively running) runners.
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ActionsScreen(Screen):
    """Org Actions usage (runs / minutes) plus self-hosted runners."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    #actions-stats { height: auto; align-horizontal: center; margin: 1 0 0 0; }
    .stat { width: 28; height: auto; border: round $panel; padding: 0 1; margin: 0 1; }
    .stat-label { width: 1fr; text-align: center; color: $text-muted; }
    .stat Digits { width: 1fr; text-align: center; color: $accent; }
    #usage-detail { height: auto; padding: 0 1; color: $text-muted; }
    .section-label { height: 1; padding: 0 1; color: $accent; text-style: bold; }
    #runner-status { height: 1; padding: 0 1; color: $text-muted; }
    #runners-table { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._spin = 0
        self._busy_keys: list[str] = []  # row keys of busy runners to animate

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="actions-stats"):
            with Vertical(classes="stat"):
                yield Label("Minutes used", classes="stat-label")
                yield Digits("", id="minutes-digits")
            with Vertical(classes="stat"):
                yield Label("Paid minutes", classes="stat-label")
                yield Digits("", id="paid-digits")
        yield Static("", id="usage-detail")
        yield Label("Self-hosted runners", classes="section-label")
        yield Static("", id="runner-status")
        table = DataTable(id="runners-table", zebra_stripes=True, cursor_type="row")
        columns = table.add_columns(
            "Runner", "OS", "Labels", "Status", "Workflow / Job", "Repo"
        )
        self._status_col = columns[3]
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / actions"
        self.set_interval(0.1, self._tick_spinner)
        self.load_runners()
        self.load_usage()

    def action_refresh(self) -> None:
        self.load_runners()
        self.load_usage()

    @work(exclusive=True, thread=True, group="usage")
    def load_usage(self) -> None:
        self.app.call_from_thread(self._set_usage_loading, True)
        try:
            usage = self.client.actions_usage()
        except GitHubError as exc:
            self.app.call_from_thread(self._usage_error, str(exc))
            return
        self.app.call_from_thread(self._render_usage, usage)

    def _set_usage_loading(self, value: bool) -> None:
        for did in ("#minutes-digits", "#paid-digits"):
            self.query_one(did, Digits).loading = value

    def _usage_error(self, msg: str) -> None:
        self._set_usage_loading(False)
        self.query_one("#usage-detail", Static).update(
            f"[yellow]Usage metrics unavailable: {msg}[/yellow]"
        )

    def _render_usage(self, usage: ActionsUsage) -> None:
        def to_digits(value: int | None) -> str:
            return str(value) if value is not None else "—"

        self.query_one("#minutes-digits", Digits).loading = False
        self.query_one("#paid-digits", Digits).loading = False
        self.query_one("#minutes-digits", Digits).update(to_digits(usage.total_minutes))
        self.query_one("#paid-digits", Digits).update(to_digits(usage.paid_minutes))
        detail = []
        if usage.included_minutes is not None:
            detail.append(f"included: {usage.included_minutes}")
        if usage.minutes_by_os:
            detail.append(
                "by OS — "
                + ", ".join(f"{os}: {m}" for os, m in usage.minutes_by_os.items())
            )
        self.query_one("#usage-detail", Static).update(" · ".join(detail))

    def _busy_status(self, frame: str) -> str:
        return f"[green]online[/green] · [green]{frame} busy[/green]"

    def _tick_spinner(self) -> None:
        if not self._busy_keys:
            return
        self._spin = (self._spin + 1) % len(_SPINNER)
        status = self._busy_status(_SPINNER[self._spin])
        table = self.query_one("#runners-table", DataTable)
        for key in self._busy_keys:
            try:
                table.update_cell(key, self._status_col, status)
            except Exception:
                pass  # row gone mid-refresh — next render rebuilds it

    @work(exclusive=True, thread=True)
    def load_runners(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
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

    def _set_loading(self, value: bool) -> None:
        self.query_one("#runners-table", DataTable).loading = value

    def _show_error(self, msg: str) -> None:
        self.query_one("#runners-table", DataTable).loading = False
        self.query_one("#runner-status", Static).update(
            f"[yellow]Runners unavailable: {msg}[/yellow]\n"
            "[dim]Requires an org-admin token with admin:org (or fine-grained "
            "self-hosted runners read) scope.[/dim]"
        )

    def _render_runners(
        self, runners: list[Runner], jobs: dict[str, RunnerJob]
    ) -> None:
        table = self.query_one("#runners-table", DataTable)
        table.loading = False
        table.clear()
        self._busy_keys = []
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
                if r.status == "online" and r.busy:
                    status = self._busy_status(_SPINNER[self._spin])
                    self._busy_keys.append(str(r.id))
                elif r.status == "online":
                    status = "[green]online[/green] · idle"
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
