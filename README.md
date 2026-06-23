# gh-recon

A [`gh`](https://cli.github.com/) CLI extension: a terminal UI (TUI) for GitHub
organization recon, built with [Textual](https://textual.textualize.io/).

Scoped to a single organization, it opens to a **home menu** that branches into:

- **Users** — search the org's members by login, then **get user info**: full profile, org-membership role, **team memberships**, **most-used languages**, **public SSH/GPG keys** (with SSH fingerprints), **repos recently committed to**, and **recent audit-log events** for that user within the org.
- **Repositories** — filter the org's repos by name/description, then drill into a repo for metadata, **language breakdown**, **top contributors**, **recent commits**, and its **rendered README** (Markdown).
- **Actions** — org Actions **usage metrics** (workflow runs in the last 30 days, minutes used / paid, with a by-OS breakdown) and **performance metrics for the past month** (success rate, average and median run duration, with a by-conclusion breakdown over a bounded sample of recent runs), both shown with `Digits`, plus a **per-workflow performance table** (workflow, source repository, whether it had job failures, average run time, workflow runs, and an estimated job count) with **click-to-sort column headers**, plus the org's **self-hosted runners**, **grouped by runner group**, with online/offline status, idle/busy state (an animated spinner for busy runners), labels, and — for busy runners — the **workflow / job** they're currently running and on which repo.
- **Copilot** — org Copilot **seat breakdown** (total/active/inactive, seat-management & public-suggestions policy) and **usage metrics** over the reporting window: active/engaged users plus per-language **suggestions, acceptances, and acceptance rate**.
- **API Explorer** — a **filterable, curated catalog** of org-scoped and **GitHub Enterprise Cloud** REST endpoints (organization, Actions, security, Copilot, enterprise, account), shown as a **collapsible tree** grouped by path prefix (`/orgs/{org}`, `/enterprises/{enterprise}`, …) with a colored method **pill** beside each entry. Pick an endpoint and its path is pre-filled with the selected org; fill any remaining `{placeholders}`, add a query string and (for writes) a JSON body, then **send**. List responses render as an **auto-columned, theme-styled table** (zebra rows; identifying fields like id/name/login/state are deduced from the items; nested objects are skipped) with a **toggle** to the **raw JSON** view and, for multi-page results, a **pager** (default page size **10**, using the endpoint's `page`/`per_page` + Link header); non-list responses show pretty-printed JSON. Every response shows status, latency, and rate-limit budget, and 4xx/5xx bodies are shown verbatim so you can inspect errors. All HTTP verbs are supported, but **mutating requests** (POST/PATCH/PUT/DELETE) require an explicit **confirmation** before they're sent.

## Install

```bash
gh extension install dubsorg/gh-recon
```

Or, for local development from a clone:

```bash
gh extension install .
```

This is a **script extension**: it runs the bundled Textual app, so each machine
needs **Python 3.9+** (with the `venv` module). On first run, `gh recon` creates a
private virtualenv next to the extension and installs its dependencies
automatically — no manual setup. Override the interpreter with `GH_RECON_PYTHON`.

> Script extensions don't need a build manifest — `gh` simply runs the executable
> `gh-recon` at the repo root, which bootstraps and launches the app.

## Auth

A token is resolved in this order: `--token`, `GH_TOKEN`, `GITHUB_TOKEN`, then `gh auth token`.

- Member search and user info need a normal token (`read:org` for full member visibility).
- **Audit log** requires an **organization owner** token with the `read:audit_log` scope
  (fine-grained: *Organization → Administration* read) and is a **GitHub Enterprise Cloud**
  feature. Without it, the user-info screen shows a clear "audit log unavailable" notice and
  the rest of the app still works.
- **Actions** runners require an **organization admin** token with `admin:org` (fine-grained:
  *Organization → Self-hosted runners* read); usage **minutes** additionally need org billing
  access. Without them, the screen shows a clear "unavailable" notice (and, for minutes, `—`)
  and the rest of the app still works. The 30-day run count and the **performance metrics**
  only need read access to the scanned repos' workflow runs (a normal `read:org` token); repos
  the token can't read are skipped, so the figures are a best-effort, bounded sample.
- **Copilot** requires the org to have Copilot Business/Enterprise and a token with
  `manage_billing:copilot`, `read:org`, or `admin:org`. Without it (or if the org has no
  Copilot), the Copilot screen shows a clear "unavailable" notice and the rest of the app
  still works.
- **API Explorer** calls whichever endpoint you pick with your resolved token, so each
  request needs that endpoint's own scope (noted next to entries that require one — e.g.
  `admin:org`, `read:audit_log`, `manage_billing:copilot`). Enterprise endpoints additionally
  need an enterprise-admin token. Requests that the token can't satisfy simply return the
  4xx response, which is displayed as-is.

## Run

```bash
gh recon ORG               # e.g. gh recon my-company
# or
GH_RECON_ORG=my-company gh recon
```

If no org is supplied, the app prompts for one on startup.

For local development without installing the extension, `./run.sh ORG` invokes the
same entrypoint (`./gh-recon`) directly.

### Mock mode

```bash
gh recon --mock            # or: gh recon ORG --mock
```

`--mock` runs the app against synthetic data generated at start time — no token
and no network calls. The dataset is seeded from the org name, so a given org
yields stable, internally-consistent members, repos, users, and runners. Useful
for demos, screenshots, and UI work offline.

Each mock call adds a short randomized delay to simulate network round-trips, so
the loading indicators (a `LoadingIndicator` spinner over each list/table while
its data is fetched) behave just like they do against the real API.

## Keys

The landing screen shows live **member** and **repository** counts for the org
(rendered with Textual's `Digits` widget) above the menu.

**Home menu**
| Key | Action |
| --- | --- |
| `Enter` | Open the highlighted area |
| `u` | Users |
| `R` | Repositories |
| `a` | Actions |
| `c` | Copilot |
| `e` | API Explorer |
| `q` | Quit |

**Member list**
| Key | Action |
| --- | --- |
| `/` | Focus the filter box |
| `Enter` | View selected user |
| `n` / `p` | Next / previous page |
| `r` | Refresh members |
| `Esc` | Back to home menu |

**Repository list** / **Repo detail**
| Key | Action |
| --- | --- |
| `/` | Focus the filter box (list) |
| `Enter` | View selected repo (list) |
| `n` / `p` | Next / previous page (list) |
| `o` | Open repo on github.com (detail) |
| `r` | Refresh |
| `Esc` | Back |

**User detail**
| Key | Action |
| --- | --- |
| `Enter` | View the selected repo (in the recent-commits list) |
| `n` / `p` | Next / previous page of audit-log events |
| `Esc` | Back to list |
| `r` | Refresh |
| `o` | Open user on github.com |

**Actions**
| Key | Action |
| --- | --- |
| `r` | Refresh |
| `Esc` | Back to home menu |

**Copilot**
| Key | Action |
| --- | --- |
| `r` | Refresh |
| `Esc` | Back to home menu |

**API Explorer**
| Key | Action |
| --- | --- |
| `/` | Focus the endpoint filter |
| `Enter` | Expand/collapse a group, or select an endpoint (focus the path field) |
| `←` / `→` | Collapse / expand the highlighted group |
| `s` | Send the request (mutations prompt to confirm) |
| `v` | Toggle table / raw-JSON response view (list responses) |
| `n` / `p` | Next / previous page (paged list responses) |
| `Esc` | Back to home menu |

## Layout

```
gh-recon          # executable extension entrypoint (gh runs this as `gh recon`)
requirements.txt  # Python deps installed into the auto-created venv
gh_recon/
  models.py       # dataclasses shared by both layers
  api/            # requests-based GitHub client, split by domain
    base.py       #   transport (_get/_request/_graphql), GitHubError, token resolution
    members.py    #   org members + roles
    repos.py      #   repositories, contributors, commits, languages
    actions.py    #   Actions usage + performance metrics + self-hosted runners + current-job correlation
    users.py      #   user profile, keys, teams, audit log, commit activity
    copilot.py    #   Copilot seat billing + usage metrics
    explorer.py   #   curated org/enterprise endpoint catalog + raw api_call
    mock.py       #   offline MockClient: synthetic data for --mock
  ui/             # Textual screens, one module per domain
    app.py        #   app shell + org prompt
    home.py       #   landing menu (Users / Repositories / Actions / Copilot / API Explorer)
    members.py    #   member-search screen
    users.py      #   user-detail screen
    repos.py      #   repository list + detail screens
    actions.py    #   Actions usage + performance + runners screen
    copilot.py    #   Copilot metrics screen
    explorer.py   #   API explorer screen (catalog + request builder) + confirm modal
    common.py     #   shared formatting helpers + Paginator
  __main__.py     # CLI entry point
```

## Notes

Lists are paged — members, repositories, and audit-log events are fetched **20 at a time**
rather than all at once, with `n`/`p` to move between pages. Member and repository listing
uses the REST `page`/`per_page` parameters; the audit log uses its Link-header cursors.

GitHub's user-search API has no `org:` qualifier, so org-scoped search is implemented by
listing org members and filtering by login client-side, then slicing the requested page —
the realistic flow for resolving known handles within an org. A substring search therefore
still lists members to filter; plain browsing pages directly without pulling everything.

The app ships with a neon **`recon`** theme but you can switch themes from Textual's
command palette (`Ctrl+P` → *Change theme*). Your choice is saved to
`$XDG_CONFIG_HOME/gh-recon/config.json` (default `~/.config/gh-recon/config.json`) and
reloaded on the next launch; it falls back to `recon` if the saved theme is unavailable.
