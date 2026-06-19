"""Application shell: org prompt and the top-level Textual App."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Input, Label

from ..api import GitHubClient, MockClient
from ..config import load_prefs, save_prefs
from .home import HomeScreen

# A neon "recon" terminal palette — green/cyan on near-black.
RECON_THEME = Theme(
    name="recon",
    primary="#39ff14",
    secondary="#00e5ff",
    accent="#39ff14",
    foreground="#c8f7d0",
    background="#06090a",
    surface="#0c1311",
    panel="#13201a",
    success="#39ff14",
    warning="#ffd166",
    error="#ff5370",
    dark=True,
    variables={
        # The selected/highlighted row sits on the bright-green cursor; force a
        # near-black foreground so it stays readable (the default "auto" picks
        # white against the dark base, which washes out on green).
        "block-cursor-foreground": "#06090a",
        "block-cursor-text-style": "bold",
    },
)


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


class GhReconApp(App):
    TITLE = "gh-recon"
    CSS = """
    Screen { layers: base; }
    """

    def __init__(self, org: str | None, token: str | None, mock: bool = False) -> None:
        super().__init__()
        self._org = org
        self._token = token
        self._mock = mock

    def on_mount(self) -> None:
        self.register_theme(RECON_THEME)
        saved = load_prefs().get("theme")
        # Fall back to "recon" if no theme was saved or the saved one is no
        # longer available (e.g. a built-in theme was renamed/removed).
        self.theme = saved if saved in self.available_themes else "recon"
        # Persist whatever the user picks later (via the command palette).
        # Subscribing after the initial set avoids re-writing the same value.
        self.theme_changed_signal.subscribe(self, self._persist_theme)
        if self._org:
            self._start(self._org)
        else:
            self.push_screen(OrgPromptScreen(), self._on_org)

    def _persist_theme(self, theme: Theme) -> None:
        prefs = load_prefs()
        prefs["theme"] = theme.name
        save_prefs(prefs)

    def _on_org(self, org: str | None) -> None:
        if not org:
            self.exit()
            return
        self._start(org)

    def _start(self, org: str) -> None:
        client = (
            MockClient(org=org)
            if self._mock
            else GitHubClient(org=org, token=self._token)
        )
        self.push_screen(HomeScreen(client))
