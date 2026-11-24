"""Kinocut error types with auto-fix suggestions."""

from __future__ import annotations

import re
from typing import Any

from .tool_routing import (
    _argument_type as _argument_type,
    cli_route_for_operation as cli_route_for_operation,
    _cli_command_set as _cli_command_set,
    retry_context as retry_context,
    retry_message as retry_message,
)
from .type_names import _register_exception_kinds, type_label

_cli_tool_name = cli_route_for_operation

# Caller-supplied values echoed into error messages are capped so a hostile
# or accidental 100 KB parameter cannot amplify into a ~200 KB error reply
# that dumps doubled garbage into the caller's agent context window.
_MAX_ECHO_CHARS = 200
_MAX_MESSAGE_CHARS = 2000
# A suggested action is shipped guidance, not caller text. It still gets a
# bound, but a generous one: truncating it would drop the words that tell the
# operator what to change.
_MAX_ACTION_CHARS = 1000


def _without_value(text: str, value: str) -> str:
    """The text with the caller's submitted value removed.

    An error names the argument and the failure; it never repeats what the
    caller passed. That string can be a path, a codec name, or a
    credential-shaped token, and it must not travel back out to the caller.
    """
    if not value:
        return text
    cleaned = text.replace(value, "").strip()
    return cleaned or "the submitted value was rejected"


def _sanitize_action(action: dict[str, Any]) -> dict[str, Any]:
    """Bound a suggested action before it leaves the process.

    The action is written by shipped code, but it is still free text that
    reaches the MCP and CLI payloads; it is bounded here rather than trusted.
    """
    clean: dict[str, Any] = {}
    for key, value in action.items():
        if isinstance(value, str):
            clean[key] = truncate_echo(value, limit=_MAX_ACTION_CHARS)
        elif value is None or isinstance(value, (int, float, bool)):
            clean[key] = value
        else:
            clean[key] = type_label(value)
    return clean


def truncate_echo(value: str, limit: int = _MAX_ECHO_CHARS) -> str:
    """Collapse an oversized caller-supplied value for an error message.

    Keeps head and tail so both the prefix and the filename end stay
    identifiable, and states how much was elided.
    """
    if len(value) <= limit:
        return value
    half = max((limit - 40) // 2, 1)
    elided = len(value) - 2 * half
    return f"{value[:half]}…[{elided} chars truncated]…{value[-half:]}"


class MCPVideoError(Exception):
    """Base error for all Kinocut operations."""

    def __init__(
        self,
        message: str,
        error_type: str = "unknown_error",
        code: str = "unknown",
        suggested_action: dict[str, Any] | None = None,
        docs_url: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ):
        self.error_type = error_type
        self.code = code
        self.suggested_action = suggested_action
        self.docs_url = docs_url
        self.details = details
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.error_type,
            "code": self.code,
            # Backstop against echo amplification on any error lane; normal
            # bilingual messages stay far below the cap.
            "message": truncate_echo(retry_message(str(self), self.code), limit=_MAX_MESSAGE_CHARS),
        }
        if self.suggested_action:
            result["suggested_action"] = _sanitize_action(self.suggested_action)
        if self.docs_url:
            result["documentation_url"] = self.docs_url
        if self.details:
            result["details"] = self.details
        return result


class FFmpegNotFoundError(MCPVideoError):
    """FFmpeg is not installed or not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "FFmpeg not found. Install it with: brew install ffmpeg (macOS), "
            "apt install ffmpeg (Ubuntu), or download from https://ffmpeg.org — "
            "FFmpeg no está instalado: instálalo con brew install ffmpeg (macOS), "
            "apt install ffmpeg (Ubuntu) o descárgalo de https://ffmpeg.org",
            error_type="dependency_error",
            code="ffmpeg_not_found",
            suggested_action={
                "auto_fix": False,
                "description": "Install FFmpeg before using Kinocut / Instala FFmpeg antes de usar Kinocut",
            },
        )


class FFprobeNotFoundError(MCPVideoError):
    """FFprobe is not installed or not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "FFprobe not found. It should be installed alongside FFmpeg.",
            error_type="dependency_error",
            code="ffprobe_not_found",
        )


class ValidationError(MCPVideoError, ValueError):
    """User parameter validation failed."""

    def __init__(self, parameter: str, detail: str) -> None:
        super().__init__(
            f"Invalid parameter {parameter}: {detail}",
            error_type="validation_error",
            code="invalid_parameter",
            suggested_action={
                "auto_fix": False,
                "description": f"Correct the {parameter} argument and retry.",
            },
        )


class C2PAToolNotFoundError(MCPVideoError):
    """c2patool is required for requested C2PA signing but is unavailable."""

    def __init__(self) -> None:
        super().__init__(
            "C2PA signing requested, but the c2patool configured in the environment is not an executable file",
            error_type="dependency_error",
            code="c2patool_not_found",
            suggested_action={
                "auto_fix": False,
                "description": "Install c2patool or pass an executable path with --c2pa-tool.",
            },
        )


class C2PASigningError(MCPVideoError):
    """c2patool failed while adding a manifest to an exported asset."""

    def __init__(self, detail: str, *, code: str = "c2pa_signing_failed") -> None:
        super().__init__(
            f"C2PA signing failed: {detail}",
            error_type="provenance_error",
            code=code,
            suggested_action={
                "auto_fix": False,
                "description": "Check the c2patool installation, manifest JSON, certificate, signer, and output path.",
            },
        )


class C2PAVerificationError(MCPVideoError):
    """A signed asset could not be verified after C2PA signing."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"C2PA verification failed: {detail}",
            error_type="provenance_error",
            code="c2pa_verification_failed",
            suggested_action={
                "auto_fix": False,
                "description": "Inspect the c2patool verification output before treating the export as signed.",
            },
        )


class InputFileError(MCPVideoError):
    """Input file doesn't exist or is not a valid video."""

    def __init__(self, path: str, reason: str = "File not found (archivo no encontrado)") -> None:
        super().__init__(
            f"Input file error — {_without_value(reason, path)}",
            error_type="input_error",
            code="invalid_input",
            suggested_action={
                "auto_fix": False,
                "description": "Check that the file exists and is a valid video file.",
            },
        )


class CodecError(MCPVideoError):
    """Unsupported or incompatible codec."""

    def __init__(self, codec: str, detail: str = "") -> None:
        message = "Codec error"
        if detail:
            message += f" — {_without_value(detail, codec)}"
        super().__init__(
            message,
            error_type="encoding_error",
            code="unsupported_codec",
            suggested_action={
                "auto_fix": True,
                "description": "Auto-convert the input to H.264/AAC before editing",
            },
            docs_url="https://git.kyanitelabs.tech/KyaniteLabs/kinocut#codec-compatibility",
        )


class HyperframesNotFoundError(MCPVideoError):
    """Hyperframes CLI or Node.js not found on PATH."""

    def __init__(self, detail: str = "") -> None:
        msg = "Hyperframes requires Node.js 22+ and a resolvable Hyperframes CLI."
        if detail:
            msg += f" — {detail}"
        super().__init__(
            msg,
            error_type="dependency_error",
            code="hyperframes_not_found",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Install Node.js (v22+) and a pinned Hyperframes package, add hyperframes to PATH, "
                    "or set MCP_VIDEO_HYPERFRAMES_COMMAND."
                ),
            },
        )


class HyperframesProjectError(MCPVideoError):
    """Invalid Hyperframes project structure."""

    def __init__(self, path: str, reason: str = "Invalid project") -> None:
        super().__init__(
            f"Hyperframes project error — {_without_value(reason, path)}",
            error_type="project_error",
            code="invalid_hyperframes_project",
            suggested_action={
                "auto_fix": False,
                "description": "Ensure the project has an index.html with a data-composition-id root element.",
            },
        )


_HYPERFRAMES_CACHE_ERRNO_RE = re.compile(r"\b(?:enoent|eacces|eperm|erofs)\b")
_HYPERFRAMES_MKDIR_RE = re.compile(r"\bmkdir\b")
_HYPERFRAMES_LOCK_PATH_RE = re.compile(r"/(?:locks|\.chrome\.install\.lock)(?=$|[\s'\"/,):;])")


def _is_hyperframes_cache_write_error(diagnostic: str) -> bool:
    """Detect Hyperframes cache/lock mkdir failures in linear time per line."""
    if (
        "the render slot cannot be taken" in diagnostic
        and "this account cannot write to " in diagnostic
        and "hyperframes_cache_dir" in diagnostic
    ):
        return True
    for line in diagnostic.splitlines():
        errno_match = _HYPERFRAMES_CACHE_ERRNO_RE.search(line)
        if errno_match is None:
            continue
        mkdir_match = _HYPERFRAMES_MKDIR_RE.search(line, errno_match.end())
        if mkdir_match is None:
            continue
        if _HYPERFRAMES_LOCK_PATH_RE.search(line, mkdir_match.end()) is not None:
            return True
    return False


class HyperframesRenderError(MCPVideoError):
    """Hyperframes render failure."""

    def __init__(self, command: str, returncode: int, stderr: str, *, reason: str | None = None) -> None:
        # The renderer's diagnostic stays on the error object. It is not
        # published: it repeats the project path the caller submitted. A
        # package-authored reason is published — it is our own text.
        message = f"Hyperframes render failed (exit code {returncode})"
        if reason:
            message = f"{message}: {reason}"
        diagnostic = (stderr or "").lower().replace("\\", "/")
        if returncode in (137, -9) or "out of memory" in diagnostic or "heap out of memory" in diagnostic:
            description = "Hyperframes ran out of memory; reduce resolution/fps or free host memory, then retry."
        elif _is_hyperframes_cache_write_error(diagnostic):
            description = "Hyperframes could not write to its cache. Set HYPERFRAMES_CACHE_DIR to a writable directory."
        elif any(tok in diagnostic for tok in ("chromium", "chrome", "browser", "playwright", "puppeteer", "sandbox")):
            description = (
                "Hyperframes could not start its browser. Check the browser install and HYPERFRAMES_BROWSER_PATH, "
                "or run `kino hyperframes-doctor`."
            )
        elif any(tok in diagnostic for tok in ("enoent", "command not found", "cannot find module", "node")):
            description = (
                "Runtime dependency or binary is missing; run `kino hyperframes-doctor` to verify Node and Hyperframes."
            )
        elif "timed out" in diagnostic or returncode == -1:
            description = "Render timed out; verify host load or simplify the composition, then retry."
        else:
            description = (
                "Check the project's index.html and its composition root, or run `kino hyperframes-doctor` "
                "to inspect environment diagnostics."
            )
        super().__init__(
            message,
            error_type="render_error",
            code=f"hyperframes_exit_{returncode}",
            suggested_action={
                "auto_fix": False,
                "description": description,
            },
        )
        self.command = command
        self.returncode = returncode
        self.full_stderr = stderr


# Actionable error keywords that can appear before standard stream markers
_ACTIONABLE_PATTERNS = (
    "permission denied",
    "no such file",
    "not found",
    "invalid data",
    "protocol not found",
    "unable to open",
    "cannot open",
    "unknown encoder",
    "no such filter",
)


def _strip_ffmpeg_banner(stderr: str) -> str:
    """Remove FFmpeg version banner and build configuration from stderr.

    The banner includes version lines, build flags, and library versions
    that clutter error messages. We keep everything from the first 'Input #'
    or from the first line that doesn't look like banner noise.

    Actionable root-cause lines (e.g. 'Permission denied') are preserved
    even if they appear before the usual stream markers.
    """
    lines = stderr.splitlines()
    result_lines: list[str] = []
    in_banner = True
    for line in lines:
        if in_banner:
            # Heuristic: banner lines are indented or start with version info
            stripped = line.strip()
            if stripped.startswith("ffmpeg version") or stripped.startswith("ffprobe version"):
                continue
            if stripped.startswith("built with") or stripped.startswith("configuration:"):
                continue
            if stripped.startswith("lib") and "/" in stripped:
                continue
            # Preserve actionable root-cause lines that appear early
            if (
                any(p in stripped.lower() for p in _ACTIONABLE_PATTERNS)
                or stripped.startswith("Stream mapping:")
                or stripped.startswith("Input #")
                or stripped.startswith("Output #")
                or (stripped.startswith("[") and "Error" in stripped)
                or "error" in stripped.lower()
            ):
                in_banner = False
            else:
                # Still looks like banner noise — skip it
                continue
        result_lines.append(line)
    return "\n".join(result_lines) if result_lines else stderr


class ProcessingError(MCPVideoError):
    """FFmpeg processing failed."""

    def __init__(self, command: str, returncode: int, stderr: str, *, reason: str | None = None) -> None:
        # The child's diagnostic is kept on the error object for local
        # debugging, but it is not published: FFmpeg echoes the path the
        # caller submitted, and a diagnostic can carry anything at all. A
        # package-authored reason is published — it is our own text.
        message = f"FFmpeg processing failed (exit code {returncode})"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(
            message,
            error_type="processing_error",
            code=f"ffmpeg_exit_{returncode}",
        )
        self.command = command
        self.returncode = returncode
        self.full_stderr = stderr


class BackendUnavailableError(MCPVideoError):
    """Requested processing backend cannot run the selected model."""

    def __init__(
        self,
        message: str,
        *,
        backend: str = "kinocut-onnx",
        suggested_action: dict[str, Any] | None = None,
        docs_url: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_type="backend_unavailable",
            code="backend_unavailable",
            suggested_action=suggested_action
            or {
                "auto_fix": False,
                "description": f"Use an available model or wait until the {backend} backend ships.",
            },
            docs_url=docs_url,
        )
        self.backend = backend


class ResourceError(MCPVideoError):
    """Insufficient disk space or memory."""

    def __init__(self, resource: str, detail: str) -> None:
        super().__init__(
            f"Resource error ({resource}): {detail}",
            error_type="resource_error",
            code="insufficient_resource",
        )


def _input_path_from_command(command: list[str] | None) -> str:
    """Extract the first -i input path from an FFmpeg command list."""
    if not command:
        return ""
    for i, arg in enumerate(command[:-1]):
        if arg == "-i":
            return command[i + 1]
    return ""


_MISSING_FFMPEG_COMPONENT = re.compile(
    r"^[ \t]*(?:\[[^\]\r\n]{1,128}\][ \t]*)?"
    r"(?:Unknown encoder[ \t]+'(?P<encoder>[A-Za-z][A-Za-z0-9_]{0,63})'"
    r"|No such filter:[ \t]+'(?P<filter>[A-Za-z][A-Za-z0-9_]{0,63})')"
    r"[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE | re.ASCII,
)


def _missing_component_error(stderr: str, command: str, original_stderr: str) -> ProcessingError | None:
    """Add advisory metadata without changing processing-error catch compatibility.

    Match complete diagnostics, never arbitrary mentions in paths/metadata.
    Bounded ASCII names are safe to include in existing per-component reason codes.
    Missing output encoders are distinct from unsupported input codecs: there is
    no automatic format substitution or environment mutation.
    """
    match = _MISSING_FFMPEG_COMPONENT.search(stderr)
    if match is None:
        return None
    kind = "encoder" if match.group("encoder") is not None else "filter"
    requested_name = match.group(kind)
    name = requested_name.lower()
    error = ProcessingError(command, 1, original_stderr)
    error.error_type = "dependency_error"
    error.code = f"missing_{kind}_{name}"
    error.suggested_action = {
        "auto_fix": False,
        "description": (
            f"FFmpeg did not recognize the requested {kind} '{requested_name}'. "
            "Check the exact component name and selected build's support, "
            "or explicitly choose a compatible operation. "
            "Kinocut has not changed the requested codec or filters."
        ),
    }
    return error


def parse_ffmpeg_error(stderr: str, command: list[str] | None = None) -> MCPVideoError:
    """Parse FFmpeg stderr and return the most specific error type.

    When the failing *command* is provided, file errors carry the actual
    input path instead of an empty string.
    """
    original_stderr = stderr
    stderr = _strip_ffmpeg_banner(stderr)
    stderr_lower = stderr.lower()
    input_path = _input_path_from_command(command)
    cmd_str = " ".join(command) if command else ""

    if "no such file or directory" in stderr_lower:
        return InputFileError(input_path, "File not found")
    if "invalid data found when processing input" in stderr_lower:
        return InputFileError(input_path, "Not a valid video file")
    if missing := _missing_component_error(stderr, cmd_str, original_stderr):
        return missing
    if "unsupported codec" in stderr_lower or "decoder" in stderr_lower:
        codec = "unknown"
        for line in stderr.split("\n"):
            if "codec" in line.lower():
                codec = line.strip()
                break
        return CodecError(codec)
    if "error while decoding" in stderr_lower:
        return ProcessingError(cmd_str, 1, stderr)
    if "permission denied" in stderr_lower:
        return InputFileError(input_path, "Permission denied")
    if "no space left on device" in stderr_lower:
        return ResourceError("disk_space", "No space left on device")

    return ProcessingError(cmd_str, 1, stderr)


def wrap_error(exc: Exception) -> MCPVideoError:
    """Convert any exception to MCPVideoError. Returns as-is if already MCPVideoError."""
    if isinstance(exc, MCPVideoError):
        return exc
    return ProcessingError(str(exc), 1, getattr(exc, "stderr", ""))


class RevideoNotFoundError(MCPVideoError):
    """Node.js or npm not found for the Revideo bridge."""

    def __init__(self, detail: str = "") -> None:
        msg = "The Revideo bridge requires Node.js 18+ and npm on PATH."
        if detail:
            msg += f" — {detail}"
        super().__init__(
            msg,
            error_type="dependency_error",
            code="revideo_not_found",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Install Node.js and npm; the bridge template pins its own "
                    "@revideo dependencies via a committed lockfile."
                ),
            },
        )


class RevideoProjectError(MCPVideoError):
    """Invalid Revideo bridge project structure or scene source."""

    def __init__(self, path: str, reason: str = "Invalid bridge project") -> None:
        super().__init__(
            f"Revideo bridge project error — {_without_value(reason, path)}",
            error_type="project_error",
            code="invalid_revideo_project",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Use the vendored bridge template via kinocut.revideo_engine; "
                    "scene sources must export makeScene2D('<name>', function* ...)."
                ),
            },
        )


class RevideoRenderError(MCPVideoError):
    """Revideo bridge render failure (non-zero exit or timeout)."""

    def __init__(self, command: str, returncode: int, stderr: str, *, reason: str | None = None) -> None:
        # The bridge's diagnostic stays on the error object. It is not
        # published: it repeats the scene path the caller submitted. A
        # package-authored reason is published — it is our own text.
        message = f"Revideo render failed (exit code {returncode})"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(
            message,
            error_type="render_error",
            code=f"revideo_exit_{returncode}",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Check the bridge project's scene sources and the render output "
                    "location, then render again to read the bridge's own diagnostic."
                ),
            },
        )
        self.command = command
        self.returncode = returncode
        self.full_stderr = stderr


#: Register every error class this module defines by identity, so
#: ``exception_kind`` may publish its name. A subclass defined elsewhere —
#: a plugin's, a caller's — is a different type object and stays
#: ``<foreign-exception>``: identity, not inheritance, is the rule,
#: because a subclass's name is its author's string.
_register_exception_kinds(
    [obj for obj in list(vars().values()) if isinstance(obj, type) and issubclass(obj, MCPVideoError)]
)
