"""Hosted prerequisite contracts for the staged MCPB workflow."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).parents[1]


class _FakeFunction:
    def __init__(self) -> None:
        self.argtypes: list[Any] | None = None
        self.restype: Any = None

    def __call__(self, *_args: object) -> int:
        return 1


class _FakeKernel:
    def __init__(self) -> None:
        for name in (
            "CreateJobObjectW",
            "OpenJobObjectW",
            "SetInformationJobObject",
            "QueryInformationJobObject",
            "AssignProcessToJobObject",
            "TerminateJobObject",
            "CloseHandle",
            "OpenProcess",
            "GetCurrentProcess",
            "GetExitCodeProcess",
        ):
            setattr(self, name, _FakeFunction())


def _owner_helper():
    path = ROOT / ".github" / "scripts" / "mcpb_process_owner.py"
    spec = importlib.util.spec_from_file_location("mcpb_hosted_owner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolver_sources() -> list[str]:
    workflow = (ROOT / ".github" / "workflows" / "mcpb.yml").read_text(encoding="utf-8")
    return [
        textwrap.dedent(part.split("\n          PY", 1)[0])
        for part in workflow.split("          python - <<'PY'\n")[1:]
    ]


def test_windows_job_api_declarations_match_distinct_real_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _owner_helper()
    kernel = _FakeKernel()
    monkeypatch.setattr(helper.os, "name", "nt")
    monkeypatch.setattr(helper.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False)

    assert helper._kernel32() is kernel
    assert kernel.SetInformationJobObject.argtypes == [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    assert kernel.QueryInformationJobObject.argtypes == [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]


def test_all_hosted_rows_provision_and_validate_native_ffmpeg_pair() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mcpb.yml").read_text(encoding="utf-8")
    clean, remainder = workflow.split("  optional-present:", 1)
    optional = remainder.split("  aggregate:", 1)[0]

    assert "matrix.os == 'linux'" in clean and "apt-get install" in clean
    assert "matrix.os == 'macos'" in clean and "brew install ffmpeg" in clean
    assert "matrix.os == 'windows'" in clean and "choco install" in clean
    assert "apt-get install" in optional

    for section in (clean, optional):
        assert 'shutil.which("ffmpeg")' in section
        assert "if not ffmpeg_raw:" in section
        assert "ffmpeg.is_absolute()" in section
        assert "ffmpeg.is_file()" in section
        assert "os.access(ffmpeg, os.X_OK)" in section
        assert 'ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")' in section
        assert "ffprobe.is_file()" in section
        assert "os.access(ffprobe, os.X_OK)" in section
        assert "timeout=20" in section
        assert 'env_file.write(f"MCPB_FFMPEG={ffmpeg}\\n")' in section


def test_each_resolver_runs_bounded_probes_and_exports_canonical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    ffmpeg = tmp_path / f"ffmpeg{suffix}"
    ffprobe = tmp_path / f"ffprobe{suffix}"
    ffmpeg.write_bytes(b"ffmpeg")
    ffprobe.write_bytes(b"ffprobe")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github-env"))
    monkeypatch.setattr(shutil, "which", lambda name: str(ffmpeg) if name == "ffmpeg" else None)
    monkeypatch.setattr(os, "access", lambda path, mode: Path(path) in {ffmpeg, ffprobe} and mode == os.X_OK)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))

    sources = _resolver_sources()
    assert len(sources) == 2 and sources[0] == sources[1]
    for source in sources:
        exec(compile(source, "mcpb-native-ffmpeg", "exec"), {})  # noqa: S102 - repository-owned workflow code.

    assert [call[0] for call in calls] == [
        [str(ffmpeg), "-version"],
        [str(ffprobe), "-version"],
    ] * 2
    assert all(call[1]["timeout"] == 20 and call[1]["check"] is True for call in calls)
    assert (tmp_path / "github-env").read_text(encoding="utf-8") == f"MCPB_FFMPEG={ffmpeg}\n" * 2


@pytest.mark.parametrize(
    ("ffmpeg_present", "ffprobe_present", "executable", "message"),
    [
        (False, False, set(), "native ffmpeg was not found"),
        (True, False, {"ffmpeg"}, "native ffprobe is not an adjacent executable file"),
        (True, True, {"ffprobe"}, "native ffmpeg is not an absolute executable file"),
        (True, True, {"ffmpeg"}, "native ffprobe is not an adjacent executable file"),
    ],
)
def test_resolver_fails_before_runtime_for_missing_or_non_executable_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ffmpeg_present: bool,
    ffprobe_present: bool,
    executable: set[str],
    message: str,
) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    ffmpeg = tmp_path / f"ffmpeg{suffix}"
    ffprobe = tmp_path / f"ffprobe{suffix}"
    if ffmpeg_present:
        ffmpeg.write_bytes(b"ffmpeg")
    if ffprobe_present:
        ffprobe.write_bytes(b"ffprobe")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "github-env"))
    monkeypatch.setattr(shutil, "which", lambda name: str(ffmpeg) if name == "ffmpeg" and ffmpeg_present else None)
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: (
            mode == os.X_OK
            and (
                (Path(path) == ffmpeg and "ffmpeg" in executable) or (Path(path) == ffprobe and "ffprobe" in executable)
            )
        ),
    )
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("version probe ran"))

    with pytest.raises(SystemExit, match=message):
        exec(  # noqa: S102 - repository-owned workflow code.
            compile(_resolver_sources()[0], "mcpb-native-ffmpeg", "exec"), {}
        )

    assert not (tmp_path / "github-env").exists()


def test_runtime_consumers_use_only_validated_ffmpeg_environment_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mcpb.yml").read_text(encoding="utf-8")

    assert workflow.count('--ffmpeg "$MCPB_FFMPEG"') == 2
    assert '--ffmpeg "$(command -v ffmpeg)"' not in workflow
