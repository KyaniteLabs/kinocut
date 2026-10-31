"""Shape the doctor's report for whoever will read it.

The report names the machine's own paths, which is what an operator running
the doctor locally needs. A caller that hands the report onward asks for
the paths to be left out: a machine's directory layout is the operator's,
not the reader's.
"""

from typing import Any

#: The report fields that name something of this machine: a path, the
#: command a probe would run — which for Hyperframes is the operator's
#: own configuration, not ours to publish — or a URL that points at one.
MACHINE_FIELDS = ("path", "origin", "executable", "command", "base_url")


def _strip_machine_fields(value: Any) -> Any:
    """Remove machine data from a structure, at every depth."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in MACHINE_FIELDS and item:
                cleaned[f"{key}_present"] = True
                continue
            cleaned[key] = _strip_machine_fields(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_machine_fields(item) for item in value]
    return value


def without_machine_paths(report: dict[str, Any]) -> dict[str, Any]:
    """Say that a path exists, not where it is.

    The report travels to whoever asked for it, so the removal goes all the
    way down: a path nested inside a check's details is still a path.
    """
    return _strip_machine_fields(report)
