"""Configuration and fail-closed preflight for offline providers and models."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .errors import MCPVideoError


class OfflineModelMissing(MCPVideoError):
    """Show the exact operator-local path without exposing it in tool errors."""

    def __init__(self, expected_file: Path, *, feature: str, env_hint: str):
        self.expected_file = expected_file
        super().__init__(
            f"{feature} requires local weights. {env_hint}",
            error_type="offline_error",
            code="offline_model_missing",
        )

    def __str__(self) -> str:
        return f"{super().__str__()} Expected file: {self.expected_file}"

    def to_dict(self) -> dict:
        return {"type": self.error_type, "code": self.code, "message": super().__str__()}


def is_offline_mode(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("KINOCUT_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}


def is_loopback_url(url: str) -> bool:
    if "\\" in url or any(char.isspace() or ord(char) < 32 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.username is None
            and parsed.password is None
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            and parsed.port != 0
            and re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]+)?", parsed.netloc, re.IGNORECASE)
            is not None
        )
    except ValueError:
        return False


def require_offline_allowed_url(url: str, *, feature: str, local_alternative: str) -> str:
    if is_offline_mode() and not is_loopback_url(url):
        raise MCPVideoError(
            f"{feature} cannot use a non-loopback endpoint in offline mode. {local_alternative}",
            error_type="offline_error",
            code="offline_network_blocked",
        )
    return url


def require_offline_local_artifact(path: Path, *, feature: str, env_hint: str) -> Path:
    if is_offline_mode() and not path.is_file():
        raise OfflineModelMissing(path, feature=feature, env_hint=env_hint)
    return path


_INFO_FLAGS = frozenset({"-version", "-h", "-help", "--help", "-filters", "-encoders", "-decoders", "-formats"})
_LAVFI_OFFLINE_OPT = r":format_opts=protocol_whitelist=file\,pipe"


def _restrict_lavfi_movie(expr: str) -> str:
    if not expr.startswith("movie=") or _LAVFI_OFFLINE_OPT in expr:
        return expr
    in_quote = False
    escaped = False
    for idx, ch in enumerate(expr):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_quote:
            escaped = True
        elif ch == "'":
            in_quote = not in_quote
        elif not in_quote and ch in ",;":
            return expr[:idx] + _LAVFI_OFFLINE_OPT + expr[idx:]
    return expr + _LAVFI_OFFLINE_OPT


def offline_media_command(cmd: list[str], *, probe: bool | None = None) -> list[str]:
    """Apply FFmpeg/ffprobe's local-only protocol policy when offline mode is enabled."""
    if not is_offline_mode() or len(cmd) < 2:
        return cmd
    if any(arg in _INFO_FLAGS for arg in cmd[1:]):
        return cmd
    name = os.path.basename(cmd[0]).lower()
    if probe is None:
        if name in {"ffprobe", "ffprobe.exe"}:
            probe = True
        elif name in {"ffmpeg", "ffmpeg.exe"}:
            probe = False
        else:
            return cmd
    policy = ("-protocol_whitelist", "file,pipe")
    cleaned: list[str] = [cmd[0]]
    args = iter(cmd[1:])
    lavfi_next = False
    for arg in args:
        if arg == "-protocol_whitelist":
            next(args, None)
            continue
        if arg == "-f":
            fmt = next(args, None)
            cleaned.append(arg)
            if fmt is not None:
                lavfi_next = fmt == "lavfi"
                cleaned.append(fmt)
            continue
        if arg == "-i" and lavfi_next:
            lavfi_next = False
            val = next(args, None)
            cleaned.append(arg)
            if val is not None:
                cleaned.append(_restrict_lavfi_movie(val))
            continue
        cleaned.append(arg)
    if probe:
        return [cleaned[0], *policy, *cleaned[1:]]
    restricted: list[str] = [cleaned[0]]
    rest = iter(cleaned[1:])
    has_input = False
    for arg in rest:
        if arg == "-i":
            has_input = True
            value = next(rest, None)
            restricted.extend((*policy, arg))
            if value is not None:
                restricted.append(value)
        else:
            restricted.append(arg)
    if has_input and len(restricted) >= 2:
        restricted[-1:-1] = policy
    return restricted
