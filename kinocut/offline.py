"""Configuration and fail-closed preflight for offline providers and models."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .errors import MCPVideoError


class OfflineModelMissing(MCPVideoError):
    """Carry expected_file for local diagnostics without leaking it via str() or to_dict()."""

    def __init__(self, expected_file: Path, *, feature: str, env_hint: str):
        self.expected_file = expected_file
        super().__init__(
            f"{feature} requires local weights. {env_hint}",
            error_type="offline_error",
            code="offline_model_missing",
        )

    def __str__(self) -> str:
        return super().__str__()

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


_INFO_FLAGS = frozenset(
    {
        "-version",
        "-h",
        "-help",
        "--help",
        "-filters",
        "-encoders",
        "-decoders",
        "-formats",
        "-buildconf",
        "-protocols",
        "-muxers",
        "-demuxers",
        "-codecs",
        "-bsfs",
        "-pix_fmts",
        "-sample_fmts",
        "-layouts",
        "-hwaccels",
    }
)
_HELP_FLAGS = frozenset({"-h", "-help", "--help"})
_INFO_PREFIX_NO_VAL = frozenset({"-hide_banner", "-nostdin"})
_INFO_PREFIX_WITH_VAL = frozenset({"-v", "-loglevel"})
_LAVFI_OFFLINE_OPT = r":format_opts=protocol_whitelist=file\,pipe"
_FILTER_GRAPH_FLAGS = frozenset({"-vf", "-af", "-filter", "-filter:v", "-filter:a", "-filter_complex", "-lavfi"})
_FILTER_SCRIPT_FLAGS = frozenset({"-filter_complex_script", "-filter_script", "-filter_script:v", "-filter_script:a"})
_REMOTE_PROTOCOL_RE = re.compile(
    r"(?:https?|ftp|ftps|rtmp|rtmps|rtsp|rtsps|tcp|udp|srt|tls|mmsh|mmst|gopher|sftp|smb|hls\+http|hls\+https)://|"
    r"\b(?:concat|subfile|crypto|data):",
    re.IGNORECASE,
)
_MEDIA_LOADER_FILTER_RE = re.compile(r"(?:^|[,;\s\]])(?:a?movie|subtitles|ass)(?:@[A-Za-z0-9_.-]+)?\s*=", re.IGNORECASE)
_LEADING_PAD_RE = re.compile(r"^(?:\s*\[[^\]]+\]\s*)*")
_TRAILING_PAD_RE = re.compile(r"(?:\s*\[[^\]]+\]\s*)+$")
_FFMPEG_BOOL_FLAGS = frozenset(
    {
        "-y",
        "-n",
        "-vn",
        "-an",
        "-sn",
        "-dn",
        "-shortest",
        "-nostdin",
        "-hide_banner",
        "-xerror",
        "-noautorotate",
        "-autorotate",
        "-re",
        "-accurate_seek",
        "-noaccurate_seek",
        "-copyts",
        "-start_at_zero",
        "-ignore_unknown",
        "-copy_unknown",
        "-stats",
        "-nostats",
    }
)


def _is_pure_info_command(args: list[str]) -> bool:
    """True only when argv is a standalone info/version/help probe with no inputs or filters."""
    idx = 0
    total = len(args)
    while idx < total:
        arg = args[idx]
        if arg in _INFO_PREFIX_NO_VAL:
            idx += 1
            continue
        if arg in _INFO_PREFIX_WITH_VAL:
            idx += 2
            continue
        break
    if idx >= total:
        return False
    flag = args[idx]
    if flag not in _INFO_FLAGS:
        return False
    remaining = args[idx + 1 :]
    if not remaining:
        return True
    # Allow a single help topic like `ffmpeg -h filter=scale` (never `-i`, filter flags, or URLs).
    return flag in _HELP_FLAGS and len(remaining) == 1 and not remaining[0].startswith("-")


def _split_filtergraph_segments(expr: str) -> list[tuple[str, str]]:
    """Split a filtergraph into (segment_text, trailing_delimiter) pairs respecting quotes and escapes."""
    segments: list[tuple[str, str]] = []
    start = 0
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
            segments.append((expr[start:idx], ch))
            start = idx + 1
    segments.append((expr[start:], ""))
    return segments


def _restrict_filter_node(segment: str) -> str:
    """Enforce offline protocol restrictions on a single filter node."""
    lead_match = _LEADING_PAD_RE.match(segment)
    lead = lead_match.group(0) if lead_match else ""
    body = segment[len(lead) :]
    trail_match = _TRAILING_PAD_RE.search(body)
    trail = trail_match.group(0) if trail_match else ""
    core = body[: len(body) - len(trail)] if trail else body
    stripped = core.strip()
    if "=" not in stripped:
        return segment
    raw_name, raw_args = stripped.split("=", 1)
    base_name = raw_name.split("@", 1)[0].strip().lower()
    if base_name in {"subtitles", "ass"}:
        if _REMOTE_PROTOCOL_RE.search(raw_args):
            raise MCPVideoError(
                "Remote subtitle filter sources are blocked in offline mode.",
                error_type="offline_error",
                code="offline_network_blocked",
            )
        return segment
    if base_name not in {"movie", "amovie"}:
        return segment
    # Always append our local-only format_opts last on THIS node (never short-circuiting
    # on substring presence elsewhere in the graph or overriding with caller format_opts).
    if stripped.endswith(_LAVFI_OFFLINE_OPT) and "format_opts=" not in stripped[: -len(_LAVFI_OFFLINE_OPT)]:
        return segment
    return f"{lead}{stripped}{_LAVFI_OFFLINE_OPT}{trail}"


def _restrict_filtergraph(expr: str) -> str:
    """Restrict every movie=/amovie=/subtitles=/ass= node anywhere in a filtergraph."""
    pieces: list[str] = []
    for segment, delim in _split_filtergraph_segments(expr):
        pieces.append(_restrict_filter_node(segment))
        if delim:
            pieces.append(delim)
    return "".join(pieces)


def _restrict_lavfi_movie(expr: str) -> str:
    """Restrict lavfi filter expressions (backward-compatible helper)."""
    return _restrict_filtergraph(expr)


def _validate_filter_script(script_path: str) -> None:
    """Block filter scripts that reference remote URLs or media-loader filters offline."""
    if _REMOTE_PROTOCOL_RE.search(script_path):
        raise MCPVideoError(
            "Remote filter script paths are blocked in offline mode.",
            error_type="offline_error",
            code="offline_network_blocked",
        )
    if "\x00" in script_path or ".." in re.split(r"[\\/]+", script_path):
        raise MCPVideoError(
            "Unsafe filter script path is blocked in offline mode.",
            error_type="offline_error",
            code="offline_network_blocked",
        )
    try:
        content = Path(script_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MCPVideoError(
            "Filter script could not be verified for offline safety.",
            error_type="offline_error",
            code="offline_network_blocked",
        ) from exc
    if _MEDIA_LOADER_FILTER_RE.search(content) or _REMOTE_PROTOCOL_RE.search(content):
        raise MCPVideoError(
            "Filter script referencing media loaders or remote protocols is blocked in offline mode.",
            error_type="offline_error",
            code="offline_network_blocked",
        )


def _is_filter_graph_flag(arg: str) -> bool:
    return arg in _FILTER_GRAPH_FLAGS or arg.startswith("-filter:")


def _is_filter_script_flag(arg: str) -> bool:
    return arg in _FILTER_SCRIPT_FLAGS or arg.startswith("-filter_script:")


def _restrict_ffmpeg_outputs(output_args: list[str], policy: tuple[str, str]) -> list[str]:
    """Inject -protocol_whitelist before EVERY FFmpeg output target and guard -f tee."""
    restricted: list[str] = []
    idx = 0
    total = len(output_args)
    tee_next = False
    while idx < total:
        arg = output_args[idx]
        if arg == "-f" and idx + 1 < total:
            fmt = output_args[idx + 1]
            if fmt == "tee":
                tee_next = True
            restricted.extend((arg, fmt))
            idx += 2
            continue
        if arg.startswith("-") and arg != "-":
            restricted.append(arg)
            if arg not in _FFMPEG_BOOL_FLAGS and idx + 1 < total:
                restricted.append(output_args[idx + 1])
                idx += 2
            else:
                idx += 1
            continue
        # Positional output target.
        if tee_next:
            tee_next = False
            if _REMOTE_PROTOCOL_RE.search(arg):
                raise MCPVideoError(
                    "Network tee muxer outputs are blocked in offline mode.",
                    error_type="offline_error",
                    code="offline_network_blocked",
                )
        restricted.extend((*policy, arg))
        idx += 1
    return restricted


def offline_media_command(cmd: list[str], *, probe: bool | None = None) -> list[str]:
    """Apply FFmpeg/ffprobe's local-only protocol policy when offline mode is enabled."""
    if not is_offline_mode() or len(cmd) < 2:
        return cmd
    if _is_pure_info_command(cmd[1:]):
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
    args = cmd[1:]
    idx = 0
    total = len(args)
    lavfi_next = False
    while idx < total:
        arg = args[idx]
        if arg == "-protocol_whitelist":
            idx += 2
            continue
        if arg == "-f" and idx + 1 < total:
            fmt = args[idx + 1]
            lavfi_next = fmt == "lavfi"
            cleaned.extend((arg, fmt))
            idx += 2
            continue
        if arg == "-i" and idx + 1 < total:
            val = args[idx + 1]
            cleaned.append(arg)
            cleaned.append(_restrict_filtergraph(val) if lavfi_next else val)
            lavfi_next = False
            idx += 2
            continue
        if _is_filter_graph_flag(arg) and idx + 1 < total:
            cleaned.extend((arg, _restrict_filtergraph(args[idx + 1])))
            idx += 2
            continue
        if _is_filter_script_flag(arg) and idx + 1 < total:
            _validate_filter_script(args[idx + 1])
            cleaned.extend((arg, args[idx + 1]))
            idx += 2
            continue
        cleaned.append(arg)
        idx += 1
    if probe:
        return [cleaned[0], *policy, *cleaned[1:]]
    # Locate the last real `-i <input>` pair while skipping option values.
    last_input_end = 1
    scan = 1
    while scan < len(cleaned):
        tok = cleaned[scan]
        if tok == "-i" and scan + 1 < len(cleaned):
            last_input_end = scan + 2
            scan += 2
            continue
        if tok.startswith("-") and tok != "-" and tok not in _FFMPEG_BOOL_FLAGS and scan + 1 < len(cleaned):
            scan += 2
            continue
        scan += 1
    if last_input_end == 1:
        return cleaned
    # Inject -protocol_whitelist before every -i input in the input section.
    restricted: list[str] = [cleaned[0]]
    inp_idx = 1
    while inp_idx < last_input_end:
        tok = cleaned[inp_idx]
        if tok == "-i" and inp_idx + 1 < last_input_end:
            restricted.extend((*policy, tok, cleaned[inp_idx + 1]))
            inp_idx += 2
            continue
        if tok.startswith("-") and tok != "-" and tok not in _FFMPEG_BOOL_FLAGS and inp_idx + 1 < last_input_end:
            restricted.extend((tok, cleaned[inp_idx + 1]))
            inp_idx += 2
            continue
        restricted.append(tok)
        inp_idx += 1
    # Inject -protocol_whitelist before EVERY output in the output section.
    restricted.extend(_restrict_ffmpeg_outputs(cleaned[last_input_end:], policy))
    return restricted
