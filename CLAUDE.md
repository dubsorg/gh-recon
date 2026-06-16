# CLAUDE.md

Guidance for working in this repo.

## What this is

`gh-recon` is a [`gh` CLI](https://cli.github.com/) **script extension**: a Textual
terminal UI for GitHub organization recon, scoped to a single org. `gh` runs the
executable `gh-recon` at the repo root as `gh recon`, which bootstraps a private
venv and launches the app.

## Layout

```
gh-recon          # executable extension entrypoint (gh runs this as `gh recon`)
run.sh            # local dev wrapper around ./gh-recon
requirements.txt  # deps installed into the auto-created venv (textual, requests)
gh_recon/
  api.py          # requests-based GitHub client; returns dataclasses, raises GitHubError
  app.py          # Textual app: member list, user detail, repo list, repo detail screens
  __main__.py     # CLI entry point + token resolution
```

Keep the layers separate: HTTP/parsing lives in `api.py`, presentation in `app.py`.

## Run / verify

```bash
./run.sh <org>          # local dev launch (e.g. ./run.sh my-company)
./gh-recon <org>        # same entrypoint gh uses
python -c "import gh_recon.api, gh_recon.app"   # quick import check for logic-only changes
```

There is no test suite yet. Verify UI changes by launching the app; verify pure
logic with a `python -c` against `gh_recon.api`.

## Conventions

- **Python 3.9+**. Files use `from __future__ import annotations`, so `str | None`
  and `list[tuple[...]]` annotations are fine — keep 3.9 runtime compatibility.
- Only `textual` and `requests` are dependencies. Don't add more without reason.
- API failures surface through `GitHubError(message, status)`. Don't swallow them.
- Network calls run inside Textual `@work` workers so the UI never blocks; events
  are handled with `@on(...)`. Follow these patterns when adding screens/widgets.
- Reuse existing helpers (`_fmt_dt`, `_language_chart`) and the dataclasses
  (`UserInfo`, `Repo`, `CommitInfo`, `AuditEvent`) rather than reinventing.

## Auth & scopes

Token resolution order: `--token`, `GH_TOKEN`, `GITHUB_TOKEN`, `gh auth token`.
Member search/user info need a normal token (`read:org` for full visibility). The
**audit log** needs an org-owner token with `read:audit_log` (Enterprise Cloud only)
and must degrade gracefully when unavailable. Never log or echo tokens.

GitHub's search API has no `org:` qualifier, so org-scoped user search is done by
listing members (paginated) and filtering by login client-side. Preserve that.

## When you change things

- Update `README.md` when commands, key bindings, scopes, or layout change.
- Project agent/skill helpers live in `.claude/` (`github-tui-expert` agent,
  `refactor-python` skill).
