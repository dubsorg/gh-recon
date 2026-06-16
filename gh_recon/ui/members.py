"""Members screen: org member search; Enter opens user detail."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from ..api import GitHubClient, GitHubError
from .users import UserDetailScreen


class MembersScreen(Screen):
    """Org member search; Enter opens user detail."""

    BINDINGS = [
        Binding("slash", "focus_search", "Search"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_selected", "View user", show=False),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    #search-row { height: 3; padding: 0 1; }
    #search { width: 1fr; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #members-table { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._all_loaded = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="search-row"):
            yield Input(
                placeholder="Filter org members by login…  (press / to focus)",
                id="search",
            )
        yield Static("", id="status")
        table = DataTable(id="members-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("Login", "Type", "Site admin", "ID")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / members"
        self.load_members("")

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh(self) -> None:
        self.load_members(self.query_one("#search", Input).value.strip())

    @on(Input.Submitted, "#search")
    def _on_search(self, event: Input.Submitted) -> None:
        self.load_members(event.value.strip())

    @on(DataTable.RowSelected, "#members-table")
    def _on_row(self, event: DataTable.RowSelected) -> None:
        self._open(event.row_key.value)

    def action_open_selected(self) -> None:
        table = self.query_one("#members-table", DataTable)
        if table.row_count:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            self._open(row_key.value)

    def _open(self, login: str | None) -> None:
        if login:
            self.app.push_screen(UserDetailScreen(self.client, login))

    @work(exclusive=True, thread=True)
    def load_members(self, query: str) -> None:
        self.app.call_from_thread(
            self.query_one("#status", Static).update, "[dim]loading members…[/dim]"
        )
        try:
            members = self.client.search_members(query)
        except GitHubError as exc:
            self.app.call_from_thread(
                self.query_one("#status", Static).update, f"[red]{exc}[/red]"
            )
            return
        self.app.call_from_thread(self._render_members, members, query)

    def _render_members(self, members, query: str) -> None:
        table = self.query_one("#members-table", DataTable)
        table.clear()
        for m in members:
            table.add_row(
                m.login,
                m.type,
                "✓" if m.site_admin else "",
                str(m.id),
                key=m.login,
            )
        scope = f" matching '{query}'" if query else ""
        self.query_one("#status", Static).update(
            f"[green]{len(members)}[/green] member(s){scope} — "
            "Enter to view, / to filter, r to refresh, Esc to go back"
        )
        if members:
            table.focus()
