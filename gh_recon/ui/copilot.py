"""Copilot screen: org Copilot seat billing and usage metrics."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..api import GitHubClient, GitHubError
from ..models import CopilotBilling, CopilotMetrics


class CopilotScreen(Screen):
    """Org Copilot seats and language-level usage over the reporting window."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    #copilot-summary { height: auto; padding: 0 1; }
    #copilot-status { height: auto; padding: 0 1; color: $text-muted; }
    #copilot-langs { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="copilot-summary")
        yield Static("", id="copilot-status")
        table = DataTable(id="copilot-langs", zebra_stripes=True, cursor_type="row")
        table.add_columns(
            "Language", "Engaged", "Suggestions", "Acceptances", "Accept %", "Lines accepted"
        )
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / copilot"
        self.load_copilot()

    def action_refresh(self) -> None:
        self.load_copilot()

    @work(exclusive=True, thread=True)
    def load_copilot(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            billing = self.client.copilot_billing()
            metrics = self.client.copilot_metrics()
        except GitHubError as exc:
            self.app.call_from_thread(self._error, str(exc))
            return
        self.app.call_from_thread(self._render_copilot, billing, metrics)

    def _set_loading(self, value: bool) -> None:
        self.query_one("#copilot-langs", DataTable).loading = value

    def _error(self, msg: str) -> None:
        self.query_one("#copilot-langs", DataTable).loading = False
        self.query_one("#copilot-status", Static).update(
            f"[yellow]Copilot unavailable: {msg}[/yellow]"
        )

    def _render_copilot(
        self, billing: CopilotBilling | None, metrics: CopilotMetrics | None
    ) -> None:
        table = self.query_one("#copilot-langs", DataTable)
        table.loading = False
        table.clear()
        summary = self.query_one("#copilot-summary", Static)
        status = self.query_one("#copilot-status", Static)

        if billing is None and metrics is None:
            summary.update("")
            status.update(
                "[yellow]Copilot metrics unavailable for this org.[/yellow]\n"
                "[dim]Requires Copilot Business/Enterprise and a token with "
                "manage_billing:copilot, read:org, or admin:org.[/dim]"
            )
            return

        lines: list[str] = []
        if billing is not None:
            lines.append(
                f"[$text-muted]Seats[/]   [b]{billing.total_seats}[/b] total · "
                f"[green]{billing.active_this_cycle}[/green] active · "
                f"{billing.inactive_this_cycle} inactive · "
                f"+{billing.added_this_cycle} this cycle"
            )
            lines.append(
                f"[$text-muted]Policy[/]  seat mgmt: {billing.seat_management_setting or '—'}"
                f" · public code suggestions: {billing.public_code_suggestions or '—'}"
            )
        if metrics is not None and metrics.days:
            lines.append(
                f"[$text-muted]Usage[/]   {metrics.start} → {metrics.end} "
                f"({metrics.days}d) · latest active: [b]{metrics.active_users_latest}[/b]"
                f" · engaged: [b]{metrics.engaged_users_latest}[/b]"
                f" · peak active: {metrics.active_users_peak}"
            )
        summary.update("\n".join(lines))

        langs = metrics.languages if metrics else []
        if not langs:
            status.update("[dim]No language-level completion data in the window.[/dim]")
            return
        status.update(
            f"[green]{len(langs)}[/green] language(s) by suggestions "
            "— r to refresh, Esc to go back"
        )
        for s in langs:
            table.add_row(
                s.language,
                str(s.engaged_users),
                f"{s.suggestions:,}",
                f"{s.acceptances:,}",
                f"{s.acceptance_rate:.0f}%",
                f"{s.lines_accepted:,}",
            )
