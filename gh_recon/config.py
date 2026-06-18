"""Tiny on-disk preferences for the app shell.

Currently just the selected theme, stored as JSON under the XDG config dir so a
user's choice survives across runs. Stdlib only; every operation degrades to a
no-op / empty dict on any I/O or parse error so a bad/locked config never breaks
startup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_APP_DIR = "gh-recon"
_FILENAME = "config.json"


def _config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / _APP_DIR / _FILENAME


def load_prefs() -> dict[str, Any]:
    """Return saved preferences, or an empty dict if none/unreadable."""
    try:
        with _config_path().open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(prefs: dict[str, Any]) -> None:
    """Persist preferences, silently ignoring any write failure."""
    path = _config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except OSError:
        pass
