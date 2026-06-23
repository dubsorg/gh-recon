"""API explorer screen: browse curated org/enterprise endpoints and call them.

Left pane is a filterable catalog of endpoints scoped to the selected org (and
GitHub Enterprise Cloud). Right pane resolves an endpoint's path, lets you add a
query string / JSON body, and sends the request — mutating verbs go through a
confirmation modal first. Responses (including 4xx/5xx bodies) render raw.
"""

from __future__ import annotations

import shlex
from urllib.parse import parse_qsl

from rich.syntax import Syntax
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.tree import TreeNode

from ..api import GitHubClient, GitHubError
from ..api.base import API_ROOT
from ..models import ApiEndpoint, ApiResponse

_METHOD_COLOR = {
    "GET": "green",
    "POST": "cyan",
    "PUT": "yellow",
    "PATCH": "yellow",
    "DELETE": "red",
}

# Emoji glyphs, all width-2 in Rich's cell table so every pill stays uniform.
_METHOD_GLYPH = {
    "GET": "📥",   # fetch / read
    "POST": "➕",  # create
    "PUT": "📤",   # replace / upload
    "PATCH": "🩹",  # partial update (a "patch")
    "DELETE": "🗑️",  # remove
}

# Folder icon prefixed to each group header.
_GROUP_GLYPH = "📁"

def _method_badge(method: str) -> Text:
    """A fixed-width, glyph-only 'badge' for the HTTP method.

    Every badge is the same width (space + width-2 emoji + space) so it stays
    uniform regardless of verb. The emoji carries the verb's color as a
    *foreground* tint (no background fill — emoji render their own glyph color on
    most terminals); the path is appended (theme-colored) by the caller.
    """
    color = _METHOD_COLOR.get(method, "white")
    glyph = _METHOD_GLYPH.get(method, "•")
    badge = Text(f" {glyph} ")
    # stylize() scopes the foreground color to a span over the badge only, so the
    # appended path keeps the theme foreground.
    badge.stylize(color)
    return badge


def _short_path(path: str) -> str:
    """Path with a leading ``/orgs/{org}`` or ``/enterprises/{enterprise}`` stripped.

    The tree groups by category, so the scope is already implied; leaves show
    just the distinguishing tail (e.g. ``/actions/runners``) to stay readable in
    the narrow catalog pane. The request pane still shows the full resolved path.
    Returns ``/`` for a group's own resource (``GET /orgs/{org}``) and the full
    path for un-scoped endpoints (``/user``, ``/rate_limit``).
    """
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in ("orgs", "enterprises"):
        prefix = "/" + "/".join(parts[:2])
        return path[len(prefix):] or "/"
    return path


def _group_label(category: str, count: int) -> Text:
    """Folder icon + bold category + dim count, e.g. ``📁 actions  (98)``."""
    return (
        Text(f"{_GROUP_GLYPH} ")
        + Text(category, style="bold")
        + Text(f"  ({count})", style="dim")
    )


# Identifying columns surfaced first (in this order) when present in the rows.
_PREFERRED_COLS = [
    "id", "number", "name", "full_name", "login", "slug", "title", "type",
    "state", "status", "conclusion", "visibility", "private", "html_url",
    "created_at", "updated_at",
]
_MAX_COLS = 8
_MAX_TABLE_ROWS = 500
_CELL_MAXLEN = 48


def _extract_rows(data: object) -> list[dict] | None:
    """Find a list-of-objects to tabulate, or ``None`` if the data isn't a list.

    Handles both a top-level array (``[{…}, …]``) and GitHub's common wrapper
    object (``{"total_count": N, "runners": [{…}]}``) by taking the first value
    that is a non-empty list of objects.
    """
    if isinstance(data, list):
        rows = [d for d in data if isinstance(d, dict)]
        return rows or None
    if isinstance(data, dict):
        for value in data.values():
            if (
                isinstance(value, list)
                and value
                and all(isinstance(d, dict) for d in value)
            ):
                return value
    return None


def _columns(rows: list[dict]) -> list[str]:
    """Pick up to ``_MAX_COLS`` scalar columns, identifying fields first."""
    scalar: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key, value in row.items():
            if key in seen or isinstance(value, (dict, list)):
                continue  # skip nested structures — they stay in the raw view
            seen.add(key)
            scalar.append(key)
    ordered = [k for k in _PREFERRED_COLS if k in seen]
    ordered += [k for k in scalar if k not in _PREFERRED_COLS]
    return ordered[:_MAX_COLS]


def _fmt_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "✓" if value else ""
    text = str(value)
    return text if len(text) <= _CELL_MAXLEN else text[: _CELL_MAXLEN - 1] + "…"


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _curl_snippet(method: str, url: str, body: str) -> str:
    """Build a copy-pasteable ``curl`` for a request, with a token placeholder.

    Mirrors the headers the client actually sends (see ``BaseClient``); the real
    token is never embedded — the snippet reads ``$GH_TOKEN`` from the env.
    """
    parts = ["curl -L"]
    if method != "GET":
        parts.append(f"-X {method}")
    parts.append('-H "Accept: application/vnd.github+json"')
    parts.append('-H "Authorization: Bearer $GH_TOKEN"')
    parts.append('-H "X-GitHub-Api-Version: 2022-11-28"')
    if body.strip():
        parts.append(f"-d {shlex.quote(body)}")
    parts.append(f'"{url}"')
    return " \\\n  ".join(parts)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation for a mutating request."""

    BINDINGS = [
        Binding("escape", "dismiss_no", "Cancel"),
        Binding("y", "confirm", "Confirm"),
    ]

    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box { width: 70; height: auto; border: round $error; padding: 1 2; background: $surface; }
    #confirm-box Label { margin-bottom: 1; }
    #confirm-buttons { height: auto; align-horizontal: center; }
    #confirm-buttons Button { margin: 0 1; }
    """

    _DEFAULT_MESSAGE = (
        "This is a [b]mutating[/b] request that can change org state. Send it?"
    )

    def __init__(
        self,
        method: str,
        path: str,
        *,
        message: str | None = None,
        confirm_label: str = "Send (y)",
    ) -> None:
        super().__init__()
        self._method = method
        self._path = path
        self._message = message or self._DEFAULT_MESSAGE
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(
                f"[b $error]{self._method}[/] [b]{self._path}[/]\n\n{self._message}"
            )
            with Horizontal(id="confirm-buttons"):
                yield Button(self._confirm_label, variant="error", id="yes")
                yield Button("Cancel (Esc)", id="no")

    @on(Button.Pressed, "#yes")
    def action_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class ShellSnippetScreen(ModalScreen[None]):
    """Show a copy-pasteable ``curl`` snippet for the composed request."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("c", "copy", "Copy"),
    ]

    CSS = """
    ShellSnippetScreen { align: center middle; }
    #snippet-box { width: 90%; max-width: 110; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #snippet-title { text-style: bold; margin-bottom: 1; }
    #snippet-body { height: auto; margin-bottom: 1; }
    #snippet-buttons { height: auto; align-horizontal: center; }
    #snippet-buttons Button { margin: 0 1; }
    """

    def __init__(self, snippet: str) -> None:
        super().__init__()
        self._snippet = snippet

    def compose(self) -> ComposeResult:
        with Vertical(id="snippet-box"):
            yield Label("Shell snippet  ·  $GH_TOKEN = your token", id="snippet-title")
            yield Static(
                Syntax(self._snippet, "bash", theme="ansi_dark", word_wrap=True),
                id="snippet-body",
            )
            with Horizontal(id="snippet-buttons"):
                yield Button("Copy (c)", variant="primary", id="copy")
                yield Button("Close (Esc)", id="close")

    @on(Button.Pressed, "#copy")
    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self._snippet)
        self.notify("Snippet copied to clipboard.")

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


class ApiExplorerScreen(Screen):
    """Browse and call curated org/enterprise REST endpoints."""

    BINDINGS = [
        Binding("slash", "focus_filter", "Filter"),
        Binding("s", "send", "Send"),
        Binding("c", "show_curl", "cURL"),
        Binding("v", "toggle_view", "Table/Raw"),
        Binding("n", "next_page", "Next page"),
        Binding("p", "prev_page", "Prev page"),
        Binding("left_square_bracket", "shrink_catalog", "Narrower", key_display="["),
        Binding("right_square_bracket", "grow_catalog", "Wider", key_display="]"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    # Catalog-pane width is adjustable at runtime with [ / ]; clamped to this range.
    CATALOG_MIN_WIDTH = 30
    CATALOG_MAX_WIDTH = 90
    CATALOG_WIDTH_STEP = 4
    catalog_width: reactive[int] = reactive(48)

    CSS = """
    #explorer-main { height: 1fr; }
    #catalog-pane { width: 48; border-right: solid $panel; }
    #endpoint-filter { margin: 0 1; }
    #endpoint-tree { height: 1fr; }
    #request-pane { width: 1fr; padding: 0 1; }
    #endpoint-summary { height: auto; padding: 0 0 1 0; }
    #mutation-warning { height: auto; display: none; margin-bottom: 1; padding: 0 1; border: round $warning; color: $warning; text-style: bold; }
    #mutation-warning.delete { border: round $error; color: $error; }
    .field-label { color: $text-muted; height: 1; }
    #path-input, #query-input { margin-bottom: 1; }
    #body-input { height: 6; margin-bottom: 1; }
    #response-header { height: auto; }
    #response-status { width: 1fr; height: auto; content-align: left middle; }
    #toggle-view { width: auto; min-width: 12; height: 3; display: none; }
    #response-scroll { height: 1fr; border: round $panel; }
    #response-body { width: 1fr; padding: 0 1; }
    #response-table { height: 1fr; border: round $panel; display: none; }
    /* Theme-driven table styling: bold accent header + zebra rows + accent cursor. */
    #response-table > .datatable--header { background: $panel; color: $accent; text-style: bold; }
    #response-table > .datatable--odd-row { background: $surface; }
    #response-table > .datatable--even-row { background: $boost; }
    #response-table > .datatable--cursor { background: $accent; color: $background; }
    #pager { height: auto; align-horizontal: center; display: none; }
    #pager Button { min-width: 10; margin: 0 1; }
    #page-label { width: auto; min-width: 16; content-align: center middle; color: $text-muted; }
    """

    def __init__(self, client: GitHubClient) -> None:
        super().__init__()
        self.client = client
        self._all: list[ApiEndpoint] = []
        self._current: ApiEndpoint | None = None
        self._rows: list[dict] | None = None  # tabular data for the last response
        self._raw_mode = False  # show JSON instead of the table
        # Pagination state for the last list request.
        self._per_page = 10
        self._page = 1
        self._has_next = False
        self._last_request: tuple[str, str, dict[str, str], str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="explorer-main"):
            with Vertical(id="catalog-pane"):
                yield Input(
                    placeholder="Filter endpoints…  (/)", id="endpoint-filter"
                )
                tree: Tree[ApiEndpoint] = Tree("endpoints", id="endpoint-tree")
                tree.show_root = False
                tree.guide_depth = 2
                yield tree
            with Vertical(id="request-pane"):
                yield Static("", id="endpoint-summary")
                yield Static("", id="mutation-warning")
                yield Label("Path", classes="field-label")
                yield Input(id="path-input", placeholder="/orgs/{org}")
                yield Label("Query  (key=value&key=value)", classes="field-label")
                yield Input(id="query-input", placeholder="per_page=5")
                yield Label("Body  (JSON, for mutations)", classes="field-label")
                yield TextArea(id="body-input")
                with Horizontal(id="response-header"):
                    yield Static(
                        "[dim]Select an endpoint, then s to send.[/dim]",
                        id="response-status",
                    )
                    yield Button("Raw JSON", id="toggle-view")
                with VerticalScroll(id="response-scroll"):
                    yield Static("", id="response-body")
                yield DataTable(
                    id="response-table", zebra_stripes=True, cursor_type="row"
                )
                with Horizontal(id="pager"):
                    yield Button("◀ Prev", id="prev-page")
                    yield Static("", id="page-label")
                    yield Button("Next ▶", id="next-page")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"org: {self.client.org} / api explorer"
        self._all = self.client.api_endpoints()
        groups = self._populate(self._all)
        # Default to collapsed groups (saves space); open the first category and
        # pre-select its first endpoint so the request pane isn't empty.
        if self._all:
            first = sorted(self._all, key=lambda e: e.category)[0]
            groups[first.category].expand()
            self._select(first)
        self.query_one("#endpoint-tree", Tree).focus()

    def _populate(
        self, endpoints: list[ApiEndpoint], *, expand: bool = False
    ) -> dict[str, TreeNode]:
        """Rebuild the category-grouped tree; returns the category → node map.

        Endpoints are sorted by category (a stable sort, so each category keeps
        the catalog's path order) and collapsed under one folder per category.
        """
        tree = self.query_one("#endpoint-tree", Tree)
        tree.clear()
        groups: dict[str, TreeNode] = {}
        for ep in sorted(endpoints, key=lambda e: e.category):
            grp = groups.get(ep.category)
            if grp is None:
                grp = tree.root.add(ep.category, expand=expand)
                groups[ep.category] = grp
            grp.add_leaf(
                _method_badge(ep.method) + Text(f" {_short_path(ep.path)}"), data=ep
            )
        for category, grp in groups.items():
            grp.set_label(_group_label(category, len(grp.children)))
        return groups

    def action_focus_filter(self) -> None:
        self.query_one("#endpoint-filter", Input).focus()

    def watch_catalog_width(self, width: int) -> None:
        """Apply the catalog pane width whenever the reactive changes (live resize)."""
        if self.is_mounted:
            self.query_one("#catalog-pane").styles.width = width

    def action_grow_catalog(self) -> None:
        self.catalog_width = min(
            self.CATALOG_MAX_WIDTH, self.catalog_width + self.CATALOG_WIDTH_STEP
        )

    def action_shrink_catalog(self) -> None:
        self.catalog_width = max(
            self.CATALOG_MIN_WIDTH, self.catalog_width - self.CATALOG_WIDTH_STEP
        )

    @on(Input.Changed, "#endpoint-filter")
    def _on_filter(self, event: Input.Changed) -> None:
        q = event.value.strip().lower()
        if not q:
            self._populate(self._all)
            return
        # While filtering, expand every group so matches are visible at a glance.
        self._populate(
            [
                ep
                for ep in self._all
                if q in ep.method.lower()
                or q in ep.path.lower()
                or q in ep.summary.lower()
                or q in ep.category.lower()
            ],
            expand=True,
        )

    @on(Tree.NodeHighlighted, "#endpoint-tree")
    def _on_highlight(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None:
            self._select(event.node.data)

    @on(Tree.NodeSelected, "#endpoint-tree")
    def _on_select(self, event: Tree.NodeSelected) -> None:
        if event.node.data is not None:
            self._select(event.node.data)
            self.query_one("#path-input", Input).focus()

    def _select(self, ep: ApiEndpoint) -> None:
        self._current = ep
        # Pre-fill {org}; leave other placeholders for the user to complete.
        self.query_one("#path-input", Input).value = ep.path.replace(
            "{org}", self.client.org
        )
        scope = f"  [dim]· scope: {ep.scope}[/dim]" if ep.scope else ""
        warn = "  [red](mutating)[/red]" if ep.mutates else ""
        self.query_one("#endpoint-summary", Static).update(
            f"[$text-muted]{ep.category}[/]\n[b]{ep.method}[/b] {ep.summary}{warn}{scope}"
        )
        self._update_warning(ep)

    def _update_warning(self, ep: ApiEndpoint) -> None:
        """Show a persistent banner for any endpoint that modifies or deletes."""
        banner = self.query_one("#mutation-warning", Static)
        banner.display = ep.mutates
        banner.set_class(ep.method == "DELETE", "delete")
        if ep.method == "DELETE":
            banner.update(
                "⚠  DELETE — permanently removes a resource. "
                "You'll be asked to confirm twice."
            )
        elif ep.mutates:
            banner.update(
                f"⚠  {ep.method} modifies org state. Confirm before sending."
            )

    def action_show_curl(self) -> None:
        """Pop a modal with a ``curl`` snippet for the currently composed request."""
        if self._current is None:
            self._set_status("[yellow]Select an endpoint first.[/yellow]")
            return
        path = self.query_one("#path-input", Input).value.strip()
        url = f"{API_ROOT}{path}" if path.startswith("/") else path
        query = self.query_one("#query-input", Input).value.strip()
        if query:
            url += f"?{query}"
        body = self.query_one("#body-input", TextArea).text
        snippet = _curl_snippet(self._current.method, url, body)
        self.app.push_screen(ShellSnippetScreen(snippet))

    def action_send(self) -> None:
        if self._current is None:
            self._set_status("[yellow]Select an endpoint first.[/yellow]")
            return
        path = self.query_one("#path-input", Input).value.strip()
        if "{" in path and "}" in path:
            self._set_status(
                "[yellow]Fill in the remaining {placeholders} in the path.[/yellow]"
            )
            return
        method = self._current.method
        if method == "DELETE":
            self._confirm_delete(method, path)
        elif self._current.mutates:
            self.app.push_screen(
                ConfirmScreen(method, path),
                lambda ok: self._do_send(method, path) if ok else None,
            )
        else:
            self._do_send(method, path)

    def _confirm_delete(self, method: str, path: str) -> None:
        """Gate a DELETE behind two separate confirmations before sending."""

        def second(ok: bool) -> None:
            if ok:
                self._do_send(method, path)

        def first(ok: bool) -> None:
            if ok:
                self.app.push_screen(
                    ConfirmScreen(
                        method,
                        path,
                        message=(
                            "[b]Final confirmation.[/b] This [b]cannot be undone[/b]. "
                            "Delete this resource for real?"
                        ),
                        confirm_label="Delete (y)",
                    ),
                    second,
                )

        self.app.push_screen(
            ConfirmScreen(
                method,
                path,
                message=(
                    "This will [b]permanently delete[/b] the resource at this path. "
                    "Continue?"
                ),
                confirm_label="Continue (y)",
            ),
            first,
        )

    def _do_send(self, method: str, path: str) -> None:
        params = dict(
            parse_qsl(self.query_one("#query-input", Input).value.strip())
        )
        body = self.query_one("#body-input", TextArea).text
        # The pager owns page/per_page, so lift any the user typed out of the base
        # params: per_page seeds the page size, page seeds the starting page.
        self._per_page = max(1, _to_int(params.pop("per_page", None), 10))
        self._page = max(1, _to_int(params.pop("page", None), 1))
        self._last_request = (method, path, params, body)
        self._send_page()

    def _send_page(self) -> None:
        method, path, params, body = self._last_request
        call_params = dict(params)
        if method == "GET":  # only GET list endpoints paginate
            call_params["per_page"] = str(self._per_page)
            call_params["page"] = str(self._page)
        self.send_request(method, path, call_params, body)

    def action_next_page(self) -> None:
        if self._has_next and self._last_request:
            self._page += 1
            self._send_page()

    def action_prev_page(self) -> None:
        if self._page > 1 and self._last_request:
            self._page -= 1
            self._send_page()

    @on(Button.Pressed, "#next-page")
    def _on_next(self, event: Button.Pressed) -> None:
        self.action_next_page()

    @on(Button.Pressed, "#prev-page")
    def _on_prev(self, event: Button.Pressed) -> None:
        self.action_prev_page()

    @work(exclusive=True, thread=True, group="explorer")
    def send_request(
        self, method: str, path: str, params: dict[str, str], body: str
    ) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            resp = self.client.api_call(method, path, params=params, body=body)
        except GitHubError as exc:
            self.app.call_from_thread(self._error, str(exc))
            return
        self.app.call_from_thread(self._render_response, resp)

    def _set_loading(self, value: bool) -> None:
        self.query_one("#response-body", Static).loading = value
        self.query_one("#response-table", DataTable).loading = value
        if value:
            self._set_status("[dim]Sending…[/dim]")

    def _error(self, msg: str) -> None:
        self.query_one("#response-body", Static).loading = False
        self.query_one("#response-table", DataTable).loading = False
        self._rows = None
        self._apply_view()
        self._update_pager()
        self._set_status(f"[red]{msg}[/red]")

    def _set_status(self, markup: str) -> None:
        self.query_one("#response-status", Static).update(markup)

    def _render_response(self, resp: ApiResponse) -> None:
        body_widget = self.query_one("#response-body", Static)
        body_widget.loading = False
        self.query_one("#response-table", DataTable).loading = False
        color = "green" if resp.ok else "red"
        rl = resp.rate_limit.get("X-RateLimit-Remaining")
        rl_txt = f" · rate-limit left: {rl}" if rl else ""
        status = (
            f"[b {color}]{resp.status} {resp.reason}[/] · {resp.method} · "
            f"{resp.elapsed_ms} ms{rl_txt}"
        )

        # Always prepare the raw body so the toggle can switch to it.
        if not resp.body:
            body_widget.update("[dim](empty response body)[/dim]")
        elif resp.is_json:
            body_widget.update(
                Syntax(resp.body, "json", theme="ansi_dark", word_wrap=True)
            )
        else:
            body_widget.update(resp.body)

        # Tabulate when the response is a list of objects; default to that view.
        rows = _extract_rows(resp.data) if resp.is_json else None
        self._raw_mode = False
        self._rows = rows if rows and self._fill_table(rows) else None
        self._has_next = bool(self._rows) and resp.has_next
        if self._rows:
            status += f" · [dim]{len(self._rows)} rows · v for raw/table[/dim]"
        self._set_status(status)
        self._apply_view()
        self._update_pager()

    def _update_pager(self) -> None:
        """Show the pager when the current list response spans multiple pages."""
        pageable = bool(self._rows) and (self._has_next or self._page > 1)
        pager = self.query_one("#pager", Horizontal)
        pager.display = pageable
        if not pageable:
            return
        self.query_one("#page-label", Static).update(
            f"page {self._page} · {self._per_page}/page"
        )
        self.query_one("#prev-page", Button).disabled = self._page <= 1
        self.query_one("#next-page", Button).disabled = not self._has_next

    def _fill_table(self, rows: list[dict]) -> bool:
        """Populate the table; return ``False`` if no scalar columns were found."""
        table = self.query_one("#response-table", DataTable)
        table.clear(columns=True)
        cols = _columns(rows)
        if not cols:
            return False  # nothing scalar to show — fall back to raw JSON
        table.add_columns(*cols)
        for row in rows[:_MAX_TABLE_ROWS]:
            table.add_row(*[_fmt_cell(row.get(c)) for c in cols])
        return True

    def action_toggle_view(self) -> None:
        if self._rows:
            self._raw_mode = not self._raw_mode
            self._apply_view()

    @on(Button.Pressed, "#toggle-view")
    def _on_toggle(self, event: Button.Pressed) -> None:
        self.action_toggle_view()

    def _apply_view(self) -> None:
        """Show table or raw JSON, and label/show the toggle button accordingly."""
        tabular = bool(self._rows)
        show_table = tabular and not self._raw_mode
        button = self.query_one("#toggle-view", Button)
        button.display = tabular
        button.label = "Raw JSON" if show_table else "Table"
        self.query_one("#response-table", DataTable).display = show_table
        self.query_one("#response-scroll", VerticalScroll).display = not show_table
