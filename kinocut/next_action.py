"""Recommended next action: typed, advisory NextAction records (#55, §4.10).

A next-action is advisory *only* — an action code, a short summary, and at most
one bounded, inert ``kino`` command template (never executed). This module
derives deterministic NextAction records from capability availability so a
failed/missing-capability state always carries a machine-readable recommendation
alongside its human text.
"""

from __future__ import annotations

from typing import Any

from kinocut.capability_report import capability_report
from kinocut.contracts.capability import AvailabilityState, CapabilityReport, NextAction


def next_action(action_code: str, summary: str, *, command_template: str | None = None) -> NextAction:
    """Build a validated, advisory NextAction (design §4.10)."""

    return NextAction(
        action_code=action_code,
        summary=summary,
        command_template=command_template,
    )


def next_action_for_unavailable(report: CapabilityReport) -> NextAction:
    """The recommended action for an unavailable capability: install its dep."""

    dep = report.required_deps[0] if report.required_deps else "dependency"
    return NextAction(
        action_code="install_dependency",
        summary=f"install {dep} to enable {report.capability_id}",
    )


def recommended_next_actions(diagnostics: dict[str, Any] | None = None) -> list[NextAction]:
    """One NextAction per unavailable capability on the current host (#55)."""

    return [
        next_action_for_unavailable(report)
        for report in capability_report(diagnostics)
        if report.availability is AvailabilityState.UNAVAILABLE
    ]


__all__ = ["next_action", "next_action_for_unavailable", "recommended_next_actions"]
