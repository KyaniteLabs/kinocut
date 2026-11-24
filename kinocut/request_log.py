"""Opt-in local log of (request -> chosen operation) pairs for routing data.

Kinocut receipts record what an operation did; nothing records what the
caller asked for, so a routing corpus built from real traffic has no data
source.  This module is that source.  See `docs/TOOLS.md` ("Request log").

Contract:

* **Opt-in.** Off unless ``KINOCUT_REQUEST_LOG`` is set.  ``1``/``true``/
  ``yes``/``on`` log to the default path; ``0``/``false``/``no``/``off`` and
  unset disable; any other value is treated as the log file path.
* **Redacted.** Nothing is written before :func:`redact_text` and the
  recursive value redactor run over the request.  The rule table
  (``_REDACTIONS``) is the privacy review surface; document changes to it in
  the PR description.
* **Local.** One JSONL file on the machine that ran the operation, under the
  Kinocut state directory (``KINOCUT_STATE_DIR`` -> ``XDG_STATE_HOME`` ->
  ``~/.local/state/kinocut``) unless a path was given.  No network upload, no
  telemetry endpoint.
* **Queryable.** ``python -m kinocut.request_log [--path P]`` re-emits the
  log as JSONL so a future eval can harvest it.

Each record has exactly the fields ``request_text``, ``chosen_operation``,
``timestamp`` (ISO-8601 UTC) and ``session_id`` (identifies the MCP server
process that handled the call; a stdio server serves one client connection
for its lifetime).

Recording is best effort, mirroring :mod:`kinocut.output_ledger`: a failure
to write the log never fails the tool call that produced it.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, cast

ENV_REQUEST_LOG = "KINOCUT_REQUEST_LOG"
_LOG_NAME = "request_log.jsonl"
_MAX_REQUEST_TEXT = 8192
_MAX_SCAN_CHARS = _MAX_REQUEST_TEXT * 2
_MAX_REDACT_ITEMS = 256
_MAX_REDACT_NODES = 512
_MAX_REDACT_DEPTH = 16
_PLACEHOLDER = "<redacted>"
_PATH_PLACEHOLDER = "<path>"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"", "0", "false", "no", "off"}

_PEM_BEGIN_RE = re.compile(r"-----BEGIN [A-Z0-9 ]{0,64}PRIVATE KEY-----")
_PEM_END_RE = re.compile(r"-----END [A-Z0-9 ]{0,64}PRIVATE KEY-----")

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(?:api[-_]?key|access[-_]?key|secret|client[-_]?secret|token|password|passwd|"
    r"authorization|auth|cookie|credential|private[-_]?key|bearer|jwt|session[-_]?id)(?:$|[_-])"
)
_EXACT_PATH_KEYS = frozenset(
    {
        "path",
        "paths",
        "file",
        "files",
        "dir",
        "dirs",
        "directory",
        "folder",
        "input",
        "inputs",
        "output",
        "outputs",
        "source",
        "sources",
        "target",
        "destination",
        "video",
        "videos",
        "audio",
        "image",
        "images",
        "clip",
        "clips",
        "subtitle",
        "subtitles",
        "srt",
        "ass",
        "font",
        "logo",
        "watermark",
        "overlay",
        "background",
        "foreground",
        "mask",
        "matte",
        "lut",
        "script",
        "project",
        "workspace",
        "workdir",
        "work_dir",
        "list_file",
        "variables_file",
        "plan",
        "plan_path_or_dir",
        "playlist_name",
        "filename",
        "file_name",
        "output_name",
    }
)
_PATH_KEY_SUFFIXES = (
    "_path",
    "_paths",
    "_file",
    "_files",
    "_filename",
    "_dir",
    "_dirs",
    "_folder",
    "_video",
    "_audio",
    "_image",
)

# Ordered redaction rules: (pattern, replacement).  Order matters — URLs are
# rewritten before path rules so `scheme://host/path` is not half-eaten, and
# credential assignments run before the generic dense-token rule so the key
# name survives as context.  PEM private key blocks are stripped in one linear
# pass before this table runs.  This table is the privacy review surface.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer credentials, with or without an assignment key.  Runs before the
    # assignment rule so the token after "Bearer" is consumed even when the
    # assignment value itself stops at whitespace.
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer " + _PLACEHOLDER),
    # Credential-shaped assignments: api_key=..., "token": ..., password: ...
    (
        re.compile(
            r"(?i)\b(api[-_]?key|access[-_]?key|secret|client[-_]?secret|token|password|passwd|"
            r"authorization|credential)\b([\"']?\s*[=:]\s*[\"']?)(\"[^\"]*\"|'[^']*'|[^\s,;}&\]]+)"
        ),
        r"\1\2" + _PLACEHOLDER,
    ),
    # Known token shapes: OpenAI-style, AWS access keys, GitHub, Slack.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), _PLACEHOLDER),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _PLACEHOLDER),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), _PLACEHOLDER),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), _PLACEHOLDER),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), _PLACEHOLDER),
    # Dense secret-shaped runs (base64-ish or long hashes).  Deliberately
    # over-broad: a false positive only loses one opaque token of text.
    (re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9+/=])"), _PLACEHOLDER),
    (re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])"), _PLACEHOLDER),
    # URL userinfo: scheme://user:password@host -> scheme://<redacted>@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/:@\"'<>]+(?::[^\s/@\"'<>]*)?@"),
        r"\1" + _PLACEHOLDER + "@",
    ),
    # URLs with a query string: drop the query (queries carry tokens and ids).
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s\"'<>?)]+)\?[^\s\"'<>]+"),
        r"\1?<redacted-query>",
    ),
    # Absolute POSIX paths and home-relative paths (~, /home/<name>, /Users/<name>).
    (re.compile(r"(?<![\w:~/])/(?:[^\s\"'<>|]+/)*[^\s\"'<>|]+"), "<path>"),
    (re.compile(r"(?<![\w])~(?:/(?:[^\s\"'<>|]+/)*[^\s\"'<>|]*)?"), "<path>"),
    # Windows drive paths.
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\(?:[^\s\"'<>|]+\\)*[^\s\"'<>|]+"), "<path>"),
    # Relative paths containing a separator and ending in a dotted filename,
    # then bare media/document filenames.  Word pairs like "and/or" or "24/7"
    # have no dotted final segment and stay untouched.
    (re.compile(r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]*\.[\w.-]*"), "<path>"),
    (
        re.compile(
            r"(?i)(?<![\w.-])[\w.-]+\.(?:mp4|mov|mkv|webm|avi|m4v|mpg|mpeg|ts|png|jpg|jpeg|gif|webp|bmp|tiff"
            r"|wav|mp3|m4a|aac|flac|ogg|aiff|json|jsonl|csv|tsv|txt|md|srt|vtt|ass|xml|yaml|yml|toml|pdf|zip|gz)\b"
        ),
        "<path>",
    ),
    # Identity-bearing "name" tokens: emails and @handles.  Free-text personal
    # names are NOT detected (no NER model by design); that limit is stated
    # in docs and is part of the privacy review surface.
    (re.compile(r"(?<![\w.@+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"(?<![\w@.])@[A-Za-z0-9_]{2,}\b"), "<handle>"),
)


def _redact_pem_blocks(text: str) -> str:
    """Strip PEM private key blocks in one linear forward pass."""
    if "PRIVATE KEY-----" not in text:
        return text
    parts: list[str] = []
    pos = 0
    while True:
        begin = _PEM_BEGIN_RE.search(text, pos)
        if begin is None:
            parts.append(text[pos:])
            return "".join(parts)
        parts.append(text[pos : begin.start()])
        parts.append(_PLACEHOLDER)
        end = _PEM_END_RE.search(text, begin.end())
        if end is None:
            return "".join(parts)
        pos = end.end()


def redact_text(text: str) -> str:
    """Apply every redaction rule to ``text``, in table order."""
    text = _redact_pem_blocks(text)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class _RedactBudget:
    chars: int = _MAX_SCAN_CHARS
    nodes: int = _MAX_REDACT_NODES

    def consume_node(self) -> bool:
        if self.nodes <= 0:
            return False
        self.nodes -= 1
        return True


def _is_path_key(key: str) -> bool:
    lowered = key.strip().lower()
    return lowered in _EXACT_PATH_KEYS or lowered.endswith(_PATH_KEY_SUFFIXES)


def _redact_path_value(value: object, budget: _RedactBudget, depth: int) -> object:
    if depth >= _MAX_REDACT_DEPTH or not budget.consume_node():
        return "<truncated>"
    if isinstance(value, str):
        return _PATH_PLACEHOLDER
    if isinstance(value, (list, tuple)):
        items: list[object] = []
        for index, item in enumerate(cast(list[object] | tuple[object, ...], value)):
            if index >= _MAX_REDACT_ITEMS or budget.nodes <= 0:
                items.append("<truncated>")
                break
            items.append(_redact_path_value(item, budget, depth + 1))
        return items
    return _redact_value(value, budget=budget, depth=depth + 1)


def _redact_bounded_str(text: str, budget: _RedactBudget) -> str:
    remaining = budget.chars
    if remaining <= 0:
        return "<truncated>"
    clipped = len(text) > remaining
    chunk = text[:remaining] if clipped else text
    budget.chars = max(0, remaining - len(chunk))
    redacted = redact_text(chunk)
    return redacted + ("...<truncated>" if clipped else "")


def _redact_value(value: object, *, budget: _RedactBudget | None = None, depth: int = 0) -> object:
    """Return a bounded redacted copy of ``value``; never mutates the input."""
    active_budget = budget if budget is not None else _RedactBudget()
    if depth >= _MAX_REDACT_DEPTH or active_budget.chars <= 0 or not active_budget.consume_node():
        return "<truncated>"
    if isinstance(value, str):
        return _redact_bounded_str(value, active_budget)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(cast(dict[object, object], value).items()):
            if index >= _MAX_REDACT_ITEMS or active_budget.chars <= 0 or active_budget.nodes <= 0:
                result["<truncated>"] = True
                break
            key_str = str(raw_key)
            safe_key = _redact_bounded_str(key_str, active_budget)
            if _SENSITIVE_KEY_RE.search(key_str):
                active_budget.consume_node()
                result[safe_key] = _PLACEHOLDER
            elif _is_path_key(key_str):
                result[safe_key] = _redact_path_value(item, active_budget, depth + 1)
            else:
                result[safe_key] = _redact_value(item, budget=active_budget, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        items: list[object] = []
        for index, item in enumerate(cast(list[object] | tuple[object, ...], value)):
            if index >= _MAX_REDACT_ITEMS or active_budget.chars <= 0 or active_budget.nodes <= 0:
                items.append("<truncated>")
                break
            items.append(_redact_value(item, budget=active_budget, depth=depth + 1))
        return items
    return value


def resolve_log_path() -> Path | None:
    """Return the enabled log path, or ``None`` when logging is off.

    Reads the environment at call time (like the output ledger) so tests and
    embedders can flip the flag per call.
    """
    raw = os.environ.get(ENV_REQUEST_LOG, "").strip()
    if raw.lower() in _FALSY:
        return None
    if raw.lower() in _TRUTHY:
        from .output_ledger import state_dir

        return Path(state_dir()) / _LOG_NAME
    return Path(raw).expanduser()


@cache
def _session_id() -> str:
    """Stable identifier for this MCP server process."""
    return uuid.uuid4().hex


def _truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    """Cap ``text`` at ``max_bytes`` UTF-8 bytes including the truncation notice."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    notice = f"...<{len(encoded) - max_bytes} bytes truncated>"
    while True:
        keep = max(0, max_bytes - len(notice.encode("utf-8")))
        prefix = encoded[:keep].decode("utf-8", errors="ignore")
        actual_omitted = len(encoded) - len(prefix.encode("utf-8"))
        updated = f"...<{actual_omitted} bytes truncated>"
        if updated == notice:
            return prefix + notice
        notice = updated


def _request_text(arguments: Mapping[str, Any]) -> str:
    """Serialize ``arguments`` to compact JSON, redacted and UTF-8 byte-capped."""
    rendered = json.dumps(_redact_value(dict(arguments)), ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) > _MAX_SCAN_CHARS:
        rendered = rendered[:_MAX_SCAN_CHARS]
    rendered = redact_text(rendered)
    return _truncate_utf8_bytes(rendered, _MAX_REQUEST_TEXT)


def _open_log(path: Path) -> int:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("Request log destination must be a regular file")
        if hasattr(os, "geteuid"):
            if st.st_uid != os.geteuid():
                raise PermissionError("Request log destination is not owned by the current user")
            if st.st_mode & 0o077:
                raise PermissionError("Request log destination must not be group- or world-accessible")
    except BaseException:
        os.close(fd)
        raise
    return fd


def log_invocation(operation: str, arguments: Mapping[str, Any]) -> None:
    """Append one redacted (request -> chosen operation) record, best effort.

    Never raises: a log that cannot be written must not fail the tool call.
    Does nothing when the log is disabled (the default).
    """
    with contextlib.suppress(Exception):
        path = resolve_log_path()
        if path is None:
            return
        record = {
            "request_text": _request_text(arguments),
            "chosen_operation": redact_text(operation),
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "session_id": _session_id(),
        }
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = _open_log(path)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


def iter_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Read the log as parsed records, skipping malformed lines.

    Malformed lines are reported on stderr so silent corruption cannot hide.
    """
    target = path if path is not None else resolve_log_path()
    if target is None or not Path(target).exists():
        return []
    records: list[dict[str, Any]] = []
    with Path(target).open("r", encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"{target}:{number}: skipping malformed line", file=sys.stderr)
    return records


def main(argv: list[str] | None = None) -> int:
    """Emit the request log as JSONL on stdout (``python -m kinocut.request_log``)."""
    parser = argparse.ArgumentParser(
        prog="python -m kinocut.request_log",
        description="Emit the opt-in Kinocut request log as JSONL for corpus harvesting.",
    )
    parser.add_argument(
        "--path", type=Path, default=None, help="Log file to read (default: KINOCUT_REQUEST_LOG resolution)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Emit at most N records")
    args = parser.parse_args(argv)
    records = iter_records(args.path)
    if args.limit is not None:
        records = records[-args.limit :] if args.limit >= 0 else records
    for record in records:
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
