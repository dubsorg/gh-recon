"""Textual TUI for GitHub organization recon."""

from __future__ import annotations

from datetime import datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Static,
)

from .api import AuditEvent, GitHubClient, GitHubError, UserInfo


def _fmt_dt(value: str | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.replace("T", " ").replace("Z", "")


class OrgPromptScreen(ModalScreen[str]):
    """Asks for the organization to scope to when none was supplied."""

    CSS = """
    OrgPromptScreen { align: center middle; }
    #box { width: 60; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #box Label { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("Enter the GitHub organization to scope recon to:")
            yield Input(placeholder="org-login", id="org-input")

    def on_mount(self) -> None:
        self.query_one("#org-input", Input).focus()

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)


class UserDetailScreen(Screen):
    """Profile + recent audit-log events for a single user."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("o", "open_browser", "Open on GitHub"),
    ]

    CSS = """
    #detail-body { height: 1fr; }
    #profile { width: 40%; border-right: solid $panel; padding: 0 1; }
    #profile-fields { height: auto; }
    #events-pane { width: 1fr; padding: 0 1; }
    .field-label { color: $text-muted; }
    #events-status { color: $warning; height: auto; }
    DataTable { height: 1fr; }
    """

    def __init__(self, client: GitHubClient, login: str) -> None:
        super().__init__()
        self.client = client
        self.login = login
        self._html_url = f"https://github.com/{login}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="detail-body"):
            with VerticalScroll(id="profile"):
                yield Static(f"[b]@{self.login}[/b]", id="profile-title")
                yield Static("loading…", id="profile-fields")
                yield Static("", id="teams")
                yield Static("", id="languages")
                yield Static("", id="keys")
            with Vertical(id="events-pane"):
                yield Label("[b]Recent commits (repos)[/b]")
                yield Static("", id="commits-status")
                commits = DataTable(
                    id="commits-table", zebra_stripes=True, cursor_type="row"
                )
                commits.add_columns("Repo", "Last commit (UTC)", "Commits")
                yield commits
                yield Label("[b]Recent audit-log events[/b]")
                yield Static("", id="events-status")
                table = DataTable(id="events-table", zebra_stripes=True, cursor_type="row")
                table.add_columns("When (UTC)", "Action", "Repo")
                yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self.client.org} / {self.login}"
        self.load_user()

    def action_refresh(self) -> None:
        self.load_user()

    def action_open_browser(self) -> None:
        import webbrowser

        webbrowser.open(self._html_url)
        self.app.notify(f"Opening {self._html_url}")

    @work(exclusive=True, thread=True)
    def load_user(self) -> None:
        try:
            info = self.client.get_user(self.login)
        except GitHubError as exc:
            self.app.call_from_thread(self._show_profile_error, str(exc))
            return
        self.app.call_from_thread(self._render_profile, info)
        try:
            teams = self.client.user_teams(self.login)
            self.app.call_from_thread(self._render_teams, teams, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_teams, None, str(exc))
        try:
            keys = self.client.public_keys(self.login)
            self.app.call_from_thread(self._render_keys, keys, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_keys, None, str(exc))
        repos = []
        try:
            repos = self.client.recent_commit_repos(self.login)
            self.app.call_from_thread(self._render_commits, repos, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_commits, [], str(exc))
        try:
            langs = self.client.language_bytes([r.repo for r in repos])
            self.app.call_from_thread(self._render_languages, langs, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_languages, [], str(exc))
        try:
            events = self.client.audit_events(self.login)
            self.app.call_from_thread(self._render_events, events, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_events, [], str(exc))

    def _show_profile_error(self, msg: str) -> None:
        self.query_one("#profile-fields", Static).update(f"[red]{msg}[/red]")

    def _render_profile(self, info: UserInfo) -> None:
        self._html_url = info.html_url or self._html_url
        title = f"[b]@{info.login}[/b]"
        if info.name:
            title += f"  ({info.name})"
        self.query_one("#profile-title", Static).update(title)
        role = info.org_role or "[dim]not a member[/dim]"
        rows = [
            ("Org role", role),
            ("Type", info.type),
            ("ID", str(info.id)),
            ("Company", info.company or "—"),
            ("Email", info.email or "—"),
            ("Location", info.location or "—"),
            ("Blog", info.blog or "—"),
            ("Public repos", str(info.public_repos)),
            ("Followers", str(info.followers)),
            ("Following", str(info.following)),
            ("Created", _fmt_dt(info.created_at)),
            ("Updated", _fmt_dt(info.updated_at)),
        ]
        lines = [f"[$text-muted]{k:<13}[/] {v}" for k, v in rows]
        if info.bio:
            lines.append("")
            lines.append(f"[i]{info.bio}[/i]")
        self.query_one("#profile-fields", Static).update("\n".join(lines))

    def _render_teams(self, teams: list[str] | None, error: str | None) -> None:
        widget = self.query_one("#teams", Static)
        if error is not None:
            widget.update(f"\n[$text-muted]Teams[/]        [yellow]unavailable[/yellow]")
            return
        teams = teams or []
        if not teams:
            widget.update(f"\n[$text-muted]Teams[/]        [dim]none[/dim]")
            return
        listed = "\n".join(f"  • {t}" for t in teams)
        widget.update(f"\n[$text-muted]Teams ({len(teams)})[/]\n{listed}")

    def _render_keys(self, keys, error: str | None) -> None:
        widget = self.query_one("#keys", Static)
        if error is not None:
            widget.update("\n[$text-muted]Public keys[/]  [yellow]unavailable[/yellow]")
            return
        lines = ["\n[$text-muted]Public keys[/]"]
        if keys.ssh:
            lines.append(f"  SSH ({len(keys.ssh)}):")
            for ktype, fp in keys.ssh:
                lines.append(f"    {ktype}  {fp}")
        else:
            lines.append("  SSH: [dim]none[/dim]")
        if keys.gpg:
            lines.append(f"  GPG ({len(keys.gpg)}):")
            for key_id, emails in keys.gpg:
                suffix = f"  {', '.join(emails)}" if emails else ""
                lines.append(f"    {key_id}{suffix}")
        else:
            lines.append("  GPG: [dim]none[/dim]")
        widget.update("\n".join(lines))

    def _render_languages(self, langs, error: str | None) -> None:
        widget = self.query_one("#languages", Static)
        if error is not None:
            widget.update("\n[$text-muted]Languages[/]    [yellow]unavailable[/yellow]")
            return
        if not langs:
            widget.update("\n[$text-muted]Languages[/]    [dim]none[/dim]")
            return
        total = sum(b for _, b in langs) or 1
        lines = ["\n[$text-muted]Languages (by repo bytes)[/]"]
        for name, b in langs[:8]:
            pct = b / total * 100
            filled = round(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"  {name[:12]:<12} {bar} {pct:5.1f}%")
        widget.update("\n".join(lines))

    def _render_commits(self, repos, error: str | None) -> None:
        status = self.query_one("#commits-status", Static)
        table = self.query_one("#commits-table", DataTable)
        table.clear()
        if error:
            status.update(f"[yellow]Commit search unavailable: {error}[/yellow]")
            return
        if not repos:
            status.update("[dim]No recently authored commits found in this org.[/dim]")
            return
        # repos is sorted by last commit desc, so max() picks the highest commit
        # count, breaking ties toward the most recently active repo.
        top = max(repos, key=lambda r: r.count)
        status.update(
            f"[green]{len(repos)} repo(s)[/green] · most active: "
            f"[b]{top.repo}[/b] ([b]{top.count}[/b] commits)"
        )
        for r in repos:
            marker = "★ " if r is top else ""
            table.add_row(f"{marker}{r.repo}", _fmt_dt(r.last_commit), str(r.count))

    def _render_events(self, events: list[AuditEvent], error: str | None) -> None:
        status = self.query_one("#events-status", Static)
        table = self.query_one("#events-table", DataTable)
        table.clear()
        if error:
            status.update(
                f"[yellow]Audit log unavailable: {error}[/yellow]\n"
                "[dim]Requires an org owner token with read:audit_log scope "
                "(GitHub Enterprise Cloud).[/dim]"
            )
            return
        if not events:
            status.update("[dim]No audit-log events found for this actor.[/dim]")
            return
        status.update(f"[green]{len(events)} event(s)[/green]")
        for e in events:
            table.add_row(_fmt_dt(e.timestamp), e.action, e.repo or "—")


class MainScreen(Screen):
    """Org member search; Enter opens user detail."""

    BINDINGS = [
        Binding("slash", "focus_search", "Search"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_selected", "View user", show=False),
        Binding("q", "app.quit", "Quit"),
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
        self.sub_title = f"org: {self.client.org}"
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
            "Enter to view, / to filter, r to refresh"
        )
        if members:
            table.focus()


class GhReconApp(App):
    TITLE = "gh-recon"
    CSS = """
    Screen { layers: base; }
    """

    def __init__(self, org: str | None, token: str | None) -> None:
        super().__init__()
        self._org = org
        self._token = token

    def on_mount(self) -> None:
        if self._org:
            self._start(self._org)
        else:
            self.push_screen(OrgPromptScreen(), self._on_org)

    def _on_org(self, org: str | None) -> None:
        if not org:
            self.exit()
            return
        self._start(org)

    def _start(self, org: str) -> None:
        client = GitHubClient(org=org, token=self._token)
        self.push_screen(MainScreen(client))
