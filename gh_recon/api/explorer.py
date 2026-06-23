"""API explorer: the full org/enterprise endpoint catalog + a raw caller.

This is the backend for the explorer screen. The catalog (:func:`build_catalog`)
is generated from GitHub's OpenAPI description — see ``scripts/gen_catalog.py``,
which writes :mod:`gh_recon.api._catalog_data` — filtered to org-scoped and
GitHub Enterprise Cloud REST endpoints (plus a few utility paths).
:meth:`ExplorerMixin.api_call` issues an arbitrary request and returns an
:class:`ApiResponse` with the body kept raw (errors included) so the UI can show
exactly what GitHub returned.
"""

from __future__ import annotations

import json

import requests

from ..models import ApiEndpoint, ApiResponse
from ._catalog_data import ENDPOINTS
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
    """The full org/enterprise REST catalog from GitHub's OpenAPI description.

    Built from :data:`gh_recon.api._catalog_data.ENDPOINTS`, generated offline by
    ``scripts/gen_catalog.py`` so the extension needs no extra dependency or
    network call to populate the explorer. ``{org}`` is pre-filled from the client
    scope by the UI; other placeholders (``{enterprise}``, ``{username}``, …) are
    filled in by the user. ``org`` is accepted for signature parity with the
    callers (real + mock clients) but isn't needed — paths stay templated.
    """
    return [
        ApiEndpoint(method, path, summary, category)
        for method, path, summary, category in ENDPOINTS
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
