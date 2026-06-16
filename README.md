# gh-recon

A [`gh`](https://cli.github.com/) CLI extension: a terminal UI (TUI) for GitHub
organization recon, built with [Textual](https://textual.textualize.io/).

Scoped to a single organization, it provides two commands:

- **Search users** — filter the org's members by login.
- **Get user info** — full profile, org-membership role, **team memberships**, **most-used languages**, **repos recently committed to**, and **recent audit-log events** for that user within the org.

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

## Run

```bash
gh recon ORG               # e.g. gh recon my-company
# or
GH_RECON_ORG=my-company gh recon
```

If no org is supplied, the app prompts for one on startup.

For local development without installing the extension, `./run.sh ORG` invokes the
same entrypoint (`./gh-recon`) directly.

## Keys

**Member list**
| Key | Action |
| --- | --- |
| `/` | Focus the filter box |
| `Enter` | View selected user |
| `r` | Refresh members |
| `q` | Quit |

**User detail**
| Key | Action |
| --- | --- |
| `Esc` | Back to list |
| `r` | Refresh |
| `o` | Open user on github.com |

## Layout

```
gh-recon          # executable extension entrypoint (gh runs this as `gh recon`)
requirements.txt  # Python deps installed into the auto-created venv
gh_recon/
  api.py          # requests-based GitHub client (members, user, audit log)
  app.py          # Textual app: MainScreen (search) + UserDetailScreen
  __main__.py     # CLI entry point
```

## Notes

GitHub's user-search API has no `org:` qualifier, so org-scoped search is implemented by
listing org members (paginated, up to 500) and filtering by login client-side — the realistic
flow for resolving known handles within an org.
