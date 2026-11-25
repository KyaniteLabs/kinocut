"""Prepare local artifacts and Hermes Gadget requests; never serve or send them."""

import contextlib
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

from .audio_bed_validation import reject_output_alias
from .data_dirs import crush_home
from .engine_runtime_utils import _ffmpeg, _ffprobe
from .errors import MCPVideoError, ProcessingError
from .ffmpeg_helpers import _run_command, _validate_input_path
from .publication import atomic_output, open_staged_writer, output_operation

_LOCAL_INPUT = ["-protocol_whitelist", "file,pipe"]
_MAX_WIDTH = 1920
_TV_SAFE_PIX_FMTS = frozenset({"yuv420p", "yuvj420p"})
_REVIEW_TTL_SECONDS = 3600.0
_MAX_PENDING_REVIEWS = 256
_REVIEW_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class _Video:
    width: int
    height: int
    sar: Fraction
    duration: float
    rotation: int = 0
    codec_name: str = "h264"
    pix_fmt: str = "yuv420p"
    is_mp4: bool = True
    audio_codecs: tuple[str, ...] = ()

    def fits(self, height_limit: int) -> bool:
        return (
            self.is_mp4
            and self.codec_name == "h264"
            and self.pix_fmt in _TV_SAFE_PIX_FMTS
            and (self.rotation % 360) == 0
            and all(codec == "aac" for codec in self.audio_codecs)
            and self.sar == 1
            and self.width <= _MAX_WIDTH
            and self.height <= height_limit
            and not (self.width % 2 or self.height % 2)
        )

    def fitted_size(self, height_limit: int) -> tuple[int, int]:
        display_width = self.width * self.sar
        scale = min(1, Fraction(_MAX_WIDTH, display_width), Fraction(height_limit - height_limit % 2, self.height))
        return max(2, 2 * round(display_width * scale / 2)), max(2, 2 * round(self.height * scale / 2))


@dataclass(frozen=True)
class _Artifact:
    path: Path
    sha256: str

    @classmethod
    def capture(cls, path: Path) -> "_Artifact":
        try:
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = path.stat()
                if not os.path.samestat(before, after) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise MCPVideoError("TV review artifact changed during verification", code="stale_tv_review")
                return cls(path, digest)
        except OSError:
            raise MCPVideoError("Could not read the TV review artifact", code="stale_tv_review") from None

    def verify(self) -> None:
        if self != self.capture(self.path):
            raise MCPVideoError("TV review artifact changed; prepare a new review", code="stale_tv_review")


_pending_reviews: dict[str, tuple[_Artifact, _Artifact, _Artifact, float]] = {}
_review_lock = Lock()


def _review_store_dir() -> Path:
    return crush_home() / "tv_reviews"


def _review_file(review_id: str) -> Path | None:
    if not isinstance(review_id, str) or not _REVIEW_ID_RE.fullmatch(review_id):
        return None
    return _review_store_dir() / f"{review_id}.json"


def _persist_review(review_id: str, artifacts: tuple[_Artifact, _Artifact, _Artifact], expires_at: float) -> None:
    target = _review_file(review_id)
    if target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "review_id": review_id,
                "expires_at": expires_at,
                "artifacts": [{"path": str(a.path), "sha256": a.sha256} for a in artifacts],
            },
            separators=(",", ":"),
        )
        tmp = target.parent / f".{review_id}.{secrets.token_hex(4)}.tmp"
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, target)
    except OSError:
        pass


def _delete_persisted_review(review_id: str) -> None:
    target = _review_file(review_id)
    if target is not None:
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)


def _load_and_remove_persisted_review(review_id: str) -> tuple[tuple[_Artifact, _Artifact, _Artifact], float] | None:
    target = _review_file(review_id)
    if target is None:
        return None
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return None
    with contextlib.suppress(OSError):
        target.unlink(missing_ok=True)
    try:
        data = json.loads(raw)
        if data.get("review_id") != review_id:
            return None
        expires_at = float(data["expires_at"])
        if not math.isfinite(expires_at):
            return None
        items = data["artifacts"]
        if not isinstance(items, list) or len(items) != 3:
            return None
        parsed = tuple(_Artifact(Path(str(item["path"])), str(item["sha256"])) for item in items)
        return (parsed[0], parsed[1], parsed[2]), expires_at
    except (KeyError, TypeError, ValueError):
        return None


def _prune_pending_reviews_locked(now: float) -> None:
    expired = [rid for rid, entry in _pending_reviews.items() if entry[3] <= now]
    for rid in expired:
        _pending_reviews.pop(rid, None)
        _delete_persisted_review(rid)
    while len(_pending_reviews) >= _MAX_PENDING_REVIEWS:
        oldest = next(iter(_pending_reviews))
        _pending_reviews.pop(oldest, None)
        _delete_persisted_review(oldest)


def _run(command: list[str]) -> str:
    try:
        return _run_command(command).stdout
    except ProcessingError:
        raise MCPVideoError("FFmpeg or ffprobe could not prepare TV review media", code="tv_preview_failed") from None


def _encode(args: list[str]) -> None:
    if os.name != "posix":
        raise MCPVideoError("Descriptor-backed TV encoding is unavailable", code="unsafe_path")
    _run([_ffmpeg(), "-v", "error", "-nostdin", "-y", *_LOCAL_INPUT, *args])


def _probe(path: Path) -> _Video:
    raw = _run(
        [
            _ffprobe(),
            "-v",
            "error",
            *_LOCAL_INPUT,
            "-show_entries",
            "stream=codec_type,codec_name,width,height,sample_aspect_ratio,pix_fmt:stream_disposition=attached_pic:stream_side_data=rotation:format=duration,format_name",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        info = json.loads(raw)
        streams = info.get("streams", [])
        video_streams = [
            s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ]
        stream = video_streams[0]
        rotation = next((item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item), 0)
        rotation = int(rotation)
        width, height = int(stream["width"]), int(stream["height"])
        raw_sar = stream.get("sample_aspect_ratio")
        sar = Fraction(raw_sar.replace(":", "/")) if raw_sar not in (None, "N/A", "0:1") else Fraction(1)
        if rotation % 90 or width <= 0 or height <= 0 or sar <= 0:
            raise ValueError
        if rotation % 180:
            width, height, sar = height, width, 1 / sar
        fmt = info["format"]
        duration = float(fmt["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        codec_name = str(stream.get("codec_name") or "").lower()
        pix_fmt = str(stream.get("pix_fmt") or "").lower()
        fmt_tokens = {tok.strip().lower() for tok in str(fmt.get("format_name") or "").split(",") if tok.strip()}
        is_mp4 = "mp4" in fmt_tokens and path.suffix.lower() == ".mp4"
        audio_codecs = tuple(str(s.get("codec_name") or "").lower() for s in streams if s.get("codec_type") == "audio")
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
        raise MCPVideoError(
            "TV review requires a video stream with valid display geometry and duration", code="invalid_tv_media"
        ) from None
    return _Video(
        width,
        height,
        sar,
        duration,
        rotation=rotation,
        codec_name=codec_name,
        pix_fmt=pix_fmt,
        is_mp4=is_mp4,
        audio_codecs=audio_codecs,
    )


def _write_proxy(source: Path, target: Path, video: _Video, limit: int) -> Path:
    reject_output_alias(str(target), (str(source),))
    with atomic_output(str(target)) as stage:
        if video.fits(limit):
            with source.open("rb") as reader, open_staged_writer(stage) as writer:
                shutil.copyfileobj(reader, writer)
        else:
            width, height = video.fitted_size(limit)
            _encode(
                [
                    "-i",
                    str(source),
                    "-map",
                    "0:V:0",
                    "-map",
                    "0:a?",
                    "-vf",
                    f"scale={width}:{height},setsar=1",
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
            if not _probe(Path(stage)).fits(limit):
                raise MCPVideoError("TV proxy exceeds the display bounds", code="invalid_tv_media")
    return target


def _write_sheet(proxy: Path, target: Path, duration: float) -> Path:
    sample_rate = 6 / duration
    filters = (
        f"fps={sample_rate:.10g}:round=up,scale=320:180:force_original_aspect_ratio=decrease,"
        "pad=320:180:(ow-iw)/2:(oh-ih)/2,tile=3x2"
    )
    with atomic_output(str(target)) as stage:
        _encode(
            [
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
                "-c:v",
                "mjpeg",
                "-f",
                "image2pipe",
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
    review_id = uuid4().hex
    with output_operation():
        source = Path(_validate_input_path(str(video_path))).absolute()
        cut = _Artifact.capture(source)
        video = _probe(source)
        target = Path(proxy_output_path).absolute() if proxy_output_path else None
        if not video.fits(max_height) and target is None:
            target = source.with_name(f"{source.stem}.{review_id}.tv-preview.mp4")
        sheet = (
            Path(_validate_input_path(str(qc_sheet_path))).absolute()
            if qc_sheet_path
            else source.with_name(f"{source.stem}.{review_id}.tv-qc.jpg")
        )
        if target:
            reject_output_alias(str(target), (str(source), str(sheet)))
            if not video.fits(max_height) and target.suffix.lower() != ".mp4":
                raise MCPVideoError("A transcoded TV proxy requires an .mp4 output path", code="invalid_parameter")
        proxy = _write_proxy(source, target, video, max_height) if target else source
        proxy_artifact = _Artifact.capture(proxy) if target else cut
        if not qc_sheet_path:
            sheet = _write_sheet(proxy, sheet, video.duration)
        cut.verify()
        if target:
            proxy_artifact.verify()
        sheet_artifact = _Artifact.capture(sheet)
    now = time.time()
    expires_at = now + _REVIEW_TTL_SECONDS
    artifacts = (cut, proxy_artifact, sheet_artifact)
    with _review_lock:
        _prune_pending_reviews_locked(now)
        _pending_reviews[review_id] = (cut, proxy_artifact, sheet_artifact, expires_at)
        _persist_review(review_id, artifacts, expires_at)
    identity = f"review {review_id} / SHA-256 {cut.sha256[:12]}"
    title = f"{caption or f'Kinocut review: {source.name}'} — {identity}"
    return {
        "review_id": review_id,
        "artifact_path": str(cut.path),
        "artifact_sha256": cut.sha256,
        "proxy_path": str(proxy),
        "qc_sheet_path": str(sheet),
        "messages": [_show_media(None, "video", title), _show_media(None, "image", f"{title} — QC contact sheet")],
        "decision_card": {
            "title": f"Export this cut? — {identity}",
            "options": ["Approve & export", "Try another range"],
        },
    }


def consume_tv_review_decision(review_id: str, decision: str) -> Path | None:
    """Consume a paired-TV decision; return the verified cut only for approval."""
    if decision not in ("APPROVE", "REJECT"):
        raise MCPVideoError("TV decision must be APPROVE or REJECT", code="invalid_tv_decision")
    now = time.time()
    with _review_lock:
        entry = _pending_reviews.pop(review_id, None)
        if entry is not None:
            _delete_persisted_review(review_id)
            artifacts: tuple[_Artifact, _Artifact, _Artifact] | None = (entry[0], entry[1], entry[2])
            expires_at = entry[3]
        else:
            persisted = _load_and_remove_persisted_review(review_id)
            if persisted is not None:
                artifacts, expires_at = persisted
            else:
                artifacts = None
                expires_at = 0.0
    if artifacts is None:
        raise MCPVideoError("TV review ID is unknown or already consumed", code="unknown_tv_review")
    if now > expires_at:
        raise MCPVideoError("TV review has expired; prepare a new review", code="expired_tv_review")
    if decision == "REJECT":
        return None
    for artifact in dict.fromkeys(reversed(artifacts)):
        artifact.verify()
    return artifacts[0].path


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
