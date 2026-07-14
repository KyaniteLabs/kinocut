"""Real-FFmpeg regressions for the governed one-shot audio-bed primitive.

Covers exact output-duration policy (keep_video), voice-aware ducking, looping
with crossfade, trimming, padding, fade-in/fade-out, loudness normalization,
deterministic receipts, privacy-safe identity, cancellation-safe temp output,
fail-closed custom errors, hostile parameter/path/privacy/tamper cases, and
module size constraints.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.contracts.audio_bed import AudioBedReceipt
from kinocut.engine_audio_bed import audio_bed
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _run_ffprobe_json
from kinocut.source_identity import immutable_verified_snapshot_available

pytestmark = [
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed"),
    pytest.mark.skipif(
        not immutable_verified_snapshot_available(),
        reason="immutable verified source snapshots are unavailable",
    ),
]


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, capture_output=True, timeout=60)


def _make_video(path, duration: float, *, with_audio: bool = True, freq: int = 440) -> str:
    args = ["-f", "lavfi", "-i", f"color=c=blue:s=320x240:r=24:d={duration}"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:d={duration}"]
    args += ["-shortest", "-pix_fmt", "yuv420p", str(path)]
    _ffmpeg(args)
    return str(path)


def _make_audio(path, duration: float, *, freq: int = 330) -> str:
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:d={duration}", str(path)])
    return str(path)


def _make_bed(path, duration: float, *, freq: int = 110) -> str:
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:d={duration}", str(path)])
    return str(path)


def _loudness(path: str) -> dict[str, str]:
    """Probe EBU R128 loudness values via ffmpeg's loudnorm filter metadata."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    stderr = result.stderr
    start = stderr.find("{")
    end = stderr.rfind("}") + 1
    if start < 0 or end <= 0:
        pytest.fail(f"Could not parse loudnorm JSON from stderr:\n{stderr[-500:]}")
    return json.loads(stderr[start:end])


def _has_audio_stream(path: str) -> bool:
    data = _run_ffprobe_json(path)
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def _has_video_stream(path: str) -> bool:
    data = _run_ffprobe_json(path)
    return any(s.get("codec_type") == "video" for s in data.get("streams", []))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio_bed")
    return {
        "video_5s": _make_video(d / "voice5.mp4", 5.0),
        "video_5s_silent": _make_video(d / "voice5s.mp4", 5.0, with_audio=False),
        "video_10s": _make_video(d / "voice10.mp4", 10.0),
        "audio_5s": _make_audio(d / "voice_aud5.wav", 5.0),
        "bed_3s": _make_bed(d / "bed3.wav", 3.0),
        "bed_5s": _make_bed(d / "bed5.wav", 5.0),
        "bed_12s": _make_bed(d / "bed12.wav", 12.0),
    }


# ---------------------------------------------------------------------------
# Duration policy: keep_video exact output duration
# ---------------------------------------------------------------------------


def test_output_matches_voice_duration_short_bed_looped(tmp_path, media):
    """Short bed looped to fill voice → output == voice duration."""
    out = tmp_path / "loop.mp4"
    result = audio_bed(media["video_5s"], media["bed_3s"], str(out), loop=True, loop_crossfade=0.5)
    assert abs(result["output_duration"] - 5.0) < 0.35


def test_output_matches_voice_duration_long_bed_trimmed(tmp_path, media):
    """Long bed trimmed to voice → output == voice duration."""
    out = tmp_path / "trim.mp4"
    result = audio_bed(media["video_5s"], media["bed_12s"], str(out))
    assert abs(result["output_duration"] - 5.0) < 0.35


def test_output_matches_voice_duration_equal_bed(tmp_path, media):
    """Equal bed → output == voice duration, no loop needed."""
    out = tmp_path / "equal.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert abs(result["output_duration"] - 5.0) < 0.35


def test_short_bed_loop_disabled_pads_to_voice(tmp_path, media):
    """Short bed, loop=False → padded with silence, output == voice duration."""
    out = tmp_path / "pad.mp4"
    result = audio_bed(media["video_5s"], media["bed_3s"], str(out), loop=False)
    assert abs(result["output_duration"] - 5.0) < 0.35


def test_10s_video_output_matches(tmp_path, media):
    """10s video with 3s bed → output == 10s."""
    out = tmp_path / "ten.mp4"
    result = audio_bed(media["video_10s"], media["bed_3s"], str(out), loop_crossfade=0.5)
    assert abs(result["output_duration"] - 10.0) < 0.35


# ---------------------------------------------------------------------------
# Audio preservation and ducking
# ---------------------------------------------------------------------------


def test_voice_audio_present_in_output(tmp_path, media):
    """Output has an audio stream when voice source has audio."""
    out = tmp_path / "ducked.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert _has_audio_stream(str(out))


def test_ducking_engaged_when_voice_has_audio(tmp_path, media):
    """Result reports ducking_engaged=True when voice source has audio."""
    out = tmp_path / "engaged.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert result["ducking_engaged"] is True


def test_ducking_skipped_when_no_voice_audio(tmp_path, media):
    """Voice-less source → no ducking, result reports ducking_engaged=False."""
    out = tmp_path / "noduck.mp4"
    result = audio_bed(media["video_5s_silent"], media["bed_5s"], str(out))
    assert result["ducking_engaged"] is False
    assert "ducking_skipped" in result["warnings"]
    assert abs(result["output_duration"] - 5.0) < 0.35
    assert _has_audio_stream(str(out))


def test_audio_only_voice_source_produces_audio_output(tmp_path, media):
    """Audio-only voice source → audio-only output with ducking."""
    out = tmp_path / "audonly.mp4"
    result = audio_bed(media["audio_5s"], media["bed_3s"], str(out), loop_crossfade=0.5)
    assert result["ducking_engaged"] is True
    assert _has_audio_stream(str(out))
    assert not _has_video_stream(str(out))
    assert abs(result["output_duration"] - 5.0) < 0.35


# ---------------------------------------------------------------------------
# Fade behavior
# ---------------------------------------------------------------------------


def test_fade_out_applied_to_bed(tmp_path, media):
    """Fade-out parameter is accepted and output still matches duration."""
    out = tmp_path / "fadeout.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out), fade_out=1.0)
    assert abs(result["output_duration"] - 5.0) < 0.35


def test_fade_in_applied_to_bed(tmp_path, media):
    """Fade-in parameter is accepted and output still matches duration."""
    out = tmp_path / "fadein.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out), fade_in=0.5)
    assert abs(result["output_duration"] - 5.0) < 0.35


# ---------------------------------------------------------------------------
# Loudness normalization
# ---------------------------------------------------------------------------


def test_output_normalized_to_target_lufs(tmp_path, media):
    """Output integrated loudness is near target_lufs."""
    out = tmp_path / "norm.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out), target_lufs=-20.0)
    loudness = _loudness(str(out))
    integrated = float(loudness.get("input_i", -999))
    assert abs(integrated - (-20.0)) < 3.5


# ---------------------------------------------------------------------------
# Receipt, hashes, privacy
# ---------------------------------------------------------------------------


def test_receipt_in_result_has_correct_structure(tmp_path, media):
    """Result includes a well-formed receipt dict."""
    out = tmp_path / "receipt.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    receipt = result["receipt"]
    assert receipt["schema_version"] == 1
    assert receipt["receipt_kind"] == "edit"
    assert receipt["operation"] == "audio_bed"
    assert len(receipt["inputs"]) == 2
    assert receipt["inputs"][0]["role"] == "voice_source"
    assert receipt["inputs"][1]["role"] == "music_bed"
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert receipt["ducking_engaged"] is True
    assert receipt["human_review_required"] is True


def test_save_receipt_writes_json_file(tmp_path, media):
    """save_receipt writes an atomic JSON receipt file."""
    out = tmp_path / "with_receipt.mp4"
    receipt_path = tmp_path / "receipt.json"
    audio_bed(media["video_5s"], media["bed_5s"], str(out), save_receipt=str(receipt_path))
    assert receipt_path.exists()
    data = json.loads(receipt_path.read_text())
    assert data["receipt_kind"] == "edit"
    assert data["operation"] == "audio_bed"


def test_receipt_content_hashes_match_file_bytes(tmp_path, media):
    """Input content_sha256 matches actual file sha256."""
    from kinocut.engine_audio_bed import _file_sha256

    out = tmp_path / "hash.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    receipt = result["receipt"]
    assert receipt["inputs"][0]["content_sha256"] == _file_sha256(media["video_5s"])
    assert receipt["inputs"][1]["content_sha256"] == _file_sha256(media["bed_5s"])
    assert receipt["output_content_sha256"] == _file_sha256(str(out))


def test_renderer_consumes_verified_snapshots_not_mutable_sources(tmp_path, media, monkeypatch):
    import kinocut.engine_audio_bed as engine

    original_run = engine._run_ffmpeg
    consumed_inputs: list[str] = []

    def capture_run(args, **kwargs):
        for index, value in enumerate(args[:-1]):
            if value == "-i":
                consumed_inputs.append(args[index + 1])
        return original_run(args, **kwargs)

    monkeypatch.setattr(engine, "_run_ffmpeg", capture_run)
    out = tmp_path / "verified-sources.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out))

    assert media["video_5s"] not in consumed_inputs
    assert media["bed_5s"] not in consumed_inputs


def test_receipt_hash_is_deterministic(tmp_path, media, tmp_path_factory):
    """Same inputs and parameters → same receipt_sha256."""
    d1 = tmp_path_factory.mktemp("det1")
    d2 = tmp_path_factory.mktemp("det2")
    out1 = d1 / "a.mp4"
    out2 = d2 / "a.mp4"
    r1 = audio_bed(media["video_5s"], media["bed_5s"], str(out1))
    r2 = audio_bed(media["video_5s"], media["bed_5s"], str(out2))
    assert r1["receipt"]["receipt_sha256"] == r2["receipt"]["receipt_sha256"]


def test_receipt_hash_binds_music_volume(tmp_path_factory, media):
    """Different render-affecting volume values must produce different intents."""
    d1 = tmp_path_factory.mktemp("volume1")
    d2 = tmp_path_factory.mktemp("volume2")
    r1 = audio_bed(media["video_5s"], media["bed_5s"], str(d1 / "a.mp4"), music_volume=0.5)
    r2 = audio_bed(media["video_5s"], media["bed_5s"], str(d2 / "a.mp4"), music_volume=1.0)
    assert r1["receipt"]["parameters"]["music_volume"] == 0.5
    assert r2["receipt"]["parameters"]["music_volume"] == 1.0
    assert r1["receipt"]["receipt_sha256"] != r2["receipt"]["receipt_sha256"]


def test_receipt_has_no_absolute_paths(tmp_path, media):
    """Receipt must never contain absolute source paths."""
    out = tmp_path / "privacy.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    receipt_json = json.dumps(result["receipt"])
    assert str(Path(media["video_5s"]).resolve()) not in receipt_json
    assert str(Path(media["bed_5s"]).resolve()) not in receipt_json
    assert "/home/" not in receipt_json
    assert "/tmp/" not in receipt_json


def test_receipt_display_names_are_basenames_only(tmp_path, media):
    """Display names must be safe basenames, not paths."""
    out = tmp_path / "dispname.mp4"
    result = audio_bed(media["video_5s"], media["bed_5s"], str(out))
    for inp in result["receipt"]["inputs"]:
        assert "/" not in inp["display_name"]
        assert "\\" not in inp["display_name"]


# ---------------------------------------------------------------------------
# Cancellation safety: no partial output on failure
# ---------------------------------------------------------------------------


def test_no_partial_output_on_render_failure(tmp_path, media, monkeypatch):
    """If the render fails, the output path must not exist."""
    import kinocut.engine_audio_bed as engine

    def failing_render(*args, **kwargs):
        raise ProcessingError("ffmpeg fake", 1, "simulated failure")

    monkeypatch.setattr(engine, "_guarded_render", failing_render)
    out = tmp_path / "cancelled.mp4"
    with pytest.raises(ProcessingError):
        audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert not out.exists()


def test_no_stale_temp_files_after_success(tmp_path, media):
    """No temp files remain after a successful render."""
    out = tmp_path / "clean.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out))
    stale = list(tmp_path.glob(".audio-bed.*"))
    assert not stale


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_same_inputs_produce_same_duration_and_receipt(tmp_path, media, tmp_path_factory):
    """Running twice with same params and same output basename yields same receipt hash."""
    d1 = tmp_path_factory.mktemp("idem1")
    d2 = tmp_path_factory.mktemp("idem2")
    out1 = d1 / "output.mp4"
    out2 = d2 / "output.mp4"
    r1 = audio_bed(media["video_5s"], media["bed_5s"], str(out1))
    r2 = audio_bed(media["video_5s"], media["bed_5s"], str(out2))
    assert abs(r1["output_duration"] - r2["output_duration"]) < 0.1
    assert r1["receipt"]["receipt_sha256"] == r2["receipt"]["receipt_sha256"]
    assert r1["receipt"]["parameters"] == r2["receipt"]["parameters"]


# ---------------------------------------------------------------------------
# Hostile parameter validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,error_code",
    [
        ({"target_lufs": 5.0}, "invalid_target_lufs"),
        ({"target_lufs": -100.0}, "invalid_target_lufs"),
        ({"duck_threshold": 0.0}, "invalid_duck_threshold"),
        ({"duck_threshold": 2.0}, "invalid_duck_threshold"),
        ({"duck_ratio": 0.5}, "invalid_duck_ratio"),
        ({"duck_ratio": 30.0}, "invalid_duck_ratio"),
        ({"fade_out": -1.0}, "invalid_fade_out"),
        ({"fade_out": 100.0}, "invalid_fade_out"),
        ({"music_volume": 3.0}, "invalid_music_volume"),
        ({"music_volume": -0.5}, "invalid_music_volume"),
        ({"duration_tolerance": float("nan")}, "invalid_duration_tolerance"),
        ({"duration_tolerance": -0.1}, "invalid_duration_tolerance"),
        ({"loop": "false"}, "invalid_loop"),
        ({"loop": 1}, "invalid_loop"),
    ],
)
def test_hostile_parameters_rejected(tmp_path, media, kwargs, error_code):
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_5s"], str(out), **kwargs)
    assert excinfo.value.code == error_code


def test_loop_crossfade_exceeds_bed_rejected(tmp_path, media):
    """loop_crossfade >= bed_duration is rejected."""
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_3s"], str(out), loop_crossfade=5.0)
    assert excinfo.value.code == "invalid_loop_crossfade"


def test_non_numeric_parameter_rejected(tmp_path, media):
    """String values for numeric parameters are rejected."""
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError):
        audio_bed(media["video_5s"], media["bed_5s"], str(out), target_lufs="not_a_number")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Hostile path validation
# ---------------------------------------------------------------------------


def test_output_aliasing_input_rejected(tmp_path, media, monkeypatch):
    """Output path == voice source must be rejected before render."""
    import kinocut.engine_audio_bed as engine

    rendered = False

    def unexpected(*args, **kwargs):
        nonlocal rendered
        rendered = True

    monkeypatch.setattr(engine, "_guarded_render", unexpected)
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_5s"], media["video_5s"])
    assert excinfo.value.code == "invalid_output_path"
    assert not rendered


def test_traversal_output_path_rejected(tmp_path, media):
    """Directory traversal in output path is rejected."""
    out = str(tmp_path / "../../etc/passwd")
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_5s"], out)
    assert excinfo.value.code in ("unsafe_path", "invalid_output_path")


def test_missing_input_rejected(tmp_path, media):
    """Missing input file raises InputFileError-derived MCPVideoError."""
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError):
        audio_bed(str(tmp_path / "nonexistent.mp4"), media["bed_5s"], str(out))


def test_bed_without_audio_rejected(tmp_path):
    """Music bed with no audio stream is rejected."""
    video = _make_video(tmp_path / "v.mp4", 3.0)
    # Create a video-only file as "bed" (no audio stream)
    bed = tmp_path / "video_only.mp4"
    _ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=160x90:r=15:d=3.0", "-pix_fmt", "yuv420p", str(bed)])
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(video, str(bed), str(out))
    assert excinfo.value.code == "missing_audio_stream"


# ---------------------------------------------------------------------------
# Fail-closed: sidechain unavailable
# ---------------------------------------------------------------------------


def test_sidechain_unavailable_fails_closed(tmp_path, media, monkeypatch):
    """When sidechaincompress is unavailable, the engine fails closed."""
    import kinocut.engine_audio_bed as engine

    monkeypatch.setattr(engine, "_check_filter_available", lambda name: False)
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert excinfo.value.code == "missing_filter_sidechaincompress"


def test_loudnorm_unavailable_fails_closed(tmp_path, media, monkeypatch):
    """When loudnorm is unavailable, the engine fails closed."""
    import kinocut.engine_audio_bed as engine

    real_check = engine._check_filter_available
    monkeypatch.setattr(
        engine,
        "_check_filter_available",
        lambda name: False if name == "loudnorm" else real_check(name),
    )
    out = tmp_path / "x.mp4"
    with pytest.raises(MCPVideoError) as excinfo:
        audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert excinfo.value.code == "missing_filter_loudnorm"


# ---------------------------------------------------------------------------
# Duration tamper detection
# ---------------------------------------------------------------------------


def test_duration_verification_gate_catches_mismatch(tmp_path, media, monkeypatch):
    """Post-render duration verification catches a mismatch via the gate."""
    import kinocut.engine_audio_bed as engine

    call_count = 0

    def failing_verify(path, target, tolerance):
        nonlocal call_count
        call_count += 1
        raise ProcessingError("audio_bed duration verification", 0, "tampered: 0.1 vs 5.0")

    monkeypatch.setattr(engine, "_verify_output_duration", failing_verify)
    out = tmp_path / "tampered.mp4"
    with pytest.raises(ProcessingError):
        audio_bed(media["video_5s"], media["bed_5s"], str(out))
    assert call_count == 1
    assert not out.exists()


def test_verify_output_duration_unit_passes_on_match(tmp_path, media):
    """_verify_output_duration returns the actual duration within tolerance."""
    from kinocut.engine_audio_bed import _verify_output_duration

    out = tmp_path / "ok.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out))
    actual = _verify_output_duration(str(out), 5.0, 0.5)
    assert abs(actual - 5.0) < 0.5


def test_verify_output_duration_unit_raises_on_mismatch(tmp_path, media):
    """_verify_output_duration raises ProcessingError on a real mismatch."""
    from kinocut.engine_audio_bed import _verify_output_duration

    out = tmp_path / "mismatch.mp4"
    audio_bed(media["video_5s"], media["bed_5s"], str(out))
    with pytest.raises(ProcessingError):
        _verify_output_duration(str(out), 100.0, 0.5)


# ---------------------------------------------------------------------------
# Module constraints
# ---------------------------------------------------------------------------


def test_engine_module_under_800_lines():
    from kinocut import engine_audio_bed

    path = Path(engine_audio_bed.__file__)
    assert len(path.read_text().splitlines()) <= 800


def test_contract_module_under_800_lines():
    from kinocut.contracts import audio_bed as contract

    path = Path(contract.__file__)
    assert len(path.read_text().splitlines()) <= 800


def test_all_functions_under_80_lines():
    """No function exceeds 80 lines."""
    import ast
    from kinocut import engine_audio_bed
    from kinocut.contracts import audio_bed as contract

    for module_path in [engine_audio_bed.__file__, contract.__file__]:
        tree = ast.parse(Path(module_path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = node.end_lineno - node.lineno + 1
                assert lines <= 80, f"{module_path}:{node.name} is {lines} lines"


def test_audio_bed_configuration_is_centralized():
    import ast
    import inspect

    from kinocut import engine_audio_bed
    from kinocut import defaults
    from kinocut.defaults import DEFAULT_AUDIO_BED_MUSIC_VOLUME, DEFAULT_HASH_CHUNK_BYTES

    tree = ast.parse(Path(engine_audio_bed.__file__).read_text())
    assignments = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert assignments.isdisjoint({"_TRUE_PEAK_DBTP", "_HASH_CHUNK", "_SAFE_DISPLAY_RE"})
    assert inspect.signature(audio_bed).parameters["music_volume"].default == DEFAULT_AUDIO_BED_MUSIC_VOLUME
    assert engine_audio_bed.DEFAULT_HASH_CHUNK_BYTES == DEFAULT_HASH_CHUNK_BYTES
    assert not hasattr(defaults, "DEFAULT_AUDIO_BED_HASH_CHUNK_BYTES")


def test_audio_bed_contract_reuses_canonical_limits_and_patterns():
    import ast

    from kinocut.contracts import audio_bed as contract

    source = Path(contract.__file__).read_text()
    assert "re.compile" not in source
    tree = ast.parse(source)
    parameters = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AudioBedParameters"
    )
    for call in (node for node in ast.walk(parameters) if isinstance(node, ast.Call)):
        for keyword in call.keywords:
            if keyword.arg in {"ge", "gt", "le", "lt"}:
                assert isinstance(keyword.value, ast.Name)


def test_audio_bed_display_name_pattern_is_exact_and_bounded():
    from kinocut.engine_audio_bed import _safe_display_name

    assert _safe_display_name("a" * 128) == "a" * 128
    assert _safe_display_name("a" * 129) == "input"


def test_audio_bed_receipt_contract_validates():
    """AudioBedReceipt rejects extra fields and invalid display names."""
    with pytest.raises(Exception):
        AudioBedReceipt(
            schema_version=1,
            receipt_kind="edit",
            operation="audio_bed",
            inputs=(),
            parameters=None,
            output_content_sha256="not-a-hash",
            output_duration_seconds=-1.0,
            output_display_name="/etc/passwd",
            ducking_engaged=True,
            unknown_field="rejected",
        )
