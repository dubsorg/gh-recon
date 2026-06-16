"""User-detail screen: profile, teams, keys, languages, commits, audit log."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from ..api import GitHubClient, GitHubError
from ..models import AuditEvent, UserInfo
from .common import _fmt_dt, _language_chart


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
        widget.update(
            "\n[$text-muted]Languages (by repo bytes)[/]\n" + _language_chart(langs)
        )

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
