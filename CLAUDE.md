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
  models.py       # dataclasses shared by both layers (Member, Repo, UserInfo, …)
  api/            # requests-based GitHub client; returns dataclasses, raises GitHubError
    base.py       #   transport: BaseClient (_get/_graphql), GitHubError, resolve_token, parse helpers
    members.py    #   MembersMixin: list/search members, org_role
    repos.py      #   ReposMixin: list/search/get repos, contributors, commits, languages
    runners.py    #   RunnersMixin: Actions self-hosted runners (+ runner group, current-job correlation)
    users.py      #   UsersMixin: profile, keys, teams, audit log, authored-commit activity
    mock.py       #   MockClient: synthetic data mirroring GitHubClient's surface (--mock)
    __init__.py   #   assembles GitHubClient from the mixins; re-exports GitHubError, resolve_token, MockClient
  ui/             # Textual presentation layer, one module per domain
    app.py        #   GhReconApp shell + OrgPromptScreen
    home.py       #   HomeScreen landing menu (Users / Repositories / Runners)
    members.py    #   MembersScreen (member search)
    users.py      #   UserDetailScreen
    repos.py      #   RepositoriesScreen + RepoDetailScreen
    runners.py    #   RunnersScreen (Actions runners + current job)
    common.py     #   shared formatting helpers (_fmt_dt, _language_chart) + Paginator
    __init__.py   #   re-exports GhReconApp
  __main__.py     # CLI entry point + token resolution
```

Keep the layers separate: HTTP/parsing lives in `api/`, presentation in `ui/`,
and the dataclasses they exchange in `models.py`. Within each layer, group code
by domain (members / repos / users). The client is one class assembled from
per-domain mixins — add a method to the mixin its endpoint belongs to.

`api/mock.py`'s `MockClient` is a drop-in stand-in selected by `--mock` that
returns the same dataclasses from synthetic data (no token/network). When you add
or change a public client method the UI calls, mirror it there so mock mode keeps
working. Its network-facing methods are wrapped with `@_latent`, which sleeps a
short randomized `latency` (default `(0.4, 1.1)`s, `None` to disable) so mock runs
exercise the same async/loading paths as the real client.

Screens show progress with Textual's `loading` reactive: a worker sets the target
widget's `.loading = True` (via `call_from_thread`) before fetching and the
render/error handler sets it back to `False`. That overlays a `LoadingIndicator`
automatically — prefer it over hand-mounting spinners or "loading…" text.

## Pagination

Browse lists are paged, not pulled whole (default page size `DEFAULT_PAGE_SIZE = 20`
in `api/base.py`). Paged client methods take a `cursor` + `per_page` and return a
`Page[T]` (`gh_recon.models`) whose `next_cursor` is an **opaque** token: a page
number for REST `page`/`per_page` endpoints (members, repos), a Link-header URL for
the audit log, or a slice index for client-side filtered lists (`_paginate_list`).
The UI never interprets the cursor, so real and mock clients can use different cursor
types. `ui/common.py`'s `Paginator` tracks visited cursors so `n`/`p` (next/prev) work
even for cursor-based endpoints. Paged so far: members, repos, audit log. Bounded
top-N lists (runners, repo contributors/commits, `recent_commit_repos` aggregation)
are intentionally not paged. Keep client-side search filtering (it lists then slices).

## Run / verify

```bash
./run.sh <org>          # local dev launch (e.g. ./run.sh my-company)
./gh-recon <org>        # same entrypoint gh uses
python -c "import gh_recon.api, gh_recon.ui"   # quick import check for logic-only changes
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
**audit log** needs an org-owner token with `read:audit_log` (Enterprise Cloud only).
**Actions runners** need an org-admin token (`admin:org`, or fine-grained self-hosted
runners read). Both must degrade gracefully when unavailable. Never log or echo tokens.

The runners screen has no org-level "running jobs" endpoint to lean on, so it maps a
busy runner to its workflow/job by scanning in-progress workflow runs across the org's
most-recently-pushed repos (bounded). It's best-effort — keep the scan bounded.

Runner group membership isn't carried on the runners endpoint either, so `list_runners`
builds a runner-id → group map from the `actions/runner-groups` endpoints and tags each
`Runner`. It's best-effort: if groups are unavailable (plan/scope), runners fall back to
the "Default" group. The screen renders runners grouped by group name.

GitHub's search API has no `org:` qualifier, so org-scoped user search is done by
listing members (paginated) and filtering by login client-side. Preserve that.

## When you change things

- Update `README.md` when commands, key bindings, scopes, or layout change.
- Project agent/skill helpers live in `.claude/` (`github-tui-expert` agent,
  `refactor-python` skill).
