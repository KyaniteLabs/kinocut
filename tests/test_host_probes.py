"""Doctor and Rescue consume the same local evidence, without using the machine's tools."""

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
    ("cached", "resampling", "expected"), [(False, True, False), (True, False, False), (True, True, True)]
)
def test_doctor_and_rescue_agree_on_local_captions(tmp_path, cached, resampling, expected):
    if cached:
        (tmp_path / "base.pt").write_bytes(b"local weights fixture")
    host = HostProbes(
        model_path=lambda model: tmp_path / f"{model}.pt",
        which=lambda name: str(tmp_path / name) if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=lambda cmd: "ffmpeg version 8",
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
    assert captions_available(rescue) is report["rescue"]["captions_available"] is expected
    assert ("captions" in report["rescue"]["automatic_repair_types"]) is expected
    assert "audio_loudness" not in report["rescue"]["automatic_repair_types"]
    assert str(tmp_path) not in str(report)
