"""Doctor and Rescue consume the same local evidence, without using the machine's tools."""

import hashlib
from types import SimpleNamespace
import subprocess

import pytest

from kinocut.doctor import run_diagnostics
from kinocut.host_probes import HostProbes
from kinocut.rescue.capabilities import captions_available, snapshot_capabilities


def test_default_version_and_filter_probes_share_sanitized_bounded_runner(monkeypatch, tmp_path):
    executable = tmp_path / "ffmpeg"
    executable.touch()
    monkeypatch.setenv("PROVIDER_API_TOKEN", "private")
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, "... aresample A->A" if "-filters" in command else "v1", "")

    monkeypatch.setattr(subprocess, "run", run)
    host = HostProbes()
    assert host.command_version(["ffmpeg", "-version"], str(executable)) == "v1"
    assert host.filters(str(executable)) == {"aresample"}
    assert len(calls) == 2
    for command, options in calls:
        assert command[0] == str(executable)
        assert options["stdin"] == subprocess.DEVNULL and options["timeout"] > 0
        assert "PROVIDER_API_TOKEN" not in options["env"]
        assert options["env"]["HYPERFRAMES_NO_UPDATE_CHECK"] == "1"


@pytest.mark.parametrize(
    ("cached", "resampling", "valid_digest", "ffprobe_ok", "expected"),
    [
        (False, True, True, True, False),
        (True, False, True, True, False),
        (True, True, False, True, False),
        (True, True, True, False, False),
        (True, True, True, True, True),
    ],
)
def test_doctor_and_rescue_agree_on_local_captions(tmp_path, cached, resampling, valid_digest, ffprobe_ok, expected):
    payload = b"local weights fixture"
    for binary in ("ffmpeg", "ffprobe"):
        (tmp_path / binary).write_bytes(b"bin")
    if cached:
        (tmp_path / "base.pt").write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest() if valid_digest else "0" * 64

    def _version_runner(cmd):
        if "ffprobe" in cmd[0]:
            return "ffprobe version 8" if ffprobe_ok else None
        return "ffmpeg version 8"

    host = HostProbes(
        model_path=lambda model: tmp_path / f"{model}.pt",
        expected_whisper_sha256=lambda _model: expected_sha,
        which=lambda name: str(tmp_path / name) if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=_version_runner,
        find_spec=lambda name: object() if name == "whisper" else None,
        package_version=lambda name: "installed",
        import_module=lambda name: SimpleNamespace(),
        filters=lambda path: frozenset({"aresample"} if resampling else set()),
        environ={},
        cwd=lambda: tmp_path,
        home=lambda: tmp_path,
    )
    rescue = snapshot_capabilities(probes=host)
    report = run_diagnostics(probes=host, include_paths=False)
    assert rescue["whisper"]["available"] is True
    assert report["rescue"]["core_ready"] is ffprobe_ok
    assert captions_available(rescue) is report["rescue"]["captions_available"] is expected
    assert ("captions" in report["rescue"]["automatic_repair_types"]) is expected
    assert "audio_loudness" not in report["rescue"]["automatic_repair_types"]
    assert str(tmp_path) not in str(report)


def test_legacy_package_callbacks_do_not_spawn_upscale_subprocess(monkeypatch):
    def _forbid_subprocess(*_args, **_kwargs):
        raise AssertionError("legacy fake find_spec/package_version must not run subprocesses")

    monkeypatch.setattr(subprocess, "run", _forbid_subprocess)
    report = run_diagnostics(
        which=lambda _name: None,
        find_spec=lambda name: object() if name == "realesrgan" else None,
        package_version=lambda name: "0.3.0" if name == "realesrgan" else None,
        import_module=lambda _name: SimpleNamespace(),
    )
    realesrgan = next(check for check in report["checks"] if check["name"] == "realesrgan")
    assert realesrgan["ok"] is True


def test_injected_environ_home_and_hyperframes_resolvers_control_discovery(tmp_path):
    cache_dir = tmp_path / "xdg_cache"
    crush_dir = tmp_path / "data" / "crush-js" / "src"
    crush_dir.mkdir(parents=True)
    (crush_dir / "common.glsl").write_text("// shader", encoding="utf-8")

    host = HostProbes(
        which=lambda name: "/fake/hyperframes" if name == "hyperframes" else None,
        version_runner=lambda _cmd: None,
        find_spec=lambda _name: None,
        package_version=lambda _name: None,
        import_module=lambda _name: SimpleNamespace(),
        resolve_executable=lambda path: path,
        hyperframes_metadata=lambda _path: "0.8.140",
        environ={"XDG_CACHE_HOME": str(cache_dir), "KINOCUT_DATA_DIR": str(tmp_path / "data")},
        home=lambda: tmp_path / "home",
        cwd=lambda: tmp_path,
    )
    assert host.whisper_weights_path("base") == cache_dir / "whisper" / "base.pt"
    assert host.matte_weights()[0].is_relative_to(tmp_path / "home")
    assert host.crush_sources() == crush_dir
    report = run_diagnostics(probes=host)
    hf = next(check for check in report["checks"] if check["name"] == "hyperframes")
    assert hf["ok"] is True and hf["version"] == "0.8.140"
