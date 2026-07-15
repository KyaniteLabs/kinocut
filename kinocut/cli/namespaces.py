"""Namespaced CLI alias resolver (#52, design §4.10).

A namespace alias maps a ``(group, action)`` path to an existing flat command,
calling the *same* handler — never a divergent behavior. This module is the
resolution layer the namespaced parser routing builds on: it keeps flat commands
as the source of truth and lets an agent use a grouped path
(e.g. ``("aivideo", "verdict")`` -> ``video_verdict``) without a second
implementation. The full ``kino <group> <action>`` parser wiring is a
controller-serialized follow-on over this map; the flat 121-command surface is
unchanged.
"""

from __future__ import annotations

# (group, action) -> flat command name. Every value MUST be an existing flat
# command handled by the same handler; namespace aliases never introduce
# behavior of their own.
NAMESPACED_ALIASES: dict[tuple[str, str], str] = {
    ("aivideo", "verdict"): "video-verdict",
    ("aivideo", "acceptance"): "video-acceptance-eval",
    ("aivideo", "salvage"): "video-salvage",
    ("aivideo", "body-swap"): "video-body-swap",
    ("aivideo", "ingest"): "video-ingest",
    ("aivideo", "preflight"): "video-preflight",
    ("aivideo", "inspect"): "video-inspect-temporal",
}


def resolve_namespaced(group: str, action: str) -> str | None:
    """Return the flat command name for a ``(group, action)`` path, or None."""

    return NAMESPACED_ALIASES.get((group, action))


def namespaced_groups() -> dict[str, tuple[str, ...]]:
    """Return each namespace group with its sorted action aliases."""

    groups: dict[str, list[str]] = {}
    for (group, action) in NAMESPACED_ALIASES:
        groups.setdefault(group, []).append(action)
    return {group: tuple(sorted(actions)) for group, actions in sorted(groups.items())}


__all__ = ["NAMESPACED_ALIASES", "namespaced_groups", "resolve_namespaced"]
