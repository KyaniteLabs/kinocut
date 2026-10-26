"""Shared test fixtures for Kinocut (formerly mcp-video) tests."""

import os
import shutil
import subprocess
import hashlib
from datetime import UTC, datetime

import pytest

from tests.rescue_fixtures import make_rescue_fixture
from mcp_video.rescue.models import (
    RescueEstimate,
    RescuePlan,
    SourceIdentity,
    canonical_payload,
)


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.fixture
def overwrite_consent():
    """Explicit consent for tests of replacement transactions after admission."""
    from kinocut.output_policy import output_operation

    with output_operation(overwrite=True):
        yield


def has_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def has_node() -> bool:
    """Check if Node.js is available on PATH."""
    return shutil.which("node") is not None


def has_npx() -> bool:
    """Check if npx is available on PATH."""
    return shutil.which("npx") is not None


@pytest.fixture
def rescue_fixture(tmp_path) -> str:
    """Create the canonical deterministic rescue E2E source."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")
    return str(make_rescue_fixture(tmp_path))


@pytest.fixture
def rescue_plan() -> RescuePlan:
    """Return a minimal, hashed rescue v1 plan for additive contract tests."""
    plan = RescuePlan(
        workspace_root=".",
        output_root="rescue-output",
        source=SourceIdentity(
            path="source.mp4",
            sha256="sha256:" + "1" * 64,
            size_bytes=1,
            streams=[],
        ),
        estimate=RescueEstimate(seconds=0.0, hardware={}, confidence="high"),
        capabilities={"local_only": True},
        created_at=datetime.now(UTC),
        observed_planning_seconds=0.0,
    )
    digest = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    return plan.model_copy(update={"plan_sha256": digest})


@pytest.fixture(scope="session")
def _sample_video_source(tmp_path_factory) -> str:
    """Create a 3-second test video with a color bar pattern."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    video_path = str(tmp_path_factory.mktemp("videos") / "test_video.mp4")

    # Generate a test video: 3 seconds, 640x480, color bars + sine audio
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptehdbars=size=640x480:duration=3:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            video_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(video_path):
        pytest.skip("Could not generate test video")

    return video_path


@pytest.fixture
def sample_video(_sample_video_source, tmp_path) -> str:
    """Isolate edits and derived filenames while reusing the encoded fixture."""
    target = tmp_path / "test_video.mp4"
    shutil.copyfile(_sample_video_source, target)
    return str(target)


@pytest.fixture(scope="session")
def _sample_audio_source(tmp_path_factory) -> str:
    """Create a 5-second test audio file."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    audio_path = str(tmp_path_factory.mktemp("audio") / "test_audio.mp3")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=5",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            audio_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(audio_path):
        pytest.skip("Could not generate test audio")

    return audio_path


@pytest.fixture(scope="session")
def _sample_audio_wav_source(tmp_path_factory) -> str:
    """Create a 5-second audio-only WAV file (no video stream).

    Regression fixture for issue #7: a valid audio-only input must not be
    probed as if it were a video, which previously raised a misleading
    "No video stream found" guardrail warning.
    """
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    audio_path = str(tmp_path_factory.mktemp("audio") / "test_audio.wav")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=5",
            "-c:a",
            "pcm_s16le",
            audio_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(audio_path):
        pytest.skip("Could not generate test audio WAV")

    return audio_path


@pytest.fixture(scope="session")
def _sample_srt_source(tmp_path_factory) -> str:
    """Create a sample SRT subtitle file."""
    srt_dir = tmp_path_factory.mktemp("subs")
    srt_path = srt_dir / "test.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello World\n\n2\n00:00:02,000 --> 00:00:04,000\nThis is a test\n"
    )
    return str(srt_path)


@pytest.fixture(scope="session")
def _sample_vtt_source(tmp_path_factory) -> str:
    """Create a sample WebVTT subtitle file."""
    vtt_dir = tmp_path_factory.mktemp("subs")
    vtt_path = vtt_dir / "test.vtt"
    vtt_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello World\n\n00:00:02.000 --> 00:00:04.000\nThis is a test\n"
    )
    return str(vtt_path)


@pytest.fixture(scope="session")
def _sample_watermark_png_source(tmp_path_factory) -> str:
    """Create a PNG image with transparency for watermark tests."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    img_dir = tmp_path_factory.mktemp("images")
    img_path = str(img_dir / "watermark.png")

    # Generate a 100x100 semi-transparent red square
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red@0.5:s=100x100:d=0.1",
            "-frames:v",
            "1",
            img_path,
        ],
        capture_output=True,
        timeout=15,
    )

    if not os.path.isfile(img_path):
        pytest.skip("Could not generate watermark image")

    return img_path


@pytest.fixture(scope="session")
def _sample_video_webm_source(tmp_path_factory) -> str:
    """Create a 2-second test video in WebM format."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    video_path = str(tmp_path_factory.mktemp("videos") / "test_video.webm")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptehdbars=size=640x480:duration=2:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "35",
            "-c:a",
            "libopus",
            "-shortest",
            video_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(video_path):
        pytest.skip("Could not generate WebM test video")

    return video_path


@pytest.fixture(scope="session")
def _sample_video_no_audio_source(tmp_path_factory) -> str:
    """Create a 2-second test video without audio track."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    video_path = str(tmp_path_factory.mktemp("videos") / "test_video_no_audio.mp4")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptehdbars=size=640x480:duration=2:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-an",
            video_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(video_path):
        pytest.skip("Could not generate video without audio")

    return video_path


@pytest.fixture(scope="session")
def _sample_video_2_source(tmp_path_factory) -> str:
    """Create a 3-second test video with different resolution for compositing tests."""
    if not has_ffmpeg():
        pytest.skip("FFmpeg not installed")

    video_path = str(tmp_path_factory.mktemp("videos") / "test_video_2.mp4")

    # Generate a test video: 3 seconds, 320x240, solid blue + sine audio
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=320x240:duration=3:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            video_path,
        ],
        capture_output=True,
        timeout=30,
    )

    if not os.path.isfile(video_path):
        pytest.skip("Could not generate second test video")

    return video_path


@pytest.fixture
def sample_audio(_sample_audio_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_audio_source)
    shutil.copyfile(_sample_audio_source, target)
    return str(target)


@pytest.fixture
def sample_audio_wav(_sample_audio_wav_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_audio_wav_source)
    shutil.copyfile(_sample_audio_wav_source, target)
    return str(target)


@pytest.fixture
def sample_srt(_sample_srt_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_srt_source)
    shutil.copyfile(_sample_srt_source, target)
    return str(target)


@pytest.fixture
def sample_vtt(_sample_vtt_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_vtt_source)
    shutil.copyfile(_sample_vtt_source, target)
    return str(target)


@pytest.fixture
def sample_watermark_png(_sample_watermark_png_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_watermark_png_source)
    shutil.copyfile(_sample_watermark_png_source, target)
    return str(target)


@pytest.fixture
def sample_video_webm(_sample_video_webm_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_video_webm_source)
    shutil.copyfile(_sample_video_webm_source, target)
    return str(target)


@pytest.fixture
def sample_video_no_audio(_sample_video_no_audio_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_video_no_audio_source)
    shutil.copyfile(_sample_video_no_audio_source, target)
    return str(target)


@pytest.fixture
def sample_video_2(_sample_video_2_source, tmp_path) -> str:
    target = tmp_path / os.path.basename(_sample_video_2_source)
    shutil.copyfile(_sample_video_2_source, target)
    return str(target)


@pytest.fixture
def sample_hyperframes_project(tmp_path):
    """Create a minimal Hyperframes project directory with required files.

    This creates a temp directory containing:
      - index.html (entry point with data-composition-id)
      - package.json (optional, for validation)

    Returns the project directory as a string.
    """
    project_dir = tmp_path / "hyperframes-project"
    project_dir.mkdir()

    # index.html — Hyperframes entry point
    (project_dir / "index.html").write_text(
        "<!DOCTYPE html>\n"
        "<html>\n"
        "  <head><title>Test</title></head>\n"
        "  <body>\n"
        '    <div data-composition-id="test-comp"></div>\n'
        "  </body>\n"
        "</html>\n"
    )

    # package.json (optional but useful for validation)
    (project_dir / "package.json").write_text('{"name": "test-hyperframes-project", "version": "1.0.0"}')

    return str(project_dir)


@pytest.fixture
def full_tool_surface():
    """Expand the MCP tool surface to the full catalog for the marked tests.

    Tests marked with this fixture exercise hidden (non-core) tools through
    the MCP layer: parity, argument-contract, and count tests written against
    the full development catalog. Both the in-process registration and the
    ``KINOCUT_TOOLS`` environment (inherited by stdio subprocess servers) are
    switched to ``all``, then restored exactly on teardown.
    """
    from kinocut import tool_registry

    previous_raw = os.environ.get("KINOCUT_TOOLS")
    os.environ["KINOCUT_TOOLS"] = "all"
    tool_registry.configure_tool_surface("all")
    try:
        yield
    finally:
        if previous_raw is None:
            os.environ.pop("KINOCUT_TOOLS", None)
        else:
            os.environ["KINOCUT_TOOLS"] = previous_raw
        tool_registry.configure_tool_surface(previous_raw)


@pytest.fixture
def default_tool_surface():
    """Re-assert the curated default surface before diet-count tests.

    Importing a ``server_tools_*`` module directly registers its tools on the
    shared FastMCP instance (module-level ``@mcp.tool()`` decorators). Without
    re-applying the active surface, later tests in the same process observe
    that pollution and the curated-default invariants drift.
    """
    from kinocut import tool_registry

    tool_registry.apply_tool_surface()
    yield
