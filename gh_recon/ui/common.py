"""Formatting helpers shared across UI screens."""

from __future__ import annotations

from datetime import datetime


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
