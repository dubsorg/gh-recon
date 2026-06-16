---
name: refactor-python
description: Refactor Python code in this project for clarity and structure without changing behavior. Use when asked to clean up, restructure, deduplicate, extract functions, improve typing, or simplify Python in gh_recon/. Behavior-preserving only — not for new features or bug fixes.
---

# Refactor Python

Improve the structure of existing Python **without changing observable behavior**. This project is `gh-recon`: a `requests` GitHub client (`gh_recon/api.py`) and a Textual TUI (`gh_recon/app.py`), Python 3.9+ with `from __future__ import annotations`.

## Before touching code

1. Read the target file(s) fully and identify the current behavior.
2. Establish a safety net: run whatever tests/checks exist, or at minimum import-check (`python -c "import gh_recon.app, gh_recon.api"`) and launch the app (`./run.sh <org>`) if the change affects the UI path.
3. Refactor in small, reviewable steps. Re-verify after each step.

## What to look for

- **Duplication** → extract a helper. Note existing helpers (`_fmt_dt`, `_language_chart`) and reuse rather than duplicate.
- **Long functions / deeply nested conditionals** → extract functions, use early returns/guard clauses.
- **Layer leakage** → keep HTTP/parsing in `api.py` and presentation in `app.py`; move misplaced logic to the right layer.
- **Weak typing** → add/strengthen type hints and dataclasses. `str | None`-style unions are OK here thanks to `from __future__ import annotations`.
- **Naming** → rename unclear locals/params; match the surrounding naming and comment density.
- **Magic values / repeated literals** → name them as module constants (e.g. alongside `API_ROOT`).
- **Error handling** → keep `GitHubError(message, status)` as the surfacing mechanism; don't swallow exceptions or change which errors propagate.

## Constraints

- **Preserve behavior**: same inputs → same outputs, same side effects, same error/exit semantics, same key bindings and screen flow. If you find a real bug, surface it separately — do not silently "fix" it inside a refactor.
- Keep the public surface stable (dataclass fields, function signatures used across modules) unless the user asks otherwise; update all call sites if you do change one.
- Don't add dependencies — only `textual` and `requests` are available (see `requirements.txt`).
- Stay within Python 3.9 compatibility.
- Keep diffs focused; avoid unrelated reformatting churn.

## Finish

- Re-run the safety net (imports, tests, and the app if relevant).
- Summarize what changed and confirm behavior is unchanged. Flag anything you could not verify.
