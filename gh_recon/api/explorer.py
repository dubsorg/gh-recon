"""API explorer: a curated catalog of org/enterprise endpoints + a raw caller.

This is the backend for the explorer screen. The catalog (:func:`build_catalog`)
is a hand-picked set of org-scoped and GitHub Enterprise Cloud REST endpoints
relevant to recon; :meth:`ExplorerMixin.api_call` issues an arbitrary request and
returns an :class:`ApiResponse` with the body kept raw (errors included) so the
UI can show exactly what GitHub returned.
"""

from __future__ import annotations

import json

import requests

from ..models import ApiEndpoint, ApiResponse
from .base import GitHubError

# Response headers worth surfacing in the explorer (rate-limit budget, etc.).
_INTERESTING_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Used",
    "X-RateLimit-Reset",
    "X-GitHub-Api-Version-Selected",
)

# Cap the rendered body so a huge list response can't lock up the UI.
_MAX_BODY = 200_000


def build_catalog(org: str) -> list[ApiEndpoint]:
    """Curated org- and enterprise-scoped REST endpoints, in display order.

    ``{org}`` is pre-filled from the client scope by the UI; ``{enterprise}`` and
    other placeholders (``{username}``, ``{repo}``) are filled in by the user.
    """
    return [
        # -- Organization (read) -----------------------------------------
        ApiEndpoint("GET", "/orgs/{org}", "Get the organization", "Organization"),
        ApiEndpoint("GET", "/orgs/{org}/members", "List org members", "Organization"),
        ApiEndpoint("GET", "/orgs/{org}/teams", "List teams", "Organization"),
        ApiEndpoint("GET", "/orgs/{org}/repos", "List org repositories", "Organization"),
        ApiEndpoint(
            "GET", "/orgs/{org}/outside_collaborators",
            "List outside collaborators", "Organization",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/installations",
            "List GitHub App installations", "Organization",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/audit-log",
            "Org audit log (Enterprise Cloud)", "Organization",
            scope="read:audit_log (org owner)",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/personal-access-tokens",
            "List fine-grained PATs with org access", "Organization",
            scope="admin:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/properties/values",
            "List custom property values for repos", "Organization",
        ),
        # -- Actions ------------------------------------------------------
        ApiEndpoint(
            "GET", "/orgs/{org}/actions/runners",
            "List self-hosted runners", "Actions", scope="admin:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/actions/runner-groups",
            "List runner groups", "Actions", scope="admin:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/actions/secrets",
            "List org Actions secrets (names only)", "Actions", scope="admin:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/actions/permissions",
            "Get Actions permissions policy", "Actions", scope="admin:org",
        ),
        # -- Security -----------------------------------------------------
        ApiEndpoint(
            "GET", "/orgs/{org}/secret-scanning/alerts",
            "List secret-scanning alerts", "Security",
            scope="repo / security_events",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/dependabot/alerts",
            "List Dependabot alerts", "Security", scope="security_events",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/code-scanning/alerts",
            "List code-scanning alerts", "Security", scope="security_events",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/code-security/configurations",
            "List code-security configurations", "Security", scope="admin:org",
        ),
        # -- Copilot ------------------------------------------------------
        ApiEndpoint(
            "GET", "/orgs/{org}/copilot/billing",
            "Copilot seat breakdown", "Copilot",
            scope="manage_billing:copilot / read:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/copilot/billing/seats",
            "List Copilot seat assignments", "Copilot",
            scope="manage_billing:copilot / read:org",
        ),
        ApiEndpoint(
            "GET", "/orgs/{org}/copilot/metrics",
            "Copilot usage metrics", "Copilot", scope="manage_billing:copilot",
        ),
        # -- Enterprise Cloud (read) -------------------------------------
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/audit-log",
            "Enterprise audit log", "Enterprise",
            scope="read:audit_log (enterprise admin)",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/consumed-licenses",
            "Consumed license breakdown", "Enterprise", scope="enterprise admin",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/copilot/billing/seats",
            "Enterprise Copilot seat assignments", "Enterprise",
            scope="manage_billing:copilot (enterprise)",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/copilot/metrics",
            "Enterprise Copilot usage metrics", "Enterprise",
            scope="manage_billing:copilot (enterprise)",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/secret-scanning/alerts",
            "Enterprise secret-scanning alerts", "Enterprise",
            scope="enterprise admin",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/code-security/configurations",
            "Enterprise code-security configurations", "Enterprise",
            scope="enterprise admin",
        ),
        ApiEndpoint(
            "GET", "/enterprises/{enterprise}/properties/schema",
            "Custom property schema", "Enterprise", scope="enterprise admin",
        ),
        # -- Account / meta ----------------------------------------------
        ApiEndpoint("GET", "/user", "The authenticated user", "Account"),
        ApiEndpoint("GET", "/rate_limit", "Current rate-limit status", "Account"),
        ApiEndpoint("GET", "/meta", "GitHub meta information", "Account"),
        # -- Mutations (require confirmation) ----------------------------
        ApiEndpoint(
            "PATCH", "/orgs/{org}", "Update org settings", "Mutations",
            scope="admin:org",
        ),
        ApiEndpoint(
            "POST", "/orgs/{org}/repos", "Create an org repository", "Mutations",
            scope="repo / admin:org",
        ),
        ApiEndpoint(
            "PUT", "/orgs/{org}/memberships/{username}",
            "Set org membership for a user", "Mutations", scope="admin:org",
        ),
        ApiEndpoint(
            "DELETE", "/orgs/{org}/members/{username}",
            "Remove a member from the org", "Mutations", scope="admin:org",
        ),
        ApiEndpoint(
            "DELETE", "/orgs/{org}/outside_collaborators/{username}",
            "Remove an outside collaborator", "Mutations", scope="admin:org",
        ),
    ]


def _build_response(method: str, resp: requests.Response, elapsed_ms: int) -> ApiResponse:
    """Turn a raw response into an :class:`ApiResponse` (pretty JSON when JSON)."""
    content_type = resp.headers.get("Content-Type", "")
    is_json = content_type.startswith("application/json")
    data = None
    if is_json:
        try:
            data = resp.json()
            body = json.dumps(data, indent=2, ensure_ascii=False)
        except ValueError:
            is_json = False
            body = resp.text
    else:
        body = resp.text
    if len(body) > _MAX_BODY:
        body = body[:_MAX_BODY] + "\n… [truncated]"
    rate_limit = {
        h: resp.headers[h] for h in _INTERESTING_HEADERS if h in resp.headers
    }
    rels = _link_rels(resp.headers.get("Link", ""))
    return ApiResponse(
        method=method.upper(),
        url=resp.url,
        status=resp.status_code,
        reason=resp.reason or "",
        elapsed_ms=elapsed_ms,
        content_type=content_type,
        body=body,
        is_json=is_json,
        data=data,
        rate_limit=rate_limit,
        has_next="next" in rels,
        has_prev="prev" in rels,
    )


def _link_rels(link_header: str) -> set[str]:
    """Return the set of ``rel`` values present in an RFC 5988 Link header."""
    rels: set[str] = set()
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        rel = section[1].strip()
        if rel.startswith('rel="') and rel.endswith('"'):
            rels.add(rel[5:-1])
    return rels


class ExplorerMixin:
    """Curated endpoint catalog + a raw request caller for the API explorer."""

    def api_endpoints(self) -> list[ApiEndpoint]:
        return build_catalog(self.org)

    def api_call(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        body: str | None = None,
    ) -> ApiResponse:
        """Issue one explorer request. ``body`` is raw JSON text (mutations).

        Raises :class:`GitHubError` only on a bad JSON body or transport failure;
        HTTP error statuses come back as an :class:`ApiResponse` to display.
        """
        json_body = None
        if body and body.strip():
            try:
                json_body = json.loads(body)
            except ValueError as exc:
                raise GitHubError(f"request body is not valid JSON: {exc}") from exc
        resp = self._request(method, path, params=params or None, json_body=json_body)
        elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        return _build_response(method, resp, elapsed_ms)
