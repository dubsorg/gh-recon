"""GitHub Copilot: org seat billing and usage metrics."""

from __future__ import annotations

from ..models import CopilotBilling, CopilotLangStat, CopilotMetrics
from .base import API_ROOT, GitHubError


class CopilotMixin:
    """Org Copilot endpoints. Mixed into :class:`GitHubClient`.

    Both endpoints need the org to have Copilot Business/Enterprise and a token
    with ``manage_billing:copilot``, ``read:org``, or ``admin:org``. They return
    ``None`` (not an error) when Copilot is unavailable for the org/token so the
    UI can degrade gracefully.
    """

    def copilot_billing(self) -> CopilotBilling | None:
        """Seat breakdown for the org's Copilot subscription."""
        try:
            data = self._get(f"{API_ROOT}/orgs/{self.org}/copilot/billing").json()
        except GitHubError as exc:
            if exc.status in (403, 404, 422):
                return None  # no Copilot / insufficient scope
            raise
        seats = data.get("seat_breakdown") or {}
        return CopilotBilling(
            total_seats=seats.get("total", 0),
            active_this_cycle=seats.get("active_this_cycle", 0),
            inactive_this_cycle=seats.get("inactive_this_cycle", 0),
            added_this_cycle=seats.get("added_this_cycle", 0),
            seat_management_setting=data.get("seat_management_setting"),
            public_code_suggestions=data.get("public_code_suggestions"),
        )

    def copilot_metrics(self) -> CopilotMetrics | None:
        """Usage metrics over the reporting window (up to the last 28 days)."""
        try:
            days = self._get(f"{API_ROOT}/orgs/{self.org}/copilot/metrics").json()
        except GitHubError as exc:
            if exc.status in (403, 404, 422):
                return None
            raise
        if not days:
            return CopilotMetrics(
                start=None, end=None, days=0,
                active_users_latest=0, engaged_users_latest=0, active_users_peak=0,
            )
        latest = days[-1]
        # Aggregate per-language code-completion stats across all days/editors/models.
        agg: dict[str, CopilotLangStat] = {}
        for day in days:
            completions = day.get("copilot_ide_code_completions") or {}
            for editor in completions.get("editors", []):
                for model in editor.get("models", []):
                    for lang in model.get("languages", []):
                        name = lang.get("name", "?")
                        stat = agg.setdefault(
                            name, CopilotLangStat(name, 0, 0, 0, 0, 0)
                        )
                        stat.engaged_users = max(
                            stat.engaged_users, lang.get("total_engaged_users", 0)
                        )
                        stat.suggestions += lang.get("total_code_suggestions", 0)
                        stat.acceptances += lang.get("total_code_acceptances", 0)
                        stat.lines_suggested += lang.get("total_code_lines_suggested", 0)
                        stat.lines_accepted += lang.get("total_code_lines_accepted", 0)
        languages = sorted(agg.values(), key=lambda s: s.suggestions, reverse=True)
        return CopilotMetrics(
            start=days[0].get("date"),
            end=latest.get("date"),
            days=len(days),
            active_users_latest=latest.get("total_active_users", 0),
            engaged_users_latest=latest.get("total_engaged_users", 0),
            active_users_peak=max(d.get("total_active_users", 0) for d in days),
            languages=languages,
        )
