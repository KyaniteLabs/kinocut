"""Prepare local artifacts and Hermes Gadget requests; never serve or send them."""

import json
import math
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from .audio_bed_validation import reject_output_alias
from .bounded_process import run_bounded
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path
from .limits import DEFAULT_FFMPEG_TIMEOUT
from .publication import atomic_output, output_operation

_LOCAL_INPUT = ["-protocol_whitelist", "file,pipe"]


def _run(command: list[str]) -> str:
    result = run_bounded(command, timeout=DEFAULT_FFMPEG_TIMEOUT)
    if result.returncode:
        raise MCPVideoError("FFmpeg or ffprobe could not prepare TV review media", code="tv_preview_failed")
    return result.stdout


def _probe(path: Path) -> tuple[int, float]:
    raw = _run(
        [
            "ffprobe",
            "-v",
            "error",
            *_LOCAL_INPUT,
            "-select_streams",
            "V:0",
            "-show_entries",
            "stream=width,height:stream_side_data=rotation:format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        info = json.loads(raw)
        stream = info["streams"][0]
        rotation = next((item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item), 0)
        height = int(stream["width" if rotation % 180 else "height"])
        duration = float(info["format"]["duration"])
        if height <= 0 or not math.isfinite(duration) or duration <= 0:
            raise ValueError
    except (IndexError, KeyError, TypeError, ValueError):
        raise MCPVideoError(
            "TV review requires a video stream with a positive duration", code="invalid_tv_media"
        ) from None
    return height, duration


def _write_proxy(source: Path, target: Path, height: int, limit: int) -> Path:
    reject_output_alias(str(target), (str(source),))
    with atomic_output(str(target)) as stage:
        if height <= limit:
            shutil.copyfile(source, stage)
        else:
            _run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    *_LOCAL_INPUT,
                    "-i",
                    str(source),
                    "-map",
                    "0:V:0",
                    "-map",
                    "0:a:0?",
                    "-vf",
                    f"scale=-2:{limit - limit % 2},setsar=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    "-f",
                    "mp4",
                    stage,
                ]
            )
            if _probe(Path(stage))[0] > limit:
                raise MCPVideoError("TV proxy exceeds the requested height", code="invalid_tv_media")
    return target


def _write_sheet(proxy: Path, target: Path, duration: float) -> Path:
    sample_rate = 6 / duration
    filters = (
        f"fps={sample_rate:.10g}:round=up,scale=320:180:force_original_aspect_ratio=decrease,"
        "pad=320:180:(ow-iw)/2:(oh-ih)/2,tile=3x2"
    )
    with atomic_output(str(target)) as stage:
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                *_LOCAL_INPUT,
                "-i",
                str(proxy),
                "-map",
                "0:V:0",
                "-vf",
                filters,
                "-frames:v",
                "1",
                "-threads",
                "1",
                "-update",
                "1",
                stage,
            ]
        )
        if not Path(stage).stat().st_size:
            raise MCPVideoError("TV contact sheet produced no frames", code="tv_preview_failed")
    return target


def prepare_tv_review_payload(
    video_path,
    *,
    qc_sheet_path=None,
    proxy_output_path=None,
    caption=None,
    max_height=1080,
) -> dict:
    """Build review artifacts and drafts; bind hosted URLs before sending to a TV."""
    if type(max_height) is not int or not 2 <= max_height <= 1080:
        raise MCPVideoError("TV preview height must be an integer from 2 to 1080", code="invalid_parameter")
    with output_operation():
        source = Path(_validate_input_path(str(video_path))).absolute()
        height, duration = _probe(source)
        target = Path(proxy_output_path).absolute() if proxy_output_path else None
        if height > max_height and target is None:
            target = source.with_name(f"{source.stem}.tv-preview.mp4")
        sheet = (
            Path(_validate_input_path(str(qc_sheet_path))).absolute()
            if qc_sheet_path
            else source.with_name(f"{source.stem}.tv-qc.jpg")
        )
        if target:
            reject_output_alias(str(target), (str(source), str(sheet)))
            if height > max_height and target.suffix.lower() != ".mp4":
                raise MCPVideoError("A transcoded TV proxy requires an .mp4 output path", code="invalid_parameter")
        proxy = _write_proxy(source, target, height, max_height) if target else source
        if not qc_sheet_path:
            sheet = _write_sheet(proxy, sheet, duration)
    title = caption or f"Kinocut review: {source.name}"
    return {
        "proxy_path": str(proxy),
        "qc_sheet_path": str(sheet),
        "messages": [_show_media(None, "video", title), _show_media(None, "image", f"{title} — QC contact sheet")],
        "decision_card": {"title": "Export this cut?", "options": ["Approve & export", "Try another range"]},
    }


def _show_media(url: str | None, kind: str, caption: str) -> dict:
    return {"action": "ui.show_media", "args": {"url": url, "kind": kind, "caption": caption}}


def tv_review_messages(payload: dict, *, proxy_url: str, qc_sheet_url: str) -> list[dict]:
    """Bind operator-provided URLs to a prepared review; performs no network I/O."""
    messages = []
    for draft, url in zip(payload["messages"], (proxy_url, qc_sheet_url), strict=True):
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or any(char.isspace() or ord(char) < 32 for char in url)
                or "\\" in url
                or parsed.port == 0
            ):
                raise ValueError
        except ValueError:
            raise MCPVideoError(
                "TV review needs a TV-reachable HTTP(S) media URL", code="invalid_tv_media_url"
            ) from None
        messages.append(_show_media(url, draft["args"]["kind"], draft["args"]["caption"]))
    return messages
