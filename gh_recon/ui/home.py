"""Landing menu: choose which recon area to drill into."""

from __future__ import annotations

from rich.text import Text
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

# Fixed-width 5-row block font. Every glyph row is the same width, so the
# wordmark is column-aligned by construction in any monospace terminal.
_FONT_ROWS = 5
_FONT = {
    "G": ["█████", "█    ", "█  ██", "█   █", "█████"],
    "H": ["█   █", "█   █", "█████", "█   █", "█   █"],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
    "E": ["█████", "█    ", "███  ", "█    ", "█████"],
    "C": ["█████", "█    ", "█    ", "█    ", "█████"],
    "O": ["█████", "█   █", "█   █", "█   █", "█████"],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "-": ["     ", "     ", " ███ ", "     ", "     "],
    " ": ["  ", "  ", "  ", "  ", "  "],
}
_WORDMARK = "GH-RECON"


def _render_wordmark(word: str = _WORDMARK) -> list[str]:
    """Tile block glyphs into equal-length rows (padded so columns align)."""
    rows = [""] * _FONT_ROWS
    for ch in word.upper():
        glyph = _FONT.get(ch, _FONT[" "])
        for i in range(_FONT_ROWS):
            rows[i] += glyph[i] + " "
    width = max(len(r) for r in rows)
    return [r.ljust(width) for r in rows]


def _gradient_banner(start=(0x39, 0xFF, 0x14), end=(0x00, 0xE5, 0xFF)) -> Text:
    """Render the wordmark with a top-to-bottom green→cyan gradient."""
    lines = _render_wordmark()
    out = Text(justify="center")
    last = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        f = i / last
        rgb = tuple(round(s + (e - s) * f) for s, e in zip(start, end))
        out.append(line + "\n", style=f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x} bold")
    return out


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
    #banner { width: 1fr; text-align: center; margin-bottom: 1; }
    #menu-title { width: 1fr; text-align: center; margin-bottom: 1; }
    #home-menu { height: auto; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._cursor_on = True

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu"):
            yield Static(_gradient_banner(), id="banner")
            yield Static("", id="menu-title")
            yield OptionList(
                Option("Users          search org members and inspect profiles", id="users"),
                Option("Repositories   browse org repositories and their detail", id="repos"),
                Option("Runners        Actions runners: status and current job", id="runners"),
                id="home-menu",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org}"
        self._tagline = f"recon for [b]{self.client.org}[/b]  [dim]· select an area[/dim] "
        self._render_tagline()
        self.set_interval(0.5, self._blink_cursor)
        self.query_one("#home-menu", OptionList).focus()
        self._animate_intro()

    def _animate_intro(self) -> None:
        """Fade the banner and menu card in on entry."""
        banner = self.query_one("#banner", Static)
        banner.styles.opacity = 0.0
        banner.styles.animate("opacity", value=1.0, duration=0.9, easing="out_cubic")
        menu = self.query_one("#menu", Vertical)
        menu.styles.opacity = 0.0
        menu.styles.animate(
            "opacity", value=1.0, duration=0.5, delay=0.1, easing="out_cubic"
        )

    def _blink_cursor(self) -> None:
        self._cursor_on = not self._cursor_on
        self._render_tagline()

    def _render_tagline(self) -> None:
        cursor = "[$accent]▌[/]" if self._cursor_on else " "
        self.query_one("#menu-title", Static).update(self._tagline + cursor)

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
