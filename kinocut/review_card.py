"""Self-contained HTML review card for Hermes Desktop chat.

Hermes renders ``::preview{file="card.html"}`` inline in a sandboxed iframe with
an opaque origin, so relative file references do not load: every image is
embedded as a ``data:`` URI. A ``<button data-hermes-send="text">`` sends
``text`` back as a hidden user turn (Hermes caps it at 500 characters).
"""

from __future__ import annotations

import base64
import html
import io
import os
import tempfile
from typing import Any

from .errors import MCPVideoError
from .validation_errors import rejected_value

MAX_SEND_TEXT = 500
MAX_INLINE_IMAGE_BYTES = 200 * 1024
MAX_IMAGE_WIDTH = 960
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png"})

_STYLE = """
body{margin:0;padding:12px;font-family:system-ui,sans-serif;color:var(--foreground,#111);background:transparent}
.card{background:var(--card,#fff);border:1px solid var(--border,#ddd);border-radius:10px;padding:14px;max-width:960px}
h1{font-size:16px;margin:0 0 10px;word-break:break-all}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;font-size:13px;margin:0 0 10px}
dt{color:var(--muted-foreground,#666)}
dd{margin:0}
img{display:block;width:100%;height:auto;border:1px solid var(--border,#ddd);border-radius:6px;margin:0 0 8px}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
button{font:inherit;font-size:13px;padding:6px 12px;border-radius:6px;cursor:pointer;
color:var(--accent,#2563eb);background:transparent;border:1px solid var(--accent,#2563eb)}
""".strip()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_review_card(
    *,
    title: str,
    facts: dict[str, str],
    images: list[tuple[str, bytes, str]],
    actions: list[tuple[str, str]],
) -> str:
    """Return one self-contained HTML document: no scripts, no external URLs.

    Visible text names the file by ``title`` only. The full path rides in the
    hidden ``data-hermes-send`` text, so a screenshot of the card shows no
    local directory names.
    """
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_esc(title)}</title>",
        f"<style>{_STYLE}</style></head><body>",
        '<div class="card">',
        f"<h1>{_esc(title)}</h1>",
    ]
    if facts:
        parts.append("<dl>")
        for key, value in facts.items():
            parts.append(f"<dt>{_esc(key)}</dt><dd>{_esc(value)}</dd>")
        parts.append("</dl>")
    for alt, data, mime in images:
        if mime not in _ALLOWED_MIME:
            raise MCPVideoError(
                f"Unsupported image type for review card: {rejected_value(mime)}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(f'<img src="data:{mime};base64,{encoded}" alt="{_esc(alt)}">')
    if actions:
        parts.append('<div class="actions">')
        for label, send in actions:
            parts.append(
                f'<button type="button" data-hermes-send="{_esc(send[:MAX_SEND_TEXT])}">{_esc(label)}</button>'
            )
        parts.append("</div>")
    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def _sheet_bytes(sheet_path: str) -> tuple[bytes, str]:
    """Return the contact sheet bytes, downscaled to JPEG when over 200 KB."""
    with open(sheet_path, "rb") as fh:
        raw = fh.read()
    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    if len(raw) <= MAX_INLINE_IMAGE_BYTES:
        return raw, mime
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        img = img.convert("RGB")
        if img.width > MAX_IMAGE_WIDTH:
            height = max(1, round(img.height * MAX_IMAGE_WIDTH / img.width))
            img = img.resize((MAX_IMAGE_WIDTH, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80, optimize=True)
    return buf.getvalue(), "image/jpeg"


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "unknown"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _fresh_card_path(input_path: str) -> str:
    """Default card path next to the input; never reuse an existing file (HTML is not overwritable media)."""
    from .paths import _auto_output

    candidate = _auto_output(input_path, "review_card", ext=".html")
    stem, ext = os.path.splitext(candidate)
    n = 2
    while os.path.lexists(candidate):
        candidate = f"{stem}_{n}{ext}"
        n += 1
    return candidate


def write_review_card(
    input_path: str,
    output_path: str | None = None,
    frame_count: int = 6,
) -> dict[str, Any]:
    """Write ``<stem>_review_card.html`` (contact sheet + facts + buttons) for chat review."""
    from .engine_probe import probe
    from .engine_storyboard import storyboard
    from .ffmpeg_helpers import _atomic_artifact, _open_staged_writer, _validate_input_path

    input_path = _validate_input_path(input_path)
    if frame_count < 1 or frame_count > 100:
        raise MCPVideoError(
            f"frame_count must be between 1 and 100, got {frame_count}",
            error_type="validation_error",
            code="invalid_frame_count",
        )
    if output_path is None:
        output_path = _fresh_card_path(input_path)

    info = probe(input_path)
    with tempfile.TemporaryDirectory(prefix="kinocut_review_card_") as tmp:
        board = storyboard(input_path, output_dir=tmp, frame_count=frame_count)
        sheet = board.grid or (board.frames[0] if board.frames else None)
        if sheet is None:
            raise MCPVideoError(
                "Could not extract any frames for the review card",
                error_type="processing_error",
                code="no_frames",
            )
        sheet_data, sheet_mime = _sheet_bytes(sheet)

    name = os.path.basename(input_path)
    facts = {
        "Duration": _format_duration(info.duration),
        "Resolution": info.resolution,
        "FPS": f"{info.fps:g}",
        "Codec": info.codec,
        "Size": _format_size(info.size_bytes),
    }
    actions = [
        ("Approve & export", f"Approve this cut and export it: {input_path}"),
        ("Dig in", f"Show me more detail on {input_path}"),
        ("Try another range", f"Try a different range of {input_path}"),
    ]
    document = render_review_card(
        title=name,
        facts=facts,
        images=[(f"Contact sheet of {name}", sheet_data, sheet_mime)],
        actions=actions,
    )
    with _atomic_artifact(output_path) as staged, _open_staged_writer(staged) as stream:
        stream.write(document.encode("utf-8"))
    return {
        "success": True,
        "operation": "review_card",
        "output_path": output_path,
        "preview_directive": f'::preview{{file="{output_path}"}}',
        "frame_count": len(board.frames),
        "duration": info.duration,
        "resolution": info.resolution,
        "size_bytes": len(document.encode("utf-8")),
    }
