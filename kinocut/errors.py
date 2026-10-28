"""Kinocut error types with auto-fix suggestions."""

from __future__ import annotations

import re
import contextlib
import functools
from contextvars import ContextVar
from typing import Any

# Caller-supplied values echoed into error messages are capped so a hostile
# or accidental 100 KB parameter cannot amplify into a ~200 KB error reply
# that dumps doubled garbage into the caller's agent context window.
_MAX_ECHO_CHARS = 200
_MAX_MESSAGE_CHARS = 2000
# A suggested action is shipped guidance, not caller text. It still gets a
# bound, but a generous one: truncating it would drop the words that tell the
# operator what to change.
_MAX_ACTION_CHARS = 1000

_RETRY_CONTEXT: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar("kinocut_retry_context", default=None)


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


@contextlib.contextmanager
def retry_context(tool_name: str, arguments: dict[str, Any] | None = None):
    """Bind a user-facing error to the operation that can be retried."""

    token = _RETRY_CONTEXT.set((tool_name, dict(arguments or {})))
    try:
        yield
    finally:
        _RETRY_CONTEXT.reset(token)


# Explicit MCP→CLI command-name map for tools whose flat CLI command is not the
# mechanical ``video_``-stripped form. Every value is verified against the
# ``kino --help`` parser choices; extend only with a name that parses.
_CLI_TOOL_OVERRIDES: dict[str, str] = {
    "video_quality_check": "video-quality-check",
    "video_review_package": "video-review-package",
}

# Tools with no single-command CLI equivalent. The retry message must say so
# instead of inventing a ``kino <name>`` command that does not exist.
_NO_CLI_EQUIVALENT: frozenset[str] = frozenset(
    {
        "search_tools",
        "video_add_texts",
        "video_project_create",
        "video_shorts",
        "video_validate_text_layout",
    }
)


@functools.lru_cache(maxsize=1)
def _cli_command_names() -> frozenset[str]:
    """The flat CLI command names the parser actually registers.

    The CLI names do not follow one mechanical pattern — ``video_trim`` is
    ``kino trim`` while ``video_ai_transcribe`` is ``kino video-ai-transcribe``
    — so a retry message checks the parser instead of inventing a command.
    """
    try:
        from kinocut.cli.parser import build_parser

        parser = build_parser()
    except Exception:
        # A parser that cannot be built means no command can be verified.
        # Saying there is no equivalent is honest; naming one is not.
        return frozenset()
    names: set[str] = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            names.update(str(name) for name in choices)
    return frozenset(names)


def _cli_tool_name(tool_name: str) -> str | None:
    """Map an MCP tool name to its flat CLI command, or None when none exists."""
    if tool_name in _NO_CLI_EQUIVALENT:
        return None
    if tool_name in _CLI_TOOL_OVERRIDES:
        return _CLI_TOOL_OVERRIDES[tool_name]
    commands = _cli_command_names()
    candidates: list[str] = []
    if tool_name.startswith("video_"):
        candidates.append(tool_name.removeprefix("video_").replace("_", "-"))
    candidates.append(tool_name.replace("_", "-"))
    for candidate in candidates:
        if candidate in commands:
            return candidate
    return None


def _argument_names(arguments: dict[str, Any]) -> str:
    """Name the arguments a failed call carried, without echoing their values.

    The retry context exists to make a refusal addressable — which tool, with
    which inputs — and the stored arguments are what make it so: the operator
    learns exactly which parameters the call carried, and therefore which one
    to correct. The values are the caller's own input and can be hostile (a
    validation error must not echo the value it just rejected), so only the
    names are named.
    """
    if not arguments:
        return ""
    return " (arguments: " + ", ".join(sorted(_argument_name(key) for key in arguments)) + ")"


def _argument_name(key: Any) -> str:
    """A printable, bounded name for one argument of a refused call.

    The names come from the caller's own argument mapping. JSON and
    ``vars()`` give string keys, but the formatter is a process-wide error
    path, so it must not assume that: a non-string key is rendered as text,
    and control characters are replaced rather than copied into human-facing
    text.
    """
    text = key if isinstance(key, str) else str(key)
    text = "".join(char if char.isprintable() else "_" for char in text)
    return text[:64] or "argument"


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
            clean[key] = type(value).__name__
    return clean


def retry_message(message: str, code: str) -> str:
    """Append an eyes-free MCP and CLI retry invocation to an error message.

    Every refusal carries the same shape: the MCP call to make, the CLI
    command to run, and the action that fixes it. When the retry context binds
    a tool and its arguments, both halves name them — the tool, the CLI
    command, and which arguments the call carried — so the refusal is
    actionable rather than advisory. Without a context the generic tokens
    stand on their own.
    """

    context = _RETRY_CONTEXT.get()
    tool_name = context[0] if context else "the same tool"
    cli_name = _cli_tool_name(tool_name) if context else None
    submitted = _argument_names(context[1]) if context else ""
    consent = code in {"hyperframes_telemetry_consent_required", "network_consent_required"}
    missing_tool = code in {"ffmpeg_not_found", "ffprobe_not_found"}
    if code in {"output_exists", "overwrite_refused"}:
        mcp_action, cli_action = f"overwrite=true{submitted}", f"--overwrite{submitted}"
    elif code in {"unsafe_path", "invalid_output_path"}:
        mcp_action, cli_action = f"a new output_path{submitted}", f"--output <new-media-path>{submitted}"
    elif consent:
        # NOTE (t_e3775201 F-INFO): no shipped code path raises
        # ``network_consent_required`` yet. Before any network-consent feature
        # lands, re-bind its hint to the actual consent env var of that feature;
        # ``KINOCUT_HYPERFRAMES_TELEMETRY`` only gates Hyperframes telemetry.
        mcp_action = f"KINOCUT_HYPERFRAMES_TELEMETRY=true{submitted}"
        cli_action = "KINOCUT_HYPERFRAMES_TELEMETRY=true kino"
    elif missing_tool:
        mcp_action = "install FFmpeg, then call " + tool_name + submitted
        cli_action = "install FFmpeg, then run kino"
    else:
        mcp_action, cli_action = f"corrected parameters{submitted}", f"corrected flags{submitted}"

    if context is None:
        # No tool bound: the tokens have to carry the refusal by themselves.
        invocation = f"{mcp_action} (MCP) / {cli_action} (CLI)"
    elif cli_name is None:
        # The tool has no single-command CLI equivalent. The special-code
        # actions are already tool-shaped, so they are not prefixed again.
        invocation = (
            f"{'' if consent or missing_tool else 'call ' + tool_name + ' with '}{mcp_action} (MCP) / "
            "no single-command CLI equivalent "
            "(run kino --help to browse related commands) (CLI)"
        )
    elif consent or missing_tool:
        invocation = f"{mcp_action} (MCP) / {cli_action} {cli_name}{submitted} (CLI)"
    else:
        invocation = f"call {tool_name} with {mcp_action} (MCP) / run kino {cli_name} with {cli_action} (CLI)"
    return f"{message}; retry with {invocation}"


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
    ):
        self.error_type = error_type
        self.code = code
        self.suggested_action = suggested_action
        self.docs_url = docs_url
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


class HyperframesRenderError(MCPVideoError):
    """Hyperframes render failure."""

    def __init__(self, command: str, returncode: int, stderr: str, *, reason: str | None = None) -> None:
        # The renderer's diagnostic stays on the error object. It is not
        # published: it repeats the project path the caller submitted. A
        # package-authored reason is published — it is our own text.
        message = f"Hyperframes render failed (exit code {returncode})"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(
            message,
            error_type="render_error",
            code=f"hyperframes_exit_{returncode}",
            suggested_action={
                "auto_fix": False,
                "description": (
                    "Check the project's index.html and its composition root, then "
                    "render again to read Hyperframes' own diagnostic."
                ),
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
