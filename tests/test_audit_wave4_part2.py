"""Wave 4 Part 2 audit remediation regression tests.

Covers:
- D7-001/C5-001, D7-003/C5-002, D7-004, D7-007, D7-009, D7-026 (desktop plugin)
- D7-017/C5-003 (MCPB launcher unified user-site env + importability)
- C5-005/D6-006 + C1-017 + D6-004/D6-005 (review_card subprocess reduction & SHA-256 binding)
- C5-004/D6-017 + D6-010 + D6-018 (design_quality launch reduction, strict=True, auto-fix failure & cleanup)
- C5-008/D5-022 + C1-015 (projectstore O(1) WAL append & dangling symlink defense)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from kinocut import bounded_process, review_card
from kinocut.contracts.verdict import ClipVerdict
from kinocut.design_quality import design_quality_check, fix_design_issues
from kinocut.design_quality.guardrails import DesignQualityGuardrails
from kinocut.design_quality.models import DesignIssue
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.projectstore import append_record, open_project, read_records
from kinocut.projectstore import store as store_mod
from tests.contracts_fixtures import verdict_kwargs

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. Desktop plugin (Node reducer suite sanity)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_desktop_plugin_node_suite_passes() -> None:
    res = subprocess.run(
        [NODE, "--test", str(ROOT / "plugins" / "kinocut" / "desktop" / "plugin.test.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert res.returncode == 0, res.stdout + "\n" + res.stderr


# ---------------------------------------------------------------------------
# 2. MCPB launcher (D7-017 / C5-003)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX Node + python3 required")
def test_mcpb_launcher_uses_unified_env_without_forcing_pythonnousersite(tmp_path: Path) -> None:
    launcher = ROOT / "mcpb" / "server" / "launcher.js"
    # Verify launcher.js no longer injects PYTHONNOUSERSITE: "1" in probePython.
    src = launcher.read_text(encoding="utf-8")
    assert 'PYTHONNOUSERSITE: "1"' not in src
    assert "PYTHONNOUSERSITE: '1'" not in src

    # Verify a user-site install under PYTHONUSERBASE passes probePython AND launch sees the same env.
    system_python = shutil.which("python3")
    if not system_python:
        pytest.skip("system python3 required")
    py_xy = subprocess.run(
        [system_python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    user_base = tmp_path / "ubase"
    site = user_base / "lib" / f"python{py_xy}" / "site-packages"
    dist_info = site / "kinocut-8.8.8.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: kinocut\nVersion: 8.8.8\n", encoding="utf-8")
    pkg = site / "kinocut"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("__version__ = '8.8.8'\n", encoding="utf-8")
    (pkg / "__main__.py").write_text("pass\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONUSERBASE"] = str(user_base)
    env.pop("PYTHONNOUSERSITE", None)
    env.pop("PYTHONPATH", None)

    res = subprocess.run(
        [
            NODE,
            "-e",
            (
                "const l = require(process.argv[1]);"
                "l.probePython(process.argv[2], '8.8.8').then((r) => console.log(JSON.stringify(r)));"
            ),
            str(launcher),
            system_python,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == {"ok": True}


# ---------------------------------------------------------------------------
# 3. Review card (C5-005 / D6-006 + C1-017 + D6-004/D6-005)
# ---------------------------------------------------------------------------


def test_review_card_cuts_subprocess_launches_and_reuses_probe_info(
    sample_video: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kinocut.engine_probe import invalidate_probe_cache, probe

    # Warm probe facts first so we can pass them via probe_info (simulating render metadata).
    info = probe(sample_video)
    invalidate_probe_cache(sample_video)

    launches: list[list[str]] = []
    real_popen = subprocess.Popen

    class CountingPopen(real_popen):  # type: ignore[misc,valid-type]
        def __init__(self, args, *a, **kw):
            launches.append(list(args) if isinstance(args, (list, tuple)) else [str(args)])
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", CountingPopen)
    out = str(tmp_path / "fast_card.html")
    card = review_card.write_review_card(sample_video, output_path=out, frame_count=4, probe_info=info)

    assert card["success"] is True
    assert card["plays_inline"] is True
    # Single-pass sheet+poster + inline preview (<= 3 immediate child launches, 0 ffprobe when probe_info given).
    assert len(launches) <= 3, f"expected <= 3 launches with probe_info, got {len(launches)}: {launches}"
    assert not any("ffprobe" in os.path.basename(cmd[0]) for cmd in launches)


def test_review_card_binds_approval_to_sha256_and_preserves_preview_directive(
    sample_video: str,
    tmp_path: Path,
) -> None:
    out = str(tmp_path / "bound_card.html")
    expected_sha = _sha256(sample_video)
    card = review_card.write_review_card(sample_video, output_path=out, frame_count=3)

    assert card["preview_directive"] == f'::preview{{file="{out}"}}'
    assert card["input_sha256"] == expected_sha
    assert card["approval_digest"] == f"sha256:{expected_sha}"

    doc = Path(out).read_text(encoding="utf-8")
    assert f'<meta name="kinocut-input-sha256" content="{expected_sha}">' in doc
    assert f'data-input-sha256="{expected_sha}"' in doc

    approve = re.search(r'data-hermes-send="(Approve this cut[^"]*)"', doc)
    assert approve is not None
    assert f"sha256:{expected_sha}" in approve.group(1)
    assert "video_release_checkpoint" in approve.group(1)


def test_attach_review_card_degrades_gracefully_on_oserror_and_rejects_bad_directive_path(
    sample_video: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(review_card, "write_review_card", boom)
    res = {"success": True, "output_path": sample_video}
    attached = review_card.attach_review_card(res, review=True)
    assert attached["success"] is True
    assert attached["review_card"]["created"] is False
    assert attached["review_card"]["error"]["code"] == "review_card_io_error"

    monkeypatch.undo()
    with pytest.raises(MCPVideoError) as exc:
        review_card.write_review_card(sample_video, output_path=str(tmp_path / 'bad"name}.html'))
    assert exc.value.code == "invalid_parameter"


# ---------------------------------------------------------------------------
# 4. Design quality (C5-004 / D6-017 + D6-010 + D6-018)
# ---------------------------------------------------------------------------


def test_design_quality_analyze_eliminates_discarded_passes_and_redundant_probes(
    sample_video: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(wraps=bounded_process.run_bounded)
    monkeypatch.setattr(bounded_process, "run_bounded", run)

    guardrails = DesignQualityGuardrails()
    report = guardrails.analyze(sample_video)

    commands = [call.args[0] for call in run.call_args_list]
    assert report.overall_score >= 0
    # Previously 37 launches (including 20 dead signature=format=xml passes); now <= 6.
    assert len(commands) <= 6, f"too many child launches ({len(commands)}): {commands}"
    assert not any("signature=format=xml" in " ".join(cmd) for cmd in commands)


def test_design_quality_check_honors_strict_mode_fail_closed(sample_video: str) -> None:
    # sample_video is 320x240, so layout emits a low-resolution warning.
    relaxed = design_quality_check(sample_video, strict=False)
    strict = design_quality_check(sample_video, strict=True)

    assert relaxed["success"] is True
    assert any(i["severity"] == "warning" for i in relaxed["issues"])

    assert strict["strict"] is True
    assert strict["passed"] is False
    assert strict["success"] is False
    assert "error" in strict
    assert not any(i["severity"] == "warning" for i in strict["issues"])
    assert any(i["severity"] == "error" for i in strict["issues"])
    assert strict["design_score"] < relaxed["design_score"]


def test_design_quality_never_masks_autofix_failure_and_cleans_fixed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dark = tmp_path / "dark.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x101010:s=160x90:d=1:r=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(dark),
        ],
        check=True,
    )

    # 1) When output is provided to fix_design_issues, render directly there and never leak dark_fixed.mp4.
    custom_out = tmp_path / "custom_fixed.mp4"
    result_path = fix_design_issues(str(dark), output=str(custom_out))
    assert result_path == str(custom_out)
    assert custom_out.is_file()
    assert not (tmp_path / "dark_fixed.mp4").exists()

    # 2) When an auto-fix fails, design_quality_check must fail (success=False) and fixes_applied must not hold "FAILED ...".
    import kinocut.design_quality.guardrails.fixes as fixes_mod

    monkeypatch.setattr(fixes_mod, "_run_design_fix", Mock(side_effect=ProcessingError("ffmpeg", 1, "", reason="boom")))
    checked = design_quality_check(str(dark), auto_fix=True)
    assert checked["success"] is False
    assert checked["passed"] is False
    assert checked["fixes_failed"]
    assert not any("FAILED" in item for item in checked["fixes_applied"])

    with pytest.raises(ProcessingError):
        fix_design_issues(str(dark), output=str(tmp_path / "should_not_succeed.mp4"))
    assert not (tmp_path / "dark_fixed.mp4").exists()


def test_design_quality_nonfilter_fix_failure_cleans_created_target_file(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x101010:s=160x90:d=0.5:r=24",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    g = DesignQualityGuardrails()
    issues = [
        DesignIssue(
            category="typography",
            severity="warning",
            message="dark",
            fix_available=True,
            auto_fix=lambda v: g._auto_fix_brightness(v),
            fix_filter="eq=brightness=0.1:gamma=1.1",
        ),
        DesignIssue(
            category="custom",
            severity="warning",
            message="broken custom fix",
            fix_available=True,
            auto_fix=lambda _v: (_ for _ in ()).throw(RuntimeError("custom boom")),
        ),
    ]
    g._apply_auto_fixes(str(src), issues)
    assert g._last_fixes_failed
    assert not (tmp_path / "clip_fixed.mp4").exists()


# ---------------------------------------------------------------------------
# 5. Project store (C5-008 / D5-022 + C1-015)
# ---------------------------------------------------------------------------


def test_projectstore_append_avoids_quadratic_full_file_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proj = open_project(tmp_path / "proj")
    write_atomically_calls = 0
    real_write = store_mod._write_atomically

    def counting_write(path, fill, *, binary=False):
        nonlocal write_atomically_calls
        if Path(path).name == "clip_verdict.jsonl":
            write_atomically_calls += 1
        return real_write(path, fill, binary=binary)

    monkeypatch.setattr(store_mod, "_write_atomically", counting_write)

    total = 80
    for i in range(total):
        append_record(
            proj,
            ClipVerdict(**verdict_kwargs(project_id=proj.project_id, reviewer=f"rev-{i:04d}-" + "x" * 900)),
        )

    records = read_records(proj, "clip_verdict")
    assert len(records) == total
    # Only the initial few records below _DIRECT_APPEND_THRESHOLD use full-file copy; the rest use O(1) WAL append.
    assert write_atomically_calls <= 6, f"quadratic full-file copy still occurring: {write_atomically_calls} calls"


def test_projectstore_wal_recovers_from_torn_tail_and_rolls_back_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proj = open_project(tmp_path / "proj")
    for i in range(10):
        append_record(
            proj,
            ClipVerdict(**verdict_kwargs(project_id=proj.project_id, reviewer=f"seed-{i:02d}-" + "y" * 700)),
        )
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    assert path.stat().st_size >= store_mod._DIRECT_APPEND_THRESHOLD
    before = path.read_bytes()

    # Simulate a write failure after appending bytes above threshold -> ftruncate rollback must restore exact prior bytes.
    real_fsync = os.fsync

    def flaky_fsync(fd):
        raise OSError("disk I/O error")

    monkeypatch.setattr(os, "fsync", flaky_fsync)
    with pytest.raises(MCPVideoError):
        append_record(proj, ClipVerdict(**verdict_kwargs(project_id=proj.project_id, reviewer="should-rollback")))
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert path.read_bytes() == before
    assert len(read_records(proj, "clip_verdict")) == 10

    # Simulate a hard crash leaving a WAL + torn partial tail bytes on disk.
    wal = store_mod._wal_path(path)
    wal.write_text(
        json.dumps({"prior_size": len(before), "payload_len": 120, "sha256": "0" * 64}) + "\n",
        encoding="utf-8",
    )
    with path.open("ab") as fh:
        fh.write(b'{"partial_torn_json": ')

    # Lock-free read ignores the torn tail cleanly.
    assert len(read_records(proj, "clip_verdict")) == 10
    # Next append recovers the WAL (truncates torn tail) and commits cleanly.
    append_record(proj, ClipVerdict(**verdict_kwargs(project_id=proj.project_id, reviewer="post-crash")))
    assert len(read_records(proj, "clip_verdict")) == 11
    assert not os.path.lexists(wal)


def test_write_atomically_rejects_dangling_symlink_at_backup_path(tmp_path: Path) -> None:
    """C1-015: a dangling symlink at .{name}.bak.{pid} must never be followed by backup copy."""
    target = tmp_path / "records.jsonl"
    target.write_text("line1\n", encoding="utf-8")
    outside_target = tmp_path / "outside_should_never_exist.txt"
    backup = target.with_name(f".{target.name}.bak.{os.getpid()}")
    backup.symlink_to(outside_target)
    assert not backup.exists()  # dangling symlink
    assert os.path.lexists(backup)

    with pytest.raises(MCPVideoError):
        store_mod._atomic_write(target, "line1\nline2\n")

    assert not outside_target.exists(), "dangling backup symlink was followed!"
    assert target.read_text(encoding="utf-8") == "line1\n"
