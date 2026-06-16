"""Landing menu: choose which recon area to drill into."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from ..api import GitHubClient
from .members import MembersScreen
from .repos import RepositoriesScreen
from .runners import RunnersScreen


class HomeScreen(Screen):
    """Top-level menu; each option pushes a domain screen."""

    BINDINGS = [
        Binding("u", "open_users", "Users"),
        Binding("R", "open_repos", "Repositories"),
        Binding("a", "open_runners", "Runners"),
        Binding("enter", "open_selected", "Open", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    CSS = """
    HomeScreen { align: center middle; }
    #menu { width: 104; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #menu-title { margin-bottom: 1; }
    #home-menu { height: auto; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu"):
            yield Static(
                f"[b]gh-recon[/b] — recon for [b]{self.client.org}[/b]\n"
                "[dim]Select an area to explore:[/dim]",
                id="menu-title",
            )
            yield OptionList(
                Option("Users          search org members and inspect profiles", id="users"),
                Option("Repositories   browse org repositories and their detail", id="repos"),
                Option("Runners        Actions runners: status and current job", id="runners"),
                id="home-menu",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org}"
        self.query_one("#home-menu", OptionList).focus()

    @on(OptionList.OptionSelected, "#home-menu")
    def _on_select(self, event: OptionList.OptionSelected) -> None:
        self._open(event.option_id)

    def action_open_selected(self) -> None:
        menu = self.query_one("#home-menu", OptionList)
        if menu.highlighted is not None:
            self._open(menu.get_option_at_index(menu.highlighted).id)

    def action_open_users(self) -> None:
        self._open("users")

    def action_open_repos(self) -> None:
        self._open("repos")

    def action_open_runners(self) -> None:
        self._open("runners")

    def _open(self, area: str | None) -> None:
        if area == "users":
            self.app.push_screen(MembersScreen(self.client))
        elif area == "repos":
            self.app.push_screen(RepositoriesScreen(self.client))
        elif area == "runners":
            self.app.push_screen(RunnersScreen(self.client))
