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
  config.py       # tiny JSON prefs under XDG config dir (persists the selected theme)
  api/            # requests-based GitHub client; returns dataclasses, raises GitHubError
    base.py       #   transport: BaseClient (_get/_request/_graphql), GitHubError, resolve_token, parse helpers
    members.py    #   MembersMixin: list/search/count members, org_role
    repos.py      #   ReposMixin: list/search/get/count repos, contributors, commits, languages, readme
    actions.py    #   ActionsMixin: usage + performance metrics + self-hosted runners (+ runner group, current-job correlation)
    users.py      #   UsersMixin: profile, keys, teams, audit log, authored-commit activity
    copilot.py    #   CopilotMixin: Copilot seat billing + usage metrics
    explorer.py   #   ExplorerMixin: curated org/enterprise endpoint catalog + raw api_call (build_catalog)
    mock.py       #   MockClient: synthetic data mirroring GitHubClient's surface (--mock)
    __init__.py   #   assembles GitHubClient from the mixins; re-exports GitHubError, resolve_token, MockClient
  ui/             # Textual presentation layer, one module per domain
    app.py        #   GhReconApp shell + OrgPromptScreen
    home.py       #   HomeScreen landing menu (Users / Repositories / Actions / Copilot / API Explorer)
    members.py    #   MembersScreen (member search)
    users.py      #   UserDetailScreen
    repos.py      #   RepositoriesScreen + RepoDetailScreen
    actions.py    #   ActionsScreen (usage + performance metrics + runners + current job)
    copilot.py    #   CopilotScreen (seats + usage metrics)
    explorer.py   #   ApiExplorerScreen (grouped endpoint tree + request builder + response) + ConfirmScreen
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
- Don't name a screen/widget method `_render` — it shadows Textual's internal
  `Widget._render()` and crashes on paint. Use a domain name (`_render_copilot`).

## Auth & scopes

Token resolution order: `--token`, `GH_TOKEN`, `GITHUB_TOKEN`, `gh auth token`.
Member search/user info need a normal token (`read:org` for full visibility). The
**audit log** needs an org-owner token with `read:audit_log` (Enterprise Cloud only).
**Actions** runners need an org-admin token (`admin:org`, or fine-grained self-hosted
runners read); usage **minutes** need org billing access (`actions_usage` leaves minutes
`None` on 403/404, or 410 once the org moves to the new enhanced billing platform that
retired the legacy endpoint, and counts 30-day runs via a bounded per-repo `total_count`
scan). **Performance metrics** (`actions_performance`: success rate, avg/median run duration,
by-conclusion breakdown, plus a per-`(repo, workflow)` breakdown) need no extra scope — they
sample one page of recent workflow runs per repo over the most-recently-pushed repos (bounded
by `scan_repos`), skip repos the token can't read, and so describe the sample, not the whole
org. The breakdown's job count isn't on the runs endpoint, so it's estimated from a bounded,
round-robin sample of per-run `runs/{id}/jobs` counts (total budget `job_scan_cap`)
extrapolated to each workflow's run count. Keep both scans bounded.
**Copilot** (seats + metrics) needs `manage_billing:copilot`/`read:org`/
`admin:org` and the org to have Copilot Business/Enterprise — `copilot_billing`/
`copilot_metrics` return `None` (not an error) on 403/404/422 so the screen degrades.
All of these must degrade gracefully when unavailable. Never log or echo tokens.

The runners screen has no org-level "running jobs" endpoint to lean on, so it maps a
busy runner to its workflow/job by scanning in-progress workflow runs across the org's
most-recently-pushed repos (bounded). It's best-effort — keep the scan bounded.

Runner group membership isn't carried on the runners endpoint either, so `list_runners`
builds a runner-id → group map from the `actions/runner-groups` endpoints and tags each
`Runner`. It's best-effort: if groups are unavailable (plan/scope), runners fall back to
the "Default" group. The screen renders runners grouped by group name.

GitHub's search API has no `org:` qualifier, so org-scoped user search is done by
listing members (paginated) and filtering by login client-side. Preserve that.

The **API explorer** (`ExplorerMixin` + `ApiExplorerScreen`) is a curated catalog of
org- and Enterprise-Cloud REST endpoints (`build_catalog(org)` in `api/explorer.py`)
plus a raw caller (`api_call(method, path, params, body)`). It uses `BaseClient._request`,
which — unlike `_get` — does **not** raise on HTTP error statuses, so 4xx/5xx bodies are
displayed verbatim; only bad JSON bodies and transport failures raise `GitHubError`.
Catalog paths are templates with `{org}`/`{enterprise}`/`{username}` placeholders; the
screen pre-fills `{org}` and the user fills the rest. The catalog renders as a collapsible
`Tree` grouped by path prefix (`_group_of` → `/orgs/{org}`, `/enterprises/{enterprise}`, or
`/` for top-level), each leaf tagged with a fixed-width colored method pill (`_method_badge`,
glyphs in `_METHOD_GLYPH`); the `ApiEndpoint` rides on the leaf's `node.data`. List
responses (`ApiResponse.data` is a list of objects, or a wrapper dict whose first list
value is — see `_extract_rows`) render in a `DataTable` with columns auto-deduced
(`_columns`: scalar fields only, identifying ones first, capped); `v` / a button toggles
to the raw JSON. Keep `ApiResponse.data` populated (real + mock) so the table can build.
Paged list responses get an `n`/`p` pager (default `per_page=10`); the screen owns the
page counter and injects `page`/`per_page` into GET requests, while `ApiResponse.has_next`
/`has_prev` (parsed from the Link header via `_link_rels`, emulated by the mock's
`_paginate`) drive the pager's enabled state. The table is theme-styled via DataTable
component classes (`datatable--header/odd-row/even-row/cursor`) in the screen CSS. All HTTP verbs are allowed, but
mutating ones (`models.WRITE_METHODS`: POST/PATCH/PUT/DELETE — see `ApiEndpoint.mutates`)
route through `ConfirmScreen` before sending. When you add/remove catalog entries, edit
only `build_catalog` — both the real and mock clients read from it, so they stay in sync.

## When you change things

- Update `README.md` when commands, key bindings, scopes, or layout change.
- Project agent/skill helpers live in `.claude/` (`github-tui-expert` agent,
  `refactor-python` skill).
