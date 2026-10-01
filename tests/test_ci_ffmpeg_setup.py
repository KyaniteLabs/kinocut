"""Execute Linux provisioning blocks without network or privileged installation."""

import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"


def _setup_blocks():
    blocks = []
    for filename in ("ci.yml", "integration-smoke.yml"):
        lines = (WORKFLOWS / filename).read_text().splitlines()
        for index, line in enumerate(lines):
            if not line.strip().startswith("- name: Ensure FFmpeg"):
                continue
            start = next(i for i in range(index + 1, len(lines)) if lines[i].strip() == "run: |")
            indentation = len(lines[start]) - len(lines[start].lstrip())
            body = []
            for following in lines[start + 1 :]:
                if following.strip() and len(following) - len(following.lstrip()) <= indentation:
                    break
                body.append(following)
            script = textwrap.dedent("\n".join(body))
            if "apt-get" in script:
                assert "timeout-minutes: 45" in "\n".join(lines[index:start])
                blocks.append((f"{filename}:{index + 1}", script))
    assert len(blocks) == 7
    return blocks


pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("awk") is None,
    reason="Linux provisioning executes POSIX Bash and awk",
)


def _executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


@pytest.mark.parametrize("name,script", _setup_blocks(), ids=[name for name, _ in _setup_blocks()])
@pytest.mark.parametrize("state", ["present", "probe_missing", "both_missing", "apt_failure", "install_failure"])
def test_actual_linux_setup_preserves_tools_and_fails_closed(tmp_path, name, script, state):
    bash = shutil.which("bash")
    awk = shutil.which("awk")
    assert bash is not None and awk is not None
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    template = tmp_path / "tool-template"
    _executable(template, '#!/bin/bash\necho "tool:$0:$*" >> "$CALLS"\necho " ... subtitles V->V "\n')
    if state in {"present", "probe_missing"}:
        shutil.copy2(template, tools / "ffmpeg")
    if state == "present":
        shutil.copy2(template, tools / "ffprobe")
    (tools / "awk").symlink_to(awk)
    _executable(
        tools / "sudo",
        "#!/bin/bash\n"
        'echo "sudo:$*" >> "$CALLS"\n'
        'if [[ "$APT_FAIL" == 1 ]]; then exit 73; fi\n'
        'if [[ "$INSTALL_FAIL" == 1 && "$2" == install ]]; then exit 74; fi\n'
        'if [[ "$2" == install ]]; then\n'
        '  /bin/cp "$TEMPLATE" "$TOOLS/ffmpeg"\n'
        '  /bin/cp "$TEMPLATE" "$TOOLS/ffprobe"\n'
        "fi\n",
    )
    environment = dict(os.environ, PATH=str(tools), CALLS=str(calls), TEMPLATE=str(template), TOOLS=str(tools))
    environment["APT_FAIL"] = str(int(state == "apt_failure"))
    environment["INSTALL_FAIL"] = str(int(state == "install_failure"))
    result = subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", script + '\necho "completed" >> "$CALLS"'],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    recorded = calls.read_text().splitlines()
    if state == "apt_failure":
        assert result.returncode == 73, (name, result.stderr)
        assert recorded == ["sudo:apt-get update"]
    elif state == "install_failure":
        assert result.returncode == 74, (name, result.stderr)
        assert recorded == ["sudo:apt-get update", "sudo:apt-get install -y --no-install-recommends ffmpeg"]
    else:
        assert result.returncode == 0, (name, result.stderr)
        assert recorded[-1] == "completed"
        installs = [line for line in recorded if line.startswith("sudo:")]
        if state == "present":
            assert installs == []
        else:
            assert installs == ["sudo:apt-get update", "sudo:apt-get install -y --no-install-recommends ffmpeg"]
        assert (tools / "ffmpeg").is_file() and (tools / "ffprobe").is_file()
        for command in ("ffmpeg -version", "ffprobe -version", "ffmpeg -hide_banner -filters"):
            if command in script:
                binary, arguments = command.split(" ", 1)
                assert f"tool:{tools / binary}:{arguments}" in recorded
