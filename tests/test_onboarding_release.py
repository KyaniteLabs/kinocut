from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import venv
import zipfile
from pathlib import Path

import pytest

from scripts import verify_onboarding_release as verify
from kinocut import defaults


COMMIT = "a" * 40


def test_run_timeout_fails_with_bounded_detail(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], stderr="x" * 9000)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(verify.AcceptanceError, match="timed out") as caught:
        verify._run(["kino", "doctor"], cwd=Path.cwd(), timeout=1)
    assert len(str(caught.value)) < 1200


@pytest.mark.parametrize(
    "quality",
    [
        {},
        {"all_passed": False, "overall_score": 90, "checks": [{"name": "audio", "passed": True}]},
        {"all_passed": True, "overall_score": float("inf"), "checks": [{"name": "audio", "passed": True}]},
        {"all_passed": True, "overall_score": 10**400, "checks": [{"name": "audio", "passed": True}]},
        {"all_passed": True, "overall_score": 79.9, "checks": [{"name": "audio", "passed": True}]},
        {"all_passed": True, "overall_score": 90, "checks": []},
        {"all_passed": True, "overall_score": 90, "checks": [{"name": "audio", "passed": False}]},
    ],
)
def test_raw_quality_is_strict(quality) -> None:
    with pytest.raises(verify.AcceptanceError):
        verify._validate_quality(quality)


def test_checkpoint_requires_review_artifacts(tmp_path: Path) -> None:
    checkpoint = {
        "quality": {"overall_score": 90},
        "review_required": True,
        "thumbnail": "missing",
        "storyboard": {"frames": []},
    }
    with pytest.raises(verify.AcceptanceError):
        verify._validate_checkpoint(checkpoint)


def test_huge_evidence_numbers_fail_with_typed_errors() -> None:
    checkpoint = {
        "quality": {"overall_score": 10**400},
        "review_required": True,
        "thumbnail": "unused",
        "storyboard": {"frames": ["unused"]},
    }
    with pytest.raises(verify.AcceptanceError, match="finite"):
        verify._validate_checkpoint(checkpoint)

    probe = {
        "format": {"duration": 10**400, "format_name": "mp4"},
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920},
            {"codec_type": "audio"},
        ],
    }
    with pytest.raises(verify.AcceptanceError, match="duration"):
        verify._validate_probe(probe, expected_duration=6.0)


def test_probe_requires_exact_vertical_av_mp4() -> None:
    valid = {
        "format": {"duration": "6.0", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920},
            {"codec_type": "audio"},
        ],
    }
    verify._validate_probe(valid, expected_duration=6.0)
    valid["streams"].append({"codec_type": "video", "width": 1080, "height": 1920})
    with pytest.raises(verify.AcceptanceError, match="one video"):
        verify._validate_probe(valid, expected_duration=6.0)


def test_checkout_identity_is_rejected(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    with pytest.raises(verify.AcceptanceError, match="checkout"):
        verify._require_outside_checkout(checkout / "kinocut.py", checkout, "kinocut")


def _passing_temporal_metrics() -> dict[str, dict[str, float | int]]:
    return {
        "outside_0.25": {"changed_pixels": 100, "crop_ssim": 0.999, "full_ssim": 0.995},
        "outside_2.60": {"changed_pixels": 120, "crop_ssim": 0.998, "full_ssim": 0.994},
        "cue_1.20": {"changed_pixels": 2000, "crop_ssim": 0.990, "full_ssim": 0.97},
        "cue_4.00": {"changed_pixels": 1800, "crop_ssim": 0.991, "full_ssim": 0.97},
    }


def test_temporal_oracle_accepts_complete_green_fixture() -> None:
    verify._validate_temporal_metrics(_passing_temporal_metrics())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (("cue_1.20", "changed_pixels"), 999, "changed pixels"),
        (("cue_1.20", "changed_pixels"), 1001, "changed pixels"),
        (("outside_0.25", "full_ssim"), 0.989, "full-frame SSIM"),
        (("cue_1.20", "crop_ssim"), 0.997, "crop SSIM"),
    ],
)
def test_temporal_oracle_rejects_each_independent_failure(field, value, message) -> None:
    metrics = _passing_temporal_metrics()
    if field == ("cue_1.20", "changed_pixels") and value == 1001:
        metrics["outside_0.25"]["changed_pixels"] = 300
    metrics[field[0]][field[1]] = value
    with pytest.raises(verify.AcceptanceError, match=message):
        verify._validate_temporal_metrics(metrics)


def test_synthetic_source_uses_shared_portrait_recipe_and_executed_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def checked(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ffmpeg version fixture\n", stderr="")

    monkeypatch.setattr(verify, "_checked", checked)
    source = tmp_path / "source with spaces.mp4"

    recipe, version = verify._generate_source(source, tmp_path, 10)

    command = calls[0]
    assert command[-1] == str(source)
    assert shlex.join([*command[:-1], "SOURCE"]) == recipe
    assert str(source) not in recipe
    assert version == "ffmpeg version fixture"
    assert (
        f"testsrc2=size={defaults.DEFAULT_ONBOARDING_FIXTURE_WIDTH}x"
        f"{defaults.DEFAULT_ONBOARDING_FIXTURE_HEIGHT}:rate={defaults.DEFAULT_ONBOARDING_FIXTURE_FRAME_RATE}" in command
    )
    video_filter = command[command.index("-vf") + 1]
    assert video_filter.index("eq=") < video_filter.index("drawbox=")
    assert f"y={defaults.DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_START_ROW}" in video_filter
    assert f"h={defaults.DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_HEIGHT}" in video_filter
    assert command[command.index("-af") + 1] == f"volume={defaults.DEFAULT_ONBOARDING_FIXTURE_AUDIO_VOLUME:g}"


def test_synthetic_source_requires_fresh_destination_before_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"existing")
    calls: list[list[str]] = []
    monkeypatch.setattr(verify, "_checked", lambda command, **_kwargs: calls.append(command))

    with pytest.raises(verify.AcceptanceError, match="fresh"):
        verify._generate_source(source, tmp_path, 10)

    assert calls == []


def test_frame_metrics_crop_matches_shared_stable_region(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame_size = defaults.DEFAULT_ONBOARDING_FIXTURE_WIDTH * defaults.DEFAULT_ONBOARDING_FIXTURE_HEIGHT * 3
    frame = bytes(frame_size)
    ssim_lengths: list[int] = []
    monkeypatch.setattr(verify, "_rgb_frame", lambda *_args: frame)
    monkeypatch.setattr(verify, "_ssim", lambda first, _second: ssim_lengths.append(len(first)) or 1.0)
    monkeypatch.setattr(verify, "_validate_temporal_metrics", lambda _metrics: None)

    verify._frame_metrics(tmp_path / "before", tmp_path / "after", tmp_path, 1)

    crop_size = defaults.DEFAULT_ONBOARDING_FIXTURE_WIDTH * defaults.DEFAULT_ONBOARDING_FIXTURE_STABLE_REGION_HEIGHT * 3
    assert ssim_lengths.count(crop_size) == len(verify.FRAME_TIMES)
    assert ssim_lengths.count(frame_size) == len(verify.FRAME_TIMES)


def test_receipt_keeps_human_review_pending() -> None:
    receipt = verify._receipt_base("synthetic", "commit", "wheel", "source", 1, "output", "run")
    assert receipt["human_review"] == {"required": True, "status": "pending"}
    assert "synthetic" in receipt["limitations"][0].lower()


def test_wheel_metadata_must_identify_kinocut(tmp_path: Path) -> None:
    wheel = tmp_path / "kinocut.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("kinocut-1.15.1.dist-info/METADATA", "Name: kinocut\nVersion: 1.15.1\n")
    assert verify._wheel_version(wheel) == "1.15.1"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("other-1.dist-info/METADATA", "Name: other\nVersion: 1\n")
    with pytest.raises(verify.AcceptanceError, match="Kinocut"):
        verify._wheel_version(wheel)


@pytest.mark.skipif(os.name == "nt", reason="Windows venv launchers are regular executables")
def test_standard_library_venv_python_symlink_keeps_lexical_launcher(tmp_path: Path) -> None:
    environment = tmp_path / "acceptance-venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    launcher = environment / "bin" / "python"
    assert launcher.is_symlink()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    selected = verify._interpreter(launcher, checkout)
    assert selected == launcher.absolute()
    result = verify._checked(
        [str(selected), "-c", "import json,sys; print(json.dumps({'prefix':sys.prefix,'executable':sys.executable}))"],
        cwd=tmp_path,
        timeout=10,
    )
    identity = json.loads(result.stdout)
    assert Path(identity["prefix"]).resolve() == environment.resolve()
    assert Path(identity["executable"]).absolute() == selected


def test_installed_facades_must_resolve_inside_selected_venv(tmp_path: Path, monkeypatch) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    environment = tmp_path / "venv"
    (environment / "bin").mkdir(parents=True)
    (environment / "lib").mkdir()
    python = environment / "bin" / "python"
    kino = environment / "bin" / "kino"
    python.write_text("python", encoding="utf-8")
    kino.write_text(f"#!{python}\n", encoding="utf-8")
    external = tmp_path / "other" / "kinocut.py"
    external.parent.mkdir()
    external.write_text("", encoding="utf-8")
    facade = environment / "lib" / "mcp_video.py"
    facade.write_text("", encoding="utf-8")
    response = {
        "version": "1.15.1",
        "prefix": str(environment),
        "executable": str(python),
        "kinocut": str(external),
        "mcp_video": str(facade),
        "release_checkpoint_callable": True,
        "release_checkpoint_origin": str(facade),
    }
    completed = subprocess.CompletedProcess([str(python)], 0, stdout=json.dumps(response), stderr="")
    monkeypatch.setattr(verify, "_checked", lambda *args, **kwargs: completed)
    with pytest.raises(verify.AcceptanceError, match="selected venv"):
        verify._installed_identity(python, kino, "1.15.1", checkout, tmp_path, 1)


@pytest.mark.parametrize(
    ("callable_value", "origin_value"),
    [(False, "inside"), (True, "outside")],
)
def test_release_checkpoint_must_be_callable_from_selected_venv(
    tmp_path: Path, monkeypatch, callable_value: bool, origin_value: str
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    environment = tmp_path / "venv"
    (environment / "bin").mkdir(parents=True)
    (environment / "lib").mkdir()
    python = environment / "bin" / "python"
    kino = environment / "bin" / "kino"
    python.write_text("python", encoding="utf-8")
    kino.write_text(f"#!{python}\n", encoding="utf-8")
    kinocut = environment / "lib" / "kinocut.py"
    mcp_video = environment / "lib" / "mcp_video.py"
    for path in (kinocut, mcp_video):
        path.write_text("", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("", encoding="utf-8")
    origin = kinocut if origin_value == "inside" else outside
    response = {
        "version": "1.15.1",
        "prefix": str(environment),
        "executable": str(python),
        "kinocut": str(kinocut),
        "mcp_video": str(mcp_video),
        "release_checkpoint_callable": callable_value,
        "release_checkpoint_origin": str(origin),
    }
    completed = subprocess.CompletedProcess([str(python)], 0, stdout=json.dumps(response), stderr="")
    monkeypatch.setattr(verify, "_checked", lambda *args, **kwargs: completed)
    with pytest.raises(verify.AcceptanceError, match="release_checkpoint"):
        verify._installed_identity(python, kino, "1.15.1", checkout, tmp_path, 1)


def _args(tmp_path: Path) -> argparse.Namespace:
    paths = {name: tmp_path / name for name in ("wheel", "source", "captions", "python", "kino")}
    for path in paths.values():
        path.write_bytes(b"data")
    return argparse.Namespace(
        wheel=paths["wheel"],
        source=paths["source"],
        captions=paths["captions"],
        output_dir=tmp_path / "output",
        python=paths["python"],
        kino=paths["kino"],
        candidate_commit=COMMIT,
        timeout=10,
        evidence_class="synthetic_fixture",
        generate_synthetic_source=False,
    )


def _mock_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "_checkout_commit", lambda *args: COMMIT)
    monkeypatch.setattr(verify, "_wheel_version", lambda wheel: "1.15.1")
    monkeypatch.setattr(verify, "_require_subtitles_filter", lambda *args: None)
    monkeypatch.setattr(
        verify,
        "_installed_identity",
        lambda *args: {
            "version": "1.15.1",
            "kinocut": "/venv/kinocut",
            "mcp_video": "/venv/mcp_video.py",
            "release_checkpoint_callable": True,
            "release_checkpoint_origin": "/venv/kinocut/client.py",
        },
    )


def test_success_receipt_records_every_temporal_tolerance(tmp_path: Path, monkeypatch) -> None:
    args = _args(tmp_path)
    _mock_preflight(monkeypatch)
    source_identity = {"sha256": "sha256:" + ("a" * 64), "byte_size": 4}
    final_identity = {"sha256": "sha256:" + ("b" * 64), "byte_size": 4}
    identities = iter([source_identity, source_identity, final_identity])
    monkeypatch.setattr(verify, "_source_identity", lambda *args: next(identities))
    monkeypatch.setattr(
        verify,
        "_cli_journey",
        lambda *args: ({"all_passed": True, "overall_score": 90, "checks": []}, [["kino", "doctor"]]),
    )

    def checkpoint(_python, _final, output, _timeout):
        thumbnail = output / "checkpoint" / "thumbnail.jpg"
        frame = output / "checkpoint" / "storyboard" / "frame.jpg"
        frame.parent.mkdir(parents=True)
        thumbnail.write_bytes(b"image")
        frame.write_bytes(b"image")
        return {"review_required": True, "thumbnail": str(thumbnail), "storyboard": {"frames": [str(frame)]}}

    monkeypatch.setattr(verify, "_checkpoint", checkpoint)
    monkeypatch.setattr(verify, "_probe_and_decode", lambda *args: {"format": {}, "streams": []})
    monkeypatch.setattr(verify, "_frame_metrics", lambda *args: {})
    receipt = verify._execute(args)
    assert receipt["media"]["temporal_tolerances"] == {
        "channel_delta": 24,
        "minimum_cue_changed_pixels": 1000,
        "cue_to_outside_changed_pixel_multiplier": 5,
        "minimum_cue_crop_ssim_delta": 0.002,
        "minimum_outside_full_frame_ssim": 0.99,
    }
    assert receipt["installed_identity"]["release_checkpoint_callable"] is True
    assert receipt["installed_identity"]["release_checkpoint_inside_selected_venv"] is True
    assert receipt["journey"]["client_calls"] == ["Client.release_checkpoint"]


@pytest.mark.parametrize("line", [".. subtitles V->V\n", "... subtitles V->V\n"])
def test_subtitles_filter_accepts_ffmpeg_capability_field_shapes(tmp_path: Path, monkeypatch, line: str) -> None:
    completed = subprocess.CompletedProcess(["ffmpeg"], 0, stdout=line, stderr="")
    monkeypatch.setattr(verify, "_checked", lambda *args, **kwargs: completed)
    verify._require_subtitles_filter(tmp_path, 1)


def test_subtitles_filter_still_fails_when_capability_is_absent(tmp_path: Path, monkeypatch) -> None:
    completed = subprocess.CompletedProcess(["ffmpeg"], 0, stdout=".. scale V->V\n", stderr="")
    monkeypatch.setattr(verify, "_checked", lambda *args, **kwargs: completed)
    with pytest.raises(verify.AcceptanceError, match="unavailable"):
        verify._require_subtitles_filter(tmp_path, 1)


def test_huge_timeout_fails_with_typed_error_before_work(tmp_path: Path) -> None:
    args = _args(tmp_path)
    args.timeout = 10**400
    with pytest.raises(verify.AcceptanceError, match="timeout"):
        verify._execute(args)


def test_failed_raw_journey_never_reaches_checkpoint(tmp_path: Path, monkeypatch) -> None:
    args = _args(tmp_path)
    _mock_preflight(monkeypatch)
    monkeypatch.setattr(verify, "_source_identity", lambda *args: {"sha256": "sha256:source", "byte_size": 4})
    monkeypatch.setattr(verify, "_cli_journey", lambda *args: (_ for _ in ()).throw(verify.AcceptanceError("quality")))
    reached = []
    monkeypatch.setattr(verify, "_checkpoint", lambda *args: reached.append(True))
    with pytest.raises(verify.AcceptanceError, match="quality"):
        verify._execute(args)
    assert reached == []


def test_source_mutation_fails_before_receipt(tmp_path: Path, monkeypatch) -> None:
    args = _args(tmp_path)
    _mock_preflight(monkeypatch)
    identities = iter(
        [
            {"sha256": "sha256:before", "byte_size": 4},
            {"sha256": "sha256:after", "byte_size": 5},
        ]
    )
    monkeypatch.setattr(verify, "_source_identity", lambda *args: next(identities))
    monkeypatch.setattr(verify, "_cli_journey", lambda *args: ({"all_passed": True}, [["kino", "doctor"]]))
    monkeypatch.setattr(
        verify,
        "_checkpoint",
        lambda *args: {"review_required": True, "thumbnail": "x", "storyboard": {"frames": ["x"]}},
    )
    monkeypatch.setattr(verify, "_probe_and_decode", lambda *args: {"format": {}, "streams": []})
    monkeypatch.setattr(verify, "_frame_metrics", lambda *args: {})
    with pytest.raises(verify.AcceptanceError, match="source identity changed"):
        verify._execute(args)


def test_source_identity_schema_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    result = subprocess.CompletedProcess(["python"], 0, stdout='{"sha256":"not-a-digest","byte_size":0}', stderr="")
    monkeypatch.setattr(verify, "_checked", lambda *args, **kwargs: result)
    with pytest.raises(verify.AcceptanceError, match="SHA-256"):
        verify._source_identity(tmp_path / "python", tmp_path / "source", tmp_path, 1)


def test_output_directory_must_be_fresh_and_outside_checkout(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale").write_text("old")
    with pytest.raises(verify.AcceptanceError, match="absent or empty"):
        verify._fresh_output(output, Path(__file__).resolve().parents[1])
