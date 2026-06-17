"""Repository screens: org repo search and per-repo detail."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Markdown, Static

from ..api import GitHubClient, GitHubError
from ..models import CommitInfo, Page, Repo
from .common import Paginator, _fmt_dt, _language_chart


class RepositoriesScreen(Screen):
    """Org repository search; Enter opens repo detail."""

    BINDINGS = [
        Binding("slash", "focus_search", "Search"),
        Binding("n", "next_page", "Next page"),
        Binding("p", "prev_page", "Prev page"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_selected", "View repo", show=False),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    #repo-search-row { height: 3; padding: 0 1; }
    #repo-search { width: 1fr; }
    #repo-status { height: 1; padding: 0 1; color: $text-muted; }
    #repos-table { height: 1fr; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._query = ""
        self._paginator = Paginator()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="repo-search-row"):
            yield Input(
                placeholder="Filter org repos by name/description…  (press / to focus)",
                id="repo-search",
            )
        yield Static("", id="repo-status")
        table = DataTable(id="repos-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("Repository", "Vis", "Language", "★", "Last push (UTC)", "Flags")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / repositories"
        self.load_repos()

    def action_focus_search(self) -> None:
        self.query_one("#repo-search", Input).focus()

    def action_refresh(self) -> None:
        self.load_repos()

    def action_next_page(self) -> None:
        if self._paginator.has_next:
            self._paginator.next()
            self.load_repos()

    def action_prev_page(self) -> None:
        if self._paginator.has_prev:
            self._paginator.prev()
            self.load_repos()

    @on(Input.Submitted, "#repo-search")
    def _on_search(self, event: Input.Submitted) -> None:
        self._query = event.value.strip()
        self._paginator.reset()  # new query starts at page 1
        self.load_repos()

    @on(DataTable.RowSelected, "#repos-table")
    def _on_row(self, event: DataTable.RowSelected) -> None:
        self._open(event.row_key.value)

    def action_open_selected(self) -> None:
        table = self.query_one("#repos-table", DataTable)
        if table.row_count:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            self._open(row_key.value)

    def _open(self, name: str | None) -> None:
        if name:
            self.app.push_screen(RepoDetailScreen(self.client, name))

    @work(exclusive=True, thread=True)
    def load_repos(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            page = self.client.search_repos(self._query, cursor=self._paginator.cursor)
        except GitHubError as exc:
            self.app.call_from_thread(self._on_error, str(exc))
            return
        self.app.call_from_thread(self._render_repos, page)

    def _set_loading(self, value: bool) -> None:
        self.query_one("#repos-table", DataTable).loading = value

    def _on_error(self, msg: str) -> None:
        self._set_loading(False)
        self.query_one("#repo-status", Static).update(f"[red]{msg}[/red]")

    def _render_repos(self, page: Page) -> None:
        self._paginator.record(page)
        table = self.query_one("#repos-table", DataTable)
        table.loading = False
        table.clear()
        for r in page.items:
            flags = "".join(["A" if r.archived else "", "F" if r.fork else ""]) or "—"
            table.add_row(
                r.name,
                "priv" if r.private else "pub",
                r.language or "—",
                str(r.stars),
                _fmt_dt(r.pushed_at),
                flags,
                key=r.name,
            )
        self.query_one("#repo-status", Static).update(self._status_line(page))
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
            f"[green]{len(page.items)}[/green] repo(s){total}{scope} · "
            f"page {self._paginator.page_number}{nav_hint} — "
            "Enter to view, / to filter, Esc to go back"
        )


class RepoDetailScreen(Screen):
    """Repository metadata, languages, contributors, and recent commits."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("o", "open_browser", "Open on GitHub"),
    ]

    CSS = """
    #detail-body { height: 1fr; }
    #repo-profile { width: 42%; border-right: solid $panel; padding: 0 1; }
    #repo-right { width: 1fr; padding: 0 1; }
    #repo-right DataTable { height: 1fr; }
    #readme-label { margin-top: 1; }
    #repo-readme { height: auto; background: transparent; margin: 0; }
    """

    def __init__(self, client: GitHubClient, name: str) -> None:
        super().__init__()
        self.client = client
        self.repo_name = name
        self._html_url = f"https://github.com/{client.org}/{name}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="detail-body"):
            with VerticalScroll(id="repo-profile"):
                yield Static(f"[b]{self.client.org}/{self.repo_name}[/b]", id="repo-title")
                yield Static("loading…", id="repo-fields")
                yield Static("", id="repo-languages")
                yield Label("[b]README[/b]", id="readme-label")
                yield Markdown("", id="repo-readme")
            with Vertical(id="repo-right"):
                yield Label("[b]Top contributors[/b]")
                yield Static("", id="contrib-status")
                contrib = DataTable(id="contrib-table", zebra_stripes=True, cursor_type="row")
                contrib.add_columns("User", "Commits")
                yield contrib
                yield Label("[b]Recent commits[/b]")
                yield Static("", id="rcommits-status")
                commits = DataTable(id="rcommits-table", zebra_stripes=True, cursor_type="row")
                commits.add_columns("When (UTC)", "SHA", "Author", "Message")
                yield commits
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self.client.org}/{self.repo_name}"
        self.load_repo()

    def action_refresh(self) -> None:
        self.load_repo()

    def action_open_browser(self) -> None:
        import webbrowser

        webbrowser.open(self._html_url)
        self.app.notify(f"Opening {self._html_url}")

    def _set_tables_loading(self, value: bool) -> None:
        self.query_one("#contrib-table", DataTable).loading = value
        self.query_one("#rcommits-table", DataTable).loading = value
        self.query_one("#repo-readme", Markdown).loading = value

    @work(exclusive=True, thread=True)
    def load_repo(self) -> None:
        self.app.call_from_thread(self._set_tables_loading, True)
        try:
            repo = self.client.get_repo(self.repo_name)
        except GitHubError as exc:
            self.app.call_from_thread(self._set_tables_loading, False)
            self.app.call_from_thread(
                self.query_one("#repo-fields", Static).update, f"[red]{exc}[/red]"
            )
            return
        self.app.call_from_thread(self._render_meta, repo)
        try:
            langs = self.client.language_bytes([repo.full_name])
            self.app.call_from_thread(self._render_languages, langs, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_languages, [], str(exc))
        try:
            contributors = self.client.repo_contributors(self.repo_name)
            self.app.call_from_thread(self._render_contributors, contributors, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_contributors, [], str(exc))
        try:
            commits = self.client.repo_commits(self.repo_name)
            self.app.call_from_thread(self._render_commits, commits, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_commits, [], str(exc))
        try:
            readme = self.client.get_readme(self.repo_name)
            self.app.call_from_thread(self._render_readme, readme, None)
        except GitHubError as exc:
            self.app.call_from_thread(self._render_readme, None, str(exc))

    def _render_readme(self, text: str | None, error: str | None) -> None:
        md = self.query_one("#repo-readme", Markdown)
        md.loading = False
        if error:
            md.update(f"*README unavailable: {error}*")
        else:
            md.update(text or "*This repository has no README.*")

    def _render_meta(self, repo: Repo) -> None:
        self._html_url = repo.html_url or self._html_url
        self.query_one("#repo-title", Static).update(f"[b]{repo.full_name}[/b]")
        rows = [
            ("Visibility", "private" if repo.private else "public"),
            ("Archived", "yes" if repo.archived else "no"),
            ("Fork", "yes" if repo.fork else "no"),
            ("Default br.", repo.default_branch),
            ("Stars", str(repo.stars)),
            ("Forks", str(repo.forks)),
            ("Watchers", str(repo.watchers)),
            ("Open issues", str(repo.open_issues)),
            ("Size", f"{repo.size} KB"),
            ("Created", _fmt_dt(repo.created_at)),
            ("Last push", _fmt_dt(repo.pushed_at)),
        ]
        lines = [f"[$text-muted]{k:<12}[/] {v}" for k, v in rows]
        if repo.description:
            lines.append("")
            lines.append(f"[i]{repo.description}[/i]")
        self.query_one("#repo-fields", Static).update("\n".join(lines))

    def _render_languages(self, langs, error: str | None) -> None:
        widget = self.query_one("#repo-languages", Static)
        if error is not None:
            widget.update("\n[$text-muted]Languages[/]    [yellow]unavailable[/yellow]")
            return
        if not langs:
            widget.update("\n[$text-muted]Languages[/]    [dim]none[/dim]")
            return
        widget.update("\n[$text-muted]Languages[/]\n" + _language_chart(langs))

    def _render_contributors(self, contributors, error: str | None) -> None:
        status = self.query_one("#contrib-status", Static)
        table = self.query_one("#contrib-table", DataTable)
        table.loading = False
        table.clear()
        if error:
            status.update(f"[yellow]unavailable: {error}[/yellow]")
            return
        if not contributors:
            status.update("[dim]none[/dim]")
            return
        status.update(f"[green]{len(contributors)} shown[/green]")
        for login, count in contributors:
            table.add_row(login, str(count))

    def _render_commits(self, commits: list[CommitInfo], error: str | None) -> None:
        status = self.query_one("#rcommits-status", Static)
        table = self.query_one("#rcommits-table", DataTable)
        table.loading = False
        table.clear()
        if error:
            status.update(f"[yellow]unavailable: {error}[/yellow]")
            return
        if not commits:
            status.update("[dim]none[/dim]")
            return
        status.update(f"[green]{len(commits)} commit(s)[/green]")
        for c in commits:
            msg = c.message if len(c.message) <= 50 else c.message[:49] + "…"
            table.add_row(_fmt_dt(c.date), c.sha, c.author or "—", msg)
