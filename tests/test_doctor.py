"""Tests for environment diagnostics."""

import json
import shutil
import subprocess
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest


def test_run_diagnostics_marks_required_tools_ok_when_present():
    from mcp_video.doctor import run_diagnostics

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe", "node", "npm", "npx", "hyperframes"} else None

    def fake_version(command: list[str]) -> str | None:
        if command[:1] == ["/usr/bin/hyperframes"]:
            return "0.6.31"
        if command[:2] == ["node", "-e"]:
            return "0.6.31"
        return f"{command[0]} version test"

    present_packages = {"mcp", "pydantic", "rich", "kinocut"}

    def fake_find_spec(name: str) -> ModuleSpec | None:
        if name not in present_packages:
            return None
        spec = ModuleSpec(name, loader=None)
        if name == "kinocut":
            spec.origin = "/env/site-packages/kinocut/__init__.py"
        return spec

    report = run_diagnostics(
        which=fake_which,
        version_runner=fake_version,
        find_spec=fake_find_spec,
        package_version=lambda name: (
            "1.7.0" if name == "kinocut" else ("1.0.0" if name in present_packages else None)
        ),
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert report["success"] is True
    assert report["summary"]["required_ok"] is True
    assert checks["mcp-video"]["ok"] is True
    assert checks["mcp-video"]["version"] == "1.7.0"
    assert checks["mcp-video"]["path"] == "/env/site-packages/kinocut/__init__.py"
    assert checks["ffmpeg"]["ok"] is True
    assert checks["ffprobe"]["ok"] is True
    assert checks["node"]["required"] is False
    assert checks["node"]["ok"] is True
    assert checks["npm"]["ok"] is True
    assert checks["npx"]["ok"] is True
    assert checks["hyperframes"]["ok"] is True
    assert checks["hyperframes"]["command"] == ["/usr/bin/hyperframes", "--version"]
    assert checks["@hyperframes/core"]["ok"] is True


def test_command_checks_resolve_the_executable_instead_of_the_display_name():
    from mcp_video.doctor import run_diagnostics

    looked_up: list[str] = []

    def fake_which(name: str) -> str | None:
        looked_up.append(name)
        return "/usr/bin/python3" if name == "python3" else None

    report = run_diagnostics(
        which=fake_which,
        version_runner=lambda command: "Python 3.14.5" if command == ["python3", "--version"] else None,
        find_spec=lambda name: None,
    )
    checks = {check["name"]: check for check in report["checks"]}

    assert checks["python"]["ok"] is True
    assert checks["python"]["path"] == "/usr/bin/python3"
    assert "python3" in looked_up


def _node_only_which(name: str) -> str | None:
    return f"/usr/bin/{name}" if name in {"node", "npm", "npx"} else None


def test_node_check_reports_hyperframes_version_via_injectable_runner():
    """The npx hyperframes probe must go through version_runner — a raw
    subprocess call here is untestable (the @hyperframes/core probe defect class)."""
    from mcp_video.doctor import run_diagnostics

    def fake_version(command: list[str]) -> str | None:
        if command[:2] == ["npx", "--yes"]:
            return "0.6.93"
        return "v22.0.0"

    report = run_diagnostics(which=_node_only_which, version_runner=fake_version, find_spec=lambda name: None)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["node"]["hyperframes_version"] == "0.6.93"


def test_node_check_omits_hyperframes_version_when_probe_fails():
    from mcp_video.doctor import run_diagnostics

    def fake_version(command: list[str]) -> str | None:
        if command[:2] == ["npx", "--yes"]:
            return None
        return "v22.0.0"

    report = run_diagnostics(which=_node_only_which, version_runner=fake_version, find_spec=lambda name: None)
    checks = {check["name"]: check for check in report["checks"]}
    assert "hyperframes_version" not in checks["node"]


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_hyperframes_core_probe_handles_esm_only_exports(tmp_path):
    """Regression: @hyperframes/core is ESM-only with a restrictive exports map,
    so probing via require('@hyperframes/core/package.json') throws
    ERR_PACKAGE_PATH_NOT_EXPORTED. The probe must read the layout from disk."""
    from mcp_video.doctor import HYPERFRAMES_CORE_PROBE

    pkg_dir = tmp_path / "node_modules" / "@hyperframes" / "core"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@hyperframes/core",
                "version": "9.9.9",
                "type": "module",
                "exports": {".": {"import": "./dist/index.js"}},
            }
        )
    )

    result = subprocess.run(
        ["node", "-e", HYPERFRAMES_CORE_PROBE],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "9.9.9"


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_hyperframes_core_probe_fails_when_package_absent(tmp_path):
    from mcp_video.doctor import HYPERFRAMES_CORE_PROBE

    result = subprocess.run(
        ["node", "-e", HYPERFRAMES_CORE_PROBE],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )

    assert result.returncode == 1


def test_run_diagnostics_marks_required_tools_missing():
    from mcp_video.doctor import run_diagnostics

    report = run_diagnostics(which=lambda name: None, version_runner=lambda command: None, find_spec=lambda name: None)

    checks = {check["name"]: check for check in report["checks"]}
    assert report["success"] is True
    assert report["summary"]["required_ok"] is False
    assert checks["ffmpeg"]["ok"] is False
    assert checks["ffmpeg"]["required"] is True
    assert "Install FFmpeg" in checks["ffmpeg"]["install_hint"]


def test_doctor_reports_rescue_readiness_from_existing_checks():
    from mcp_video.doctor import run_diagnostics

    def ffmpeg_only(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None

    report = run_diagnostics(
        which=ffmpeg_only,
        version_runner=lambda command: f"{command[0]} version 8.0",
        find_spec=lambda name: None,
        package_version=lambda name: None,
    )

    assert report["rescue"] == {
        "core_ready": True,
        "local_only": True,
        "captions_available": False,
        "automatic_repair_types": [
            "audio_loudness",
            "container_timestamps",
            "exposure",
            "metadata",
            "rotation",
            "universal_mp4",
        ],
    }


def test_run_diagnostics_marks_command_probe_failures_missing():
    from mcp_video.doctor import run_diagnostics

    present_packages = {"mcp", "pydantic", "rich"}

    def fake_find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, loader=None) if name in present_packages else None

    report = run_diagnostics(
        which=lambda name: f"/usr/bin/{name}",
        version_runner=lambda command: None,
        find_spec=fake_find_spec,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert report["summary"]["required_ok"] is False
    assert checks["ffmpeg"]["ok"] is False
    assert checks["ffmpeg"]["path"] == "/usr/bin/ffmpeg"


def test_run_diagnostics_checks_optional_packages_without_importing_them():
    from mcp_video.doctor import run_diagnostics

    present = {"PIL", "sklearn", "webcolors"}

    def fake_find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, loader=None) if name in present else None

    report = run_diagnostics(
        which=lambda name: None,
        version_runner=lambda command: None,
        find_spec=fake_find_spec,
        package_version=lambda name: "1.0.0" if name in {"pillow", "scikit-learn", "webcolors"} else None,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["pillow"]["ok"] is True
    assert checks["scikit-learn"]["ok"] is True
    assert checks["openai-whisper"]["ok"] is False
    assert checks["openai-whisper"]["required"] is False
    assert "kinocut[transcribe]" in checks["openai-whisper"]["install_hint"]
    assert "kinocut[stems]" in checks["demucs"]["install_hint"]
    assert "kinocut[stems]" in checks["torchcodec"]["install_hint"]
    assert "kinocut[upscale]" in checks["opencv-contrib-python"]["install_hint"]
    assert "kinocut[ai-scene]" in checks["imagehash"]["install_hint"]


def test_run_diagnostics_explains_python313_basicsr_guard(monkeypatch):
    import mcp_video.doctor as doctor

    monkeypatch.setattr(doctor.sys, "version_info", (3, 13, 12))

    report = doctor.run_diagnostics(
        which=lambda name: None,
        version_runner=lambda command: None,
        find_spec=lambda name: None,
        package_version=lambda name: None,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert "BasicSR currently fails to build" in checks["basicsr"]["install_hint"]
    assert "OpenCV fallback" in checks["realesrgan"]["install_hint"]
    assert "Python 3.11 or 3.12" in checks["basicsr"]["install_hint"]
    assert "manual optional integration" in checks["basic-pitch"]["install_hint"]
    assert "Python 3.11 or 3.12" in checks["basic-pitch"]["install_hint"]


def test_run_diagnostics_requires_matching_distribution_for_package_checks():
    from mcp_video.doctor import run_diagnostics

    present = {"mcp", "pydantic", "rich", "cv2", "kinocut"}

    def fake_find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, loader=None) if name in present else None

    def fake_package_version(name: str) -> str | None:
        return "1.0.0" if name in {"mcp", "pydantic", "rich"} else None

    report = run_diagnostics(
        which=lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=lambda command: f"{command[0]} version test",
        find_spec=fake_find_spec,
        package_version=fake_package_version,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert report["summary"]["required_ok"] is True
    assert checks["opencv-contrib-python"]["ok"] is False
    assert checks["opencv-contrib-python"]["version"] is None


def test_run_diagnostics_reports_kinocut_import_path_when_distribution_metadata_missing():
    from mcp_video.doctor import run_diagnostics

    def fake_find_spec(name: str) -> ModuleSpec | None:
        if name != "kinocut":
            return ModuleSpec(name, loader=None) if name in {"mcp", "pydantic", "rich"} else None
        spec = ModuleSpec(name, loader=None)
        spec.origin = str(Path("/repo/kinocut/__init__.py"))
        return spec

    report = run_diagnostics(
        which=lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
        version_runner=lambda command: f"{command[0]} version test",
        find_spec=fake_find_spec,
        package_version=lambda name: None,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["mcp-video"]["ok"] is True
    assert checks["mcp-video"]["path"] == "/repo/kinocut/__init__.py"
    assert checks["mcp-video"]["version"] is None


def test_cli_doctor_json_outputs_structured_report():
    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "doctor", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["success"] is True
    assert "summary" in data
    assert isinstance(data["checks"], list)
    assert any(check["name"] == "mcp-video" for check in data["checks"])
    assert any(check["name"] == "ffmpeg" for check in data["checks"])


def test_cli_doctor_text_outputs_summary():
    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "doctor"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "Kinocut doctor" in result.stdout
    assert "ffmpeg" in result.stdout
    assert "hyperframes" in result.stdout
    assert "openai-whisper" in result.stdout
