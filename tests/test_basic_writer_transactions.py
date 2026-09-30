"""Trim/speed publish only fully rendered and postflight-verified media."""

from pathlib import Path
import shutil

import pytest

from kinocut import engine_edit, engine_speed, ffmpeg_helpers
from kinocut.engine_probe import probe
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError


@pytest.fixture(params=[engine_edit, engine_speed], ids=["trim", "speed"])
def writer(request):
    module = request.param
    options = {"start": 0.5, "duration": 1, "accurate": True} if module is engine_edit else {"factor": 2}
    function = module.trim if module is engine_edit else module.speed
    return module, function, options


def _destination(tmp_path, source, existing):
    destination = tmp_path / "destination.mp4"
    if existing:
        shutil.copyfile(source, destination)
    return destination, destination.read_bytes() if existing else None


def _preserved(destination, original):
    if original is None:
        assert not destination.exists()
    else:
        assert destination.read_bytes() == original
        assert probe(str(destination)).duration > 0
    assert not list(destination.parent.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["after_render", "postflight", "ffmpeg", "timeout"])
def test_failed_writer_preserves_destination(writer, sample_video, tmp_path, monkeypatch, existing, failure):
    module, function, options = writer
    destination, original = _destination(tmp_path, sample_video, existing)
    run = module._run_ffmpeg
    if failure == "postflight":
        build = module._build_edit_result

        def reject(path, *args, **kwargs):
            result = build(path, *args, **kwargs)
            assert result.duration > 0 and Path(path).name.startswith(".kinocut_tmp_")
            raise InputFileError(path, "injected postflight failure")

        monkeypatch.setattr(module, "_build_edit_result", reject)
        expected = InputFileError
    else:

        def fail(args):
            if failure == "ffmpeg":
                args = [*args[:-1], "-c:v", "missing_encoder_for_transaction_test", args[-1]]
            elif failure == "timeout":
                args = ["-re", *args]
            result = run(args)
            if failure == "after_render":
                assert probe(args[-1]).duration > 0
                raise MCPVideoError("injected completion failure", code="completion_failed")
            return result

        monkeypatch.setattr(module, "_run_ffmpeg", fail)
        if failure == "timeout":
            monkeypatch.setattr(ffmpeg_helpers, "DEFAULT_FFMPEG_TIMEOUT", 0.2)
        expected = MCPVideoError if failure == "after_render" else ProcessingError
    with pytest.raises(expected):
        function(sample_video, output_path=str(destination), **options)
    _preserved(destination, original)


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink"])
def test_writer_rejects_source_alias_before_render(writer, sample_video, tmp_path, monkeypatch, alias):
    module, function, options = writer
    source = tmp_path / "source.mp4"
    shutil.copyfile(sample_video, source)
    destination = source if alias == "same" else tmp_path / "alias.mp4"
    if alias == "hardlink":
        destination.hardlink_to(source)
    elif alias == "symlink":
        destination.symlink_to(source)
    original = source.read_bytes()

    def unexpected(args):
        pytest.fail("alias guard must run before encoding")

    monkeypatch.setattr(module, "_run_ffmpeg", unexpected)
    with pytest.raises(MCPVideoError):
        function(str(source), output_path=str(destination), **options)
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("with_audio", [False, True])
@pytest.mark.parametrize("suffix", ["mp4", "mov"])
def test_writer_success_preserves_streams_and_public_result(
    writer, sample_video, sample_video_no_audio, tmp_path, suffix, with_audio
):
    module, function, options = writer
    source = sample_video if with_audio else sample_video_no_audio
    destination = tmp_path / f"output.{suffix}"
    shutil.copyfile(source, destination)
    original = destination.read_bytes()
    result = function(source, output_path=str(destination), **options)
    info = probe(str(destination))
    assert result.success and result.output_path == str(destination)
    assert result.operation in {"trim", "speed"}
    assert result.duration == pytest.approx(info.duration)
    assert result.resolution == info.resolution and result.size_mb == info.size_mb
    assert destination.stat().st_size > 0
    assert (info.audio_codec is not None) == with_audio
    assert 0 < info.duration < probe(source).duration
    assert destination.read_bytes() != original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
    reference = tmp_path / f"reference.{suffix}"
    if module is engine_edit:
        args = ["-ss", "0.5", "-i", source, "-t", "1", *ffmpeg_helpers._build_ffmpeg_cmd(output_path=str(reference))]
    elif with_audio:
        args = ffmpeg_helpers._build_ffmpeg_cmd(
            source,
            output_path=str(reference),
            extra=["-filter_complex", "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]", "-map", "[v]", "-map", "[a]"],
        )
    else:
        args = ffmpeg_helpers._build_ffmpeg_cmd(
            source, output_path=str(reference), video_filter="setpts=0.5*PTS", audio_codec=None, extra=["-an"]
        )
    ffmpeg_helpers._run_ffmpeg(args)

    def decoded_hash(path):
        return ffmpeg_helpers._run_ffmpeg(
            ["-i", str(path), "-map", "0", "-c:v", "rawvideo", "-c:a", "pcm_s16le", "-f", "hash", "-"]
        ).stdout.strip()

    assert decoded_hash(destination) == decoded_hash(reference)


@pytest.mark.parametrize("field", ["start", "duration", "end"])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        None,
        [],
        {},
        float("nan"),
        float("inf"),
        -float("inf"),
        "nan",
        "inf",
        "00:00:nan",
        "x",
        "1" * 129,
        10**400,
    ],
)
def test_invalid_trim_times_fail_before_writer(tmp_path, monkeypatch, field, value):
    if field != "start" and value is None:
        pytest.skip("optional absence is valid")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture not decoded")
    destination = tmp_path / "destination.mp4"
    destination.write_bytes(b"existing media placeholder")

    def unexpected(args):
        pytest.fail("invalid time must not reach FFmpeg")

    monkeypatch.setattr(engine_edit, "_run_ffmpeg", unexpected)
    with pytest.raises(MCPVideoError) as exc:
        engine_edit.trim(str(source), output_path=str(destination), **{field: value})
    assert exc.value.code == "invalid_parameter"
    assert destination.read_bytes() == b"existing media placeholder"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
