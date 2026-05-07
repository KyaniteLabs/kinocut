"""Tests for environment diagnostics."""

import json
import subprocess
import sys
from importlib.machinery import ModuleSpec


def test_run_diagnostics_marks_required_tools_ok_when_present():
    from mcp_video.doctor import run_diagnostics

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None

    def fake_version(command: list[str]) -> str | None:
        return f"{command[0]} version test"

    present_packages = {"mcp", "pydantic", "rich"}

    def fake_find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, loader=None) if name in present_packages else None

    report = run_diagnostics(
        which=fake_which,
        version_runner=fake_version,
        find_spec=fake_find_spec,
        package_version=lambda name: "1.0.0" if name in present_packages else None,
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert report["success"] is True
    assert report["summary"]["required_ok"] is True
    assert checks["ffmpeg"]["ok"] is True
    assert checks["ffprobe"]["ok"] is True
    assert checks["node"]["required"] is False
    assert checks["node"]["ok"] is False


def test_run_diagnostics_marks_required_tools_missing():
    from mcp_video.doctor import run_diagnostics

    report = run_diagnostics(which=lambda name: None, version_runner=lambda command: None, find_spec=lambda name: None)

    checks = {check["name"]: check for check in report["checks"]}
    assert report["success"] is True
    assert report["summary"]["required_ok"] is False
    assert checks["ffmpeg"]["ok"] is False
    assert checks["ffmpeg"]["required"] is True
    assert "Install FFmpeg" in checks["ffmpeg"]["install_hint"]


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
    assert "mcp-video[transcribe]" in checks["openai-whisper"]["install_hint"]
    assert "mcp-video[stems]" in checks["demucs"]["install_hint"]
    assert "mcp-video[stems]" in checks["torchcodec"]["install_hint"]
    assert "mcp-video[upscale]" in checks["opencv-contrib-python"]["install_hint"]
    assert "mcp-video[ai-scene]" in checks["imagehash"]["install_hint"]


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


def test_run_diagnostics_requires_matching_distribution_for_package_checks():
    from mcp_video.doctor import run_diagnostics

    present = {"mcp", "pydantic", "rich", "cv2"}

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
    assert any(check["name"] == "ffmpeg" for check in data["checks"])


def test_cli_doctor_text_outputs_summary():
    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "doctor"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "mcp-video doctor" in result.stdout
    assert "ffmpeg" in result.stdout
    assert "openai-whisper" in result.stdout
