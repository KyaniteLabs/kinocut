"""Bounded authenticated event protocol for the Windows collection diagnostic."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_COLLECTOR_PAIRS = 8192
MAX_ACTIVE_COLLECTORS = 128
MAX_COLLECTOR_BYTES = 64
MAX_NODEID_BYTES = 512
TOKEN = re.compile(r"[0-9a-f]{64}")
SHA = re.compile(r"[0-9a-f]{40,64}")
OUTCOMES = frozenset({"passed", "failed", "skipped", "error"})
FAILURES = frozenset(
    "invalid_event invalid_outcome collector_duplicate collector_unmatched "  # noqa: SIM905 - closed enum.
    "collector_capacity_exceeded collector_identity_invalid".split()
)
EVENT_FIELDS = {
    "DIAG_START": frozenset({"utc", "elapsed", "pid", "python", "platform", "runner_os", "image_os", "github_sha"}),
    "DIAG_HEARTBEAT": frozenset({"elapsed"}),
    "COLLECT_START": frozenset({"elapsed", "collector", "nodeid"}),
    "COLLECT_DONE": frozenset({"elapsed", "collector", "nodeid", "outcome"}),
    "DIAG_RESULT": frozenset({"elapsed", "rc", "collected"}),
}
_ELAPSED = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,9})?")
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


class DiagnosticError(RuntimeError):
    """A diagnostic invariant failed with a bounded public classification."""


def prepared_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.prepared")


def atomic_bytes(path: Path, contents: bytes, maximum: int) -> None:
    prepared = prepared_path(path)
    if len(contents) > maximum or path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError("bounded_atomic_write_invalid")
    if prepared.exists() or prepared.is_symlink():
        raise OSError("bounded_atomic_write_stale")
    path.parent.mkdir(parents=True, exist_ok=True)
    with prepared.open("xb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
    prepared.replace(path)


def atomic_json(path: Path, payload: dict[str, Any], maximum: int) -> None:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    atomic_bytes(path, encoded, maximum)


def valid_text(value: object, maximum: int, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, str) or (not value and not allow_empty):
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return len(encoded) <= maximum and all(ord(character) >= 32 and ord(character) != 127 for character in value)


def _valid_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_elapsed(value: object) -> bool:
    return isinstance(value, str) and _ELAPSED.fullmatch(value) is not None


def _collector_key(fields: dict[str, object]) -> tuple[str, str] | None:
    collector = fields.get("collector")
    nodeid = fields.get("nodeid")
    if not valid_text(collector, MAX_COLLECTOR_BYTES) or not valid_text(nodeid, MAX_NODEID_BYTES, allow_empty=True):
        return None
    if nodeid.startswith(("/", "\\")) or (len(nodeid) > 1 and nodeid[1] == ":"):
        return None
    return collector, nodeid


def _valid_event_fields(event: str, fields: dict[str, object]) -> bool:
    if not isinstance(event, str) or event not in EVENT_FIELDS or set(fields) != EVENT_FIELDS[event]:
        return False
    if not _valid_elapsed(fields["elapsed"]):
        return False
    if event == "DIAG_START":
        return (
            isinstance(fields["utc"], str)
            and _UTC.fullmatch(fields["utc"]) is not None
            and _valid_int(fields["pid"], minimum=1)
            and valid_text(fields["python"], 64)
            and valid_text(fields["platform"], 512)
            and valid_text(fields["runner_os"], 64, allow_empty=True)
            and valid_text(fields["image_os"], 64, allow_empty=True)
            and isinstance(fields["github_sha"], str)
            and SHA.fullmatch(fields["github_sha"]) is not None
        )
    if event == "DIAG_RESULT":
        return _valid_int(fields["rc"]) and _valid_int(fields["collected"])
    return True


def _empty_state(token: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "authenticator": token,
        "sequence": 0,
        "started": False,
        "terminal": False,
        "failure_class": None,
        "collector_starts": 0,
        "collector_completions": 0,
        "active_collectors": [],
        "completed_digest": hashlib.sha256(b"").hexdigest(),
        "last_completed": None,
        "heartbeat_count": 0,
        "result": None,
    }


class EventRecorder:
    """Serialize the old wrapper's callbacks into one authenticated snapshot."""

    def __init__(self, path: Path, token: str) -> None:
        if not TOKEN.fullmatch(token):
            raise DiagnosticError("event_authenticator_invalid")
        self.path = path
        self.token = token
        self.lock = threading.Lock()
        self.state = _empty_state(token)
        self.active: dict[tuple[str, str], dict[str, Any]] = {}
        self.next_collector_id = 1
        self._persist()

    def _persist(self) -> None:
        self.state["active_collectors"] = sorted(self.active.values(), key=lambda item: item["id"])
        try:
            atomic_json(self.path, self.state, MAX_EVENT_BYTES)
        except OSError as error:
            self.state["terminal"] = True
            raise DiagnosticError("event_state_write_failed") from error

    def _reject(self, classification: str) -> None:
        self.state["terminal"] = True
        self.state["failure_class"] = classification
        self.state["sequence"] += 1
        self._persist()
        raise DiagnosticError(classification)

    def _start_collector(self, fields: dict[str, object]) -> None:
        key = _collector_key(fields)
        if key is None:
            self._reject("collector_identity_invalid")
        if key in self.active:
            self._reject("collector_duplicate")
        if self.state["collector_starts"] >= MAX_COLLECTOR_PAIRS or len(self.active) >= MAX_ACTIVE_COLLECTORS:
            self._reject("collector_capacity_exceeded")
        record = {"id": self.next_collector_id, "collector": key[0], "nodeid": key[1]}
        self.next_collector_id += 1
        self.active[key] = record
        self.state["collector_starts"] += 1

    def _finish_collector(self, fields: dict[str, object]) -> None:
        key = _collector_key(fields)
        if key is None:
            self._reject("collector_identity_invalid")
        outcome = fields["outcome"]
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            self._reject("invalid_outcome")
        record = self.active.pop(key, None)
        if record is None:
            self._reject("collector_unmatched")
        completed = {**record, "outcome": outcome}
        prior = bytes.fromhex(self.state["completed_digest"])
        encoded = json.dumps(completed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.state["completed_digest"] = hashlib.sha256(prior + encoded).hexdigest()
        self.state["collector_completions"] += 1
        self.state["last_completed"] = completed

    def _finish_run(self, fields: dict[str, object]) -> None:
        if self.active or self.state["collector_starts"] != self.state["collector_completions"]:
            self._reject("invalid_event")
        self.state["result"] = {"return_code": fields["rc"], "collected": fields["collected"]}
        self.state["terminal"] = True

    def write(self, event: str, **fields: object) -> None:
        with self.lock:
            if self.state["terminal"]:
                raise DiagnosticError("event_state_terminal")
            if not _valid_event_fields(event, fields):
                self._reject("invalid_event")
            if event == "DIAG_START" and not self.state["started"]:
                self.state["started"] = True
            elif event == "DIAG_HEARTBEAT" and self.state["started"]:
                self.state["heartbeat_count"] += 1
            elif event == "COLLECT_START" and self.state["started"]:
                self._start_collector(fields)
            elif event == "COLLECT_DONE" and self.state["started"]:
                self._finish_collector(fields)
            elif event == "DIAG_RESULT" and self.state["started"]:
                self._finish_run(fields)
            else:
                self._reject("invalid_event")
            self.state["sequence"] += 1
            self._persist()


def read_json(path: Path, maximum: int) -> Any:
    prepared = prepared_path(path)
    try:
        if (
            prepared.exists()
            or prepared.is_symlink()
            or path.is_symlink()
            or not path.is_file()
            or not 0 < path.stat().st_size <= maximum
        ):
            raise OSError("bounded_json_invalid")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DiagnosticError("event_state_invalid") from error


def _valid_active(active: object) -> bool:
    if not isinstance(active, list) or len(active) > MAX_ACTIVE_COLLECTORS:
        return False
    identities: set[tuple[str, str]] = set()
    identifiers: set[int] = set()
    for item in active:
        if not isinstance(item, dict) or set(item) != {"id", "collector", "nodeid"}:
            return False
        key = _collector_key(item)
        identifier = item.get("id")
        if key is None or not _valid_int(identifier, minimum=1):
            return False
        identities.add(key)
        identifiers.add(identifier)
    return len(identities) == len(active) == len(identifiers)


def _terminal_shape_valid(state: dict[str, Any]) -> bool:
    terminal, failure, result = state["terminal"], state["failure_class"], state["result"]
    last = state["last_completed"]
    if state["collector_completions"] == 0:
        if last is not None:
            return False
    elif (
        not isinstance(last, dict)
        or set(last) != {"id", "collector", "nodeid", "outcome"}
        or _collector_key(last) is None
        or not _valid_int(last["id"], minimum=1)
        or last["id"] > state["collector_starts"]
        or not isinstance(last["outcome"], str)
        or last["outcome"] not in OUTCOMES
    ):
        return False
    if failure is not None:
        return terminal and result is None
    if result is None:
        return not terminal
    return (
        terminal
        and state["sequence"]
        == 2 + state["heartbeat_count"] + state["collector_starts"] + state["collector_completions"]
        and not state["active_collectors"]
        and state["collector_starts"] == state["collector_completions"]
        and isinstance(result, dict)
        and set(result) == {"return_code", "collected"}
        and _valid_int(result["return_code"])
        and _valid_int(result["collected"])
    )


def _state_shape_valid(state: object, token: str) -> bool:
    keys = {
        "schema",
        "authenticator",
        "sequence",
        "started",
        "terminal",
        "failure_class",
        "collector_starts",
        "collector_completions",
        "active_collectors",
        "completed_digest",
        "last_completed",
        "heartbeat_count",
        "result",
    }
    if (
        not isinstance(state, dict)
        or set(state) != keys
        or not _valid_int(state.get("schema"), minimum=1)
        or state.get("schema") != 1
    ):
        return False
    integers = [
        state.get(name) for name in ("sequence", "collector_starts", "collector_completions", "heartbeat_count")
    ]
    if any(not _valid_int(value) for value in integers):
        return False
    if state.get("authenticator") != token or not isinstance(state.get("started"), bool):
        return False
    if not isinstance(state.get("terminal"), bool) or not _valid_active(state.get("active_collectors")):
        return False
    starts, completions = state["collector_starts"], state["collector_completions"]
    if starts > MAX_COLLECTOR_PAIRS or completions > starts or starts - completions != len(state["active_collectors"]):
        return False
    digest = state.get("completed_digest")
    failure = state.get("failure_class")
    return (
        isinstance(digest, str)
        and TOKEN.fullmatch(digest) is not None
        and (failure is None or (isinstance(failure, str) and failure in FAILURES))
        and _terminal_shape_valid(state)
    )


def read_private_state(path: Path, token: str) -> dict[str, Any]:
    state = read_json(path, MAX_EVENT_BYTES)
    if not _state_shape_valid(state, token):
        raise DiagnosticError("event_state_invalid")
    return state


def sanitize_state(state: dict[str, Any]) -> dict[str, Any]:
    public = json.loads(json.dumps(state))
    public.pop("authenticator", None)
    public["trace_status"] = "not_captured"
    return public


def read_sanitized_state(path: Path) -> dict[str, Any]:
    state = read_json(path, MAX_EVENT_BYTES)
    if not isinstance(state, dict) or state.get("trace_status") != "not_captured" or "authenticator" in state:
        raise DiagnosticError("event_state_invalid")
    private = dict(state)
    private.pop("trace_status")
    private["authenticator"] = "0" * 64
    if not _state_shape_valid(private, "0" * 64):
        raise DiagnosticError("event_state_invalid")
    return state
