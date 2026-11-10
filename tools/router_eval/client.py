"""HTTP client and typed-answer parser for ``/v1/systemone``."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence

QUESTION_ID = "operation"
DEFAULT_TIMEOUT_SECONDS = 10.0


class AskError(RuntimeError):
    """The endpoint did not return a usable typed answer."""


def ask(
    endpoint: str,
    body: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict[str, object], float]:
    """POST one body and return ``(reply, wall_ms)``.

    Raises ``AskError`` on any transport, HTTP or JSON failure; the caller is
    responsible for the protocol's degraded fallback.
    """

    url = endpoint.rstrip("/")
    if not url.endswith("/v1/systemone"):
        url = f"{url}/v1/systemone"
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - endpoint is an operator-supplied local URL
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    token = os.environ.get("KINOCUT_ROUTER_EVAL_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise AskError(f"endpoint request failed: {error}") from error
    wall_ms = (time.perf_counter() - started) * 1000.0
    try:
        reply = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AskError(f"endpoint returned non-JSON: {error}") from error
    if not isinstance(reply, dict):
        raise AskError("endpoint returned a non-object JSON body")
    return reply, wall_ms


def _probabilities(node: dict[str, object]) -> dict[str, float]:
    raw = node.get("probabilities")
    if not isinstance(raw, dict):
        return {}
    probabilities: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        probabilities[str(name)] = float(value)
    return probabilities


def parse_choice(
    reply: dict[str, object],
    candidates: Sequence[str],
) -> tuple[str, dict[str, float]]:
    """Return the picked candidate (or ``unsure``) and its probabilities.

    Accepts a typed ``choice`` and falls back to the probabilities' argmax.
    Rejects a pick outside the offered criteria, except for the protocol's
    explicit ``unsure`` option.
    """

    node = reply.get(QUESTION_ID)
    if not isinstance(node, dict):
        raise AskError(f"reply has no typed {QUESTION_ID!r} answer")
    probabilities = _probabilities(node)
    choice = node.get("choice")
    allowed = set(candidates) | {"unsure"}
    if not isinstance(choice, str) or choice not in allowed:
        if not probabilities:
            raise AskError("reply has neither a valid choice nor probabilities")
        best = max(probabilities.items(), key=lambda item: (item[1], item[0]))
        choice = best[0]
    if choice not in allowed:
        raise AskError(f"reply picked {choice!r}, which was not offered")
    return choice, probabilities
