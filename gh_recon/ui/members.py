"""Members screen: org member search; Enter opens user detail."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from ..api import GitHubClient, GitHubError
from ..models import Page
from .common import Paginator
from .users import UserDetailScreen


class MembersScreen(Screen):
    """Org member search; Enter opens user detail."""

    BINDINGS = [
        Binding("slash", "focus_search", "Search"),
        Binding("n", "next_page", "Next page"),
        Binding("p", "prev_page", "Prev page"),
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
        self._query = ""
        self._paginator = Paginator()

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
        self.load_members()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh(self) -> None:
        self.load_members()

    def action_next_page(self) -> None:
        if self._paginator.has_next:
            self._paginator.next()
            self.load_members()

    def action_prev_page(self) -> None:
        if self._paginator.has_prev:
            self._paginator.prev()
            self.load_members()

    @on(Input.Submitted, "#search")
    def _on_search(self, event: Input.Submitted) -> None:
        self._query = event.value.strip()
        self._paginator.reset()  # new query starts at page 1
        self.load_members()

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
    def load_members(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            page = self.client.search_members(
                self._query, cursor=self._paginator.cursor
            )
        except GitHubError as exc:
            self.app.call_from_thread(self._on_error, str(exc))
            return
        self.app.call_from_thread(self._render_members, page)

    def _set_loading(self, value: bool) -> None:
        self.query_one("#members-table", DataTable).loading = value

    def _on_error(self, msg: str) -> None:
        self._set_loading(False)
        self.query_one("#status", Static).update(f"[red]{msg}[/red]")

    def _render_members(self, page: Page) -> None:
        self._paginator.record(page)
        table = self.query_one("#members-table", DataTable)
        table.loading = False
        table.clear()
        for m in page.items:
            table.add_row(
                m.login,
                m.type,
                "✓" if m.site_admin else "",
                str(m.id),
                key=m.login,
            )
        self.query_one("#status", Static).update(self._status_line(page))
        if page.items:
            table.focus()

    def _status_line(self, page: Page) -> str:
        scope = f" matching '{self._query}'" if self._query else ""
        total = f" of {page.total}" if page.total is not None else ""
        nav = []
        if self._paginator.has_prev:
            nav.append("p prev")
        if self._paginator.has_next:
            nav.append("n next")
        nav_hint = f" · {', '.join(nav)}" if nav else ""
        return (
            f"[green]{len(page.items)}[/green] member(s){total}{scope} · "
            f"page {self._paginator.page_number}{nav_hint} — "
            "Enter to view, / to filter, Esc to go back"
        )
