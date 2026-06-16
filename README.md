# gh-recon

A terminal UI (TUI) for GitHub organization recon, built with [Textual](https://textual.textualize.io/).

Scoped to a single organization, it provides two commands:

- **Search users** — filter the org's members by login.
- **Get user info** — full profile, org-membership role, and **recent audit-log events** for that user within the org.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Auth

A token is resolved in this order: `--token`, `GH_TOKEN`, `GITHUB_TOKEN`, then `gh auth token`.

- Member search and user info need a normal token (`read:org` for full member visibility).
- **Audit log** requires an **organization owner** token with the `read:audit_log` scope
  (fine-grained: *Organization → Administration* read) and is a **GitHub Enterprise Cloud**
  feature. Without it, the user-info screen shows a clear "audit log unavailable" notice and
  the rest of the app still works.

## Run

```bash
./run.sh ORG            # e.g. ./run.sh my-company
# or
GH_RECON_ORG=my-company ./run.sh
# or
./.venv/bin/python -m gh_recon ORG
```

If no org is supplied, the app prompts for one on startup.

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
gh_recon/
  api.py        # requests-based GitHub client (members, user, audit log)
  app.py        # Textual app: MainScreen (search) + UserDetailScreen
  __main__.py   # CLI entry point
```

## Notes

GitHub's user-search API has no `org:` qualifier, so org-scoped search is implemented by
listing org members (paginated, up to 500) and filtering by login client-side — the realistic
flow for resolving known handles within an org.
