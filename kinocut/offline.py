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
