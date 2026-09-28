"""Source contract: every child process names its stdin explicitly.

Under an MCP stdio server, the server's own stdin is the JSON-RPC protocol channel. Any child
that inherits it can consume or block the channel (adversarial + integrator evidence: #547 — a
trim stalled until the next tool call arrived). PR #559 fixed the central runners in
``ffmpeg_helpers``; this contract pins the WHOLE tree: every ``subprocess`` call site in
``kinocut/`` and ``kinocut_sound/`` must pass an explicit ``stdin=`` (normally ``DEVNULL``).
If a future call genuinely needs piped stdin (``stdin=PIPE``), it satisfies the contract by
naming it — the failure mode is silent *inheritance*, not piping.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("kinocut", "kinocut_sound")
_CALL = re.compile(r"subprocess\.(?:run|Popen|check_output|check_run)\(")


def test_every_subprocess_call_names_stdin_explicitly() -> None:
    offenders: list[str] = []
    checked = 0
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in _CALL.finditer(text):
                checked += 1
                window = text[match.end() : match.end() + 500]
                call_body = window.split("\n\n")[0]
                if "stdin" not in call_body:
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert checked > 50, f"expected the full call surface, checked only {checked}"
    assert not offenders, (
        "subprocess call sites without an explicit stdin= (children would inherit the MCP "
        f"stdio protocol channel — #547 class): {offenders}"
    )
