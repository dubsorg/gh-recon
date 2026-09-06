"""Landing menu: choose which recon area to drill into."""

from __future__ import annotations

import random

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Digits, Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..api import GitHubClient, GitHubError
from .actions import ActionsScreen
from .audit import AuditLogScreen
from .copilot import CopilotScreen
from .explorer import ApiExplorerScreen
from .members import MembersScreen
from .repos import RepositoriesScreen

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


# GitHub contribution-graph palette: an empty cell + four "intensity" greens.
_CONTRIB_LEVELS = ["#1b2027", "#0e4429", "#006d32", "#26a641", "#39d353"]
_CONTRIB_ROWS = 7
_CONTRIB_COLS = 48


def _gen_contrib(seed: str) -> list[list[int]]:
    """A stable, sparse 0–4 intensity grid (mostly empty, GitHub-like)."""
    rng = random.Random(seed)
    return [
        [rng.choices((0, 1, 2, 3, 4), weights=(52, 20, 14, 9, 5))[0]
         for _ in range(_CONTRIB_COLS)]
        for _ in range(_CONTRIB_ROWS)
    ]


def _render_contrib(grid: list[list[int]], revealed: int, sweep: int | None) -> Text:
    """Render the grid: columns ``< revealed`` are shown; unrevealed ones stay blank.

    ``sweep`` (a column index, or ``None``) lights up a two-wide band by boosting
    those cells' intensity — a soft highlight that travels across the graph.
    """
    out = Text(justify="center")
    last_row = len(grid) - 1
    for r, row in enumerate(grid):
        for c, lvl in enumerate(row):
            if c >= revealed:
                out.append("  ")  # keep line width constant so centering is stable
                continue
            if sweep is not None and 0 <= sweep - c <= 1:
                lvl = min(4, lvl + 2)
            out.append("█ ", style=_CONTRIB_LEVELS[lvl])
        if r < last_row:
            out.append("\n")
    return out


class HomeScreen(Screen):
    """Top-level menu; each option pushes a domain screen."""

    BINDINGS = [
        Binding("u", "open_users", "Users"),
        Binding("R", "open_repos", "Repositories"),
        Binding("a", "open_actions", "Actions"),
        Binding("l", "open_audit", "Audit Log"),
        Binding("c", "open_copilot", "Copilot"),
        Binding("e", "open_explorer", "API Explorer"),
        Binding("enter", "open_selected", "Open", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    CSS = """
    HomeScreen { align: center middle; }
    #menu { width: 104; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #banner { width: 1fr; text-align: center; margin-bottom: 1; }
    #contrib { width: 1fr; height: 7; text-align: center; margin-bottom: 1; }
    #menu-title { width: 1fr; text-align: center; margin-bottom: 1; }
    #stats { height: auto; align-horizontal: center; margin-bottom: 1; }
    .stat { width: 32; height: auto; border: round $panel; padding: 0 1; margin: 0 1; }
    .stat-label { width: 1fr; text-align: center; color: $text-muted; }
    #stats Digits { width: 1fr; text-align: center; color: $accent; }
    #home-menu { height: auto; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._cursor_on = True
        self._contrib_grid = _gen_contrib(f"{client.org}/contrib")
        self._contrib_frame = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu"):
            yield Static(_gradient_banner(), id="banner")
            yield Static(
                _render_contrib(self._contrib_grid, 0, None), id="contrib"
            )
            yield Static("", id="menu-title")
            with Horizontal(id="stats"):
                with Vertical(classes="stat"):
                    yield Label("Users", classes="stat-label")
                    yield Digits("", id="users-digits")
                with Vertical(classes="stat"):
                    yield Label("Repositories", classes="stat-label")
                    yield Digits("", id="repos-digits")
            yield OptionList(
                Option("Users          search org members and inspect profiles", id="users"),
                Option("Repositories   browse org repositories and their detail", id="repos"),
                Option("Actions        usage metrics + self-hosted runners", id="actions"),
                Option("Audit Log      org-wide audit-log events with filters", id="audit"),
                Option("Copilot        org Copilot seats and usage metrics", id="copilot"),
                Option("API Explorer   call curated org/enterprise REST endpoints", id="explorer"),
                id="home-menu",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org}"
        self._tagline = f"recon for [b]{self.client.org}[/b]  [dim]· select an area[/dim] "
        self._render_tagline()
        self.set_interval(0.5, self._blink_cursor)
        self.set_interval(0.05, self._tick_contrib)
        self.query_one("#home-menu", OptionList).focus()
        self._animate_intro()
        self.load_counts()

    @work(exclusive=True, thread=True)
    def load_counts(self) -> None:
        self.app.call_from_thread(self._set_counts_loading, True)
        try:
            users = self.client.member_count()
        except GitHubError:
            users = None
        try:
            repos = self.client.repo_count()
        except GitHubError:
            repos = None
        self.app.call_from_thread(self._render_counts, users, repos)

    def _set_counts_loading(self, value: bool) -> None:
        self.query_one("#users-digits", Digits).loading = value
        self.query_one("#repos-digits", Digits).loading = value

    def _render_counts(self, users: int | None, repos: int | None) -> None:
        for digit_id, value in (("#users-digits", users), ("#repos-digits", repos)):
            digit = self.query_one(digit_id, Digits)
            digit.loading = False
            digit.update(str(value) if value is not None else "—")

    def _animate_intro(self) -> None:
        """Fade the banner in on entry.

        We deliberately fade only the banner, not the whole #menu card. The
        OptionList lives inside #menu, and animating the container's opacity
        composites the list against the screen's black background — on first
        mount that leaves the list rendered black/unreadable until a full
        re-render (e.g. switching screens and back). Keeping the card at full
        opacity avoids putting the list through opacity compositing.
        """
        banner = self.query_one("#banner", Static)
        banner.styles.opacity = 0.0
        banner.styles.animate("opacity", value=1.0, duration=0.9, easing="out_cubic")

    def _blink_cursor(self) -> None:
        self._cursor_on = not self._cursor_on
        self._render_tagline()

    def _tick_contrib(self) -> None:
        """Animate the contribution graph: plant it left→right, then sweep-shimmer.

        Reveal runs once; afterwards a soft highlight band sweeps across on a
        cycle with an idle gap. During the gap we skip the redraw entirely so the
        idle landing screen isn't repainting for nothing.
        """
        self._contrib_frame += 1
        f = self._contrib_frame
        speed = 2  # columns revealed per tick
        reveal_end = _CONTRIB_COLS // speed
        if f <= reveal_end:
            self._paint_contrib(min(_CONTRIB_COLS, f * speed), None)
            return
        cycle = _CONTRIB_COLS + 70  # sweep span + idle gap before repeating
        pos = (f - reveal_end) % cycle
        if pos <= _CONTRIB_COLS + 2:
            self._paint_contrib(_CONTRIB_COLS, pos)
        elif pos == _CONTRIB_COLS + 3:
            self._paint_contrib(_CONTRIB_COLS, None)  # settle once, then idle

    def _paint_contrib(self, revealed: int, sweep: int | None) -> None:
        self.query_one("#contrib", Static).update(
            _render_contrib(self._contrib_grid, revealed, sweep)
        )

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

    def action_open_actions(self) -> None:
        self._open("actions")

    def action_open_audit(self) -> None:
        self._open("audit")

    def action_open_copilot(self) -> None:
        self._open("copilot")

    def action_open_explorer(self) -> None:
        self._open("explorer")

    def _open(self, area: str | None) -> None:
        if area == "users":
            self.app.push_screen(MembersScreen(self.client))
        elif area == "repos":
            self.app.push_screen(RepositoriesScreen(self.client))
        elif area == "actions":
            self.app.push_screen(ActionsScreen(self.client))
        elif area == "audit":
            self.app.push_screen(AuditLogScreen(self.client))
        elif area == "copilot":
            self.app.push_screen(CopilotScreen(self.client))
        elif area == "explorer":
            self.app.push_screen(ApiExplorerScreen(self.client))
