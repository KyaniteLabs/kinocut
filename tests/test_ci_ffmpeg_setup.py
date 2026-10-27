"""Linux FFmpeg provisioning: workflows delegate to the retrying installer."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / ".github" / "scripts" / "install-ffmpeg-ubuntu.sh"
WORKFLOWS = ROOT / ".github" / "workflows"


pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="Linux provisioning executes POSIX Bash",
)


def test_linux_ci_delegates_ffmpeg_to_the_retrying_installer() -> None:
    """ci.yml / integration-smoke / mcpb / pr-safety must not inline apt-get."""
    for filename in ("ci.yml", "integration-smoke.yml", "mcpb.yml", "pr-safety.yml"):
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "install-ffmpeg-ubuntu.sh" in text, filename
        for line in text.splitlines():
            if "apt-get" in line and "install-ffmpeg-ubuntu.sh" not in line:
                raise AssertionError(f"{filename} still inlines apt-get: {line}")


def test_shared_installer_skips_apt_when_ffmpeg_is_on_path(tmp_path):
    bash = shutil.which("bash")
    assert bash is not None
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    fake = tools / "ffmpeg"
    fake.write_text('#!/bin/bash\necho "tool:$0:$*" >> "$CALLS"\n')
    fake.chmod(0o755)
    (tools / "ffprobe").write_text(fake.read_text())
    (tools / "ffprobe").chmod(0o755)
    environment = dict(os.environ, PATH=str(tools), CALLS=str(calls))
    result = subprocess.run(
        [bash, str(INSTALLER)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "skipping install" in result.stdout
    recorded = calls.read_text().splitlines() if calls.exists() else []
    assert any("version" in line for line in recorded)
    assert not any("sudo" in line for line in recorded)
