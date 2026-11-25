"""Self-contained HTML review card for Hermes Desktop chat.

Hermes renders ``::preview{file="card.html"}`` inline in a sandboxed iframe with
an opaque origin, so relative file references do not load: every image is
embedded as a ``data:`` URI, and so is the muted preview player. A ``<button data-hermes-send="text">`` sends
``text`` back as a hidden user turn (Hermes caps it at 500 characters).
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import tempfile
from typing import Any

from .errors import MCPVideoError
from .validation_errors import exception_kind, rejected_value

MAX_SEND_TEXT = 500
MAX_INLINE_IMAGE_BYTES = 200 * 1024
MAX_IMAGE_WIDTH = 960
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png"})
# Hermes web reads at most 512 KB of a previewed text file; stay under it.
MAX_CARD_BYTES = 480 * 1024
SHEET_BYTES_WITH_PLAYER = 60 * 1024
POSTER_WIDTH = 480
MIN_PREVIEW_BITRATE = 48_000
MAX_PREVIEW_BITRATE = 400_000
# A poster darker than this mean luma (0-255) reads as a black frame.
MIN_POSTER_LUMA = 24

_STYLE = """
body{margin:0;padding:12px;font-family:system-ui,sans-serif;color:var(--foreground,#111);background:transparent}
.card{background:var(--card,#fff);border:1px solid var(--border,#ddd);border-radius:10px;padding:14px;max-width:960px}
h1{font-size:16px;margin:0 0 10px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;font-size:13px;margin:0 0 10px}
dt{color:var(--muted-foreground,#666)}
dd{margin:0}
video{display:block;width:100%;height:auto;background:#000;border-radius:6px;margin:0 0 8px}
img{display:block;width:100%;height:auto;border:1px solid var(--border,#ddd);border-radius:6px;margin:0 0 8px}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
button{font:inherit;font-size:13px;padding:6px 12px;border-radius:6px;cursor:pointer;
color:var(--accent,#2563eb);background:transparent;border:1px solid var(--accent,#2563eb)}
dd,h1{overflow-wrap:anywhere}
@media (max-width:480px){
body{padding:8px}
.card{padding:12px}
dl{grid-template-columns:1fr;gap:0}
dt{font-size:12px;margin-top:6px}
.actions{flex-direction:column}
button{width:100%;min-height:44px;font-size:15px}
}
""".strip()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_review_card(
    *,
    title: str,
    facts: dict[str, str],
    images: list[tuple[str, bytes, str]],
    actions: list[tuple[str, str]],
    video: bytes | None = None,
    poster: bytes | None = None,
    input_sha256: str | None = None,
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
    ]
    if input_sha256:
        parts.append(f'<meta name="kinocut-input-sha256" content="{_esc(input_sha256)}">')
    card_attrs = f' class="card" data-input-sha256="{_esc(input_sha256)}"' if input_sha256 else ' class="card"'
    parts.extend(
        [
            f"<title>{_esc(title)}</title>",
            f"<style>{_STYLE}</style></head><body>",
            f"<div{card_attrs}>",
            f"<h1>{_esc(title)}</h1>",
        ]
    )
    if video:
        poster_attr = f' poster="data:image/jpeg;base64,{base64.b64encode(poster).decode("ascii")}"' if poster else ""
        parts.append(
            f'<video src="data:video/mp4;base64,{base64.b64encode(video).decode("ascii")}"{poster_attr}'
            f' muted autoplay loop playsinline controls aria-label="Preview of {_esc(title)}"></video>'
        )
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


def _jpeg(image_path: str, width: int, qscale: int) -> bytes:
    """Encode one image as JPEG no wider than ``width`` with FFmpeg (``qscale``: 2 best .. 31 worst)."""
    from .ffmpeg_helpers import _run_ffmpeg_bytes

    # FFmpeg is a core dependency; Pillow is not, so a plain install can still build the card.
    return _run_ffmpeg_bytes(
        [
            "-v", "error", "-i", image_path, "-frames:v", "1",
            "-vf", f"scale=w='min({width},iw)':h=-2,format=yuvj420p",
            "-q:v", str(qscale), "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
        ]
    )  # fmt: skip


def _mean_luma(image_path: str) -> float:
    """Mean 8-bit luma of an image, sampled on a 16x16 grayscale thumbnail."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(image_path) as img:
                thumb = img.convert("L").resize((16, 16))
                raw = thumb.tobytes()
            return sum(raw) / len(raw) if raw else 0.0
        except OSError:
            pass

    from .ffmpeg_helpers import _run_ffmpeg_bytes

    raw = _run_ffmpeg_bytes(
        [
            "-v", "error", "-i", image_path, "-frames:v", "1",
            "-vf", "scale=16:16,format=gray", "-f", "rawvideo", "pipe:1",
        ]
    )  # fmt: skip
    return sum(raw) / len(raw) if raw else 0.0


def _sheet_bytes(sheet_path: str, max_bytes: int = MAX_INLINE_IMAGE_BYTES) -> tuple[bytes, str]:
    """Return the contact sheet bytes, downscaled to JPEG when over ``max_bytes``."""
    with open(sheet_path, "rb") as fh:
        raw = fh.read()
    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    if len(raw) <= max_bytes:
        return raw, mime
    data = _jpeg(sheet_path, MAX_IMAGE_WIDTH, 5)
    for width, qscale in ((MAX_IMAGE_WIDTH, 9), (640, 9), (480, 12), (320, 18), (240, 24)):
        if len(data) <= max_bytes:
            break
        data = _jpeg(sheet_path, width, qscale)
    return data, "image/jpeg"


def _poster_bytes(frames: list[str], *, preencoded_jpeg: bool = False) -> bytes | None:
    """Return a JPEG of the first storyboard frame that isn't near-black, else the brightest one."""
    best: tuple[float, str] | None = None
    for frame in frames:
        luma = _mean_luma(frame)
        if luma >= MIN_POSTER_LUMA:
            best = (luma, frame)
            break
        if best is None or luma > best[0]:
            best = (luma, frame)
    if best is None:
        return None
    if preencoded_jpeg:
        with open(best[1], "rb") as fh:
            raw = fh.read()
        if raw[:2] == b"\xff\xd8":
            return raw
    return _jpeg(best[1], POSTER_WIDTH, 6)


def _sha256_file(path: str) -> str:
    """Compute hex SHA-256 of ``path`` in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_probe_info(input_path: str, probe_info: Any) -> Any:
    """Reuse already-available render metadata when complete, avoiding a redundant ffprobe."""
    from .models import VideoInfo

    if isinstance(probe_info, VideoInfo):
        return probe_info
    if not isinstance(probe_info, dict):
        return None
    duration = probe_info.get("duration")
    fps = probe_info.get("fps")
    codec = probe_info.get("codec") or probe_info.get("video_codec")
    width = probe_info.get("width")
    height = probe_info.get("height")
    if (width is None or height is None) and isinstance(probe_info.get("resolution"), str):
        parts = probe_info["resolution"].lower().split("x", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            width, height = int(parts[0]), int(parts[1])
    if (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and duration > 0
        and isinstance(width, int)
        and not isinstance(width, bool)
        and width > 0
        and isinstance(height, int)
        and not isinstance(height, bool)
        and height > 0
        and isinstance(fps, (int, float))
        and not isinstance(fps, bool)
        and fps > 0
        and isinstance(codec, str)
        and codec.strip()
    ):
        size_bytes = probe_info.get("size_bytes")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
            try:
                size_bytes = os.path.getsize(input_path)
            except OSError:
                size_bytes = None
        return VideoInfo(
            path=input_path,
            duration=float(duration),
            width=width,
            height=height,
            fps=float(fps),
            codec=codec.strip(),
            size_bytes=size_bytes,
        )
    return None


def _extract_sheet_and_frames(
    input_path: str,
    duration: float,
    frame_count: int,
    out_dir: str,
) -> tuple[str | None, list[str]]:
    """Extract contact sheet and poster-sized frames in a single FFmpeg pass."""
    from .ffmpeg_helpers import _run_ffmpeg

    sheet_path = os.path.join(out_dir, "review_sheet.jpg")
    frame_pattern = os.path.join(out_dir, "review_frame_%03d.jpg")

    if frame_count > 1 and duration > 0:
        cols = min(4, frame_count)
        rows = (frame_count + cols - 1) // cols
        tile_w = min(480, max(160, (MAX_IMAGE_WIDTH // cols) & ~1))
        tile_h = max(90, int(tile_w * 9 / 16) & ~1)
        interval = duration / (frame_count + 1)
        fps_expr = f"{1.0 / interval:.6f}"
        filter_complex = (
            f"[0:v]fps={fps_expr},split=2[for_sheet][for_frames];"
            f"[for_sheet]scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease,"
            f"pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2,tile={cols}x{rows},format=yuvj420p[sheet];"
            f"[for_frames]scale=w='min({POSTER_WIDTH},iw)':h=-2,format=yuvj420p[poster_frames]"
        )
        _run_ffmpeg(
            [
                "-ss",
                f"{interval:.3f}",
                "-i",
                input_path,
                "-filter_complex",
                filter_complex,
                "-map",
                "[sheet]",
                "-frames:v",
                "1",
                "-q:v",
                "6",
                "-y",
                sheet_path,
                "-map",
                "[poster_frames]",
                "-frames:v",
                str(frame_count),
                "-q:v",
                "6",
                "-y",
                frame_pattern,
            ]
        )
    else:
        single_frame = os.path.join(out_dir, "review_frame_001.jpg")
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-frames:v",
                "1",
                "-vf",
                f"scale=w='min({POSTER_WIDTH},iw)':h=-2,format=yuvj420p",
                "-q:v",
                "6",
                "-y",
                single_frame,
            ]
        )
        sheet_path = single_frame

    frames = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith("review_frame_") and name.endswith(".jpg")
    )
    if not frames:
        fallback = os.path.join(out_dir, "review_frame_001.jpg")
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-frames:v",
                "1",
                "-vf",
                f"scale=w='min({POSTER_WIDTH},iw)':h=-2,format=yuvj420p",
                "-q:v",
                "6",
                "-y",
                fallback,
            ]
        )
        if os.path.isfile(fallback) and os.path.getsize(fallback) > 0:
            frames = [fallback]
    sheet = (
        sheet_path
        if os.path.isfile(sheet_path) and os.path.getsize(sheet_path) > 0
        else (frames[0] if frames else None)
    )
    return sheet, frames


def _preview_bytes(input_path: str, duration: float, budget: int) -> bytes | None:
    """Encode a silent low-res H.264 preview that fits in ``budget`` bytes, or None if the cut is too long."""
    from .ffmpeg_helpers import _run_ffmpeg_bytes

    if duration <= 0 or budget <= 0:
        return None
    bitrate = min(MAX_PREVIEW_BITRATE, int(budget * 8 * 0.85 / duration))
    for _attempt in range(2):
        if bitrate < MIN_PREVIEW_BITRATE:
            return None
        width = 480 if bitrate >= 150_000 else 320
        data = _run_ffmpeg_bytes(
            [
                "-i", input_path, "-an",
                "-vf", f"fps=12,scale='min({width},iw)':-2",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-b:v", str(bitrate), "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", "pipe:1",
            ]
        )  # fmt: skip
        if len(data) <= budget:
            return data
        bitrate = int(bitrate * 0.6)
    return None


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


def final_export_path(input_path: str) -> str:
    """Where Approve & export asks the agent to write the delivered cut: ``<stem>-final.mp4``."""
    return f"{os.path.splitext(input_path)[0]}-final.mp4"


def write_review_card(
    input_path: str,
    output_path: str | None = None,
    frame_count: int = 6,
    *,
    probe_info: Any = None,
) -> dict[str, Any]:
    """Write ``<stem>_review_card.html`` (contact sheet + facts + buttons) for chat review."""
    from .engine_probe import probe
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
    elif any(ch in output_path for ch in ('"', "}", "\r", "\n")):
        raise MCPVideoError(
            "Review card output_path cannot contain directive-breaking characters",
            error_type="validation_error",
            code="invalid_parameter",
        )

    info = _coerce_probe_info(input_path, probe_info) or probe(input_path)
    input_sha256 = _sha256_file(input_path)
    with tempfile.TemporaryDirectory(prefix="kinocut_review_card_") as tmp:
        sheet, frames = _extract_sheet_and_frames(input_path, info.duration, frame_count, tmp)
        if sheet is None:
            raise MCPVideoError(
                "Could not extract any frames for the review card",
                error_type="processing_error",
                code="no_frames",
            )
        sheet_data, sheet_mime = _sheet_bytes(sheet, SHEET_BYTES_WITH_PLAYER)
        poster = _poster_bytes(frames, preencoded_jpeg=True)

    name = os.path.basename(input_path)
    facts = {
        "Duration": _format_duration(info.duration),
        "Resolution": info.resolution,
        "FPS": f"{info.fps:g}",
        "Codec": info.codec,
        "Size": _format_size(info.size_bytes),
        "SHA-256": input_sha256[:16],
    }
    final_path = final_export_path(input_path)
    actions = [
        (
            "Approve & export",
            f"Approve this cut: {input_path} (sha256:{input_sha256}). "
            f"Run video_release_checkpoint on it; "
            f"if it passes, video_export it to {final_path}.",
        ),
        ("Dig in", f"Show me more detail on {input_path}"),
        ("Try another range", f"Try a different range of {input_path}"),
    ]
    card = {
        "title": name,
        "facts": facts,
        "images": [(f"Contact sheet of {name}", sheet_data, sheet_mime)],
        "actions": actions,
        "input_sha256": input_sha256,
    }
    shell = render_review_card(**card)
    poster_b64 = len(base64.b64encode(poster)) if poster else 0
    room = MAX_CARD_BYTES - len(shell.encode("utf-8")) - poster_b64 - 400
    video = _preview_bytes(input_path, info.duration, room * 3 // 4)
    if video is None:
        facts["Preview"] = "too long to play here; open the file to watch it"
    document = render_review_card(**card, video=video, poster=poster)
    with _atomic_artifact(output_path) as staged, _open_staged_writer(staged) as stream:
        stream.write(document.encode("utf-8"))
    return {
        "success": True,
        "operation": "review_card",
        "output_path": output_path,
        "preview_directive": f'::preview{{file="{output_path}"}}',
        "input_sha256": input_sha256,
        "approval_digest": f"sha256:{input_sha256}",
        "frame_count": len(frames),
        "duration": info.duration,
        "resolution": info.resolution,
        "size_bytes": len(document.encode("utf-8")),
        "plays_inline": video is not None,
    }


def attach_review_card(result: dict[str, Any], review: bool) -> dict[str, Any]:
    """Add a review card for the rendered output to a successful media-writing result.

    The edit already succeeded, so a card that cannot be made is reported
    beside the result rather than failing it.
    """
    output_path = result.get("output_path")
    if not review or not result.get("success") or not output_path:
        return result
    try:
        card = write_review_card(output_path, probe_info=result)
    except MCPVideoError as exc:
        result["review_card"] = {"created": False, "error": exc.to_dict()}
        return result
    except OSError as exc:
        err = MCPVideoError(
            f"Could not write review card: {exception_kind(exc)}",
            error_type="processing_error",
            code="review_card_io_error",
        )
        result["review_card"] = {"created": False, "error": err.to_dict()}
        return result
    result["review_card"] = {
        "created": True,
        "output_path": card["output_path"],
        "input_sha256": card["input_sha256"],
    }
    result["preview_directive"] = card["preview_directive"]
    return result
