"""Org-wide audit log screen: searchable event stream with high-risk presets."""

from __future__ import annotations

import json

from rich.syntax import Syntax
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

from ..api import GitHubClient, GitHubError
from ..models import AuditEvent, Page
from .common import Paginator, _fmt_dt

# High-risk event presets: (key, phrase, short label). ``action:`` matches
# category prefixes, so e.g. personal_access_token covers all its sub-events.
_PRESETS = [
    ("1", "action:repo.access", "visibility"),
    ("2", "action:repo.destroy", "repo deletes"),
    ("3", "action:org.update_member", "role changes"),
    ("4", "action:org.remove_member", "removals"),
    ("5", "action:personal_access_token", "PATs"),
    ("6", "action:oauth_application", "OAuth apps"),
]


class AuditEventDetailScreen(ModalScreen[None]):
    """Raw JSON payload of a single audit-log event."""

    BINDINGS = [Binding("escape", "close", "Close")]

    CSS = """
    AuditEventDetailScreen { align: center middle; }
    #event-box { width: 90%; max-width: 110; height: auto; max-height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    #event-title { text-style: bold; margin-bottom: 1; }
    #event-body { height: auto; max-height: 100%; margin-bottom: 1; }
    #event-buttons { height: auto; align-horizontal: center; }
    """

    def __init__(self, event: AuditEvent) -> None:
        super().__init__()
        self._event = event

    def compose(self) -> ComposeResult:
        e = self._event
        body = json.dumps(e.raw, indent=2, sort_keys=True, default=str) or "{}"
        with Vertical(id="event-box"):
            yield Label(
                f"{e.action}  ·  {e.actor or '—'}  ·  {_fmt_dt(e.timestamp)}",
                id="event-title",
            )
            with VerticalScroll(id="event-body"):
                yield Static(Syntax(body, "json", theme="ansi_dark", word_wrap=True))
            with Horizontal(id="event-buttons"):
                yield Button("Close (Esc)", id="close")

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


class AuditLogScreen(Screen):
    """Org-wide audit-log browser with search-phrase filtering."""

    BINDINGS = [
        Binding("slash", "focus_search", "Filter"),
        Binding("n", "next_page", "Next page"),
        Binding("p", "prev_page", "Prev page"),
        Binding("r", "refresh", "Refresh"),
        Binding("g", "toggle_group", "Group by actor"),
        Binding("u", "open_actor", "Actor detail"),
        Binding("enter", "open_selected", "Event JSON", show=False),
        Binding("escape", "app.pop_screen", "Back"),
    ] + [
        Binding(key, f"preset('{phrase}')", label, show=False)
        for key, phrase, label in _PRESETS
    ]

    CSS = """
    #search-row { height: 3; padding: 0 1; }
    #search { width: 1fr; }
    #presets { height: 1; padding: 0 1; color: $text-muted; }
    #status { height: auto; padding: 0 1; color: $text-muted; }
    #audit-table { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._phrase = ""
        self._paginator = Paginator()
        self._events: list[AuditEvent] = []
        self._row_events: list[AuditEvent | None] = []  # row index → event
        self._grouped = False
        self._last_page: Page | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="search-row"):
            yield Input(
                placeholder=(
                    "Filter events…  e.g. action:repo.access actor:octocat "
                    "created:>=2026-01-01  (press / to focus)"
                ),
                id="search",
            )
        presets = "  ".join(
            f"[b]{key}[/b] [$accent]{label}[/]" for key, _, label in _PRESETS
        )
        yield Static(f"presets: {presets}  ·  [b]0[/b] clear", id="presets")
        yield Static("", id="status")
        table = DataTable(id="audit-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("When (UTC)", "Actor", "Action", "Repo")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / audit log"
        self.load_events()

    def key_0(self) -> None:
        if not self.query_one("#search", Input).has_focus:
            self.action_preset("")

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh(self) -> None:
        self._paginator.reset()
        self.load_events()

    def action_next_page(self) -> None:
        if self._paginator.has_next:
            self._paginator.next()
            self.load_events()

    def action_prev_page(self) -> None:
        if self._paginator.has_prev:
            self._paginator.prev()
            self.load_events()

    def action_preset(self, phrase: str) -> None:
        if self.query_one("#search", Input).has_focus:
            return  # don't hijack digits while typing a phrase
        self._phrase = phrase
        self.query_one("#search", Input).value = phrase
        self._paginator.reset()
        self.load_events()

    def action_toggle_group(self) -> None:
        self._grouped = not self._grouped
        if self._last_page is not None:
            self._render_table()

    @on(Input.Submitted, "#search")
    def _on_search(self, event: Input.Submitted) -> None:
        self._phrase = event.value.strip()
        self._paginator.reset()
        self.load_events()

    def _selected_event(self) -> AuditEvent | None:
        table = self.query_one("#audit-table", DataTable)
        if not table.row_count:
            return None
        row = table.cursor_coordinate.row
        if 0 <= row < len(self._row_events):
            return self._row_events[row]
        return None

    @on(DataTable.RowSelected, "#audit-table")
    def _on_row(self, event: DataTable.RowSelected) -> None:
        self.action_open_selected()

    def action_open_selected(self) -> None:
        event = self._selected_event()
        if event is not None:
            self.app.push_screen(AuditEventDetailScreen(event))

    def action_open_actor(self) -> None:
        event = self._selected_event()
        if event is not None and event.actor:
            from .users import UserDetailScreen

            self.app.push_screen(UserDetailScreen(self.client, event.actor))

    @work(exclusive=True, thread=True)
    def load_events(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            page = self.client.org_audit_events(
                phrase=self._phrase or None, cursor=self._paginator.cursor
            )
        except GitHubError as exc:
            self.app.call_from_thread(self._on_error, str(exc))
            return
        self.app.call_from_thread(self._render_events, page)

    def _set_loading(self, value: bool) -> None:
        self.query_one("#audit-table", DataTable).loading = value

    def _on_error(self, msg: str) -> None:
        self._set_loading(False)
        self.query_one("#status", Static).update(
            f"[red]Audit log unavailable: {msg}[/red]\n"
            "[dim]Requires an org owner token with read:audit_log scope "
            "(GitHub Enterprise Cloud).[/dim]"
        )

    def _render_events(self, page: Page) -> None:
        self._paginator.record(page)
        self._last_page = page
        self._events = list(page.items)
        self._render_table()

    def _render_table(self) -> None:
        page = self._last_page
        table = self.query_one("#audit-table", DataTable)
        table.loading = False
        table.clear()
        self._row_events = []
        if self._grouped:
            # Group this page's events by actor (pages are server-side, so
            # grouping is per-page), busiest actors first.
            groups: dict[str, list[AuditEvent]] = {}
            for e in self._events:
                groups.setdefault(e.actor or "—", []).append(e)
            ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            for actor, events in ordered:
                table.add_row(
                    "",
                    f"[b]▌ {actor}[/b]",
                    f"[dim]{len(events)} event(s)[/dim]",
                    "",
                )
                self._row_events.append(events[0])  # header selects the actor
                for e in events:
                    table.add_row(
                        _fmt_dt(e.timestamp), "", e.action, e.repo or "—"
                    )
                    self._row_events.append(e)
        else:
            for e in self._events:
                table.add_row(
                    _fmt_dt(e.timestamp), e.actor or "—", e.action, e.repo or "—"
                )
                self._row_events.append(e)
        self.query_one("#status", Static).update(self._status_line(page))
        if self._events:
            table.focus()

    def _status_line(self, page: Page) -> str:
        scope = f" matching '{self._phrase}'" if self._phrase else ""
        if not page.items and not self._paginator.has_prev:
            return f"[dim]No audit-log events found{scope}.[/dim]"
        nav = []
        if self._paginator.has_prev:
            nav.append("p prev")
        if self._paginator.has_next:
            nav.append("n next")
        nav_hint = f" · {', '.join(nav)}" if nav else ""
        grouped = " · grouped by actor" if self._grouped else ""
        return (
            f"[green]{len(page.items)}[/green] event(s){scope}{grouped} · "
            f"page {self._paginator.page_number}{nav_hint} — "
            "Enter for JSON, u for actor, g to group, / to filter, Esc to go back"
        )
