"""Shape the doctor's report for whoever will read it.

The report names the machine's own paths, which is what an operator running
the doctor locally needs. A caller that hands the report onward asks for
the paths to be left out: a machine's directory layout is the operator's,
not the reader's.
"""

from typing import Any

#: The report fields that name something of this machine: a path, or the
#: command a probe would run — which for Hyperframes is the operator's
#: own configuration, not ours to publish.
MACHINE_FIELDS = ("path", "origin", "executable", "command")


def without_machine_paths(report: dict[str, Any]) -> dict[str, Any]:
    """Say that a path exists, not where it is."""
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        for field in MACHINE_FIELDS:
            value = check.get(field)
            if not value:
                continue
            check.pop(field, None)
            check[f"{field}_present"] = True
    platform = report.get("platform")
    if isinstance(platform, dict) and platform.get("executable"):
        platform.pop("executable", None)
        platform["executable_present"] = True
    return report
