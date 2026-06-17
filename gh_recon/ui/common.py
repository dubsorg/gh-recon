"""Formatting helpers shared across UI screens."""

from __future__ import annotations

from datetime import datetime

from ..models import Page


class Paginator:
    """Tracks page cursors so a screen can walk a :class:`Page` stream.

    Cursors are opaque (page number, Link URL, …); the screen passes
    :attr:`cursor` to its client method and feeds the result back via
    :meth:`record`. Visited cursors are remembered so ``prev`` works even for
    cursor-based endpoints.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._cursors: list = [None]  # cursor to fetch each visited page
        self._index = 0
        self._has_next = False

    @property
    def page_number(self) -> int:
        return self._index + 1

    @property
    def has_prev(self) -> bool:
        return self._index > 0

    @property
    def has_next(self) -> bool:
        return self._has_next

    @property
    def cursor(self):
        return self._cursors[self._index]

    def record(self, page: Page) -> None:
        """Note the fetched page's next cursor (call after each load)."""
        self._has_next = page.next_cursor is not None
        if page.next_cursor is not None and self._index + 1 == len(self._cursors):
            self._cursors.append(page.next_cursor)

    def next(self) -> None:
        if self._has_next:
            self._index += 1

    def prev(self) -> None:
        if self._index > 0:
            self._index -= 1


def _fmt_dt(value: str | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.replace("T", " ").replace("Z", "")


def _language_chart(langs: list[tuple[str, int]]) -> str:
    """Render a list of (language, bytes) as a padded percentage bar chart."""
    total = sum(b for _, b in langs) or 1
    lines = []
    for name, b in langs[:8]:
        pct = b / total * 100
        filled = round(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"  {name[:12]:<12} {bar} {pct:5.1f}%")
    return "\n".join(lines)
