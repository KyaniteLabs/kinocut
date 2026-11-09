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


def _fake(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(0o755)


def test_static_fallback_is_on_path_in_the_same_step(tmp_path):
    """A caller that runs `bash installer; ffmpeg` in one step must find the fallback (#692)."""
    bash = shutil.which("bash")
    assert bash is not None
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("find", "dirname", "head", "mkdir", "ln", "cat", "sleep", "rm", "chmod"):
        real = shutil.which(name)
        assert real is not None, name
        (tools / name).symlink_to(real)
    # apt always fails, which forces the static fallback; sudo never touches the host.
    _fake(tools / "sudo", 'case "$1" in sed) exit 0 ;; ln) shift; exec ln "$@" ;; *) exit 1 ;; esac')
    _fake(tools / "curl", 'while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && : > "$2"; shift; done')
    fake_bin = 'mkdir -p "$4/ffmpeg-fixture/bin"\n'
    for tool in ("ffmpeg", "ffprobe"):
        fake_bin += f'printf \'#!/bin/bash\\necho {tool}-static "$@"\\n\' > "$4/ffmpeg-fixture/bin/{tool}"\n'
        fake_bin += f'chmod +x "$4/ffmpeg-fixture/bin/{tool}"\n'
    _fake(tools / "python3", fake_bin)
    link_dir = tmp_path / "usr-local-bin"
    link_dir.mkdir()
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    environment = {
        "PATH": f"{tools}:{link_dir}",
        "RUNNER_TEMP": str(runner_temp),
        "FFMPEG_LINK_DIR": str(link_dir),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        [bash, "-c", f'set -euo pipefail; "{bash}" "{INSTALLER}"; ffmpeg -hide_banner -filters'],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "falling back to static build" in result.stderr
    assert result.stdout.rstrip().endswith("ffmpeg-static -hide_banner -filters")
    assert (link_dir / "ffprobe").exists()
